"""Closing the download/extract hardening gaps.

Covers the three real-world holes in the vendored fetch/extract layer:

1. ``Utils.extract_zip_file`` trusted ``ZipFile.extractall`` and let a member
   named ``../evil`` or an absolute path (and any symlink member) escape the
   extraction directory -- which the engine later chmods and executes.
2. Every ``urlopen`` response is now closed on every path.
3. A ``socket.timeout`` raised while the *body* is streaming -- after headers
   already arrived -- used to escape the retry loop as a bare exception; it is
   now guarded, retried, and surfaces as a typed engine error.

Plus: downloads are atomic, so a failed one leaves nothing at the destination.
"""

import hashlib
import os
import socket
import stat
import sys
import zipfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocengine import runtime
from ocengine import utils as oc_utils
from ocengine import resource_fetcher
from ocengine.utils import Utils, UnsafeArchiveMember
from ocengine.resource_fetcher import ResourceFetcher, DownloadStalled


@pytest.fixture(autouse=True)
def quiet_sink():
    previous = runtime.set_sink(runtime.NullSink())
    yield
    runtime.set_sink(previous)


def make_fetcher():
    fetcher = ResourceFetcher()
    # create_ssl_context reads a system/certifi trust store; the socket is patched
    # out in every test here, so a non-None sentinel is enough to get past the
    # trust-store guard without touching the real store.
    fetcher.ssl_context = object()
    return fetcher


# ---------------------------------------------------------------------------
# Gap 1: zip-slip and symlink members
# ---------------------------------------------------------------------------

def _write_zip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(name, data)


def test_zip_slip_relative_traversal_is_refused(tmp_path):
    destination = tmp_path / "out"
    archive = tmp_path / "payload.zip"
    _write_zip(archive, [("../escaped.txt", "boom"), ("good.txt", "fine")])

    with pytest.raises(UnsafeArchiveMember) as caught:
        Utils().extract_zip_file(str(archive), str(destination))

    assert caught.value.code == "archive.unsafe_member"
    # Nothing was written above the destination, and nothing was extracted at all.
    assert not (tmp_path / "escaped.txt").exists()
    assert not os.listdir(destination)


def test_zip_slip_absolute_member_is_refused(tmp_path):
    destination = tmp_path / "out"
    archive = tmp_path / "payload.zip"
    _write_zip(archive, [("/etc/evil.conf", "boom")])

    with pytest.raises(UnsafeArchiveMember):
        Utils().extract_zip_file(str(archive), str(destination))

    assert not (tmp_path / "etc").exists()
    assert not os.listdir(destination)


def test_zip_symlink_member_is_refused(tmp_path):
    destination = tmp_path / "out"
    archive = tmp_path / "payload.zip"

    with zipfile.ZipFile(archive, "w") as z:
        info = zipfile.ZipInfo("innocent-link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "/etc/passwd")

    with pytest.raises(UnsafeArchiveMember):
        Utils().extract_zip_file(str(archive), str(destination))

    assert not os.listdir(destination)


def test_legitimate_archive_still_extracts(tmp_path):
    destination = tmp_path / "out"
    archive = tmp_path / "ok.zip"
    _write_zip(archive, [("readme.txt", "hello"), ("nested/data.bin", "bytes")])

    Utils().extract_zip_file(str(archive), str(destination))

    assert (destination / "readme.txt").read_text() == "hello"
    assert (destination / "nested" / "data.bin").read_bytes() == b"bytes"


# ---------------------------------------------------------------------------
# Gaps 2 and 3, plus atomicity: the HTTP paths
# ---------------------------------------------------------------------------

class _Headers:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, key, default=None):
        return self._mapping.get(key, default)


