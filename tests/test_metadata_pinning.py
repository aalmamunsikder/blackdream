"""The metadata that supplies every other digest must itself be pinned.

The build index and the kernel patch plists are consumed as data: the index
feeds the digest used for every artifact download, and the plists become
Kernel > Patch entries in config.plist. Neither is followed by a verification
step that would catch substituted bytes, so each is fetched from a commit-pinned
URL and hashed against a recorded digest before it is parsed.
"""

import hashlib
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocengine import gathering_files
from ocengine import resource_fetcher
from ocengine import runtime
from ocengine.gathering_files import BuildIndexUnavailable, gatheringFiles
from ocengine.resource_fetcher import (
    ContentDigestMismatch,
    ExpectedHashMissing,
    ResourceFetcher,
)


@pytest.fixture(autouse=True)
def quiet_sink():
    previous = runtime.set_sink(runtime.NullSink())
    yield
    runtime.set_sink(previous)


class _Response:
    def __init__(self, body, code=200):
        self._body = body
        self._pos = 0
        self._code = code
        self.close_calls = 0

    def getcode(self):
        return self._code

    def getheader(self, name, default=None):
        return str(len(self._body)) if name == "Content-Length" else default

    def info(self):
        return {}

    def read(self, size=None):
        data = self._body[self._pos:] if size is None else self._body[self._pos:self._pos + size]
        self._pos += len(data)
        return data

    def close(self):
        self.close_calls += 1


def _urlopen(monkeypatch, bodies):
    """Serve ``bodies`` in order, repeating the last one, and record requests."""
    calls = []

    def fake(request, *args, **kwargs):
        calls.append(request.full_url)
        body = bodies[len(calls) - 1] if len(calls) <= len(bodies) else bodies[-1]
        return _Response(body)

    monkeypatch.setattr(resource_fetcher, "urlopen", fake)
    return calls


def make_fetcher():
    fetcher = ResourceFetcher()
    fetcher.ssl_context = object()
    return fetcher


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def test_verified_metadata_refuses_an_unpinned_fetch(monkeypatch):
    calls = _urlopen(monkeypatch, [b"{}"])

    with pytest.raises(ExpectedHashMissing):
        make_fetcher().fetch_and_verify_content("https://example.test/index.json", None, "json")

    assert calls == []


def test_verified_metadata_parses_only_matching_bytes(monkeypatch):
    body = b'{"OpenCorePkg": {"versions": []}}'
    _urlopen(monkeypatch, [body])

    parsed = make_fetcher().fetch_and_verify_content(
        "https://example.test/index.json", _digest(body), "json")

    assert parsed == {"OpenCorePkg": {"versions": []}}


def test_verified_metadata_raises_on_a_digest_mismatch(monkeypatch):
    body = b'{"OpenCorePkg": {"versions": [{"links": {"release": "https://evil.test"}}]}}'
    calls = _urlopen(monkeypatch, [body])

    with pytest.raises(ContentDigestMismatch) as caught:
        make_fetcher().fetch_and_verify_content(
            "https://example.test/index.json", "0" * 64, "json",
            product="DortaniaBuildIndex")

    assert caught.value.code == "download.content_digest_mismatch"
    assert "nothing was parsed or cached" in caught.value.detail
    assert len(calls) == resource_fetcher.MAX_ATTEMPTS


def test_verified_metadata_retries_a_transient_mismatch(monkeypatch):
    good = b'{"Kernel": {"Patch": []}}'
    _urlopen(monkeypatch, [b"truncated", good])

    parsed = make_fetcher().fetch_and_verify_content(
        "https://example.test/patches.plist", _digest(good), "json")

    assert parsed == {"Kernel": {"Patch": []}}


def test_metadata_urls_are_commit_pinned_not_branch_pinned():
    g = gatheringFiles()
    pinned = [
        (g.dortania_builds_url, g.dortania_builds_sha256, gathering_files.DORTANIA_BUILDS_COMMIT),
        (g.amd_vanilla_patches_url, g.amd_vanilla_patches_sha256, gathering_files.AMD_VANILLA_COMMIT),
        (g.aquantia_macos_patches_url, g.aquantia_macos_patches_sha256,
         gathering_files.AQUANTIA_PATCHES_COMMIT),
        (g.hyper_threading_patches_url, g.hyper_threading_patches_sha256,
         gathering_files.CPUTOPOLOGYREBUILD_HT_COMMIT),
    ]

    for url, digest, commit in pinned:
        assert len(commit) == 40 and set(commit) <= set("0123456789abcdef")
        assert commit in url
        assert "/refs/heads/" not in url and "/master/" not in url and "/main/" not in url
        assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")


def _patch_index():
    return {"OpenCorePkg": {"versions": [{
        "release": {"id": 1},
        "links": {"release": "https://example.test/OpenCore.zip"},
        "hashes": {"release": {"sha256": "b" * 64}},
    }]}}


def test_the_build_index_is_fetched_with_its_pinned_digest(monkeypatch):
    g = gatheringFiles()
    seen = {}

    def fake(url, digest, content_type=None, product=None):
        seen.update(url=url, digest=digest, content_type=content_type, product=product)
        return _patch_index()

    monkeypatch.setattr(g.fetcher, "fetch_and_verify_content", fake)

    products = g.fetch_latest_products_info([], {})

    assert seen["url"] == g.dortania_builds_url
    assert seen["digest"] == g.dortania_builds_sha256
    assert seen["content_type"] == "json"
    assert seen["product"] == "DortaniaBuildIndex"
    assert products["OpenCorePkg"]["sha256"] == "b" * 64


def test_an_index_without_its_root_entry_is_refused(monkeypatch):
    g = gatheringFiles()
    monkeypatch.setattr(g.fetcher, "fetch_and_verify_content",
                        lambda *args, **kwargs: {"_version": 1})

    with pytest.raises(BuildIndexUnavailable):
        g.fetch_latest_products_info([], {})


def test_kernel_patches_are_fetched_through_the_verified_path(monkeypatch):
    g = gatheringFiles()
    seen = {}

    def fake(url, digest, content_type=None, product=None):
        seen.update(url=url, digest=digest, content_type=content_type, product=product)
        return {"Kernel": {"Patch": [{"Comment": "AMD Vanilla"}]}}

    monkeypatch.setattr(g.fetcher, "fetch_and_verify_content", fake)

    patches = g.get_kernel_patches(
        "AMD Vanilla Patches", g.amd_vanilla_patches_url, g.amd_vanilla_patches_sha256)

    assert patches == [{"Comment": "AMD Vanilla"}]
    assert seen == {
        "url": g.amd_vanilla_patches_url,
        "digest": g.amd_vanilla_patches_sha256,
        "content_type": "plist",
        "product": "AMD Vanilla Patches",
    }


def test_a_patch_digest_mismatch_is_not_disguised_as_a_network_error(monkeypatch):
    g = gatheringFiles()
    mismatch = ContentDigestMismatch(detail="tampered patch set")

    def fake(*args, **kwargs):
        raise mismatch

    monkeypatch.setattr(g.fetcher, "fetch_and_verify_content", fake)

    with pytest.raises(ContentDigestMismatch) as caught:
        g.get_kernel_patches(
            "AMD Vanilla Patches", g.amd_vanilla_patches_url, g.amd_vanilla_patches_sha256)

    assert caught.value is mismatch
