"""Recover saved Wi-Fi keys so itlwm can auto-connect at boot -- for a GUI host.

Terminal menu version removed. Three deliberate changes drive everything below.

1. Consent is a parameter, never a prompt. Nothing in this file reads a
   terminal, writes one, or blocks on a human. A GUI asks first, then calls in.
2. Key material is read-only and never displayed. The OS commands below print
   plaintext PSKs on their stdout. stdout is captured into a variable, parsed,
   and stored in a field that is excluded from every repr. It is never passed to
   a sink, a log line, an exception message, or ``__repr__``. Anything a human
   may see is either a count or an SSID, and SSIDs are attacker-influenceable
   (they come from nearby access points), so every one is sanitised for display
   even though only the exact original is ever handed to a subprocess.
3. Enumeration is separate from recovery. ``list_networks()`` touches names
   only; ``recover_passwords()`` touches keys. The GUI can render "found 4
   networks" and ask for consent before the second call exists to be made.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import subprocess

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from ocengine import runtime, utils

# Wall-clock ceilings. A hung child would otherwise hold the GUI's worker
# thread forever, and on macOS the keychain dialog is waiting on a human, so
# the key-recovery budget is the longer one and is caller-tunable.
COMMAND_TIMEOUT = 15.0
KEYCHAIN_TIMEOUT = 60.0

# Upper bounds, so one call cannot open hundreds of keychain dialogs.
MAX_CANDIDATES = 32
MAX_PROFILES = 16
MAX_CONSECUTIVE_FAILURES = 3

RETURN_CODE_TIMEOUT = -1
RETURN_CODE_MISSING = 1

# Display sanitising patterns. An SSID may legitimately contain almost any
# printable character, so these only remove what could forge a log line --
# never what is needed to look the profile up. A PSK is never rendered at all.
_ANSI_RE = re.compile(r"\033\[[0-9;?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Zero-width joiners, bidi overrides (U+202A-U+202E) and line/paragraph
# separators: an SSID is broadcast by a nearby access point, so it can carry
# U+202E and make a rendered log line read differently from the bytes it
# contains (Trojan-source style).
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2028\u2029\u2060-\u2064\ufeff]")

_SOURCE_MACOS = "Darwin"
_SOURCE_WINDOWS = "Windows"
_SOURCE_LINUX = "Linux"
_SUPPORTED_OS = (_SOURCE_MACOS, _SOURCE_WINDOWS, _SOURCE_LINUX)

# nmcli reports this prefix for Wi-Fi connections; anything else (wired, VPN,
# PPPoE, bluetooth pan) has no PSK to recover and must not be handed to
# --show-secrets.
_NMCLI_WIRELESS_PREFIX = "802-11-wireless"

# Leading token of the netsh header that introduces a profile block.
_NPSH_PROFILES_HEADER = "user profiles for"


def redacted_ssid(value: object, limit: int = 48) -> str:
    """Return a display-safe form of an SSID.

    Names are not secret, so this is log-injection hygiene only: no escape
    sequences, no control characters, no invisible/bidi codepoints, no unbounded
    length. Never apply this to a value used as a command argument -- the exact
    original string is what the OS lookup needs.
    """
    text = value if isinstance(value, str) else repr(value)
    text = _ANSI_RE.sub("", text)
    text = _INVISIBLE_RE.sub("", text)
    text = _CONTROL_RE.sub(" ", text)
    text = text.strip()
    if not text:
        return "<unnamed>"
    if len(text) > limit:
        return text[: limit - 1] + "\u2026"
    return text


@dataclass(frozen=True)
class _CommandResult:
    """Captured output of one bounded subprocess. Content is never logged."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 1
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass(frozen=True)
class NetworkCandidate:
    """One saved wireless profile, as named by the OS. Carries no key."""

    ssid: str
    source_os: str = ""
    interface: str = ""

    def __repr__(self) -> str:
        return "NetworkCandidate(ssid={!r}, source_os={!r}, interface={!r})".format(
            redacted_ssid(self.ssid), self.source_os, self.interface
        )