class _FakeResponse:
    """Minimal stand-in for a ``urlopen`` result.

    ``fail_first`` makes the first ``fail_first`` read() calls raise the given
    exception, modelling a server that sends headers then stalls mid-body; the
    shared counter is what lets a *stall* be retried by the loop.
    """

    def __init__(self, body=b"", code=200, encoding=None, stall=None):
        self._body = body
        self._pos = 0
        self._code = code
        self._encoding = encoding
        self._stall = stall  # shared list used as a countdown counter
        self.close_calls = 0

    def getcode(self):
        return self._code

    def getheader(self, name, default=None):
        if name == "Content-Length":
            return str(len(self._body))
        return default

    def info(self):
        mapping = {}
        if self._encoding:
            mapping["Content-Encoding"] = self._encoding
        return _Headers(mapping)

    def read(self, size=None):
        if self._stall is not None and self._stall and self._stall[0] > 0:
            self._stall[0] -= 1
            raise self._stall_error()
        if size is None:
            data = self._body[self._pos:]
        else:
            data = self._body[self._pos:self._pos + size]
        self._pos += len(data)
        return data

    def _stall_error(self):
        # socket.timeout is an alias of TimeoutError on this interpreter; raise
        # the classic name so the guard for both is exercised.
        return socket.timeout("stalled mid-stream")

    def close(self):
        self.close_calls += 1


class _FakeUrlopen:
    """Patch target for ``resource_fetcher.urlopen``.

    Returns a fresh response per call, optionally stalling the first
    ``stall_reads`` read() calls across all attempts, and records every response
    created so tests can assert each one was closed.
    """

    def __init__(self, body=b"", code=200, encoding=None, stall_reads=0):
        self._body = body
        self._code = code
        self._encoding = encoding
        self._stall = [stall_reads]
        self.calls = 0
        self.responses = []

    def __call__(self, request, *args, **kwargs):
        self.calls += 1
        response = _FakeResponse(
            body=self._body, code=self._code, encoding=self._encoding,
            stall=self._stall)
        self.responses.append(response)
        return response


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def test_midstream_stall_is_retried_then_succeeds(monkeypatch):
    body = b"the payload bytes"
    fake = _FakeUrlopen(body=body, stall_reads=2)
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    destination = "/tmp/blackdream_dl_ok.bin"
    fetcher = make_fetcher()
    if os.path.exists(destination):
        os.remove(destination)

    assert fetcher.download_and_save_file(
        "https://example.test/payload", destination,
        sha256_hash=_digest(body), product="payload") is True

    # Two stalled bodies then a good one: exactly three connections.
    assert fake.calls == 3
    assert os.path.exists(destination)
    assert open(destination, "rb").read() == body
    os.remove(destination)


def test_exhausting_stall_retries_raises_typed_error(monkeypatch):
    fake = _FakeUrlopen(body=b"never arrives", stall_reads=99)
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    destination = "/tmp/blackdream_dl_stall.bin"
    fetcher = make_fetcher()

    with pytest.raises(DownloadStalled) as caught:
        fetcher.download_and_save_file(
            "https://example.test/payload", destination,
            sha256_hash="0" * 64, product="payload")

    assert caught.value.code == "network.download_stalled"
    assert fake.calls == resource_fetcher.MAX_ATTEMPTS
    # A stall must never leave a file at the final destination.
    assert not os.path.exists(destination)
    assert not [p for p in os.listdir("/tmp") if p.startswith("blackdream_dl_stall") and p.endswith(".part")]


def test_every_urlopen_response_is_closed_on_download(monkeypatch):
    body = b"payload for close test"
    fake = _FakeUrlopen(body=body)
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    destination = "/tmp/blackdream_dl_close.bin"
    fetcher = make_fetcher()
    try:
        assert fetcher.download_and_save_file(
            "https://example.test/x", destination,
            sha256_hash=_digest(body), product="x") is True
    finally:
        if os.path.exists(destination):
            os.remove(destination)

    assert fake.responses and all(r.close_calls >= 1 for r in fake.responses)


def test_every_urlopen_response_is_closed_on_fetch(monkeypatch):
    fake = _FakeUrlopen(body=b"hello text", code=200)
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    fetcher = make_fetcher()
    assert fetcher.fetch_and_parse_content("https://example.test/text") == "hello text"
    assert all(r.close_calls >= 1 for r in fake.responses)


def test_midstream_stall_in_fetch_does_not_escape(monkeypatch):
    # Headers arrive, body stalls, then a retry delivers the text: the raw
    # socket.timeout must not propagate.
    fake = _FakeUrlopen(body=b"recovered", stall_reads=1)
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    fetcher = make_fetcher()
    assert fetcher.fetch_and_parse_content("https://example.test/text") == "recovered"
    assert fake.calls == 2


