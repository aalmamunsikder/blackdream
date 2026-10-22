"""Release assets come from the API, with HTML scraping only as a fallback.

The HTML releases page is served in more than one shape. A response without any
``/releases/tag/`` link used to abort the whole gather stage for every kext repo
outside dortania's build index, which is why Coffee Lake and Raven Ridge stopped
building. The JSON API has a stable shape and publishes each asset digest.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocengine import github
from ocengine import runtime
from ocengine.github import Github, InvalidReleaseTag

API = "https://api.github.com/repos/ChefKissInc/NootedRed/releases/latest"


@pytest.fixture(autouse=True)
def quiet_sink():
    previous = runtime.set_sink(runtime.NullSink())
    yield
    runtime.set_sink(previous)


def _release(*assets):
    return {"tag_name": "v1", "body": "notes", "assets": list(assets)}


def _asset(name, digest="sha256:" + "a" * 64, asset_id=7):
    return {
        "name": name,
        "id": asset_id,
        "digest": digest,
        "browser_download_url": "https://github.com/example/releases/download/v1/" + name,
    }


def _github(monkeypatch, responses):
    g = Github()
    seen = []

    def fake(url, content_type=None):
        seen.append((url, content_type))
        return responses.get(url)

    monkeypatch.setattr(g.fetcher, "fetch_and_parse_content", fake)
    return g, seen


def test_api_assets_carry_their_published_digest(monkeypatch):
    g, seen = _github(monkeypatch, {API: _release(
        _asset("NootedRed-0.8.10-DEBUG.zip"),
        _asset("NootedRed-0.8.10-RESEARCH_RELEASE.zip"),
        _asset("NootedRed-0.8.10-RELEASE.zip", digest="sha256:" + "b" * 64, asset_id=9),
    )})

    release = g.get_latest_release("ChefKissInc", "NootedRed")

    assert seen == [(API, "json")]
    assert [asset["product_name"] for asset in release["assets"]] == ["NootedRed"]
    assert release["assets"][0]["sha256"] == "b" * 64
    assert release["assets"][0]["id"] == 9
    assert release["body"] == "notes"


def test_itlwm_debug_assets_stay_visible(monkeypatch):
    g, _ = _github(monkeypatch, {API: _release(
        _asset("itlwm-DEBUG.zip"),
        _asset("itlwm-RELEASE.zip"),
    )})

    release = g.get_latest_release("ChefKissInc", "NootedRed")

    assert [asset["sha256"] for asset in release["assets"]] == ["a" * 64, "a" * 64]


def test_an_asset_without_a_digest_is_still_reported_for_the_gather_gate(monkeypatch):
    g, _ = _github(monkeypatch, {API: _release(_asset("NootedRed-RELEASE.zip", digest=None))})

    release = g.get_latest_release("ChefKissInc", "NootedRed")

    assert release["assets"][0]["sha256"] is None


def test_api_without_assets_falls_back_to_html(monkeypatch):
    html = (
        '<a class="x" href="/ChefKissInc/NootedRed/releases/tag/v0.9.0">v0.9.0</a>\n'
    )
    expanded = (
        "<ul>\n"
        '<li class="Box-row">\n'
        '<a href="/ChefKissInc/NootedRed/releases/download/v0.9.0/NootedRed-0.9.0-RELEASE.zip">x</a>\n'
        "<span>sha256:" + "c" * 64 + "</span>\n"
        '<relative-time datetime="2026-01-02T03:04:05Z">when</relative-time>\n'
        "</li>\n"
        "</ul>\n"
    )
    g, seen = _github(monkeypatch, {
        API: None,
        "https://github.com/ChefKissInc/NootedRed/releases": html,
        "https://github.com/ChefKissInc/NootedRed/releases/expanded_assets/v0.9.0": expanded,
    })

    release = g.get_latest_release("ChefKissInc", "NootedRed")

    assert [url for url, _ in seen][0] == API
    assert release["assets"][0]["sha256"] == "c" * 64
    assert release["assets"][0]["url"].endswith("NootedRed-0.9.0-RELEASE.zip")


def test_the_atom_feed_finds_the_tag_when_the_api_is_unavailable(monkeypatch):
    atom = (
        "<feed>"
        '<link type="text/html" rel="alternate" href="https://github.com/o/r/releases"/>'
        '<link rel="alternate" href="https://github.com/o/r/releases/tag/v0.9.0"/>'
        "</feed>"
    )
    expanded = (
        "<ul>\n"
        '<li class="Box-row">\n'
        '<a href="/o/r/releases/download/v0.9.0/Foo-0.9.0-RELEASE.zip">x</a>\n'
        "<span>sha256:" + "d" * 64 + "</span>\n"
        '<relative-time datetime="2026-01-02T03:04:05Z">when</relative-time>\n'
        "</li>\n"
        "</ul>\n"
    )
    g, seen = _github(monkeypatch, {
        API: None,
        "https://github.com/o/r/releases.atom": atom,
        "https://github.com/o/r/releases/expanded_assets/v0.9.0": expanded,
    })

    release = g.get_latest_release("o", "r")

    assert seen[1][0] == "https://github.com/o/r/releases.atom"
    assert release["assets"][0]["sha256"] == "d" * 64
    assert release["assets"][0]["product_name"] == "Foo"


def test_an_unsafe_atom_tag_is_refused(monkeypatch):
    atom = '<link rel="alternate" href="https://github.com/o/r/releases/tag/../evil"/>'
    g, _ = _github(monkeypatch, {
        API: None,
        "https://github.com/o/r/releases.atom": atom,
    })

    with pytest.raises(InvalidReleaseTag):
        g.get_latest_release("o", "r")


def test_html_without_a_release_tag_is_still_refused(monkeypatch):
    g, _ = _github(monkeypatch, {API: None, "https://github.com/o/r/releases": "<html></html>"})

    with pytest.raises(InvalidReleaseTag):
        g.get_latest_release("o", "r")