@dataclass(frozen=True)
class WifiProfile:
    """A recovered profile. ``password`` is deliberately absent from repr/str."""

    ssid: str
    password: str = field(default="", repr=False, compare=False)
    source_os: str = ""
    interface: str = ""
    authentication: str = ""

    @property
    def has_key(self) -> bool:
        return bool(self.password)

    def as_tuple(self) -> tuple[str, str]:
        """(ssid, password) -- the shape upstream wrote into the Info.plist.

        A migration affordance for callers converted from the old tuple list.
        The password is reachable this way exactly as it is via ``.password``;
        neither path appears in repr, str, or any log line.
        """
        return self.ssid, self.password

    def __getitem__(self, index: int) -> str:
        # Supports the legacy ``profile[0]`` / ``profile[1]`` pair access that
        # kext_maestro used, so it does not need restructuring to migrate.
        return self.as_tuple()[index]

    def __repr__(self) -> str:
        return (
            "WifiProfile(ssid={!r}, source_os={!r}, interface={!r}, "
            "authentication={!r}, password=<redacted>)"
        ).format(
            redacted_ssid(self.ssid),
            self.source_os,
            self.interface,
            self.authentication,
        )


@dataclass
class ExtractionResult:
    """Outcome of one recovery pass, including what could not be completed.

    ``denied`` carries SSIDs whose keychain authorisation was refused or timed
    out (macOS). ``partial`` means the caller got fewer profiles than the target
    and may retry with different networks.
    """

    profiles: list[WifiProfile] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    candidates_seen: int = 0
    source_os: str = ""
    partial: bool = False
    stopped_reason: str = ""

    @property
    def recovered(self) -> int:
        return len(self.profiles)

    def __iter__(self):
        return iter(self.profiles)

    def __getitem__(self, index):
        # ``result[0]`` is a WifiProfile, so the legacy ``result[0][0]`` /
        # ``result[0][1]`` pair access keeps working for a migrated caller.
        return self.profiles[index]

    def __len__(self) -> int:
        return len(self.profiles)

    def __repr__(self) -> str:
        return (
            "ExtractionResult(source_os={!r}, candidates_seen={}, recovered={}, "
            "denied={}, failed={}, skipped={}, partial={}, stopped_reason={!r}, "
            "keys=<redacted>)"
        ).format(
            self.source_os,
            self.candidates_seen,
            self.recovered,
            len(self.denied),
            len(self.failed),
            len(self.skipped),
            self.partial,
            self.stopped_reason,
        )