def test_a_rate_limit_response_is_not_retried(monkeypatch):
    fake = _FakeUrlopen(body=b"rate limited", code=403)
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    fetcher = make_fetcher()
    assert fetcher.fetch_and_parse_content("https://example.test/x") is None
    assert fake.calls == 1
    assert all(r.close_calls >= 1 for r in fake.responses)


def test_a_rate_limit_fetch_logs_a_warning_not_an_error(monkeypatch):
    # The GitHub API rate limit is expected and recovered by the release feed;
    # logging it at error level made successful builds look failed in CI.
    fake = _FakeUrlopen(body=b"rate limited", code=403)
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    sink = runtime.RecordingSink()
    previous = runtime.set_sink(sink)
    try:
        assert make_fetcher().fetch_and_parse_content("https://example.test/x") is None
    finally:
        runtime.set_sink(previous)

    levels = {level for level, message in sink.logs if "example.test" in message}
    assert "error" not in levels
    assert "warning" in levels


def _raising_urlopen(code, calls):
    """urlopen's real behaviour for 4xx: raise HTTPError instead of returning."""
    import io
    from urllib.error import HTTPError

    def urlopen(request, *args, **kwargs):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, code, "error", {}, io.BytesIO(b"error body"))

    return urlopen


def test_a_raised_rate_limit_stops_after_one_request(monkeypatch):
    # The fake above returns a 403 response; real urlopen raises HTTPError. Both
    # shapes must stop the retry loop, because GitHub's API rate limit is exactly
    # this path and used to cost MAX_ATTEMPTS requests per repository.
    calls = []
    monkeypatch.setattr(resource_fetcher, "urlopen", _raising_urlopen(403, calls))

    fetcher = make_fetcher()
    assert fetcher.fetch_and_parse_content("https://example.test/x") is None
    assert calls == ["https://example.test/x"]


def test_a_raised_rate_limit_during_download_is_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(resource_fetcher, "urlopen", _raising_urlopen(429, calls))

    destination = "/tmp/blackdream_dl_ratelimit.bin"
    fetcher = make_fetcher()
    assert fetcher.download_and_save_file(
        "https://example.test/x", destination,
        sha256_hash="0" * 64, product="x") is False
    assert calls == ["https://example.test/x"]
    assert not os.path.exists(destination)


def test_other_http_errors_are_still_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(resource_fetcher, "urlopen", _raising_urlopen(500, calls))

    fetcher = make_fetcher()
    assert fetcher.fetch_and_parse_content("https://example.test/x") is None
    assert len(calls) == resource_fetcher.MAX_ATTEMPTS


def test_failed_download_leaves_no_partial_file(monkeypatch):
    # Digest never matches: the bytes are discarded and the destination is absent.
    fake = _FakeUrlopen(body=b"tampered bytes")
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    destination = "/tmp/blackdream_dl_bad.bin"
    fetcher = make_fetcher()
    result = fetcher.download_and_save_file(
        "https://example.test/x", destination,
        sha256_hash="f" * 64, product="x")

    assert result is False
    assert not os.path.exists(destination)
    assert not [p for p in os.listdir("/tmp")
                if p.startswith("blackdream_dl_bad") and p.endswith(".part")]


def test_unpinned_download_still_refused(monkeypatch):
    fake = _FakeUrlopen(body=b"whatever")
    monkeypatch.setattr(resource_fetcher, "urlopen", fake)

    fetcher = make_fetcher()
    with pytest.raises(resource_fetcher.ExpectedHashMissing):
        fetcher.download_and_save_file("https://example.test/x", "/tmp/x.bin")

    assert fake.calls == 0


def test_extract_has_no_terminal_io():
    # AST-level guard: the extract path must raise typed errors, never prompt/exit.
    import ast

    tree = ast.parse(oc_utils.__file__ and open(oc_utils.__file__, encoding="utf-8").read())
    forbidden = {"print", "input", "exit_program", "request_input"}
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            names.add(node.attr)
    assert "print" not in names and "input" not in names
