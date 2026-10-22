"""Download and cache the bootloader, kexts and patch plists into OCK_Files/.

Converted for the GUI host. The five "press Enter to continue" gates that used to
sit between a failure and the engine's next move are typed raises now, each one
carrying the product that failed and why, so the application can render the
reason instead of a blinking cursor. The cache layout, history.json and the
per-folder manifest.json are untouched -- a GUI displays them, it does not
replace them.

Every digest a download is verified against comes from dortania's build index or
from the GitHub release metadata, both of which publish a SHA256. Products whose
source publishes none have to be pinned in ARTIFACT_DIGESTS below before they can
be fetched: ResourceFetcher refuses unverified bytes outright, because these
artifacts end up inside an EFI that boots the user's machine.
"""

from ocengine import github
from ocengine import kext_maestro
from ocengine import integrity_checker
from ocengine import resource_fetcher
from ocengine import paths
from ocengine import utils
from ocengine.fatal import EngineError
import os
import shutil
import platform
import zipfile

os_name = platform.system()

# Upper bounds for the recursive nested-archive pass over one downloaded product.
# A legitimate kext release is one archive containing one or two archives, so
# these are far above real input; tripping one means the artifact is not what we
# think it is.
NESTED_ZIP_MAX_DEPTH = 3
NESTED_ZIP_MAX_TOTAL_BYTES = 512 * 1024 * 1024
NESTED_ZIP_MAX_ARCHIVES = 64

# Pinned SHA256 digests for artifacts whose upstream publishes none, keyed by
# product name. OcBinaryData has no releases that carry the picker resources, so it
# is fetched by full commit sha instead of a branch: GitHub renders the same bytes for
# a given sha forever, which makes a recorded digest meaningful. Bumping the pin means
# re-verifying the archive by hand, then updating both constants together.
#
# The kext entries in this table carry a literal release URL rather than a repository,
# so the build index never supplies a digest for them and this table is the only way
# they can ever be fetched. Their pins were minted TOFU-style on 2026-10-22 from the
# bytes each URL served over TLS, after opening the archive and matching every
# Contents/Info.plist CFBundleIdentifier to the expected kext; each digest was fetched
# twice and reproduced. A pin covers the URL it was minted for: if upstream republishes
# the asset, ResourceFetcher discards the bytes and the download fails closed -- re-mint
# by hand after checking the new archive. A previously cached, verified copy of that
# product is still usable.
#
# Three URLs are mutable at the source, so their pins are a freeze rather than an
# upstream guarantee: NootRX is published only as a nightly.link artifact of the latest
# successful CI run, and the dortania and lzhoang2801 links point at a `main` branch
# (their filenames are versioned, which is why the bytes have been stable).
# SMCRadeonSensors deliberately does not use its nightly artifact: release 2.4.0
# publishes a stable asset and a GitHub SHA256, and its pin is that published digest.
OCBINARYDATA_COMMIT = "640e7e9240938f2529e725351e1e1150dc3569db"
ARTIFACT_DIGESTS = {
    "OcBinaryData": "c72841c90873747fd47ff37d4270dac1fb5b0f8cacf7db0c9a1237ca240213ee",
    # plist-only injector, no executable; bundle id org.rehabman.injector.XHCI.unsupported
    "XHCI-unsupported": "c54279175c7a01c26eb361f4ac54ad4778f351fb57bc0f7247dc7fa7a46dff1d",

    # ChefKissInc. SMCRadeonSensors is the stable 2.4.0 release asset; NootRX is the
    # nightly.link master artifact, whose Release/ member is NootRX-1.0.0-RELEASE.zip.
    "SMCRadeonSensors": "9a6fd44185b2f51f0c91981c28dd4372a53fef64164dd1e4790c42cf39a97da0",
    "NootRX": "cd5a376ef9de4ba2a157b28eeda1af8a803e7ea1fee72b5e6749defaa90e69df",

    # dortania/OpenCore-Legacy-Patcher payloads, versioned filenames on `main`.
    "AirPortAtheros40-Tahoe": "e76697222592ba575c98052f81b864e5ba467e74b152f6374ec9ad6b06ff0415",
    "AirPortBrcmNIC-Tahoe": "04edd7127ce096f5de9f8112af6d06744f27e5bc659e3d6516408755cb9af032",
    "corecaptureElCap": "59dbbd272c3a796219ddfa43df5349731e2dd068047136b69109c64c6657a47f",
    "IO80211ElCap": "7fcf956d36d3c1f35fc16c2c6570b4b004224369497971dadb38ccba794e6327",
    "IO80211FamilyLegacy": "e681dcc76a2cd2cea4b0ad5f27a3c816055fde3cdccd890dd10a3e2c84e96d93",
    "IOSkywalkFamily": "1e12b7ef42f55b39ea54ada97b46331220668b2c48a28656e9875c5145fe2479",
    "CatalinaBCM5701Ethernet": "da1d49bf724c66516f2116a66f1765ac54f544bf3c600d62c70fc74f974eaff2",
    "AMFIPass": "07b266145906db41f4b13a7938fbb173ea28888cc1fa65f84417f8820adc961e",
    # plist-only: ASPP-Override and AppleMCEReporterDisabler have no executable
    "ASPP-Override": "25049d8ce3f9d1251be36781abac4e2cc993d7bcfaf7e202f49544a99e723d5c",
    "AppleMCEReporterDisabler": "470417c4958dd6ecb982182140a6b76cf85f847c15f1b0f6f59617d5abcc5f76",
    "AppleIntelCPUPowerManagement": "8adeb0f3002387bb18d78c50100fa79f4939277b654e43d8f1178f0831e4f332",
    "AppleIntelCPUPowerManagementClient": "8d90f67dc7a94b61e80a0a3448248fa4246eb7271ecd049debfb3d90b6fdfd01",

    # lzhoang2801/extra-files, versioned filenames on `main`.
    "AppleIGB": "e4401fddb1fd7734977c295181fb64ee02b3c7effe72b2ee50596fce7b910773",
    "RealtekRTL8100": "7fa6624e771ae08fd60db52338b2374226d983e43433c7ec4d8e48375f96aeb8",
    "VoodooTSCSync": "4d91dfb553b529a29f9f1028dc78a37c5b8a17aaf8d861b8d03e79a9a636703c",

    # Release / download assets from the maintainers' own repositories.
    "HoRNDIS": "8f9641ab02744ec6a6e74a1480babf36fbf8228533079ba0782ba016cf2968c3",
    "NullEthernet": "a516d98e2a0c901dd6fe1b3be0b1415dc0b71f9d1c336c07bb67068b074ec4d2",
    "RealtekRTL8111": "fa2a6a8435b4f7211fb503e30a2966017cf050c09e839a13e79c4a8a9cd2a8ba",
}

