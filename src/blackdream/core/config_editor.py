"""Native editing for the built ``config.plist``.

This replaces handing the file to an external configurator. The document model is
deliberately schema-free on read: every key in the plist is editable, including
keys newer than this build, because the point of a configurator is that an
OpenCore update does not make yesterday's file unopenable. A pinned copy of
OpenCore's own ``Sample.plist`` is used only to suggest defaults when a key is
added and to offer the standard children of a dictionary.

Validation is delegated to OpenCore's ``ocvalidate``, whose bytes are pinned per
platform. It is resolved from the app's tools directories, or fetched once from
the pinned OpenCorePkg release and verified member-by-member before it is made
executable. Nothing here executes a binary that has not matched its digest.
"""

from __future__ import annotations

import copy
import hashlib
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path

from ocengine import paths as engine_paths
from ocengine.fatal import EngineError

OPEN_CORE_VERSION = "1.0.8"
OCVALIDATE_ARCHIVE_URL = (
    "https://github.com/acidanthera/OpenCorePkg/releases/download/"
    "{}/OpenCore-{}-RELEASE.zip".format(OPEN_CORE_VERSION, OPEN_CORE_VERSION))
OCVALIDATE_ARCHIVE_SHA256 = (
    "2011e8b7216ecb2645d97ea710df965947edd406846e92050b9bc4190be6d27b")
OCVALIDATE_SAMPLE = "OpenCore-1.0.8-Sample.plist"

# platform -> (install name, archive member, member sha256)
OCVALIDATE_ASSETS = {
    "darwin": (
        "ocvalidate",
        "Utilities/ocvalidate/ocvalidate",
        "c76f907d5caad299889a2314ae68f03cd8538ad53f65a3c2c7c95ae0d0bb0b38",
    ),
    "linux": (
        "ocvalidate.linux",
        "Utilities/ocvalidate/ocvalidate.linux",
        "3411f3b7e645f94c7ba602687d42ce6bf4e5ee560f50c3f2ca134e26dfe394ab",
    ),
    "win32": (
        "ocvalidate.exe",
        "Utilities/ocvalidate/ocvalidate.exe",
        "f459053cefdf1b2ff8c1d74d61d9dc5bb30ce72a4fcbf15bb29333e77d8d045f",
    ),
}

PLIST_TYPES = (
    "boolean", "integer", "real", "string", "data", "dictionary", "array",
    "date",
)
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_VALIDATOR_OUTPUT = 512 * 1024


class ConfigEditorError(EngineError):
    code = "config.error"
    title = "The config.plist could not be handled"


class ConfigReadFailed(ConfigEditorError):
    code = "config.read_failed"
    title = "The config.plist could not be read"
    remediation = (
        "Choose a property list produced by OpenCore or BlackDream, not a partial "
        "or renamed file.",
        "If the file came from another tool, open it there once and export it again.",
    )


class ConfigWriteFailed(ConfigEditorError):
    code = "config.write_failed"
    title = "The config.plist could not be saved"
    remediation = (
        "Check that the folder is writable and the drive is still connected.",
        "The previous file is left in place; nothing is written if the save fails.",
    )


class OcvalidateUnavailable(ConfigEditorError):
    code = "config.validator_unavailable"
    title = "OpenCore's ocvalidate is not available"
    remediation = (
        "Place the pinned ocvalidate for this platform in the app tools directory, "
        "or allow the verified OpenCorePkg download.",
        "Do not put it in the package directory: engine code refuses anything on "
        "Python's import path.",
    )


class OcvalidateVerificationFailed(ConfigEditorError):
    code = "config.validator_verification_failed"
    title = "ocvalidate did not match its pinned digest"
    remediation = (
        "Nothing was executed. Remove the file from the tools directory and retry "
        "so the pinned OpenCorePkg copy can be installed.",
        "A locally built ocvalidate has different bytes; the pin has to be updated "
        "deliberately to trust it.",
    )
    recoverable = True


class OcvalidateDownloadFailed(ConfigEditorError):
    code = "config.validator_download_failed"
    title = "The pinned ocvalidate could not be fetched"
    remediation = (
        "Check the network and retry. The archive comes from the fixed OpenCorePkg "
        "release and is verified before use.",
        "Without ocvalidate the file can still be edited and saved; validation is "
        "the only part that is unavailable.",
    )


