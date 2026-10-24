"""Named shortcuts to a machine's report and its last build folder.

A profile is a label, not an identity. It remembers where the hardware report and
the EFI folder are so the next build does not have to ask again; it deliberately
holds no serial number, MLB, UUID or ROM value, because those describe the machine
and would turn a convenience file into personal data.

The file is local, plain JSON, and written atomically. A corrupt file reads as no
profiles rather than as an error: losing shortcuts is annoying, but refusing to
start because one record is malformed is worse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from blackdream.core import state_store
from ocengine import paths

FORMAT = 1


@dataclass(frozen=True)
class Profile:
    name: str
    report: str
    efi_folder: str = ""
    release: str = ""
    updated: str = ""

    def to_dict(self) -> dict:
        """Exactly the five local fields; never an identity field."""
        return {
            "name": self.name,
            "report": self.report,
            "efi_folder": self.efi_folder,
            "release": self.release,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, data) -> "Profile | None":
        """Build a profile from stored data, or None when it is malformed."""
        if not isinstance(data, dict):
            return None
        name = data.get("name")
        report = data.get("report")
        if not isinstance(name, str) or not isinstance(report, str):
            return None
        name = name.strip()
        if not name or not report.strip():
            return None
        optional = {}
        for field in ("efi_folder", "release", "updated"):
            value = data.get(field, "")
            if not isinstance(value, str):
                return None
            optional[field] = value
        return cls(name=name, report=report, **optional)


def default_path() -> Path:
    return paths.current().state_dir / "profiles.json"


def _key(profile: Profile) -> tuple[str, str]:
    return profile.name.casefold(), profile.name


def _ordered(profiles) -> list[Profile]:
    return sorted(profiles, key=_key)


def load(path=None) -> list[Profile]:
    """Read the stored profiles; absent, corrupt or unknown versions read as []."""
    target = Path(path) if path is not None else default_path()
    document = state_store.read_json(target)
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        return []
    records = document.get("profiles")
    if not isinstance(records, list):
        return []

    # A duplicate name is resolved the way a later save would resolve it: the last
    # record wins. Names are compared case-insensitively for the same reason.
    kept: dict[str, Profile] = {}
    for record in records:
        profile = Profile.from_dict(record)
        if profile is not None:
            kept[profile.name.casefold()] = profile
    return _ordered(kept.values())


def save(profiles, path=None) -> Path:
    """Write the profiles sorted by name, atomically; returns the file path."""
    target = Path(path) if path is not None else default_path()
    document = {
        "format": FORMAT,
        "profiles": [profile.to_dict() for profile in _ordered(profiles)],
    }
    state_store.atomic_write_text(
        target, json.dumps(document, indent=2) + "\n")
    return target


def upsert(profiles, profile: Profile) -> list[Profile]:
    """Replace a same-named profile, case-insensitively, or append it."""
    key = profile.name.casefold()
    kept = [existing for existing in profiles if existing.name.casefold() != key]
    kept.append(profile)
    return _ordered(kept)


def remove(profiles, name: str) -> list[Profile]:
    """Drop every profile whose name matches, case-insensitively."""
    key = name.strip().casefold()
    return _ordered(
        profile for profile in profiles if profile.name.casefold() != key)


def find(profiles, name: str) -> Profile | None:
    """The profile with this name, ignoring case, or None."""
    key = name.strip().casefold()
    for profile in profiles:
        if profile.name.casefold() == key:
            return profile
    return None