# Products whose repository is not in dortania's build index and whose release page
# publishes no SHA256 either. Without an entry here the gather stage refuses them,
# so every device that needs one of these kexts could not build at all.
#
# Unlike ARTIFACT_DIGESTS, a pin here freezes the exact asset URL together with its
# digest. The release page is not consulted for these products, which matters for
# Sinetek-rtsx in particular: its tag is ``Releases/v9.0``, and the HTML release
# scraper rejects tags containing a path.
#
# Pins were minted TOFU-style on 2026-10-22: each URL was downloaded twice over TLS,
# both copies produced the digest recorded below, and every Contents/Info.plist
# inside the archive (nested archives included) was opened and its bundle identifier
# matched to the catalogue product. Ath3kBT's archive carries both Ath3kBT.kext and
# Ath3kBTInjector.kext; the digest covers both, and the catalogue maps either kext
# to this product. Bumping a pin means repeating that whole check by hand. If an
# asset disappears or is republished the download fails closed; a previously cached,
# verified copy of that product is still usable.
PINNED_RELEASES = {
    # archive also contains Ath3kBTInjector.kext (com.zxystd.Ath3kBTInjector)
    "Ath3kBT": {
        "id": 212520504,
        "url": "https://github.com/zxystd/AthBluetoothFirmware/releases/download/v1.1.0/Ath3kBT.kext.zip",
        "sha256": "83b68fa50c76699f343da606c297877915a43fdfa985ae6e2a6e36fd16a2b03a",
    },
    "AtherosE2200Ethernet": {
        "id": 335422222,
        "url": "https://github.com/Mieze/AtherosE2200Ethernet/releases/download/v2.4.0/AtherosE2200Ethernet-V2.4.0.zip",
        "sha256": "4702edfcda5cc1b9c7e2ec1278130bb02c5c5a42c77f39b525fa5ac1ca900bfb",
    },
    "GenericUSBXHCI": {
        "id": 648501608,
        "url": "https://github.com/RattletraPM/GUX-RyzenXHCIFix/releases/download/v1.3.0b1-ryzenxhcifix/GenericUSBXHCI.kext.zip",
        "sha256": "2a97459605c13af889ad9e35d23ca520a0debd24e4fb1155b029753548d85b3d",
    },
    "AlpsHID": {
        "id": 307141502,
        "url": "https://github.com/blankmac/AlpsHID/releases/download/v1.2/AlpsHID1.2_release.zip",
        "sha256": "79c3181532b69b7db4fc27f6a4a22732da3d99ab0a0d10080f81d0bb014521e2",
    },
    "AsusSMC": {
        "id": 247360600,
        "url": "https://github.com/hieplpvip/AsusSMC/releases/download/1.4.1/AsusSMC-1.4.1-RELEASE.zip",
        "sha256": "e688da90f79e76967557f06251bcbabd600145972f5b7392094fbfecee1a2000",
    },
    "BigSurface": {
        "id": 33311623,
        "url": "https://github.com/Xiashangning/BigSurface/releases/download/v6.5/BigSurface.zip",
        "sha256": "e3c6ea71133b9fef26a85b9184361f0cc08a25775115ddd7a3638a361616a4c3",
    },
    # release page also lists a .dmg and a dSYM archive, all named YogaSMC; the pin
    # selects the only asset that carries the kext
    "YogaSMC": {
        "id": 808581220,
        "url": "https://github.com/zhen-zen/YogaSMC/releases/download/1.5.3/YogaSMC-Release.zip",
        "sha256": "d212edf601a6f7722f60e63a572ed3e689430d89fdae8a0f5365c8d6f799768e",
    },
    "RealtekCardReader": {
        "id": 453191520,
        "url": "https://github.com/0xFireWolf/RealtekCardReader/releases/download/v0.9.7/RealtekCardReader_0.9.7_006a845_RELEASE.zip",
        "sha256": "48c21aaf8e83e21220ca417351e75c98b16930f0ce311bb3f651d163bd694760",
    },
    "RealtekCardReaderFriend": {
        "id": 156191520,
        "url": "https://github.com/0xFireWolf/RealtekCardReaderFriend/releases/download/v1.0.4/RealtekCardReaderFriend_1.0.4_e1e3301_RELEASE.zip",
        "sha256": "8fed1884e751fb1e9355604b1d047e8414b6abc986393ce7c56f32008278687c",
    },
    "AmdTscSync": {
        "id": 31261208,
        "url": "https://github.com/naveenkrdy/AmdTscSync/releases/download/2.0.0/AmdTscSync-2.0.0-RELEASE.zip",
        "sha256": "aed2dffed57b2ea21e5e323a423652e00868d4831558113fd8551f536e3f3133",
    },
    "CpuTopologyRebuild": {
        "id": 606290112,
        "url": "https://github.com/b00t0x/CpuTopologyRebuild/releases/download/2.0.2/CpuTopologyRebuild-2.0.2-RELEASE.zip",
        "sha256": "c25d07464d2c9adf120dbf13a50321ff1bdb273290a5e82235eef4740db7b911",
    },
    "Sinetek-rtsx": {
        "id": 33191267,
        "url": "https://github.com/cholonam/Sinetek-rtsx/releases/download/Releases/v9.0/Sinetek-rtsx-9.0.zip",
        "sha256": "91709ab1898ac7437c83480a0d43de945401ccf8aa7f0a9c1081aea01099597d",
    },
}

# Metadata consumed as data rather than executed: dortania's build index and the
# three kernel patch sets. They used to be fetched from mutable branches and
# trusted on TLS alone. A substituted index would redirect every artifact
# download, and a substituted patch set would become config.plist entries, so
# each is now fetched by full commit sha and verified before parsing.
#
# Pins were minted on 2026-10-22: each file was fetched twice from its commit
# URL and the digests reproduced, and the parsed contents were checked (36 build
# index product entries, all with a release sha256; 27 AMD, 11 Aquantia and 3
# hyper-threading patches). The index pins OpenCorePkg 1.0.9 and the kext
# versions it lists, so updating any of those is a reviewed code change rather
# than a silent download.
DORTANIA_BUILDS_COMMIT = "c86812b4bf3bc07011dee0c3dcd89dbc99611f14"
DORTANIA_BUILDS_SHA256 = "c01f235818a57f9fc18f4c86fc20111a305bd85c9d4427db10646e409bb3e552"

AMD_VANILLA_COMMIT = "a174cca80efe2377fde3b902666c70863ea66454"
AMD_VANILLA_PATCHES_SHA256 = "dc147342ba068f8221783b43ca5d233587167e4907ae523d83146e5451bf3298"

