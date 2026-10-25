#: Xe-LP iGPUs with a WhateverXe backend, from the project's own device table
#: (``docs/device-selection.md`` in b00t0x/WhateverXe at 0.5.0). Tiger Lake, Alder
#: Lake-N / Twin Lake, Alder Lake-S/HX and Raptor Lake-S/HX. The Xe-LPG (Meteor Lake)
#: and Xe2 parts are explicitly out of scope upstream and are not listed here.
WHATEVERXE_DEVICE_IDS = frozenset((
    # Tiger Lake
    "9A40", "9A49", "9A60", "9A68", "9A70", "9A78",
    # Alder Lake-N / Twin Lake
    "46D0", "46D1", "46D2", "46D3", "46D4",
    # Alder Lake-S / HX
    "4680", "4682", "4688", "468A", "468B", "4690", "4692", "4693",
    # Raptor Lake-S / HX
    "A780", "A781", "A782", "A783", "A788", "A789", "A78A", "A78B",
))

#: Big Sur 11.7.11 is the oldest release WhateverXe 0.5.0 accepts.
WHATEVERXE_MIN_DARWIN = "20.6.0"

#: The signed graphics package version WEX 0.5.0 needs; it is installed by the user
#: after the first boot, never by this application.
WHATEVERXE_GRAPHICS_VERSION = "0.2.0"


def is_whateverxe_device_id(device_id) -> bool:
    """True for a report device id such as ``8086-9A49`` in the WhateverXe table."""
    if not isinstance(device_id, str):
        return False
    tail = device_id.strip().upper().split("-")[-1]
    return tail in WHATEVERXE_DEVICE_IDS


#: Turing-and-newer display ids the NullMoth driver 2.5.4 accepts, from the release's
#: own ``p1401/nvidia_gsp_ids.json`` (NVIDIA open-gpu-kernel-modules 615.78.08).
#: GTX 16, RTX 20/30/40/50, TITAN RTX, Quadro RTX and the T-series.
NULLMOTH_DEVICE_IDS = frozenset((
    "1E02", "1E04", "1E07", "1E30", "1E36", "1E78", "1E81", "1E82",
    "1E84", "1E87", "1E89", "1E90", "1E91", "1E93", "1EB0", "1EB1",
    "1EB5", "1EB6", "1EC2", "1EC7", "1ED0", "1ED1", "1ED3", "1EF5",
    "1F02", "1F03", "1F06", "1F07", "1F08", "1F0A", "1F10", "1F11",
    "1F12", "1F14", "1F15", "1F36", "1F42", "1F47", "1F50", "1F51",
    "1F54", "1F55", "1F76", "1F82", "1F83", "1F91", "1F95", "1F96",
    "1F97", "1F98", "1F99", "1F9C", "1F9D", "1F9F", "1FA0", "1FB0",
    "1FB1", "1FB2", "1FB6", "1FB7", "1FB8", "1FB9", "1FBA", "1FBB",
    "1FBC", "1FDD", "1FF0", "1FF2", "1FF9", "2182", "2184", "2187",
    "2188", "2191", "2192", "21C4", "21D1", "2203", "2204", "2206",
    "2207", "2208", "220A", "2216", "2230", "2231", "2232", "2233",
    "2414", "2420", "2438", "2460", "2482", "2484", "2486", "2487",
    "2488", "2489", "249C", "249D", "24A0", "24B0", "24B1", "24B6",
    "24B7", "24B8", "24B9", "24BA", "24BB", "24C7", "24C9", "24DC",
    "24DD", "24E0", "24FA", "2503", "2504", "2507", "2508", "2520",
    "2521", "2523", "2531", "2544", "2560", "2563", "2571", "2582",
    "2584", "25A0", "25A2", "25A5", "25A6", "25A7", "25A9", "25AA",
    "25AB", "25AC", "25AD", "25B0", "25B2", "25B8", "25B9", "25BA",
    "25BB", "25BC", "25BD", "25E0", "25E2", "25E5", "25EC", "25ED",
    "25F9", "25FA", "25FB", "2684", "2685", "2689", "26B1", "26B2",
    "26B3", "2702", "2704", "2705", "2709", "2717", "2730", "2757",
    "2770", "2782", "2783", "2786", "2788", "27A0", "27B0", "27B1",
    "27B2", "27BA", "27BB", "27E0", "27FB", "2803", "2805", "2808",
    "2820", "2822", "2838", "2860", "2882", "28A0", "28A1", "28A3",
    "28B0", "28B8", "28B9", "28BA", "28BB", "28E0", "28E1", "28E3",
    "28F8", "2B85", "2B87", "2B8C", "2BB1", "2BB3", "2BB4", "2BB5",
    "2BB9", "2C02", "2C05", "2C09", "2C18", "2C19", "2C31", "2C33",
    "2C34", "2C38", "2C39", "2C3A", "2C58", "2C59", "2C77", "2C79",
    "2D04", "2D05", "2D18", "2D19", "2D30", "2D39", "2D58", "2D59",
    "2D79", "2D83", "2D98", "2DB8", "2DB9", "2DD8", "2DF9", "2E03",
    "2E06", "2E12", "2F04", "2F06", "2F18", "2F38", "2F58",
))

