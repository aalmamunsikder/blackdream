"""macOS version selection, extracted from the reference CLI's prompt loop.

Upstream computed the suggestion and the listing inline in `select_macos_version`,
mixed with terminal printing, and walked version numbers with string slices
(`int(version[:2])`) that break on any single-digit Darwin major. Both use
``parse_darwin_version`` here instead, which is equivalent for every real release.

Native ranges arrive as ``(min_darwin, max_darwin)`` from the compatibility engine;
OCLP ranges arrive reversed, as ``(max_darwin, min_darwin)``, which is why the two
are unpacked separately.
"""

from dataclasses import dataclass

from ocengine.datasets import os_data
from ocengine.utils import Utils

_u = Utils()

# Device classes whose per-device ceiling can lower the suggested version.
_CEILING_DEVICE_TYPES = ("GPU", "Network", "Bluetooth", "SD Controller")

# Integrated GPUs that cannot drive a newer macOS than this, whatever the report says.
_COMET_LAKE_CEILING = "22.99.99"
_CANNON_LAKE_CEILING = "21.99.99"


@dataclass(frozen=True)
class VersionOption:
    darwin_major: int
    name: str
    requires_oclp: bool
    is_suggested: bool

    @property
    def value(self) -> str:
        return "{}.99.99".format(self.darwin_major)


def suggest(hardware_report: dict, native_range: tuple[str, str]) -> str:
    """The newest macOS that every present device class still supports natively."""
    suggested = native_range[1]

    for device_type in _CEILING_DEVICE_TYPES:
        for props in hardware_report.get(device_type, {}).values():
            compatibility = props.get("Compatibility", (None, None))
            if compatibility == (None, None):
                continue

            if device_type == "GPU" and props.get("Device Type") == "Integrated GPU":
                device_id = props.get("Device ID", "")[5:]
                if props.get("Manufacturer") == "AMD" or device_id.startswith(("59", "87C0")):
                    suggested = _COMET_LAKE_CEILING
                elif device_id.startswith(("09", "19")):
                    suggested = _CANNON_LAKE_CEILING

            if _u.parse_darwin_version(suggested) > _u.parse_darwin_version(compatibility[0]):
                suggested = compatibility[0]

    while "Beta" in (os_data.get_macos_name_by_darwin(suggested) or ""):
        major, minor, patch = _u.parse_darwin_version(suggested)
        suggested = "{}.{}.{}".format(major - 1, minor, patch)

    return suggested


def options(native_range: tuple[str, str],
            oclp_range: tuple[str, str] | None,
            suggested: str | None = None) -> list[VersionOption]:
    """Every selectable major version between the oldest supported release and the
    newest one this machine can reach, natively or through OCLP."""
    suggested = suggested or suggest({}, native_range)
    suggested_major = _u.parse_darwin_version(suggested)[0]

    oclp_min = _u.parse_darwin_version(oclp_range[1])[0] if oclp_range else 99
    oclp_max = _u.parse_darwin_version(oclp_range[0])[0] if oclp_range else 0

    lowest = min(_u.parse_darwin_version(native_range[0])[0], oclp_min)
    highest = max(_u.parse_darwin_version(native_range[1])[0], oclp_max)

    return [
        VersionOption(
            darwin_major=major,
            name=os_data.get_macos_name_by_darwin(str(major)) or "macOS {}".format(major),
            requires_oclp=oclp_min <= major <= oclp_max,
            is_suggested=major == suggested_major,
        )
        for major in range(lowest, highest + 1)
    ]


def needs_oclp(darwin_version: str, oclp_range: tuple[str, str] | None,
               native_range: tuple[str, str]) -> bool:
    """True when the chosen version is only reachable by patching root graphics."""
    if not oclp_range:
        return False
    target = _u.parse_darwin_version(darwin_version)
    return (_u.parse_darwin_version(oclp_range[1]) <= target <= _u.parse_darwin_version(oclp_range[0])
            and not (_u.parse_darwin_version(native_range[0]) <= target <= _u.parse_darwin_version(native_range[1])))