class OcvalidateRunFailed(ConfigEditorError):
    code = "config.validator_run_failed"
    title = "ocvalidate could not be run"
    remediation = (
        "The file can still be edited and saved; try validation again after the "
        "next build.",
        "If the binary was just installed, check that the tools directory is "
        "executable.",
    )


class SerialGenerationFailed(ConfigEditorError):
    code = "config.serial_generation_failed"
    title = "SMBIOS serials could not be generated"
    remediation = (
        "macserial is provided by OpenCorePkg and is resolved like iasl; check that "
        "the tools directory is intact.",
        "Change the model and retry, or set the PlatformInfo fields by hand.",
    )


def _platform_key() -> str:
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sample_plist() -> dict:
    """The pinned OpenCore 1.0.8 Sample.plist, warnings stripped."""
    resource = resources.files("blackdream").joinpath("data", OCVALIDATE_SAMPLE)
    with resource.open("rb") as handle:
        data = plistlib.load(handle)
    if not isinstance(data, dict):
        raise ConfigReadFailed(detail="The bundled OpenCore sample is not a dictionary.")
    return {key: value for key, value in data.items()
            if not key.startswith("#WARNING")}


def schema_at(path) -> object | None:
    """The sample value at ``path``, or None when the sample has no such key."""
    node = sample_plist()
    for part in path:
        if isinstance(node, dict):
            if part not in node:
                return None
            node = node[part]
        elif isinstance(node, list) and isinstance(part, int):
            if not 0 <= part < len(node):
                return None
            node = node[part]
        else:
            return None
    return node


def known_children(dict_path) -> list[tuple[str, object]]:
    """Standard child keys the sample suggests for a dictionary path."""
    node = schema_at(dict_path)
    if not isinstance(node, dict):
        return []
    return [(key, copy.deepcopy(value)) for key, value in node.items()
            if not key.startswith("#WARNING")]


def array_template(list_path) -> object | None:
    """A copy of the sample's first element, used when adding to an array."""
    node = schema_at(list_path)
    if isinstance(node, list) and node:
        return copy.deepcopy(node[0])
    return None


def type_name(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "real"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (bytes, bytearray)):
        return "data"
    if isinstance(value, dict):
        return "dictionary"
    if isinstance(value, list):
        return "array"
    if isinstance(value, datetime):
        return "date"
    return "unknown"


def format_value(value, limit: int = 160) -> str:
    kind = type_name(value)
    if kind == "boolean":
        return "true" if value else "false"
    if kind == "integer":
        return str(value)
    if kind == "real":
        return repr(value)
    if kind == "string":
        return value if len(value) <= limit else value[:limit] + "\u2026"
    if kind == "data":
        raw = bytes(value)
        shown = raw[:24]
        text = " ".join("{:02X}".format(byte) for byte in shown)
        if len(raw) > len(shown):
            text += " \u2026"
        return text or "(empty)"
    if kind == "dictionary":
        return "{} key{}".format(len(value), "" if len(value) == 1 else "s")
    if kind == "array":
        return "{} item{}".format(len(value), "" if len(value) == 1 else "s")
    if kind == "date":
        return value.isoformat()
    return str(value)


def data_to_hex(value: bytes) -> str:
    return " ".join("{:02X}".format(byte) for byte in bytes(value))


def hex_to_data(text: str) -> bytes:
    compact = "".join(text.split()).replace("0x", "").replace("0X", "")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("Data must be an even number of hexadecimal digits.") from exc


_ASCII_ESCAPES = {0x5C: "\\\\", 0x0A: "\\n", 0x0D: "\\r", 0x09: "\\t"}
_TEXT_ESCAPES = {"\\": 0x5C, "n": 0x0A, "r": 0x0D, "t": 0x09}
_HEX_DIGITS = "0123456789abcdefABCDEF"


def data_to_text(value: bytes) -> str:
    """Printable ASCII with ``\\xNN`` escapes, lossless for every byte."""
    parts = []
    for byte in bytes(value):
        if byte in _ASCII_ESCAPES:
            parts.append(_ASCII_ESCAPES[byte])
        elif 0x20 <= byte <= 0x7E:
            parts.append(chr(byte))
        else:
            parts.append("\\x{:02X}".format(byte))
    return "".join(parts)