AQUANTIA_PATCHES_COMMIT = "cb6f025cf4e04c0884a1037a39bbd1f3b06265a0"
AQUANTIA_PATCHES_SHA256 = "d16a2874849e33f662e92ef5e1c6fa90aa243cd152d9952f6406c8638f31fc87"

CPUTOPOLOGYREBUILD_HT_COMMIT = "fe58fd88bf0d472b09ce4bc3c8e2789f05549bb6"
CPUTOPOLOGYREBUILD_HT_SHA256 = "cd8e41626327447f029eba4e8a6c817387f77d1fc8351ec93936a606b62d28b0"


def product_name_for_kext(kext_name):
    """The product name gather looks up, for kexts whose product is a family.

    Versioned products (the AirportItlwm family) are resolved by the caller
    because their name depends on the target macOS version.
    """
    if "VoodooPS2" in kext_name:
        return "VoodooPS2"
    if kext_name == "BlueToolFixup" or kext_name.startswith("Brcm"):
        return "BrcmPatchRAM"
    if kext_name.startswith("Ath3kBT"):
        return "Ath3kBT"
    if kext_name.startswith("IntelB"):
        return "IntelBluetoothFirmware"
    if kext_name.startswith("VoodooI2C"):
        return "VoodooI2C"
    if kext_name == "UTBDefault":
        return "USBToolBox"
    return kext_name

# ---------------------------------------------------------------------------
# macserial supply chain
# ---------------------------------------------------------------------------
# OpenCorePkg ships ``macserial`` inside its release archive. The archive itself
# is authenticated by the archive-level SHA256 the dortania build index publishes,
# which ``gather_bootloader_kexts`` verifies before it extracts a byte -- but that
# digest says nothing about an individual member. So every binary we are willing to
# run is pinned here by the SHA256 of its own bytes, exactly like dsdt.IASL_ASSETS
# pins the ``iasl`` member out of its zip.
#
# The digests below were minted TOFU-style on 2026-10-22. `macserial` and
# `macserial.linux` come from OpenCore-1.0.9-RELEASE.zip (release tag
# OpenCorePkg-6d8490d), whose ARCHIVE digest --
# fcd1e0f9682f8cb6cc69491e4ce304df299b4fdfca068fb7ee8a144917133968 -- is the value
# the build index published. `macserial.exe` was re-minted from
# OpenCore-1.0.9-RELEASE.zip (release tag OpenCorePkg-25d02c8), archive digest
# 7ccefa2ea7e1738738f6c7da4861a6e012f7e397fa2a55c6b5b2894ae381a832, after upstream
# rebuilt that PE; the other two members were byte-identical in both archives. The
# per-member digests were NOT published anywhere; they are what those authenticated
# archives served when the pins were recorded. If a future OpenCorePkg release ships
# different macserial bytes, verification fails loudly here and the pin has to be
# re-minted by hand -- the same branch-ref tradeoff dsdt documents for
# corpnewt/MaciASL.
#
# Keyed (platform, name) so a Linux build is never measured against the Mach-O
# digest that shares a name. ``macserial`` is the Mach-O universal binary (the
# macOS tool, and upstream's secondary Linux candidate); ``macserial.linux`` is
# the ELF build; ``macserial.exe`` is the PE build.
MACSERIAL_ASSETS = {
    ("darwin", "macserial"): {
        "member": "Utilities/macserial/macserial",
        "install_name": "macserial",
        "sha256": "54dcbd20da6d06e88d3711fbc31e4f1f504dfadda490c4cb88a43c7c82491ac3",
    },
    ("linux", "macserial.linux"): {
        "member": "Utilities/macserial/macserial.linux",
        "install_name": "macserial.linux",
        "sha256": "3aaf4e64bad2d8cebdf545235b7eba93e28764cc61e49249c850494a6ccad8dc",
    },
    ("linux", "macserial"): {
        "member": "Utilities/macserial/macserial",
        "install_name": "macserial",
        "sha256": "54dcbd20da6d06e88d3711fbc31e4f1f504dfadda490c4cb88a43c7c82491ac3",
    },
    ("win32", "macserial.exe"): {
        "member": "Utilities/macserial/macserial.exe",
        "install_name": "macserial.exe",
        "sha256": "a9d73ddbbd7afb950fefe75ca1411235acd87f7f86e0c5939038d86b5080a639",
    },
}

# (platform, name) -> expected digest, used to check a binary that was already in a
# tools directory before we looked (bundled or hand-provisioned).
MACSERIAL_PINS_BY_NAME = {
    (plat, asset["install_name"].lower()): asset["sha256"]
    for (plat, _name), asset in MACSERIAL_ASSETS.items()
}

# install_name -> expected digest, used on the download path: each macserial member
# name uniquely identifies one binary, so the archive can be checked per member.
MACSERIAL_MEMBER_SHA = {
    asset["install_name"].lower(): asset["sha256"]
    for asset in MACSERIAL_ASSETS.values()
}

# Which candidate names we will run, per OS, in preference order -- these double as
# the allowlist. A remote member whose name is not here is never installed, whatever
# bytes the archive carried under it.
MACSERIAL_NAMES_BY_OS = {
    "Windows": ("macserial.exe",),
    "Linux": ("macserial.linux", "macserial"),
    "Darwin": ("macserial",),
}
MACSERIAL_PLATFORM_BY_OS = {
    "Windows": "win32",
    "Linux": "linux",
    "Darwin": "darwin",
}


class MacserialUnsupportedPlatform(EngineError):
    """No macserial candidate names are defined for this OS.

    Replaces the bare ``Exception("Unknown OS for macserial")`` upstream raised
    before it looked for a binary, so the GUI can present it instead of crashing.
    """

    code = "engine.macserial_unsupported_platform"
    title = "This operating system has no macserial build"
    remediation = (
        "macserial is fetched from OpenCorePkg for Windows, macOS and Linux only.",
        "Confirm the platform reported by Python matches the machine you are on.",
    )


class MacserialUnavailable(EngineError):
    """No verified macserial binary could be located or fetched.

    Replaces the bare ``Exception("Failed to find macserial ...")`` upstream raised
    once its retries ran out. Raised at the point of use, never at construction.
    """

    code = "engine.macserial_unavailable"
    title = "The serial generator (macserial) is not available"
    remediation = (
        "Place a verified macserial in the application tools directory (override it "
        "with BLACKDREAM_TOOLS_DIR), or fix the network and retry.",
        "Do not put it in the package directory -- engine code refuses to run "
        "anything that sits on Python's import path.",
    )


