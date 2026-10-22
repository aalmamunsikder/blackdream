"""Which digest a product is verified against, and what happens when nothing pins one.

``ResourceFetcher`` refuses to download without a digest, so the gatherer has to
produce one from either the build index or the hand-pinned table. These tests pin the
selection order: published metadata first, the hand-minted TOFU pin only as a fallback.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocengine.datasets.kext_data import kexts
from ocengine.gathering_files import (
    ARTIFACT_DIGESTS,
    PINNED_RELEASES,
    pinned_digest,
    product_name_for_kext,
    resolved_product_info,
)

HEX = re.compile(r"^[0-9a-f]{64}$")

# Pinned in the same table, but fetched by commit sha rather than a kext release.
NON_KEXT_PINS = {"OcBinaryData"}

# Repository keys present in dortania's build index on 2026-10-22. A catalogue
# repository outside this set has to be covered by PINNED_RELEASES or by
# RELEASE_DIGEST_REPOS below; otherwise its kexts can only fail at build time.
BUILD_INDEX_REPOS = {
    "AirportBrcmFixup", "AppleALC", "AppleSupportPkg", "BT4LEContinuityFixup",
    "BrcmPatchRAM", "BrightnessKeys", "CPUFriend", "CpuTopologySync", "CpuTscSync",
    "CryptexFixup", "DebugEnhancer", "ECEnabler", "EmeraldSDHC", "FeatureUnlock",
    "HibernationFixup", "IntelBluetoothFirmware", "IntelMausi", "Lilu",
    "MacHyperVSupport", "NVMeFix", "NoTouchID", "OpenCorePkg", "RTCMemoryFixup",
    "RealtekRTL8111", "RestrictEvents", "SerialMouse", "UEFIGraphicsFB",
    "VirtualSMC", "VoodooI2C", "VoodooInput", "VoodooPS2", "VoodooPS2-Alps",
    "VoodooRMI", "VoodooSMBus", "WhateverGreen", "gfxutil",
}

# Repositories outside the build index whose release pages publish a SHA256 for
# the asset the gatherer selects. Verified on 2026-10-22: every selected asset's
# release page showed a "sha256:" digest, and downloaded bytes for a sample
# (NootedRed, USBToolBox, PC711Probe) matched it byte for byte. Products from
# these repositories that do not publish a digest are in PINNED_RELEASES instead.
RELEASE_DIGEST_REPOS = {
    "ChefKissInc/ForgedInvariant",
    "ChefKissInc/NootedRed",
    "CloverHackyColor/IntelMausiEthernet",
    "DexterSLamb/itlwm",
    "Mieze/IntelLucy",
    "Mieze/LucyRTL8125Ethernet",
    "Mieze/RTL812xLucy",
    "SongXiaoXi/AppleIGC",
    "USBToolBox/kext",
    "hrx114514x/PC711Probe",
    "laobamac/SimpleHDA",
    "laobamac/itlwm",
    "thegwchr/Feixiao",
    "thegwchr/RealtekBluetoothFirmware",
}


def _repo_key(kext):
    repo = (kext.github_repo or {}).get("repo")
    owner = (kext.github_repo or {}).get("owner")
    return "{}/{}".format(owner, repo) if repo else None


def test_a_published_digest_wins_over_the_pin_table():
    info = {"sha256": "a" * 64}
    assert pinned_digest(info, "XHCI-unsupported") == "a" * 64


def test_the_pin_table_fills_a_missing_digest():
    assert pinned_digest({"sha256": None}, "XHCI-unsupported") == ARTIFACT_DIGESTS["XHCI-unsupported"]


def test_an_artifact_with_neither_still_has_no_digest():
    # This is what the gatherer turns into ArtifactDigestMissing rather than fetching.
    assert pinned_digest({"url": "https://example.test/x.zip"}, "SomeUnpinnedKext") is None


def test_every_pin_is_a_lowercase_sha256():
    for name, digest in ARTIFACT_DIGESTS.items():
        assert HEX.match(digest), "{} is pinned to {!r}".format(name, digest)


def test_every_literal_url_kext_resolves_to_a_digest():
    # The gatherer looks the pin up by the kext's own name, so a renamed kext whose
    # pin was not renamed with it would otherwise fail only at build time.
    unpinned = []
    for kext in kexts:
        info = kext.download_info or {}
        if not info.get("url"):
            continue
        if pinned_digest({"product_name": kext.name, **info}, kext.name) is None:
            unpinned.append(kext.name)
    assert unpinned == []


def test_every_pinned_kext_name_still_exists():
    literal = {kext.name for kext in kexts if (kext.download_info or {}).get("url")}
    stray = set(ARTIFACT_DIGESTS) - literal - NON_KEXT_PINS
    assert stray == set()


def test_literal_kext_urls_are_https_without_credentials():
    for kext in kexts:
        url = (kext.download_info or {}).get("url")
        if not url:
            continue
        parsed = urlsplit(url)
        assert parsed.scheme == "https", "{} uses {}".format(kext.name, parsed.scheme)
        assert parsed.username is None and parsed.password is None


def test_the_amd_sensor_kext_uses_a_stable_release_not_a_nightly_artifact():
    info = next(k for k in kexts if k.name == "SMCRadeonSensors").download_info
    assert "/releases/download/" in info["url"]
    assert "nightly.link" not in info["url"]


def test_every_pinned_release_is_a_wellformed_https_asset():
    urls, digests = set(), set()
    for name, pin in PINNED_RELEASES.items():
        assert set(pin) == {"id", "url", "sha256"}, name
        assert isinstance(pin["id"], int) and pin["id"] > 0, name
        assert HEX.match(pin["sha256"]), "{} is pinned to {!r}".format(name, pin["sha256"])
        parsed = urlsplit(pin["url"])
        assert parsed.scheme == "https", name
        assert parsed.netloc == "github.com", name
        assert "/releases/download/" in parsed.path, name
        assert parsed.query == "" and parsed.fragment == "", name
        assert parsed.username is None and parsed.password is None, name
        assert pin["url"] not in urls, "duplicate pinned URL: {}".format(name)
        assert pin["sha256"] not in digests, "duplicate pinned digest: {}".format(name)
        urls.add(pin["url"])
        digests.add(pin["sha256"])


def test_a_pinned_release_overrides_whichever_metadata_arrives_from_upstream():
    remote = {"CpuTopologyRebuild": {
        "id": 1, "url": "https://example.test/not-the-pin.zip", "sha256": "b" * 64}}
    info = resolved_product_info("CpuTopologyRebuild", remote)
    assert info is PINNED_RELEASES["CpuTopologyRebuild"]
    assert info["url"] != remote["CpuTopologyRebuild"]["url"]


def test_a_pinned_release_resolves_without_any_remote_metadata():
    # Sinetek-rtsx is the case that needs this: its release tag contains a "/",
    # so the scraper raises before it can contribute anything.
    info = resolved_product_info("Sinetek-rtsx", {})
    assert info is PINNED_RELEASES["Sinetek-rtsx"]
    assert info["url"].endswith("/Sinetek-rtsx-9.0.zip")


def test_an_unpinned_product_still_uses_remote_metadata():
    remote = {"Lilu": {"url": "https://example.test/Lilu.zip", "sha256": "c" * 64}}
    assert resolved_product_info("Lilu", remote) is remote["Lilu"]


def test_every_pin_still_names_a_product_the_catalogue_can_select():
    reachable = {product_name_for_kext(kext.name) for kext in kexts}
    assert set(PINNED_RELEASES) - reachable == set()
    # A literal URL is handled by ARTIFACT_DIGESTS before a pin is consulted, so a
    # pin on such a kext would be dead weight and a sign the two tables drifted.
    literal = {kext.name for kext in kexts if (kext.download_info or {}).get("url")}
    assert set(PINNED_RELEASES) & literal == set()
    assert set(PINNED_RELEASES) & set(ARTIFACT_DIGESTS) == set()


def test_family_kexts_resolve_to_the_one_product_that_ships_them():
    assert product_name_for_kext("Ath3kBTInjector") == "Ath3kBT"
    assert product_name_for_kext("UTBDefault") == "USBToolBox"
    assert product_name_for_kext("VoodooI2CSynaptics") == "VoodooI2C"
    assert product_name_for_kext("BrcmFirmwareData") == "BrcmPatchRAM"
    assert product_name_for_kext("IntelBTPatcher") == "IntelBluetoothFirmware"
    assert product_name_for_kext("VoodooPS2Controller") == "VoodooPS2"
    assert product_name_for_kext("Lilu") == "Lilu"


def test_every_catalogue_route_is_accounted_for():
    # A kext whose repository is neither indexed, pinned nor known to publish a
    # digest can only fail after the user has collected hardware and chosen a
    # macOS version. Catch that here instead.
    untracked = []
    for kext in kexts:
        if (kext.download_info or {}).get("url"):
            continue
        if product_name_for_kext(kext.name) in PINNED_RELEASES:
            continue
        if _repo_key(kext) in RELEASE_DIGEST_REPOS:
            continue
        if (kext.github_repo or {}).get("repo") in BUILD_INDEX_REPOS:
            continue
        untracked.append((kext.name, _repo_key(kext)))
    assert untracked == []