def text_to_data(text: str) -> bytes:
    """The inverse of :func:`data_to_text`; tabs and newlines need escapes."""
    out = bytearray()
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\":
            code = ord(char)
            if not 0x20 <= code <= 0x7E:
                raise ValueError(
                    "Text mode accepts printable ASCII; use \\xNN for other "
                    "bytes.")
            out.append(code)
            index += 1
            continue
        if index + 1 >= len(text):
            raise ValueError(
                "The text ends with a lone backslash; write \\\\ for one.")
        escape = text[index + 1]
        if escape == "x":
            digits = text[index + 2:index + 4]
            if len(digits) != 2 or any(
                    digit not in _HEX_DIGITS for digit in digits):
                raise ValueError(
                    "\\x must be followed by exactly two hexadecimal digits.")
            out.append(int(digits, 16))
            index += 4
            continue
        if escape not in _TEXT_ESCAPES:
            raise ValueError("Unknown escape \\{}.".format(escape))
        out.append(_TEXT_ESCAPES[escape])
        index += 2
    return bytes(out)


def parse_value(kind: str, text: str):
    if kind != "string":
        text = text.strip()
    if kind == "boolean":
        lowered = text.lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
        raise ValueError("Boolean values are true or false.")
    if kind == "integer":
        try:
            return int(text, 0)
        except ValueError:
            try:
                return int(text, 10)
            except ValueError as exc:
                raise ValueError("Expected a whole number.") from exc
    if kind == "real":
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError("Expected a decimal number.") from exc
    if kind == "string":
        return text
    if kind == "data":
        return hex_to_data(text)
    if kind == "date":
        try:
            return datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("Expected an ISO 8601 date and time.") from exc
    raise ValueError("{} values cannot be edited as text.".format(kind))


def get_at(data, path):
    node = data
    for part in path:
        node = node[part]
    return node


def set_at(data, path, value) -> None:
    if not path:
        raise ValueError("Cannot replace the document root.")
    parent = get_at(data, path[:-1])
    last = path[-1]
    if isinstance(parent, dict):
        parent[last] = value
    elif isinstance(parent, list) and isinstance(last, int):
        if not 0 <= last < len(parent):
            raise IndexError(last)
        parent[last] = value
    else:
        raise TypeError("The parent is not a dictionary or array.")


def remove_at(data, path) -> None:
    if not path:
        raise ValueError("Cannot remove the document root.")
    parent = get_at(data, path[:-1])
    last = path[-1]
    if isinstance(parent, dict):
        del parent[last]
    elif isinstance(parent, list) and isinstance(last, int):
        del parent[last]
    else:
        raise TypeError("The parent is not a dictionary or array.")


def add_child(mapping: dict, key: str, value) -> None:
    if not key:
        raise ValueError("A key name is required.")
    if key in mapping:
        raise ValueError("The key already exists.")
    mapping[key] = value


def add_item(sequence: list, value) -> None:
    sequence.append(value)


def move_item(data, path, delta: int) -> tuple:
    """Move an array element and return its new path."""
    if not path or not isinstance(path[-1], int):
        raise ValueError("Only array elements can be moved.")
    parent = get_at(data, path[:-1])
    index = path[-1]
    target = index + delta
    if not isinstance(parent, list) or not 0 <= target < len(parent):
        return path
    parent[index], parent[target] = parent[target], parent[index]
    return tuple(path[:-1]) + (target,)


def serialize_document(data: dict) -> bytes:
    try:
        return plistlib.dumps(data, fmt=plistlib.FMT_XML, sort_keys=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConfigWriteFailed(detail=(
            "The document contains a value plist cannot serialise: {}".format(exc))) from exc


def _atomic_write(path: Path, payload: bytes, mode: int) -> None:
    directory = path.parent
    handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix=".{}.".format(path.name), dir=str(directory),
        delete=False)
    staging = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(staging, mode)
        os.replace(staging, path)
    except BaseException:
        try:
            staging.unlink()
        except OSError:
            pass
        raise