class MacserialVerificationFailed(EngineError):
    """A macserial binary -- downloaded or already present -- did not match its pin.

    Nothing is chmod-ed, installed, or executed on this path.
    """

    code = "engine.macserial_verification_failed"
    title = "macserial failed verification against its pinned digest"
    remediation = (
        "The bytes do not match the digest pinned for this macserial build; the pin "
        "may be stale after an OpenCorePkg update.",
        "Re-verify the archive by hand and update MACSERIAL_ASSETS, or remove the "
        "offending file from the tools directory and retry.",
    )
    recoverable = True


class DownloadUrlMissing(EngineError):
    """No release metadata anywhere yielded a URL for a product."""

    code = "gathering.download_url_missing"
    title = "No download URL found for a required file"
    remediation = (
        "Check that the upstream repository still publishes the asset this product expects.",
        "Re-run once the release feed responds; a partial GitHub outage looks like this.",
    )


class ArtifactDigestMissing(EngineError):
    """A product's bytes cannot be verified because nothing pins its digest."""

    code = "gathering.artifact_digest_missing"
    title = "No SHA256 digest is pinned for a required file"
    remediation = (
        "Publish or record the artifact's SHA256; unverified bytes are never cached.",
        "Products sourced from a branch archive need a mirrored copy with a fixed digest.",
    )


class DownloadFailed(EngineError):
    """A verified download could not be completed or could not be trusted."""

    code = "gathering.download_failed"
    title = "Could not download a required file"
    remediation = (
        "Retry -- the engine already fell back to a cached copy where one was valid.",
        "If it keeps failing, download the file from the release page and retry.",
    )


class KernelPatchFetchFailed(EngineError):
    """A kernel patch plist could not be fetched or parsed."""

    code = "gathering.kernel_patch_fetch_failed"
    title = "Could not load a kernel patch set"
    remediation = (
        "Without these patches the boot process can panic or misreport hardware, so the "
        "build stops here rather than emitting a config that silently lacks them.",
        "Add the patch set manually in Kernel > Patch if the upstream host is unreachable.",
    )


class BuildIndexUnavailable(EngineError):
    """The pinned dortania build index did not parse or lacked its root entry."""

    code = "gathering.build_index_unavailable"
    title = "The OpenCore build index could not be read"
    remediation = (
        "The index is pinned to a fixed commit and digest, so its shape cannot "
        "legitimately change.",
        "Retry the build; if it persists, the pinned revision in "
        "ocengine.gathering_files is wrong.",
    )


class ReleaseInfoMissing(EngineError):
    """GitHub returned no usable asset entry for a product."""

    code = "gathering.release_info_missing"
    title = "Could not find release information for a required file"
    remediation = (
        "The upstream release page changed shape, or the asset was renamed or removed.",
        "Confirm the expected asset name still appears in the repository's latest release.",
    )


class HardwareSnifferUnsupportedPlatform(EngineError):
    """The Hardware Sniffer *tool* is a Windows executable.

    BlackDream's Windows collector is the only caller that wants it; Linux scans
    natively and macOS has no built-in scan, so reaching this on either platform
    means a caller bypassed the capability gate. Stated as a typed error rather
    than upstream's silent ``None``.
    """

    code = "gathering.hardware_sniffer.unsupported_platform"
    title = "Hardware Sniffer only runs on Windows"
    remediation = (
        "Export the hardware report on Windows, or supply a report produced by another tool.",
        "BlackDream scans natively on Linux; macOS has no built-in scan in this build.",
    )


class ArchiveLimitExceeded(EngineError):
    """A downloaded archive is deeper or larger than any real kext release."""

    code = "gathering.archive_limit_exceeded"
    title = "A downloaded archive exceeded the extraction limits"
    remediation = (
        "Nested-archive bombs and decompression floods look exactly like this.",
        "Nothing further was extracted from that product; re-check its source.",
    )


def resolved_product_info(product_name, latest_products):
    """The metadata a product will be downloaded with.

    A pinned release wins over everything a remote source supplied, and it is
    returned even when no remote source mentioned the product at all.
    """
    pinned = PINNED_RELEASES.get(product_name)
    if pinned is not None:
        return pinned
    return latest_products.get(product_name)


def pinned_digest(product_info, product_name):
    """The digest this product will be verified against, or None if nothing pins it.

    Build-index and scraped release entries carry their own digest. Entries with a
    literal release URL have none, so ARTIFACT_DIGESTS is the only way in for them.
    Fully pinned releases never reach this fallback: their product_info is the
    PINNED_RELEASES entry, digest included.
    """
    return product_info.get("sha256") or ARTIFACT_DIGESTS.get(product_name)


