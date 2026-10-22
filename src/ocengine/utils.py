import os
import json
import plistlib
import shutil
import re
import binascii
import stat
import ntpath
import subprocess
import pathlib
import time
import zipfile
import tempfile

from ocengine import runtime
from ocengine.fatal import EngineError, ExitRequested, InteractivePrompt

# ESC[@-~] CSI sequences plus OSC hyperlinks: whatever a subprocess, an archive
# listing or a remote error can emit. No escape sequence may reach the sink, so
# every message is scrubbed at the one boundary the engine logs through.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


class UnsafeArchiveMember(EngineError):
    """An archive member tried to write outside the extraction directory.

    ``extract_zip_file`` used to hand the whole archive to ``ZipFile.extractall``
    and trust it. A crafted member named ``../../evil`` -- or a symlink aimed at
    ``~/.bashrc`` -- lands in a directory whose files the engine later makes
    executable and runs, so the archive, not the interpreter, must decide what is
    allowed out.
    """

    code = "archive.unsafe_member"
    title = "Refusing to extract an archive entry that escapes its target"
    remediation = (
        "The download's pinned digest still matched, so the release itself is "
        "the source of the traversal -- report it upstream.",
    )


def _strip_ansi(text):
    return ANSI_ESCAPE.sub("", str(text))


