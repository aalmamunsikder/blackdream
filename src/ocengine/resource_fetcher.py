"""Raw HTTP access for the engine.

Two things were rebuilt here for the GUI host, and one defect was closed:

* The carriage-return throughput meter in ``_download_with_progress`` cannot be
  read by anything but a terminal, so it now emits ``runtime.Transfer`` events on
  the active sink. The rolling-average throughput math is untouched -- it is the
  clock that drives the event cadence.
* Every message went through ``print``. They are sink logs now.
* ``download_and_save_file`` used to return success when no ``sha256_hash`` was
  supplied, which put unverified bytes straight into the bundle that later boots
  the user's machine, and ``create_ssl_context`` fell back to an unverified TLS
  context whenever the system certificate store could not be located. Both
  fallbacks are gone: a download without a pinned digest is a typed error, and a
  missing trust store is a typed error, never a silent downgrade.

The URL set, the retry counts and the request/response parsing are unchanged, so
this file can still be diffed against upstream.
"""

from ocengine import integrity_checker
from ocengine import runtime
from ocengine import utils
from ocengine.fatal import EngineError
import ssl
import os
import json
import plistlib
import socket
import gzip
import zlib
import time
import hashlib
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

MAX_ATTEMPTS = 3

# Seconds between throughput samples. Upstream used this window to average the
# last few readings before printing a bar; here it is also the download event
# cadence, so a download produces at most two Transfer events per second.
SPEED_SAMPLE_INTERVAL = 0.5


class TlsTrustStoreMissing(EngineError):
    """No certificate store could be loaded, so no request can be verified.

    Upstream answered this situation by turning certificate checking off. This
    build has no such switch: a packaged app either ships its CA bundle or says
    so.
    """

    code = "network.tls_trust_store_missing"
    title = "TLS certificates are missing, so nothing can be downloaded safely"
    remediation = (
        "The application bundles certifi; a broken install or a stripped PyInstaller "
        "build usually means the certificate bundle was not collected.",
        "Reinstall the application, or set SSL_CERT_FILE to a readable CA bundle.",
    )


class ExpectedHashMissing(EngineError):
    """A caller asked for a download without saying what bytes it should be.

    Raised before any socket is opened, so the engine never writes a partial
    unverified file on the way to failing.
    """

    code = "download.expected_hash_missing"
    title = "Refusing to download a file with no expected SHA256 hash"
    remediation = (
        "Pin the digest where the product is declared, or take it from the upstream "
        "release metadata that already publishes one.",
    )


class ContentDigestMismatch(EngineError):
    """A pinned metadata file arrived with different bytes than recorded.

    The build index and the kernel patch plists are consumed as data rather than
    executed, so there is no later verification step that would catch a
    substitution. They are fetched by commit sha and hashed before parsing.
    """

    code = "download.content_digest_mismatch"
    title = "Downloaded metadata did not match its pinned SHA256"
    remediation = (
        "The URL is pinned to a commit, so its bytes cannot legitimately change; "
        "treat the response as tampered with or the recorded digest as wrong.",
        "Do not build with this metadata. Only update the pin after reviewing the "
        "new content by hand.",
    )


class MetadataFetchFailed(EngineError):
    """A pinned metadata file could not be fetched on any attempt."""

    code = "network.metadata_fetch_failed"
    title = "Required build metadata could not be downloaded"
    remediation = (
        "Nothing could be parsed, so no partial build index or patch set was used.",
        "Retry once the network is stable.",
    )


class DownloadStalled(EngineError):
    """The body stopped arriving after the connection had already succeeded.

    The retry loop used to guard only the connect and the ``urlopen`` call, so a
    server that sent headers and then fell silent let ``socket.timeout`` escape
    straight out of ``download_and_save_file`` -- past the retry, past the digest
    check, and into whatever sat above the engine. Now the stall is retried like
    any other failure and, once the attempts run out, surfaces as this typed
    error for the UI to present. It is never a bare exception and never a prompt.
    """

    code = "network.download_stalled"
    title = "A download stalled while its contents were being read"
    remediation = (
        "The connection worked but the transfer never finished; every partial file "
        "was discarded, so nothing was cached.",
        "Retry once the network is stable.",
    )