class gatheringFiles:
    def __init__(self):
        self.utils = utils.Utils()
        self.github = github.Github()
        self.kext = kext_maestro.KextMaestro()
        self.fetcher = resource_fetcher.ResourceFetcher()
        self.integrity_checker = integrity_checker.IntegrityChecker()
        self.dortania_builds_url = (
            "https://raw.githubusercontent.com/dortania/build-repo/{}/latest.json".format(
                DORTANIA_BUILDS_COMMIT))
        self.dortania_builds_sha256 = DORTANIA_BUILDS_SHA256
        self.ocbinarydata_url = "https://github.com/acidanthera/OcBinaryData/archive/{}.zip".format(OCBINARYDATA_COMMIT)
        self.amd_vanilla_patches_url = (
            "https://raw.githubusercontent.com/laobamac/AMD_Vanilla/{}/patches.plist".format(
                AMD_VANILLA_COMMIT))
        self.amd_vanilla_patches_sha256 = AMD_VANILLA_PATCHES_SHA256
        self.aquantia_macos_patches_url = (
            "https://raw.githubusercontent.com/CaseySJ/Aquantia-macOS-Patches/{}/"
            "CaseySJ-Aquantia-Patch-Sets-1-and-2.plist".format(AQUANTIA_PATCHES_COMMIT))
        self.aquantia_macos_patches_sha256 = AQUANTIA_PATCHES_SHA256
        self.hyper_threading_patches_url = (
            "https://raw.githubusercontent.com/b00t0x/CpuTopologyRebuild/{}/"
            "patches_ht.plist".format(CPUTOPOLOGYREBUILD_HT_COMMIT))
        self.hyper_threading_patches_sha256 = CPUTOPOLOGYREBUILD_HT_SHA256
        # Allocated by gather_bootloader_kexts, not here: every SMBIOS and
        # ConfigProdigy instance constructs a gatherer, and a scratch directory
        # per construction was one empty /tmp/ocs_* per report.
        self.temporary_dir = None
        self.ock_files_dir = str(paths.current().cache_dir)
        self.download_history_file = os.path.join(self.ock_files_dir, "history.json")

    def _load_download_history(self):
        history_data = self.utils.read_file(self.download_history_file)
        return {item["product_name"]: item for item in history_data if item.get("product_name")} if isinstance(history_data, list) else {}
    
    def _save_download_history(self, local_download_history, product_name, product_id, product_url, sha256_hash):
        local_download_history[product_name] = {
            "product_name": product_name, 
            "id": product_id,
            "url": product_url,
            "sha256": sha256_hash
        }
        
        self.utils.create_folder(os.path.dirname(self.download_history_file))
        sorted_history = sorted(local_download_history.values(), key=lambda x: x.get("product_name", ""))
        self.utils.write_file(self.download_history_file, sorted_history)

    def fetch_latest_products_info(self, kexts, local_download_history):
        latest_products = {k: v.copy() for k, v in local_download_history.items()}
        dortania_builds_data = self.fetcher.fetch_and_verify_content(
            self.dortania_builds_url, self.dortania_builds_sha256, "json",
            product="DortaniaBuildIndex")
        if not isinstance(dortania_builds_data, dict) or "OpenCorePkg" not in dortania_builds_data:
            raise BuildIndexUnavailable(detail=(
                "{} did not contain the expected OpenCorePkg entry, so no artifact "
                "could be resolved from it.".format(self.dortania_builds_url)))
        seen_repos = set()

        def add_product_info(products):
            if isinstance(products, dict):
                products = [products]

            for product in products:
                name = product.get("product_name")
                if not product or not name:
                    continue

                if name not in latest_products:
                    latest_products[name] = product
                else:
                    latest_products[name].update(product)

        for kext in kexts:
            if not kext.checked:
                continue

            if kext.download_info:
                if not kext.download_info.get("sha256"):
                    kext.download_info["sha256"] = None
                add_product_info({"product_name": kext.name, **kext.download_info})
            elif kext.name == "AirportItlwm-laobamac":
                release = self.github.get_latest_release("laobamac", "itlwm") or {}
                for asset in release.get("assets", []):
                    if "-RELEASE" in asset["url"] and asset["product_name"] in ("AirportItlwm24", "AirportItlwm25"):
                        add_product_info({**asset, "product_name": kext.name + asset["product_name"][-2:]})
            elif kext.github_repo and kext.github_repo.get("repo") not in seen_repos:
                name = kext.github_repo.get("repo")
                seen_repos.add(name)
                if name in dortania_builds_data:
                    add_product_info({
                        "product_name": name,
                        "id": dortania_builds_data[name]["versions"][0]["release"]["id"], 
                        "url": dortania_builds_data[name]["versions"][0]["links"]["release"],
                        "sha256": dortania_builds_data[name]["versions"][0]["hashes"]["release"]["sha256"]
                    })
                else:
                    repo_products = [
                        product_name_for_kext(checked.name) for checked in kexts
                        if checked.checked and checked.github_repo.get("repo") == name
                    ]
                    if repo_products and all(product in PINNED_RELEASES for product in repo_products):
                        # Every product this repository contributes is frozen, so the
                        # release page's current shape is irrelevant -- including the
                        # Sinetek-rtsx tag that the scraper cannot represent.
                        self.utils.log_message(
                            "{}: using pinned release metadata.".format(name), level="debug")
                        continue

                    latest_release = self.github.get_latest_release(kext.github_repo.get("owner"), kext.github_repo.get("repo")) or {}
                    add_product_info(latest_release.get("assets"))

        add_product_info({
            "product_name": "OpenCorePkg",
            "id": dortania_builds_data["OpenCorePkg"]["versions"][0]["release"]["id"], 
            "url": dortania_builds_data["OpenCorePkg"]["versions"][0]["links"]["release"],
            "sha256": dortania_builds_data["OpenCorePkg"]["versions"][0]["hashes"]["release"]["sha256"]
        })

        return latest_products
    
    def move_bootloader_kexts_to_product_directory(self, product_name):
        if not os.path.exists(self.temporary_dir):
            raise FileNotFoundError("The directory {} does not exist.".format(self.temporary_dir))
        
        temp_product_dir = os.path.join(self.temporary_dir, product_name)
        
        if not "OpenCore" in product_name:
            kext_paths = self.utils.find_matching_paths(temp_product_dir, extension_filter=".kext")
            for kext_path, type in kext_paths:
                source_kext_path = os.path.join(self.temporary_dir, product_name, kext_path)
                destination_kext_path = os.path.join(self.ock_files_dir, product_name, os.path.basename(kext_path))
                
                if "research" in kext_path.lower() or "debug" in kext_path.lower() or "Contents" in kext_path or not self.kext.process_kext(temp_product_dir, kext_path):
                    continue
                
                shutil.move(source_kext_path, destination_kext_path)
        else:
            source_bootloader_path = os.path.join(self.temporary_dir, product_name, "X64", "EFI")
            if os.path.exists(source_bootloader_path):
                destination_efi_path = os.path.join(self.ock_files_dir, product_name, os.path.basename(source_bootloader_path))
                shutil.move(source_bootloader_path, destination_efi_path)
                source_config_path = os.path.join(os.path.dirname(os.path.dirname(source_bootloader_path)), "Docs", "Sample.plist")
                destination_config_path = os.path.join(destination_efi_path, "OC", "config.plist")
                shutil.move(source_config_path, destination_config_path)

            ocbinarydata_dir = os.path.join(
                self.temporary_dir, "OcBinaryData", "OcBinaryData-{}".format(OCBINARYDATA_COMMIT))
            if os.path.exists(ocbinarydata_dir):
                background_picker_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "datasets", "background_picker.icns")
                product_dir = os.path.join(self.ock_files_dir, product_name)
                efi_dirs = self.utils.find_matching_paths(product_dir, name_filter="EFI", type_filter="dir")

                for efi_dir, _ in efi_dirs:
                    for dir_name in os.listdir(ocbinarydata_dir):
                        source_dir = os.path.join(ocbinarydata_dir, dir_name)
                        destination_dir = os.path.join(destination_efi_path, "OC", dir_name)
                        if os.path.isdir(destination_dir):
                            shutil.copytree(source_dir, destination_dir, dirs_exist_ok=True)

                    resources_image_dir = os.path.join(product_dir, efi_dir, "OC", "Resources", "Image")
                    picker_variants = self.utils.find_matching_paths(resources_image_dir, type_filter="dir")
                    for picker_variant, _ in picker_variants:
                        if ".icns" in ", ".join(os.listdir(os.path.join(resources_image_dir, picker_variant))):
                            shutil.copy(background_picker_path, os.path.join(resources_image_dir, picker_variant, "Background.icns"))

            macserial_paths = self.utils.find_matching_paths(temp_product_dir, name_filter="macserial", type_filter="file")
            if macserial_paths:
                # Only the builds this host can run. The archive also carries the
                # other platforms' tools, and a pin for one of those must not decide
                # whether this platform's build can proceed.
                host_builds = {name.lower() for name in self._macserial_candidate_names()}
                try:
                    for macserial_path, _ in macserial_paths:
                        member_name = os.path.basename(macserial_path)
                        if member_name.lower() not in host_builds:
                            self.utils.log_message(
                                "Skipping {}: it is not a macserial build for this "
                                "system.".format(member_name), level="debug")
                            continue
                        source_macserial_path = os.path.join(self.temporary_dir, product_name, macserial_path)
                        self._install_macserial_member(source_macserial_path, member_name)
                except BaseException:
                    # The archive is already extracted at this point; a verification
                    # failure must not leave a full copy of it in the temp tree.
                    self._discard_temporary_dir()
                    raise
        
        return True

    # ---- macserial provisioning ----------------------------------------

    def _macserial_platform_key(self):
        """The MACSERIAL_ASSETS platform token for the current OS, or None."""
        return MACSERIAL_PLATFORM_BY_OS.get(os_name)

    def _macserial_candidate_names(self):
        """macserial names to look for on this OS, in upstream's preference order.

        Raises :class:`MacserialUnsupportedPlatform` instead of the bare
        ``Exception`` upstream raised for an unknown OS, so the GUI can present it.
        """
        names = MACSERIAL_NAMES_BY_OS.get(os_name)
        if names is None:
            raise MacserialUnsupportedPlatform(detail=(
                "No macserial build is defined for OS {!r}; only Windows, macOS and "
                "Linux are supported.".format(os_name)))
        return names

    def verify_macserial_candidate(self, candidate):
        """Return ``candidate`` if it is a safe, pinned macserial; else None or raise.

        A name we pin a digest for must match that digest -- same name, different
        bytes is exactly the tampering this defends against, so that raises rather
        than silently skipping. A name outside the pins could only have been placed
        by an operator or the bundle, never by a download, so it is logged as
        unverified and returned. The caller owns the import-path check; this does
        not run the binary.
        """
        name = os.path.basename(candidate)
        if not os.path.isfile(candidate):
            return None
        resolved = os.path.realpath(candidate)
        if os.path.dirname(resolved) != os.path.realpath(os.path.dirname(candidate)):
            self.utils.log_message("Ignoring symlinked macserial: {}".format(candidate), level="error")
            return None
        expected = MACSERIAL_PINS_BY_NAME.get((self._macserial_platform_key(), name.lower()))
        if expected is None:
            self.utils.log_message(
                "Using {} from {} - no pinned digest exists for this name, so it was "
                "provisioned locally, not downloaded.".format(name, os.path.dirname(candidate)),
                level="warning")
            return candidate
        actual = self.integrity_checker.get_sha256(candidate)
        if actual and actual.lower() == expected:
            self.utils.log_message("Verified {} against its pinned digest.".format(name), level="debug")
            return candidate
        raise MacserialVerificationFailed(detail=(
            "Refusing {}: digest {} does not match the pinned {}.").format(
                candidate, actual or "unreadable", expected))

    def find_macserial(self):
        """Resolve a verified macserial from ``paths.tools_dirs()``, or None.

        Performs no network I/O and no writes: it scans the trust-ordered tools
        directories, refuses any that is on Python's import path (so a file dropped
        next to the code can never shadow or become the tool), and pin-checks each
        candidate before returning it.
        """
        names = self._macserial_candidate_names()
        for directory in paths.tools_dirs():
            if paths.is_on_import_path(directory):
                self.utils.log_message(
                    "Refusing to run macserial from {} - it is on the import path.".format(directory),
                    level="error")
                continue
            for name in names:
                candidate = os.path.join(directory, name)
                if not os.path.exists(candidate):
                    continue
                if paths.is_on_import_path(candidate):
                    self.utils.log_message(
                        "Refusing to run macserial at {} - it is on the import path.".format(candidate),
                        level="error")
                    continue
                verified = self.verify_macserial_candidate(candidate)
                if verified:
                    return verified
        return None

    def _install_macserial_member(self, source_path, member_name):
        """Install one verified macserial member from OpenCorePkg into the tools dir.

        Order matters: the archive was already digest-checked by the fetcher before
        extraction; this re-checks the member's own bytes against the pin, and only
        then writes and chmods. It never touches the package directory, and a member
        whose name is not a known macserial build is skipped -- bytes we have not
        authenticated are never installed or made executable.
        """
        expected = MACSERIAL_MEMBER_SHA.get(member_name.lower())
        if expected is None:
            self.utils.log_message(
                "Skipping {}: it is not one of the pinned macserial builds, and "
                "remote-named binaries are never installed.".format(member_name),
                level="warning")
            return None

        actual = self.integrity_checker.get_sha256(source_path)
        if not actual or actual.lower() != expected:
            raise MacserialVerificationFailed(detail=(
                "macserial member {} failed content verification: expected {}, got "
                "{}. Nothing was installed.").format(
                member_name, expected, actual or "unreadable"))

        install_dir = paths.install_tools_dir()
        if install_dir is None:
            self.utils.log_message(
                "No writable app-managed tools directory; would have installed {} there.".format(
                    member_name),
                level="error")
            return None

        target = os.path.join(install_dir, member_name)
        staging = target + ".{}.part".format(os.getpid())
        try:
            shutil.copyfile(source_path, staging)
            # Re-hash the staged copy so a truncated write cannot slip past the chmod.
            staged = self.integrity_checker.get_sha256(staging)
            if not staged or staged.lower() != expected:
                raise MacserialVerificationFailed(detail=(
                    "Staged macserial {} did not match its pin after writing: expected "
                    "{}, got {}.").format(member_name, expected, staged or "unreadable"))
            if os.name != "nt":
                # Verified above, so it may now be executable.
                os.chmod(staging, 0o755)
            os.replace(staging, target)
        except OSError as exception:
            if os.path.exists(staging):
                os.remove(staging)
            raise MacserialVerificationFailed(detail=(
                "Could not install macserial {} to {}: {}".format(
                    member_name, install_dir, exception)))
        self.utils.log_message(
            "Installed verified {} to {}.".format(member_name, install_dir), level="info")
        return target

    def _archive_uncompressed_size(self, archive_path):
        """Total bytes the archive declares it will produce, before extracting it.

        A corrupt or truncated zip raises zipfile.BadZipFile from here, exactly as
        it did when extractall met it, so the failure is not softened.
        """
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            return sum(info.file_size for info in zip_ref.infolist())

    def _extract_nested_archives(self, root_dir, product_name, base_extracted_bytes=0):
        """Unpack archives nested inside an already-extracted product.

        Upstream walked the tree with no bound on archive depth, archive count or
        unpacked size, so one artifact could fill the disk or bury the engine in
        archives. This keeps the same walk -- plain directory nesting is still
        followed without limit, because real release archives nest folders deeply
        and a bound there would silently drop kexts -- but bounds how many
        *archives* may sit inside one another (NESTED_ZIP_MAX_DEPTH) and how much
        they may produce (NESTED_ZIP_MAX_TOTAL_BYTES, counted from
        base_extracted_bytes, which is the outer archive's own declared size).
        """
        extracted_bytes = base_extracted_bytes
        archive_count = 0
        # archive_depth is how many archives had to be unpacked to reach a
        # directory: 0 for the extracted product, 1 for the first nested archive.
        dirs_to_scan = [(root_dir, 0)]

        while dirs_to_scan:
            current_dir, archive_depth = dirs_to_scan.pop()
            if not os.path.isdir(current_dir):
                continue

            for item in os.listdir(current_dir):
                item_path = os.path.join(current_dir, item)
                if os.path.isdir(item_path):
                    dirs_to_scan.append((item_path, archive_depth))
                    continue

                if not item.lower().endswith(".zip"):
                    continue

                if archive_depth >= NESTED_ZIP_MAX_DEPTH:
                    raise ArchiveLimitExceeded(detail=(
                        "{} contains an archive nested {} levels deep, past the limit of "
                        "{}. Nothing more was extracted.".format(
                            product_name, archive_depth + 1, NESTED_ZIP_MAX_DEPTH)))

                if archive_count >= NESTED_ZIP_MAX_ARCHIVES:
                    raise ArchiveLimitExceeded(detail=(
                        "{} contains more than {} archives. Nothing more was "
                        "extracted.".format(product_name, NESTED_ZIP_MAX_ARCHIVES)))

                archive_size = self._archive_uncompressed_size(item_path)

                if extracted_bytes + archive_size > NESTED_ZIP_MAX_TOTAL_BYTES:
                    raise ArchiveLimitExceeded(detail=(
                        "{} would unpack more than {} MiB (this archive declares {} bytes "
                        "on top of {} already counted). Nothing more was "
                        "extracted.".format(product_name,
                                             NESTED_ZIP_MAX_TOTAL_BYTES // (1024 * 1024),
                                             archive_size, extracted_bytes)))

                extracted_bytes += archive_size
                archive_count += 1

                self.utils.log_message(
                    "Extracting nested archive {} ({} bytes, depth {}).".format(
                        item, archive_size, archive_depth + 1), level="debug")

                self.utils.extract_zip_file(item_path)
                os.remove(item_path)
                dirs_to_scan.append((os.path.splitext(item_path)[0], archive_depth + 1))

    def _discard_temporary_dir(self):
        """Remove the scratch tree before a failure leaves the loop.

        Upstream deleted it on the way out of the "press Enter" branches; a raise
        needs the same cleanup or a retried run starts in contaminated
        directories.
        """
        if self.temporary_dir:
            shutil.rmtree(self.temporary_dir, ignore_errors=True)
            self.temporary_dir = None

    def gather_bootloader_kexts(self, kexts, macos_version):
        self.utils.head("Gathering Files")
        self.utils.log_message("Please wait for download OpenCorePkg, kexts and macserial...")
        local_download_history = self._load_download_history()

        latest_products = self.fetch_latest_products_info(kexts, local_download_history)

        self.temporary_dir = self.utils.get_temporary_dir()
        self.utils.create_folder(self.temporary_dir)

        seen_download_urls = set()

        for product in kexts + [{"Name": "OpenCorePkg"}]:
            if not isinstance(product, dict) and not product.checked:
                continue

            raw_name = product.name if not isinstance(product, dict) else product.get("Name")

            if raw_name == "AirportItlwm":
                product_name = raw_name
                version = macos_version[:2]
                if all((self.utils.parse_darwin_version("24.0.0") <= self.utils.parse_darwin_version(macos_version), kexts[kext_maestro.kext_data.kext_index_by_name.get("IOSkywalkFamily")].checked, kexts[kext_maestro.kext_data.kext_index_by_name.get("IO80211FamilyLegacy")].checked)):
                    version = "22"
                elif self.utils.parse_darwin_version("23.4.0") <= self.utils.parse_darwin_version(macos_version):
                    version = "23.4"
                elif self.utils.parse_darwin_version("23.0.0") <= self.utils.parse_darwin_version(macos_version):
                    version = "23.0"
                product_name += version
            elif raw_name == "AirportItlwm-laobamac":
                product_name = raw_name + macos_version[:2]
            else:
                product_name = product_name_for_kext(raw_name)

            # A pinned release overrides both the release page and the build index:
            # URL and digest are frozen as a pair, so no remote metadata can move
            # the download away from the bytes the digest describes.
            product_info = resolved_product_info(product_name, latest_products)
            if product_info is None:
                if hasattr(product, 'github_repo') and product.github_repo:
                    product_info = latest_products.get(product.github_repo.get("repo"))
            
            if product_info is None:
                self.utils.log_message(
                    "Could not find download URL for {}.".format(product_name), level="error")
                self._discard_temporary_dir()
                raise DownloadUrlMissing(detail=(
                    "{} is enabled in this plan, but no release metadata provides a "
                    "download URL for it. Building now would produce an EFI without a "
                    "kext the plan selected, so the build stops here.".format(product_name)))

            product_id = product_info.get("id")
            product_download_url = product_info.get("url")
            sha256_hash = pinned_digest(product_info, product_name)

            if product_download_url in seen_download_urls:
                continue
            seen_download_urls.add(product_download_url)

            history_item = local_download_history.get(product_name)
            asset_dir = os.path.join(self.ock_files_dir, product_name)
            manifest_path = os.path.join(asset_dir, "manifest.json")

            if history_item is not None:
                is_latest_id = (product_id == history_item.get("id"))
                folder_is_valid, _ = self.integrity_checker.verify_folder_integrity(asset_dir, manifest_path)
                
                if is_latest_id and folder_is_valid:
                    self.utils.log_message(
                        "Latest version of {} already downloaded.".format(product_name), level="info")
                    continue

            self.utils.log_message("{} {}...".format(
                "Updating" if history_item is not None else "Please wait for download", product_name))

            if not product_download_url:
                self.utils.log_message(
                    "Could not find download URL for {}.".format(product_name), level="error")
                self._discard_temporary_dir()
                raise DownloadUrlMissing(detail=(
                    "No release metadata provided a download URL for {}. Nothing was "
                    "downloaded for it.".format(product_name)))

            self.utils.log_message("from {}".format(product_download_url))

            if not sha256_hash:
                self._discard_temporary_dir()
                raise ArtifactDigestMissing(detail=(
                    "{} is offered at {} with no SHA256 digest, so its bytes cannot be "
                    "verified before they enter the EFI cache.".format(
                        product_name, product_download_url)))

            zip_path = os.path.join(self.temporary_dir, product_name) + ".zip"
            if not self.fetcher.download_and_save_file(product_download_url, zip_path, sha256_hash, product=product_name):
                folder_is_valid, _ = self.integrity_checker.verify_folder_integrity(asset_dir, manifest_path)
                if history_item is not None and folder_is_valid:
                    self.utils.log_message(
                        "Using previously downloaded version of {}.".format(product_name), level="warning")
                    continue
                else:
                    raise DownloadFailed(detail="Could not download {} at this time. Please try again later.".format(product_name))
            
            zip_unpacked_size = self._archive_uncompressed_size(zip_path)
            self.utils.extract_zip_file(zip_path)
            self.utils.create_folder(asset_dir, remove_content=True)

            try:
                self._extract_nested_archives(
                    os.path.join(self.temporary_dir, product_name), product_name,
                    base_extracted_bytes=zip_unpacked_size)
            except ArchiveLimitExceeded:
                self._discard_temporary_dir()
                raise

            if "OpenCore" in product_name:
                oc_binary_data_zip_path = os.path.join(self.temporary_dir, "OcBinaryData.zip")
                self.utils.log_message("Please wait for download OcBinaryData...")
                self.utils.log_message("from {}".format(self.ocbinarydata_url))

                ocbinarydata_sha256 = ARTIFACT_DIGESTS.get("OcBinaryData")
                if not ocbinarydata_sha256:
                    self._discard_temporary_dir()
                    raise ArtifactDigestMissing(detail=(
                        "OcBinaryData is fetched as a branch archive from {}, which "
                        "publishes no digest and no stable bytes. Record its SHA256 in "
                        "ocengine.gathering_files.ARTIFACT_DIGESTS before this can be "
                        "cached.".format(self.ocbinarydata_url)))

                self.fetcher.download_and_save_file(
                    self.ocbinarydata_url, oc_binary_data_zip_path, ocbinarydata_sha256,
                    product="OcBinaryData")

                if not os.path.exists(oc_binary_data_zip_path):
                    self._discard_temporary_dir()
                    raise DownloadFailed(detail=(
                        "Could not download OcBinaryData at this time. Please try again later."))
                
                self.utils.extract_zip_file(oc_binary_data_zip_path)

            if self.move_bootloader_kexts_to_product_directory(product_name):
                self.integrity_checker.generate_folder_manifest(asset_dir, manifest_path)
                self._save_download_history(local_download_history, product_name, product_id, product_download_url, sha256_hash)

        shutil.rmtree(self.temporary_dir, ignore_errors=True)
        self.temporary_dir = None
        return True

    def get_kernel_patches(self, patches_name, patches_url, sha256_hash):
        try:
            response = self.fetcher.fetch_and_verify_content(
                patches_url, sha256_hash, "plist", product=patches_name)

            return response["Kernel"]["Patch"]
        except EngineError:
            # A digest mismatch or a refused unpinned fetch is already specific;
            # wrapping it in "could not download" would hide the security fact.
            raise
        except Exception as e:
            self.utils.log_message(
                "Unable to download {} at this time".format(patches_name), level="error")
            self.utils.log_message("from {}".format(patches_url), level="error")
            raise KernelPatchFetchFailed(detail=(
                "{} could not be fetched or parsed from {}: {}. The kernel patch set is "
                "missing, not empty.".format(patches_name, patches_url, e))) from e
        
    def gather_hardware_sniffer(self):
        if os_name != "Windows":
            message = (
                "Hardware Sniffer is a Windows executable, so no hardware report can be "
                "collected on {}.".format(os_name))
            self.utils.log_message(message, level="warning")
            raise HardwareSnifferUnsupportedPlatform(detail=message)

        self.utils.head("Gathering Hardware Sniffer")

        PRODUCT_NAME = "Hardware-Sniffer-CLI.exe"
        REPO_OWNER = "lzhoang2801"
        REPO_NAME = "Hardware-Sniffer"

        # Install into the app-managed tools directory, never the package directory:
        # a binary dropped next to the code sits on Python's import path. The name is
        # a fixed literal (not remote-controlled) and the bytes are verified against
        # the SHA256 the release publishes before anything is run.
        install_dir = paths.install_tools_dir()
        if install_dir is None:
            message = ("No writable app-managed tools directory; cannot install {}.".format(
                PRODUCT_NAME))
            self.utils.log_message(message, level="error")
            raise DownloadFailed(detail=message)
        destination_path = os.path.join(install_dir, PRODUCT_NAME)
        
        latest_release = self.github.get_latest_release(REPO_OWNER, REPO_NAME) or {}
        
        product_id = None
        product_download_url = None
        sha256_hash = None

        asset_name = PRODUCT_NAME.split('.')[0]
        for asset in latest_release.get("assets", []):
            if asset.get("product_name") == asset_name:
                product_id = asset.get("id")
                product_download_url = asset.get("url")
                sha256_hash = asset.get("sha256")
                break

        if not all([product_id, product_download_url, sha256_hash]):
            message = ("Could not find release information for {} in github.com/{}/{}.".format(
                PRODUCT_NAME, REPO_OWNER, REPO_NAME))
            self.utils.log_message(message, level="error")
            raise ReleaseInfoMissing(detail=message)

        local_download_history = self._load_download_history()

        history_item = local_download_history.get(PRODUCT_NAME)
        
        if history_item is not None:
            is_latest_id = (product_id == history_item.get("id"))
            
            file_is_valid = False
            if os.path.exists(destination_path):
                local_hash = self.integrity_checker.get_sha256(destination_path)
                file_is_valid = (sha256_hash == local_hash)

            if is_latest_id and file_is_valid:
                self.utils.log_message(
                    "Latest version of {} already downloaded.".format(PRODUCT_NAME), level="info")
                return destination_path

        self.utils.log_message("{} {}...".format(
            "Updating" if history_item is not None else "Please wait for download", PRODUCT_NAME))
        self.utils.log_message("from {}".format(product_download_url))
        
        if not self.fetcher.download_and_save_file(
                product_download_url, destination_path, sha256_hash, product=PRODUCT_NAME):
            manual_download_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest"
            self.utils.notify(
                "Could not download {}".format(PRODUCT_NAME),
                "Go to {} to download {} manually.".format(manual_download_url, PRODUCT_NAME),
                level="error")
            raise DownloadFailed(detail=(
                "Failed to download {}. It can be fetched manually from {}.".format(
                    PRODUCT_NAME, manual_download_url)))

        self._save_download_history(local_download_history, PRODUCT_NAME, product_id, product_download_url, sha256_hash)
        
        return destination_path
