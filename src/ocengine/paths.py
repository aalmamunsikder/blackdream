"""Where the engine keeps downloaded artifacts.

Upstream resolved this next to its own source file, which is correct for a script
you unzip and run, but inside a packaged application that path is the read-only,
code-signed bundle. A macOS ``.app`` cannot write into its own ``Contents/Resources``,
and Windows blocks it under ``Program Files``, so the location is resolved once by the
application and handed to the engine here.

The default preserves upstream behaviour so the engine still works standalone.

``tools_dirs()`` is the single authority for where a runtime binary -- ``iasl``,
``macserial`` -- may be looked up or installed. The engine's own package directory
can never appear there: a file that lands next to the code is on Python's import
path, and executing it there means a download can shadow a module.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SRC_ROOT = Path(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def _data_root(os_name=None, platform=None) -> Path:
    """Per-user writable root, without importing the application layer.

    ``os_name`` and ``platform`` default to the running host. They are parameters
    because ``os.name`` cannot be faked on another OS -- patching it makes
    ``pathlib`` hand back a ``WindowsPath`` that cannot be built on POSIX -- and
    the Windows branch still has to be testable from a Linux checkout.
    """
    os_name = os.name if os_name is None else os_name
    platform = sys.platform if platform is None else platform
    if os_name == "nt":
        return Path(os.environ.get("LOCALAPPDATA")
                    or Path.home() / "AppData" / "Local") / "blackdream"
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "blackdream"
    return Path(os.environ.get("XDG_DATA_HOME")
                or Path.home() / ".local" / "share") / "blackdream"


@dataclass(frozen=True)
class EnginePaths:
    cache_dir: Path
    tools_dir: Path = field(default_factory=lambda: _data_root() / "tools")


DEFAULT = EnginePaths(cache_dir=_SRC_ROOT / "OCK_Files")


def is_on_import_path(path) -> bool:
    """True when ``path`` is, or sits inside, a directory Python imports from.

    Covers ``sys.path`` and this package's own source tree, so a frozen build that
    hides its layout from ``sys.path`` is still refused.
    """
    real = os.path.realpath(str(path))
    for entry in list(sys.path) + [str(_SRC_ROOT)]:
        if not entry:
            continue
        entry = os.path.realpath(entry)
        if real == entry or real.startswith(entry + os.sep):
            return True
    return False


def tools_dirs(create=False):
    """App-managed directories tools are looked up in, in trust order.

    Operator-provisioned first (``BLACKDREAM_TOOLS_DIR``, then the ``tools/`` the
    repository reserves at its root), then the per-user directory downloads install
    into. The engine's package directory is never in this list, and callers that
    iterate it must still reject a hit with :func:`is_on_import_path` -- a symlinked
    ``tools/`` can point back into the source tree.
    """
    dirs = []
    override = os.environ.get("BLACKDREAM_TOOLS_DIR")
    if override:
        dirs.append(os.path.abspath(os.path.expanduser(override)))
    app_dir = str(_SRC_ROOT.parent / "tools")
    if os.path.isdir(app_dir):
        dirs.append(app_dir)
    user_dir = str(current().tools_dir)
    if create and not os.path.isdir(user_dir):
        try:
            os.makedirs(user_dir)
        except OSError:
            pass
    dirs.append(user_dir)
    # Dedupe on realpath and return the realpaths: comparing raw strings let
    # "/tmp/tools" and "/tmp/tools/" both survive.
    unique = []
    for directory in dirs:
        real = os.path.realpath(directory)
        if real not in unique:
            unique.append(real)
    return unique


def install_tools_dir():
    """The one directory a verified download may write into, or None."""
    for directory in tools_dirs(create=True):
        if is_on_import_path(directory):
            continue
        if os.path.isdir(directory) and os.access(directory, os.W_OK):
            return directory
    return None


def _default_cache_dir() -> Path:
    return _data_root() / "cache"


_current = EnginePaths(cache_dir=_default_cache_dir())


def current() -> EnginePaths:
    return _current


def set_paths(paths: EnginePaths) -> EnginePaths:
    global _current
    previous = _current
    _current = paths
    return previous