class WifiProfileExtractor:
    """Enumerates saved wireless networks and recovers their PSKs.

    Public surface, all of it non-blocking:

        list_networks()                        -> list[NetworkCandidate]   # names
        recover_passwords(candidates, consent) -> ExtractionResult          # keys
        get_profiles(consent, selection, max_networks, interactive) -> ExtractionResult

    ``get_profiles()`` defaults to ``consent=False``, which is a total no-op:
    callers that have not asked the user get an empty result and no subprocess
    runs. ``recover_passwords()`` requires consent positionally, so it cannot be
    called by accident.

    ``ExtractionResult`` is iterable, sized and indexable over its profiles, and
    each profile supports ``.ssid`` / ``.password`` as well as the legacy
    ``[0]`` / ``[1]`` pair access -- so a caller written against the old
    ``(ssid, password)`` tuple list migrates by name, not by restructuring.
    """

    def __init__(
        self,
        os_name: str | None = None,
        command_timeout: float = COMMAND_TIMEOUT,
        keychain_timeout: float = KEYCHAIN_TIMEOUT,
        max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
    ) -> None:
        self.utils = utils.Utils()
        self.os_name = os_name or platform.system()
        self.command_timeout = float(command_timeout)
        self.keychain_timeout = float(keychain_timeout)
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))

    # ---- output boundary -------------------------------------------------
    # Everything user-visible funnels through these two. Neither accepts a
    # password, and the only strings passed in are counts, phase names, and
    # redacted_ssid() output.

    def _log(self, message: str, level: str = "info") -> None:
        self.utils.log_message(message, level)

    def _say(self, title: str, body: str = "", level: str = "info") -> None:
        self.utils.notify(title, body, level)

    # ---- subprocess boundary ---------------------------------------------

    def _run_argv(self, argv: Sequence[str], *, timeout: float, label: str) -> _CommandResult:
        """Run one argv list, bounded, detached from any terminal.

        ``shell=False`` is stated rather than inherited, stdin is /dev/null so a
        child can never read (or wait on) our terminal, and both pipes are
        captured instead of echoed -- these commands print plaintext keys.
        Output content is never logged, only exit status.
        """
        if isinstance(argv, str):
            raise TypeError("argv must be a list; a shell string is never accepted")

        command = list(argv)
        if not command or not all(isinstance(item, str) for item in command):
            raise TypeError("argv must be a non-empty list of str")

        try:
            completed = subprocess.run(
                command,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            # TimeoutExpired keeps the captured (secret-bearing) output on the
            # instance and in its message, so never str() it into a sink.
            self._log(
                "{} timed out after {:.0f}s.".format(label, timeout),
                level="warning",
            )
            return _CommandResult(returncode=RETURN_CODE_TIMEOUT, timed_out=True)
        except (OSError, ValueError) as exception:
            self._log(
                "{} did not run ({}).".format(label, type(exception).__name__),
                level="debug",
            )
            return _CommandResult(returncode=RETURN_CODE_MISSING)

        return _CommandResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
        )

    # ---- classification helpers (pure) ------------------------------------

    def get_authentication_type(self, authentication_type: str) -> str | None:
        authentication_type = authentication_type.lower()

        for open_type in ("none", "owe", "open"):
            if open_type in authentication_type:
                return "open"

        if "wep" in authentication_type or "shared" in authentication_type:
            return "wep"

        if "wpa" in authentication_type or "sae" in authentication_type:
            return "wpa"

        return None

    def validate_wifi_password(self, authentication_type: str | None = None, password: str | None = None) -> str | None:
        """Return the key only if it is usable by itlwm, else None.

        Logs the security class and nothing else -- not the key, not its length.
        """
        if password is None:
            return None

        self._log(
            "Checking a saved key against {} rules.".format(authentication_type or "unknown"),
            level="debug",
        )

        if authentication_type is None:
            return password

        if authentication_type == "open":
            return ""

        try:
            password.encode("ascii")
        except UnicodeEncodeError:
            return None

        if 8 <= len(password) <= 63 and all(32 <= ord(char) <= 126 for char in password):
            return password

        return None

    # ---- per-OS key recovery (SECRET-RETURNING) --------------------------
    # Each returns (plaintext PSK or None, security class). The key goes straight
    # into WifiProfile.password and nowhere else. Do not log or format it.

    def get_wifi_password_macos(self, ssid: str) -> tuple[str | None, str]:
        result = self._run_argv(
            ["security", "find-generic-password", "-wa", ssid],
            timeout=self.keychain_timeout,
            label="Keychain lookup",
        )

        if not result.ok:
            return None, ""

        payload = result.stdout.strip()
        if not payload:
            return None, ""

        try:
            parsed = json.loads(payload)
            password = parsed.get("password") if isinstance(parsed, dict) else None
        except ValueError:
            # The common shape: -w prints the bare key on stdout.
            password = payload

        if password is None:
            return None, ""

        # macOS stores every Wi-Fi item the same way, so upstream assumed WPA.
        key = self.validate_wifi_password("wpa", str(password))
        return key, "wpa" if key else ""

    def get_wifi_password_windows(self, ssid: str) -> tuple[str | None, str]:
        result = self._run_argv(
            ["netsh", "wlan", "show", "profile", ssid, "key=clear"],
            timeout=self.command_timeout,
            label="Saved-profile lookup",
        )

        if not result.ok:
            return None, ""

        authentication_type = None
        password = None

        for line in result.stdout.splitlines():
            # partition() on the first colon only. netsh renders
            # "Key Content : <psk>", and a PSK may itself contain colons, which
            # the old split(":")[1] silently truncated.
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            if authentication_type is None and key.endswith("Authentication"):
                authentication_type = self.get_authentication_type(value)
            elif key.endswith("Key Content"):
                password = value or None

        key = self.validate_wifi_password(authentication_type, password)
        return key, authentication_type or ""

    def get_wifi_password_linux(self, ssid: str) -> tuple[str | None, str]:
        result = self._run_argv(
            ["nmcli", "--show-secrets", "connection", "show", ssid],
            timeout=self.command_timeout,
            label="Saved-connection lookup",
        )

        if not result.ok:
            return None, ""

        authentication_type = None
        password = None

        for line in result.stdout.splitlines():
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            if key.endswith("802-11-wireless-security.key-mgmt"):
                authentication_type = self.get_authentication_type(value)
            elif key.endswith("802-11-wireless-security.psk"):
                password = value or None

        key = self.validate_wifi_password(authentication_type, password)
        return key, authentication_type or ""

    # ---- enumeration: names only, no key material -------------------------

    def list_networks(self, max_candidates: int | None = None) -> list[NetworkCandidate]:
        """Saved wireless profiles on this device, without touching any key.

        Safe to call before asking the user anything: this only reads profile
        names, which is what the GUI needs in order to show "found 4 networks"
        and request consent for the recovery pass.
        """
        limit = self._bounded(max_candidates, MAX_CANDIDATES, default=MAX_CANDIDATES)

        if self.os_name not in _SUPPORTED_OS:
            self._log(
                "Reading saved Wi-Fi profiles is not supported on {}.".format(self.os_name),
                level="warning",
            )
            return []

        self.utils.head("Detecting WiFi Profiles")

        if self.os_name == _SOURCE_WINDOWS:
            candidates = self._list_windows()
        elif self.os_name == _SOURCE_LINUX:
            candidates = self._list_linux()
        else:
            candidates = self._list_macos()

        unique: list[NetworkCandidate] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            identity = (candidate.ssid, candidate.interface)
            if candidate.ssid and identity not in seen:
                seen.add(identity)
                unique.append(candidate)

        if len(unique) > limit:
            self._log(
                "Capping the recovery pass at {} of {} saved networks.".format(limit, len(unique)),
                level="warning",
            )
            unique = unique[:limit]

        self._log("Found {} saved wireless network(s).".format(len(unique)))
        return unique

    def _list_macos(self) -> list[NetworkCandidate]:
        candidates: list[NetworkCandidate] = []

        for interface in self.get_wifi_interfaces():
            result = self._run_argv(
                ["networksetup", "-listpreferredwirelessnetworks", interface],
                timeout=self.command_timeout,
                label="Preferred-network list",
            )

            if not result.ok or "Preferred networks on" not in result.stdout:
                continue

            for line in result.stdout.splitlines()[1:]:
                name = line.strip()
                # networksetup repeats the device name as the last line.
                if name and name != interface:
                    candidates.append(NetworkCandidate(name, _SOURCE_MACOS, interface))

        if not candidates:
            self._log("No saved wireless networks were reported by networksetup.", level="warning")

        return candidates

    def _list_windows(self) -> list[NetworkCandidate]:
        result = self._run_argv(
            ["netsh", "wlan", "show", "profiles"],
            timeout=self.command_timeout,
            label="Saved-profile list",
        )

        if not result.ok:
            self._log("netsh reported no saved Wi-Fi profiles.", level="warning")
            return []

        candidates: list[NetworkCandidate] = []
        interface = ""

        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if key.lower().startswith(_NPSH_PROFILES_HEADER):
                # netsh writes this header in three shapes across versions:
                #   User profiles for : Wi-Fi
                #   User profiles for Wi-Fi
                #   User profiles for Interface "Wi-Fi"
                # Taking the text after the prefix when there is no colon keeps
                # the adapter name instead of losing it.
                tail = value or stripped[len(_NPSH_PROFILES_HEADER):].strip()
                tail = tail.lstrip(":").strip()
                if tail.lower().startswith("interface"):
                    tail = tail[len("interface"):].strip()
                tail = tail.strip("\"'").rstrip(".").strip()
                if tail and "all devices" not in tail.lower():
                    interface = tail
            elif key.endswith("All User Profile") and value:
                candidates.append(NetworkCandidate(value, _SOURCE_WINDOWS, interface))

        if not candidates:
            self._log("netsh listed no Wi-Fi profiles for this device.", level="warning")

        return candidates

    def _list_linux(self) -> list[NetworkCandidate]:
        result = self._run_argv(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"],
            timeout=self.command_timeout,
            label="Saved-connection list",
        )

        if not result.ok:
            self._log("NetworkManager reported no saved connections.", level="warning")
            return []

        candidates: list[NetworkCandidate] = []

        for line in result.stdout.splitlines():
            fields = self._split_terse(line)
            if not fields:
                continue

            name = fields[0]
            connection_type = fields[1] if len(fields) > 1 else ""
            device = fields[2] if len(fields) > 2 else ""

            # A single field means an nmcli too old to answer for TYPE, in which
            # case fall back to upstream behaviour: try every saved connection.
            if len(fields) == 1 or connection_type.startswith(_NMCLI_WIRELESS_PREFIX):
                candidates.append(NetworkCandidate(name, _SOURCE_LINUX, device))

        if not candidates:
            self._log("NetworkManager has no saved wireless connections.", level="warning")

        return candidates

    @staticmethod
    def _split_terse(line: str, expected: int = 3) -> list[str]:
        """Split one ``nmcli -t`` row on its *unescaped* colons.

        Terse output escapes a colon inside a value as ``\\:``, so a connection
        name containing a colon survives intact rather than being cut in half
        and later looked up under a wrong name.
        """
        fields: list[str] = []
        current: list[str] = []
        index = 0

        while index < len(line):
            char = line[index]
            if char == "\\" and index + 1 < len(line):
                nxt = line[index + 1]
                current.append(nxt if nxt in (":", "\\") else line[index : index + 2])
                index += 2
                continue
            if char == ":" and len(fields) < expected - 1:
                fields.append("".join(current))
                current = []
                index += 1
                continue
            current.append(char)
            index += 1

        fields.append("".join(current))
        return [field.strip() for field in fields]

    def get_wifi_interfaces(self) -> list[str]:
        """macOS only: device ids of hardware ports that expose preferred networks."""
        result = self._run_argv(
            ["networksetup", "-listallhardwareports"],
            timeout=self.command_timeout,
            label="Hardware-port list",
        )

        if not result.ok:
            return []

        interfaces: list[str] = []

        for block in result.stdout.split("\n\n"):
            if "Device: en" not in block:
                continue

            device = block.split("Device: en", 1)[1].split("\n")[0].strip()
            if not device.isdigit():
                continue

            interface = "en{}".format(device)
            probe = self._run_argv(
                ["networksetup", "-listpreferredwirelessnetworks", interface],
                timeout=self.command_timeout,
                label="Interface probe",
            )

            if probe.ok and "Preferred networks on" in probe.stdout:
                interfaces.append(interface)

        if not interfaces:
            self._log("No Wi-Fi interface detected via networksetup.", level="warning")

        return interfaces

    # ---- key recovery: requires consent ----------------------------------

    def recover_passwords(
        self,
        candidates: Iterable[NetworkCandidate],
        consent: bool,
        max_networks: int | None = None,
    ) -> ExtractionResult:
        """Recover PSKs for the supplied candidates.

        ``consent`` must come from the user having been asked; without it this
        returns an empty result and no subprocess is launched.
        """
        working_set = [c for c in candidates if isinstance(c, NetworkCandidate) and c.ssid]
        result = ExtractionResult(source_os=self.os_name, candidates_seen=len(working_set))

        if not consent:
            result.stopped_reason = "consent_not_given"
            result.skipped = [redacted_ssid(c.ssid) for c in working_set]
            self._log("Recovery not attempted: the caller did not supply consent.")
            return result

        if not working_set:
            result.stopped_reason = "no_networks_found"
            self._log("No saved wireless networks to process.", level="warning")
            return result

        limit = min(self._bounded(max_networks, MAX_PROFILES, default=len(working_set)), len(working_set))
        fetch = self._key_source()

        if fetch is None:
            result.stopped_reason = "unsupported_platform"
            self._log(
                "No key-recovery backend for {}.".format(self.os_name),
                level="warning",
            )
            return result

        self.utils.head("Recovering Saved WiFi Keys")

        if self.os_name == _SOURCE_MACOS:
            # The old text asked the user to "enter your administrator name and
            # password", which this app never does. macOS itself owns that
            # dialog; say what will actually happen.
            body = (
                "macOS may show a Keychain Access dialog for each network. Choose Allow or "
                "Always Allow to read the saved key, or Deny to skip that network. BlackDream "
                "never asks for your administrator name or password."
            )
            self._say("Keychain access required", body, level="info")
            self._log(body, level="info")

        steps = [redacted_ssid(c.ssid) for c in working_set[:limit]]
        consecutive_failures = 0

        for index, candidate in enumerate(working_set[:limit]):
            self.utils.progress_bar("Recovering saved keys", steps, index)

            name = redacted_ssid(candidate.ssid)
            recovered_key = None
            authentication = ""
            failure_note = ""

            try:
                # The raw candidate.ssid is passed unchanged, as one argv
                # element. The redacted form is used for display only.
                recovered_key, authentication = fetch(candidate.ssid)
            except Exception as exception:
                # type name, never str(exception): a child-process exception can
                # carry the captured secret in its own message.
                failure_note = " ({})".format(type(exception).__name__)

            if recovered_key:
                consecutive_failures = 0
                if not any(profile.ssid == candidate.ssid for profile in result.profiles):
                    result.profiles.append(
                        WifiProfile(
                            ssid=candidate.ssid,
                            password=recovered_key,
                            source_os=self.os_name,
                            interface=candidate.interface,
                            authentication=authentication,
                        )
                    )
                    self._log("Recovered a saved key for '{}'.".format(name))
                continue

            if authentication == "open":
                # Open / OWE stores no key at all: nothing was denied and there
                # was nothing to recover, so this is not counted as a failure.
                self._log("'{}' is an open network and stores no key.".format(name))
                continue

            if self.os_name == _SOURCE_MACOS:
                result.denied.append(name)
                consecutive_failures += 1
                self._log(
                    "Keychain access was not granted for '{}', so no key was read.".format(name),
                    level="warning",
                )
            else:
                result.failed.append(name)
                self._log(
                    "No usable saved key for '{}'.{}".format(name, failure_note),
                    level="warning",
                )

            if self.os_name == _SOURCE_MACOS and consecutive_failures >= self.max_consecutive_failures:
                # Was a terminal "Continue trying? (Yes/no)" prompt. Return the
                # shortfall and let the GUI decide whether to retry.
                result.stopped_reason = "keychain_denied"
                result.partial = True
                result.skipped = [redacted_ssid(c.ssid) for c in working_set[index + 1 : limit]]
                self._log(
                    "Stopped after {} consecutive keychain denials; {} network(s) left untried.".format(
                        consecutive_failures, len(result.skipped)
                    ),
                    level="warning",
                )
                break

        self.utils.progress_bar("Recovering saved keys", steps, len(steps), done=True)

        result.skipped.extend(redacted_ssid(c.ssid) for c in working_set[limit:])

        if not result.profiles:
            result.partial = bool(result.denied or result.failed)
            if result.denied:
                result.stopped_reason = result.stopped_reason or "keychain_denied"
            elif not result.stopped_reason:
                result.stopped_reason = "no_keys_recovered"
        elif len(result.profiles) < limit and not result.partial:
            result.partial = True
            result.stopped_reason = result.stopped_reason or "incomplete"

        if result.partial:
            self._log(
                "Recovered {} of {} requested network(s): {} denied, {} without a usable key, {} not attempted.".format(
                    len(result.profiles),
                    limit,
                    len(result.denied),
                    len(result.failed),
                    len(result.skipped),
                ),
                level="warning",
            )

        self.utils.head("WiFi Profile Extractor")
        self._log(
            "Recovery finished: {} key(s) from {} candidate(s).".format(len(result.profiles), result.candidates_seen)
        )

        return result

    def _key_source(self) -> Callable[[str], tuple[str | None, str]] | None:
        """The per-OS key fetcher for this platform, or None if unsupported.

        Timeouts live on the fetchers themselves (keychain_timeout on macOS,
        where the command waits on a human; command_timeout elsewhere, where it
        does not).
        """
        if self.os_name == _SOURCE_WINDOWS:
            return self.get_wifi_password_windows
        if self.os_name == _SOURCE_LINUX:
            return self.get_wifi_password_linux
        if self.os_name == _SOURCE_MACOS:
            return self.get_wifi_password_macos
        return None

    @staticmethod
    def _bounded(requested: int | None, ceiling: int, *, default: int) -> int:
        value = default if requested is None else requested
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return max(1, min(value, ceiling))

    # ---- one-shot entry point (the app layer calls this, then hands the
    # pairs to kext_maestro.apply_wifi_profiles) ---------------------------

    def get_profiles(
        self,
        consent: bool = False,
        selection: Sequence[str] | None = None,
        max_networks: int | None = None,
        interactive: bool | None = None,
    ) -> ExtractionResult:
        """Enumerate then recover, gated on ``consent``.

        ``consent=False`` (the default) runs no subprocess at all. ``selection``
        is the list of SSIDs the user ticked in the GUI; names that are not
        present in this device's saved profiles are logged and dropped.

        ``interactive`` is accepted only so that a caller written against the
        old prompt-based contract does not crash. It never prompts (there is
        nothing to prompt) and it never grants consent; passing it logs a warning
        and is otherwise ignored.
        """
        if interactive is not None:
            self._log(
                "'interactive' is obsolete: this module never prompts, and it "
                "never scans without consent=True. Ignored.",
                level="warning",
            )

        if not consent:
            self._log("Wi-Fi profile scan skipped: no consent supplied.")
            return ExtractionResult(source_os=self.os_name, stopped_reason="consent_not_given")

        candidates = self.list_networks()

        if selection is not None:
            candidates = self._restrict(candidates, selection)

        return self.recover_passwords(candidates, consent=True, max_networks=max_networks)

    def _restrict(self, candidates: list[NetworkCandidate], selection: Sequence[str] | None) -> list[NetworkCandidate]:
        if selection is None:
            return candidates

        wanted = [name for name in selection if isinstance(name, str) and name.strip()]
        wanted_set = set(wanted)
        picked = [candidate for candidate in candidates if candidate.ssid in wanted_set]
        matched = {candidate.ssid for candidate in picked}

        for name in wanted:
            if name not in matched:
                self._log("'{}' is not a saved network on this device.".format(redacted_ssid(name)), level="debug")

        if not picked:
            self._log("None of the requested networks matched a saved profile.", level="warning")

        return picked


# Upstream ``ask_network_count``, ``process_networks`` and the three
# ``get_preferred_networks_*`` methods are gone: each of them mixed enumeration,
# a terminal prompt and printing into one call. Their roles are now
# ``list_networks()`` (names), ``recover_passwords()`` (keys, consent required)
# and ``get_profiles()`` (both, consent-gated). ``kext_maestro`` calls the last
# one and now receives an ExtractionResult, not a list of (ssid, password)
# tuples -- iterate it or read ``.profiles``, and use ``profile.ssid`` /
# ``profile.password``.


if __name__ == "__main__":
    # Headless smoke run for developers. Sink events become log records, so this
    # shows what a GUI host would receive. It deliberately stops at enumeration:
    # no key is read without an explicit consent=True.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    runtime.set_sink(runtime.LoggingSink(logging.getLogger("ocengine")))

    _extractor = WifiProfileExtractor()
    _preview = _extractor.list_networks()

    logging.getLogger("ocengine").info(
        "Enumerated %d saved network(s); no keys were read. recover_passwords(candidates, consent=True) does that.",
        len(_preview),
    )