#: macOS 15.5 Sequoia is the oldest release the driver's README names (its installer
#: accepts macOS 15 and 26 by major version, and the runtime check refuses older).
NULLMOTH_MIN_DARWIN = "24.5.0"

#: The driver release this integration is written against. The driver is installed on
#: the target by the user; nothing here is bundled into the EFI.
NULLMOTH_DRIVER_VERSION = "2.5.4"

#: SIP bits the driver needs (``csr-active-config`` 0x0A43). The vendor installer ORs
#: these into whatever the config already has, so the value may carry more than this.
NULLMOTH_SIP_BITS = 0x0A43

NULLMOTH_RELEASES_URL = "https://github.com/nullmoth/nvidia-macos-driver/releases"

#: SHA-256 of ``nullmoth-nvidia-2.5.4.tar.gz``, published in the release's own
#: ``SHA256SUMS.txt``. The hand-off repeats it so a manual download can be checked.
NULLMOTH_TARBALL_SHA256 = (
    "648280bea54fa57809e3bf3b312bdb6709a00fa0292af3b37c665e111fe27eaa")


def _nvidia_tail(device_id):
    """The four hex digits of a report NVIDIA display id, or None for anything else."""
    if not isinstance(device_id, str):
        return None
    parts = device_id.strip().upper().split("-")
    if len(parts) > 1 and parts[-2] != "10DE":
        return None
    tail = parts[-1]
    if len(tail) != 4 or any(character not in "0123456789ABCDEF" for character in tail):
        return None
    return tail


def is_nullmoth_device_id(device_id) -> bool:
    """True for a display id the NullMoth driver 2.5.4 supports.

    The table is the release's own list. Its installer also accepts any display id at
    or above 0x1E00 (Turing's first id) that postdates the list, so this mirrors both
    and does not claim older GeForce cards.
    """
    tail = _nvidia_tail(device_id)
    if tail is None:
        return False
    return tail in NULLMOTH_DEVICE_IDS or int(tail, 16) >= 0x1E00


def is_turing_device_id(device_id) -> bool:
    """True for the Turing ids whose GSP needs ``nvrmsettle=10000`` before display."""
    tail = _nvidia_tail(device_id)
    if tail is None:
        return False
    value = int(tail, 16)
    return 0x1E00 <= value <= 0x1FFF or 0x2180 <= value <= 0x21FF


# Resource: https://en.wikipedia.org/wiki/Graphics_Core_Next
AMDCodenames = [
    "Hainan",
    "Oland",
    "Cape Verde",
    "Pitcairn",
    "Tahiti",
    "Bonaire",
    "Hawaii",
    "Tonga",
    "Fiji"
]