@dataclass
class ConfigDocument:
    """An opened config.plist and the bytes it was loaded from."""

    path: Path
    data: dict
    original: bytes = field(repr=False)

    @classmethod
    def load(cls, path) -> "ConfigDocument":
        config = Path(path)
        try:
            if config.stat().st_size > MAX_DOCUMENT_BYTES:
                raise ConfigReadFailed(detail=(
                    "The file is larger than 16 MB, so it is not an OpenCore "
                    "config.plist."))
            payload = config.read_bytes()
            data = plistlib.loads(payload)
        except ConfigEditorError:
            raise
        except (OSError, plistlib.InvalidFileException, ValueError, TypeError) as exc:
            raise ConfigReadFailed(detail=str(exc)) from exc
        if not isinstance(data, dict):
            raise ConfigReadFailed(detail="The property list root is not a dictionary.")
        return cls(path=config, data=data, original=payload)

    def to_bytes(self) -> bytes:
        return serialize_document(self.data)

    def is_dirty(self) -> bool:
        return self.to_bytes() != self.original

    def changed_on_disk(self) -> bool:
        try:
            return self.path.read_bytes() != self.original
        except OSError:
            return True

    def save(self, path=None) -> None:
        target = Path(path) if path is not None else self.path
        payload = self.to_bytes()
        try:
            mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
            if target.exists():
                _atomic_write(
                    target.with_name(target.name + ".bak"),
                    target.read_bytes(), mode)
            _atomic_write(target, payload, mode)
        except OSError as exc:
            raise ConfigWriteFailed(detail=str(exc)) from exc
        self.path = target
        self.original = payload


def _verify_ocvalidate(candidate: Path) -> Path:
    asset = OCVALIDATE_ASSETS.get(_platform_key())
    if asset is None:
        raise OcvalidateUnavailable(detail=(
            "No ocvalidate build is pinned for {}.".format(sys.platform)))
    install_name, _member, expected = asset
    if candidate.name.lower() != install_name.lower():
        raise OcvalidateUnavailable(detail=(
            "{} is not one of the pinned ocvalidate names.".format(candidate.name)))
    if not candidate.is_file():
        raise OcvalidateUnavailable(detail="{} is not a file.".format(candidate))
    if engine_paths.is_on_import_path(candidate):
        raise OcvalidateUnavailable(detail=(
            "Refusing {} because it is on Python's import path.".format(candidate)))
    actual = _digest(candidate)
    if actual.lower() != expected:
        raise OcvalidateVerificationFailed(detail=(
            "{} has digest {}, expected {}.".format(candidate, actual, expected)))
    if not os.access(candidate, os.X_OK):
        raise OcvalidateUnavailable(detail=(
            "{} is not executable.".format(candidate)))
    return candidate


def find_ocvalidate() -> Path | None:
    """A verified ``ocvalidate`` from the tools directories, or None."""
    asset = OCVALIDATE_ASSETS.get(_platform_key())
    if asset is None:
        return None
    install_name = asset[0]
    for directory in engine_paths.tools_dirs():
        if engine_paths.is_on_import_path(directory):
            continue
        candidate = Path(directory) / install_name
        if candidate.is_file():
            return _verify_ocvalidate(candidate)
    return None


def _install_ocvalidate() -> Path:
    asset = OCVALIDATE_ASSETS.get(_platform_key())
    if asset is None:
        raise OcvalidateUnavailable(detail=(
            "No ocvalidate build is pinned for {}.".format(sys.platform)))
    install_name, member, expected = asset
    install_dir = engine_paths.install_tools_dir()
    if install_dir is None:
        raise OcvalidateUnavailable(detail=(
            "No writable app-managed tools directory is available."))
    destination = Path(install_dir) / install_name
    with tempfile.TemporaryDirectory(prefix="blackdream-ocvalidate-") as folder:
        archive = Path(folder) / "OpenCorePkg.zip"
        from ocengine.resource_fetcher import ResourceFetcher

        fetched = ResourceFetcher().download_and_save_file(
            OCVALIDATE_ARCHIVE_URL, str(archive), OCVALIDATE_ARCHIVE_SHA256,
            product="ocvalidate")
        if not fetched or not archive.is_file():
            raise OcvalidateDownloadFailed(detail=(
                "OpenCore {} could not be downloaded.".format(OPEN_CORE_VERSION)))
        if _digest(archive).lower() != OCVALIDATE_ARCHIVE_SHA256:
            raise OcvalidateVerificationFailed(detail=(
                "The OpenCorePkg archive did not match its pinned archive digest."))
        try:
            with zipfile.ZipFile(archive) as bundle:
                info = bundle.getinfo(member)
                if info.is_dir():
                    raise KeyError(member)
                payload = bundle.read(info)
        except (KeyError, zipfile.BadZipFile, OSError) as exc:
            raise OcvalidateDownloadFailed(detail=(
                "The verified archive did not contain {}.".format(member))) from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual.lower() != expected:
        raise OcvalidateVerificationFailed(detail=(
            "{} inside the verified archive has digest {}, expected {}.".format(
                member, actual, expected)))
    try:
        _atomic_write(destination, payload, 0o755)
    except OSError as exc:
        raise OcvalidateDownloadFailed(detail=(
            "The verified binary could not be installed: {}".format(exc))) from exc
    return _verify_ocvalidate(destination)