class ResourceFetcher:
    def __init__(self, headers=None):
        self.request_headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }
        self.buffer_size = 16 * 1024
        self.ssl_context = self.create_ssl_context()
        self.integrity_checker = integrity_checker.IntegrityChecker()
        self.utils = utils.Utils()

    @property
    def sink(self) -> runtime.EngineSink:
        return runtime.current_sink()

    @staticmethod
    def _close(response):
        """Release a socket-backed response without letting a close fail a fetch.

        Every ``urlopen`` result is owned by whoever received it, and every path
        that reads one must close it; leaving a response open pins a connection
        and a file descriptor for the life of the GUI process.
        """
        if response is None:
            return
        try:
            response.close()
        except Exception:
            pass

    @staticmethod
    def _discard(path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def create_ssl_context(self):
        """Return a verifying context, or ``None`` when no trust store exists.

        Returning ``None`` instead of raising keeps constructing a
        ``ResourceFetcher`` safe -- the failure surfaces on the first request,
        where the product name is known and can be shown. Upstream answered this
        failure by handing back a context with certificate checking switched
        off, which silently accepted any certificate and any byte stream. That
        downgrade is gone.
        """
        try:
            cafile = ssl.get_default_verify_paths().openssl_cafile
            if not cafile or not os.path.exists(cafile):
                import certifi
                cafile = certifi.where()
            return ssl.create_default_context(cafile=cafile)
        except Exception as e:
            self.utils.log_message(
                "Could not load a TLS certificate store: {}".format(e), level="error")
            return None

    def _make_request(self, resource_url, timeout=10):
        if self.ssl_context is None:
            raise TlsTrustStoreMissing(
                detail="No CA bundle is available, so {} cannot be fetched over a "
                       "verified TLS connection.".format(resource_url))

        try:
            headers = dict(self.request_headers)
            headers["Accept-Encoding"] = "gzip, deflate"

            return urlopen(Request(resource_url, headers=headers), timeout=timeout, context=self.ssl_context)
        except socket.timeout as e:
            self.utils.log_message("Timeout error: {}".format(e), level="warning")
        except ssl.SSLError as e:
            self.utils.log_message("SSL error: {}".format(e), level="warning")
        except HTTPError as e:
            # urlopen raises on 4xx/5xx; hand the response back so the caller can
            # read the status and stop retrying a refusal. Falling through to
            # URLError made every rate limit look like a transient connection
            # error and cost MAX_ATTEMPTS requests per repository.
            self.utils.log_message(
                "HTTP {} from {}.".format(e.code, resource_url), level="warning")
            return e
        except (URLError, socket.gaierror) as e:
            self.utils.log_message("Connection error: {}".format(e), level="warning")
        except Exception as e:
            self.utils.log_message("Request failed: {}".format(e), level="warning")

        return None

    def _fetch_content(self, resource_url):
        """Return the decompressed response body, or ``None`` after the attempts."""
        attempt = 0
        response = None
        content = None
        content_encoding = None
        got_content = False
        refusal_code = None

        while attempt < MAX_ATTEMPTS:
            attempt += 1
            response = self._make_request(resource_url)

            if not response:
                self.utils.log_message(
                    "Failed to fetch content from {}. Retrying...".format(resource_url),
                    level="warning")
                continue

            try:
                if response.getcode() != 200:
                    if response.getcode() in (403, 429):
                        # A rate limit or refusal will not clear between two
                        # immediate retries, and callers of this method have a
                        # fallback path (the GitHub release feed). It is not an
                        # engine failure, so it must not be logged as one.
                        refusal_code = response.getcode()
                        break
                    self.utils.log_message(
                        "Unexpected status {} from {}.".format(
                            response.getcode(), resource_url), level="warning")
                    continue

                try:
                    # The body read is the part that used to escape: headers
                    # arrive, then the stream stalls, and a raw socket.timeout
                    # leaves past the retry loop. It is guarded here and retried.
                    content = response.read()
                    content_encoding = response.info().get("Content-Encoding")
                    got_content = True
                except (socket.timeout, TimeoutError) as e:
                    self.utils.log_message(
                        "Reading content from {} stalled: {}. Retrying...".format(
                            resource_url, e), level="warning")
                    continue
            finally:
                self._close(response)
                response = None

            break

        if not got_content:
            if refusal_code is not None:
                self.utils.log_message(
                    "HTTP {} refused {}; not retrying.".format(
                        refusal_code, resource_url), level="warning")
            else:
                self.utils.log_message(
                    "Failed to fetch content from {}".format(resource_url), level="error")
            return None

        if content_encoding == "gzip" or content.startswith(b"\x1f\x8b"):
            try:
                content = gzip.decompress(content)
            except Exception as e:
                self.utils.log_message(
                    "Failed to decompress gzip content: {}".format(e), level="warning")
        elif content_encoding == "deflate":
            try:
                content = zlib.decompress(content)
            except Exception as e:
                self.utils.log_message(
                    "Failed to decompress deflate content: {}".format(e), level="warning")

        return content

    def _parse_content(self, content, content_type=None):
        try:
            if content_type == "json":
                return json.loads(content)
            elif content_type == "plist":
                return plistlib.loads(content)
            else:
                return content.decode("utf-8")
        except Exception as e:
            self.utils.log_message(
                "Error parsing content as {}: {}".format(content_type, e), level="error")

        return None

    def fetch_and_parse_content(self, resource_url, content_type=None):
        content = self._fetch_content(resource_url)
        if content is None:
            return None
        return self._parse_content(content, content_type)

    def fetch_and_verify_content(self, resource_url, sha256_hash, content_type=None,
                                 product=None):
        """Fetch a file whose exact bytes are pinned, verify, then parse it.

        The build index supplies the digests of every other artifact, and the
        kernel patch plists become entries in ``config.plist``; neither is
        followed by a check that would notice substituted bytes. They are
        fetched from commit-pinned URLs and hashed before anything is parsed.
        """
        if not sha256_hash:
            raise ExpectedHashMissing(detail=(
                "{} has no expected SHA256 hash, so it cannot be trusted. Refused "
                "before contacting {}.".format(
                    product or os.path.basename(resource_url), resource_url)))

        expected = sha256_hash.lower()
        mismatched = False

        for _attempt in range(MAX_ATTEMPTS):
            content = self._fetch_content(resource_url)
            if content is None:
                continue
            actual = hashlib.sha256(content).hexdigest()
            if actual == expected:
                return self._parse_content(content, content_type)
            mismatched = True
            self.utils.log_message(
                "Checksum mismatch for {}: expected {}, got {}.".format(
                    product or resource_url, expected, actual), level="warning")

        if mismatched:
            raise ContentDigestMismatch(detail=(
                "{} from {} did not match its pinned SHA256 after {} attempts. The "
                "URL is pinned to a fixed commit, so the bytes cannot legitimately "
                "change; nothing was parsed or cached.".format(
                    product or resource_url, resource_url, MAX_ATTEMPTS)))
        raise MetadataFetchFailed(detail=(
            "{} could not be fetched from {} on any of {} attempts.".format(
                product or resource_url, resource_url, MAX_ATTEMPTS)))

    def _download_with_progress(self, response, local_file, product=None):
        """Stream the body to disk, reporting bytes on the sink.

        The bar this replaces was 40 characters redrawn with ``end="\\r"``, which
        only a terminal can read. The same accounting now leaves as
        ``runtime.Transfer``: one event at the start (so the host learns the total
        size), one per throughput sample, and one at the end.
        """
        total_size = response.getheader("Content-Length")
        if total_size:
            total_size = int(total_size)

        product = product or os.path.basename(getattr(local_file, "name", "") or "download")

        bytes_downloaded = 0
        started = time.time()
        last_time = started
        last_bytes = 0
        speeds = []
        avg_speed = 0.0
        last_reported_bytes = None
        sink = self.sink

        def emit():
            sink.transfer(runtime.Transfer(
                product=product,
                done_bytes=bytes_downloaded,
                total_bytes=total_size,
                bytes_per_second=avg_speed,
            ))

        emit()

        while True:
            chunk = response.read(self.buffer_size)
            if not chunk:
                break
            local_file.write(chunk)
            bytes_downloaded += len(chunk)

            current_time = time.time()
            time_diff = current_time - last_time

            if time_diff > SPEED_SAMPLE_INTERVAL:
                current_speed = (bytes_downloaded - last_bytes) / time_diff
                speeds.append(current_speed)
                if len(speeds) > 5:
                    speeds.pop(0)
                avg_speed = sum(speeds) / len(speeds)

                last_time = current_time
                last_bytes = bytes_downloaded

                if bytes_downloaded != last_reported_bytes:
                    emit()
                    last_reported_bytes = bytes_downloaded

        # A body that arrives inside one sampling window never sets the rolling
        # average; fall back to the whole-transfer average so the host never
        # reports 0 KB/s for a completed file.
        if avg_speed == 0.0 and bytes_downloaded:
            elapsed = time.time() - started
            if elapsed > 0:
                avg_speed = bytes_downloaded / elapsed

        emit()

    def download_and_save_file(self, resource_url, destination_path, sha256_hash=None, product=None):
        """Download a file, verify it against a pinned SHA256, publish it atomically.

        ``sha256_hash`` is required. Upstream returned ``True`` when it was
        missing -- "downloading file without verification" -- which let any
        response, including a tampered or redirected one, into the cache that
        feeds a bootable EFI. Callers with nothing to verify against must fail
        loudly instead.

        The body is streamed to a ``*.part`` sibling and only ``os.replace``-d
        onto the destination once its digest matches, so a stall, a mismatch or a
        killed process can never leave a half-written file where a later run would
        read it as complete. Each attempt closes its response; a mid-stream
        ``socket.timeout`` is retried like any other failure and, once the
        attempts run out, raised as a typed :class:`DownloadStalled` rather than
        escaping as a bare exception.
        """
        if not sha256_hash:
            raise ExpectedHashMissing(detail=(
                "{} has no expected SHA256 hash, so its contents cannot be trusted. "
                "Refused before contacting {}.".format(
                    product or os.path.basename(destination_path), resource_url)))

        product = product or os.path.basename(destination_path)
        staging_path = "{}.{}.part".format(destination_path, os.getpid())
        attempt = 0
        stalled = False

        while attempt < MAX_ATTEMPTS:
            attempt += 1
            stalled = False
            response = self._make_request(resource_url)

            if not response:
                self.utils.log_message(
                    "Failed to fetch content from {}. Retrying...".format(resource_url),
                    level="warning")
                continue

            try:
                if response.getcode() != 200:
                    self.utils.log_message(
                        "Unexpected status {} from {}.".format(
                            response.getcode(), resource_url), level="warning")
                    if response.getcode() in (403, 429):
                        break
                    continue

                try:
                    with open(staging_path, "wb") as local_file:
                        self._download_with_progress(response, local_file, product=product)
                except (socket.timeout, TimeoutError) as e:
                    # Headers arrived, the body did not. Guarded now, so the retry
                    # actually runs instead of a raw timeout punching through.
                    stalled = True
                    self.utils.log_message(
                        "Download of {} stalled mid-stream: {}. Retrying...".format(product, e),
                        level="warning")
                    self._discard(staging_path)
                    continue
                except OSError as e:
                    self.utils.log_message(
                        "Could not write the download of {}: {}. Retrying...".format(product, e),
                        level="warning")
                    self._discard(staging_path)
                    continue

                if os.path.getsize(staging_path) > 0:
                    self.utils.log_message(
                        "Verifying SHA256 checksum for {}...".format(product), level="debug")
                    downloaded_hash = self.integrity_checker.get_sha256(staging_path)
                    if downloaded_hash and downloaded_hash.lower() == sha256_hash.lower():
                        os.replace(staging_path, destination_path)
                        self.utils.log_message(
                            "Checksum verified successfully for {}.".format(product), level="debug")
                        return True
                    self.utils.log_message(
                        "Checksum mismatch for {}! Discarding and retrying download...".format(product),
                        level="warning")
                else:
                    self.utils.log_message(
                        "Downloaded nothing for {}. Retrying...".format(product), level="warning")

                self._discard(staging_path)
            finally:
                self._close(response)

            if attempt < MAX_ATTEMPTS:
                self.utils.log_message(
                    "Download failed for {}. Retrying...".format(resource_url), level="warning")

        if stalled:
            raise DownloadStalled(detail=(
                "Download of {} from {} stalled while its contents were being read on "
                "all {} attempts. No partial file was kept.".format(
                    product, resource_url, MAX_ATTEMPTS)))

        self.utils.log_message(
            "Failed to download {} after {} attempts.".format(resource_url, MAX_ATTEMPTS),
            level="error")
        return False