class Utils:
    """Data helpers plus the engine's only output boundary.

    Upstream, the bottom half of this class was terminal control: a clear-screen
    banner, a carriage-return step checklist, a blocking ``input()``, an
    ``sys.exit``, and an xterm window-resize escape. Each is kept here under the
    same name and signature, but now emits an event on the active sink instead.
    Call sites are unchanged, which is what keeps the rebase onto upstream a
    file-level copy rather than a merge.
    """

    def __init__(self, script_name="BlackDream"):
        self.script_name = script_name

    # ---- output boundary -------------------------------------------------

    @property
    def sink(self) -> runtime.EngineSink:
        return runtime.current_sink()

    def log_message(self, message, level="info"):
        self.sink.log(level, _strip_ansi(message))

    def head(self, text=None, width=68, resize=True):
        """Phase boundary. Was: clear screen, draw a Unicode box, reprint."""
        self.sink.section(text or self.script_name)

    def progress_bar(self, title, steps, current_step_index, done=False):
        """Stage progress. Was: a redrawn [check]/[tick]/[pending] checklist."""
        sink = self.sink
        total = len(steps)

        if done:
            current_step_index = total

        for index, step in enumerate(steps):
            if index < current_step_index:
                state = "done"
            elif index == current_step_index:
                state = "running"
            else:
                state = "pending"
            sink.stage(step, index, total, state)

    def notify(self, title, body="", level="info"):
        self.sink.notify(title, body, level)

    def request_input(self, prompt="Press Enter to continue..."):
        """No terminal exists. A surviving call site is an unfinished conversion."""
        raise InteractivePrompt(detail="Blocked waiting on terminal input: {!r}".format(prompt))

    def exit_program(self):
        """No terminal exists. Never terminate the process from engine code."""
        raise ExitRequested(detail="Engine code attempted to terminate the process.")

    # ---- filesystem ------------------------------------------------------

    def clean_temporary_dir(self, max_age_hours=12):
        """Sweep stale scratch dirs, leaving any in-flight session alone.

        Upstream deleted every ``ocs_*`` directory in the system temp root at
        startup, which would destroy the working directory of a second running
        instance or an interrupted build being resumed.
        """
        temporary_dir = tempfile.gettempdir()
        cutoff = time.time() - max_age_hours * 3600

        for entry in os.listdir(temporary_dir):
            if not entry.startswith("ocs_"):
                continue

            path = os.path.join(temporary_dir, entry)

            if not os.path.isdir(path):
                continue

            try:
                if os.path.getmtime(path) > cutoff:
                    continue
                shutil.rmtree(path)
            except OSError as exception:
                self.log_message("Could not clean {}: {}".format(path, exception), level="warning")

    def get_temporary_dir(self):
        return tempfile.mkdtemp(prefix="ocs_")

    def write_file(self, file_path, data):
        file_extension = os.path.splitext(file_path)[1]

        with open(file_path, "w" if file_extension == ".json" else "wb") as file:
            if file_extension == ".json":
                json.dump(data, file, indent=4)
            else:
                if file_extension == ".plist":
                    data = plistlib.dumps(data)

                file.write(data)

    def read_file(self, file_path):
        if not os.path.exists(file_path):
            return None

        file_extension = os.path.splitext(file_path)[1]

        with open(file_path, "r" if file_extension == ".json" else "rb") as file_handle:
            if file_extension == ".plist":
                data = plistlib.load(file_handle)
            elif file_extension == ".json":
                data = json.load(file_handle)
            else:
                data = file_handle.read()
            return data

    def find_matching_paths(self, root_path, extension_filter=None, name_filter=None, type_filter=None):

        def is_valid_item(name):
            if name.startswith("."):
                return False
            if extension_filter and not name.lower().endswith(extension_filter.lower()):
                return False
            if name_filter and name_filter not in name:
                return False
            return True

        found_paths = []

        for root, dirs, files in os.walk(root_path):
            relative_root = root.replace(root_path, "")[1:]

            if type_filter in (None, "dir"):
                for d in dirs:
                    if is_valid_item(d):
                        found_paths.append((os.path.join(relative_root, d), "dir"))

            if type_filter in (None, "file"):
                for file in files:
                    if is_valid_item(file):
                        found_paths.append((os.path.join(relative_root, file), "file"))

        return sorted(found_paths, key=lambda path: path[0])

    def create_folder(self, path, remove_content=False):
        if os.path.exists(path):
            if remove_content:
                shutil.rmtree(path)
                os.makedirs(path)
        else:
            os.makedirs(path)

    def open_folder(self, folder_path):
        """Reveal a build result in the desktop's own file manager."""
        if not os.path.exists(folder_path):
            self.log_message("Refusing to open missing path: {}".format(folder_path), level="warning")
            return False

        try:
            if os.name == "posix":
                if "darwin" in os.uname().sysname.lower():
                    subprocess.run(["open", folder_path], check=False)
                else:
                    subprocess.run(["xdg-open", folder_path], check=False)
            elif os.name == "nt":
                os.startfile(folder_path)
            else:
                return False
            return True
        except (OSError, ValueError) as exception:
            self.log_message("Could not open {}: {}".format(folder_path, exception), level="warning")
            return False

    # ---- value helpers ---------------------------------------------------

    def hex_to_bytes(self, string):
        try:
            hex_string = re.sub(r'[^0-9a-fA-F]', '', string)

            if len(re.sub(r"\s+", "", string)) != len(hex_string):
                return string

            return binascii.unhexlify(hex_string)
        except binascii.Error:
            return string

    def int_to_hex(self, number):
        return format(number, '02X')

    def to_little_endian_hex(self, hex_string):
        hex_string = hex_string.lower().lstrip("0x")

        return ''.join(reversed([hex_string[i:i+2] for i in range(0, len(hex_string), 2)])).upper()

    def string_to_hex(self, string):
        return ''.join(format(ord(char), '02X') for char in string)

    def extract_zip_file(self, zip_path, extraction_directory=None):
        """Extract an archive, refusing any member that escapes the target.

        ``ZipFile.extractall`` is not a security boundary. Some interpreters
        silently rewrite ``../`` and absolute members into the destination, which
        turns a hostile archive into a "successful" extract of the wrong files,
        and none of them refuse a symlink member at all. So every member is
        checked from its *raw* name first, and only a clean archive is extracted.
        """
        if extraction_directory is None:
            extraction_directory = os.path.splitext(zip_path)[0]

        os.makedirs(extraction_directory, exist_ok=True)
        destination = os.path.realpath(extraction_directory)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for info in zip_ref.infolist():
                self._check_archive_member(info, destination)
            zip_ref.extractall(destination)

    @staticmethod
    def _check_archive_member(info, destination):
        """Raise :class:`UnsafeArchiveMember` if *info* would land outside
        *destination* (already resolved, absolute) -- absolute paths, ``..``
        traversal, and symlink members are all refused."""
        name = info.filename

        if stat.S_ISLNK(info.external_attr >> 16):
            raise UnsafeArchiveMember(
                "{!r} is a symlink member; refusing to extract it.".format(name))

        normalized = name.replace("\\", "/")
        is_absolute = (
            normalized.startswith("/")
            or normalized.startswith("//")
            or bool(ntpath.splitdrive(normalized)[0])
            or os.path.isabs(name)
        )
        if is_absolute:
            raise UnsafeArchiveMember(
                "{!r} is an absolute path; refusing to extract it.".format(name))

        target = os.path.realpath(os.path.join(destination, *normalized.split("/")))
        if target != destination and not target.startswith(destination + os.sep):
            raise UnsafeArchiveMember(
                "{!r} would extract to {!r}, outside the target directory {!r}.".format(
                    name, target, destination))

    def contains_any(self, data, search_item, start=0, end=None):
        return next((item for item in data[start:end] if item.lower() in search_item.lower()), None)

    def normalize_path(self, path):
        """Clean a user-supplied path.

        Upstream stripped backslashes on POSIX, silently corrupting the only
        filename characters a POSIX path may legitimately contain. A GUI hands
        back paths from a native picker rather than typed text, so quote and
        whitespace stripping is all that is left, and it applies everywhere.
        """
        path = re.sub(r'^[\'"]+|[\'"]+$', '', path.strip())

        if os.name == "nt":
            path = path.replace('\\', '/')

        return str(pathlib.Path(os.path.expanduser(path)).resolve())

    def parse_darwin_version(self, darwin_version):
        major, minor, patch = map(int, darwin_version.split('.'))
        return major, minor, patch