def ensure_ocvalidate(allow_download: bool = True) -> Path:
    found = find_ocvalidate()
    if found is not None:
        return found
    if not allow_download:
        raise OcvalidateUnavailable(detail=(
            "No verified ocvalidate was found in the app tools directories."))
    return _install_ocvalidate()


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    version: str
    issues: tuple[str, ...]
    output: str

    @property
    def summary(self) -> str:
        if self.ok:
            return "No issues found."
        count = len(self.issues)
        return "{} issue{} found.".format(count, "" if count == 1 else "s")


def parse_validator_output(output: str, returncode: int) -> ValidationResult:
    issues = []
    version = ""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("OCS:") or stripped.startswith("OCV:"):
            issues.append(stripped)
        elif stripped.startswith("Serialisation returns"):
            issues.append(stripped)
        elif stripped.startswith("NOTE: This version of ocvalidate"):
            version = stripped
    ok = returncode == 0 and "No issues found" in output
    if not ok and not issues:
        issues.append(
            "ocvalidate exited with status {}.".format(returncode))
    return ValidationResult(ok=ok, version=version, issues=tuple(issues),
                            output=output)


def run_ocvalidate(config_path, allow_download: bool = True) -> ValidationResult:
    tool = ensure_ocvalidate(allow_download=allow_download)
    command = [str(tool), str(config_path)]
    try:
        completed = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=90, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise OcvalidateRunFailed(detail=str(exc)) from exc
    output = (completed.stdout or "") + (completed.stderr or "")
    if len(output) > MAX_VALIDATOR_OUTPUT:
        output = output[:MAX_VALIDATOR_OUTPUT] + "\n[output truncated]"
    return parse_validator_output(output, completed.returncode)


def validate_document(data: dict, allow_download: bool = True) -> ValidationResult:
    """Validate an in-memory document without touching the saved file."""
    payload = serialize_document(data)
    folder = Path(tempfile.mkdtemp(prefix="blackdream-validate-"))
    target = folder / "config.plist"
    try:
        os.chmod(folder, 0o700)
        _atomic_write(target, payload, 0o600)
        return run_ocvalidate(target, allow_download=allow_download)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def serial_models() -> list[str]:
    from ocengine.datasets.mac_model_data import mac_devices

    return [device.name for device in mac_devices]


def generate_serials(model: str) -> dict:
    """Generate SMBIOS values with OpenCore's macserial, as config.plist types."""
    from ocengine.smbios import SMBIOS

    try:
        generated = SMBIOS().generate_smbios(model)
    except EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced as a typed dialog, never a crash
        raise SerialGenerationFailed(detail=str(exc)) from exc
    if not isinstance(generated, dict) or "SystemSerialNumber" not in generated:
        raise SerialGenerationFailed(detail="macserial returned no usable values.")
    result = dict(generated)
    rom = result.get("ROM", "")
    if isinstance(rom, str):
        try:
            result["ROM"] = bytes.fromhex(rom)
        except ValueError as exc:
            raise SerialGenerationFailed(detail=(
                "macserial returned a ROM that is not hexadecimal.")) from exc
    return result


def apply_serials(data: dict, values: dict, model: str) -> None:
    platform = data.setdefault("PlatformInfo", {})
    if not isinstance(platform, dict):
        raise ValueError("PlatformInfo is not a dictionary.")
    generic = platform.setdefault("Generic", {})
    if not isinstance(generic, dict):
        raise ValueError("PlatformInfo/Generic is not a dictionary.")
    generic["SystemProductName"] = model
    for key in ("SystemSerialNumber", "MLB", "SystemUUID", "ROM"):
        if key in values:
            generic[key] = values[key]
