"""Terminal-free subset of Hardware Sniffer's ``Scripts/utils.py`` (BSD-3).

Dropped from upstream: ``head``, ``progress_bar``, ``adjust_window_size``,
``request_input`` and ``exit_program`` (terminal control codes, a blocking prompt
and a ``sys.exit``); ``create_folder``/``extract_zip_file``, the ``plistlib``
reader/writer and the ``rich_format`` flag (only the download and self-update paths
used them).  ``get_full_path`` became ``get_data_path``: upstream resolved data
files through a PyInstaller ``_MEIPASS`` bundle, which this package has no
equivalent of.
"""

import json
import os
import sys

_DATA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "datasets")


class Utils:
    def get_data_path(self, *path):
        return os.path.join(_DATA_DIR, *path)

    def write_file(self, file_path, data):
        with open(file_path, "w") as file_handle:
            json.dump(data, file_handle, indent=4)

    def read_file(self, file_path):
        if not os.path.exists(file_path):
            return None

        extension = os.path.splitext(file_path)[1]

        if extension == ".json":
            with open(file_path, "r") as file_handle:
                return json.load(file_handle)

        with open(file_path, "rb") as file_handle:
            if extension == ".ids":
                return _parse_ids(file_handle.read().decode(errors="ignore"))

            data = file_handle.read()

        # sysfs and procfs are text except for the EDID blobs, which the caller
        # decodes itself -- turning those into a str breaks the monitor name.
        if (
            isinstance(data, bytes)
            and sys.platform.startswith("linux")
            and file_path.startswith(("/sys/", "/proc/"))
            and "edid" not in os.path.basename(file_path).lower()
        ):
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError:
                pass

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
                for directory in dirs:
                    if is_valid_item(directory):
                        found_paths.append((os.path.join(relative_root, directory), "dir"))

            if type_filter in (None, "file"):
                for name in files:
                    if is_valid_item(name):
                        found_paths.append((os.path.join(relative_root, name), "file"))

        return sorted(found_paths, key=lambda path: path[0])

    def get_unique_key(self, base_key, dictionary):
        if base_key not in dictionary:
            return base_key

        counter = 1
        unique_key = f"{base_key}_#{counter}"

        while unique_key in dictionary:
            counter += 1
            unique_key = f"{base_key}_#{counter}"

        return unique_key

    def contains_any(self, data, search_item, start=0, end=None):
        return next((item for item in data[start:end] if item.lower() in search_item.lower()), None)


def _parse_ids(text):
    """A PCI/USB ids file as ``{VENDOR: {"name": ..., "devices": {DDDD: name}}}``."""
    data = {}
    current_vendor = None

    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue

        if not line.startswith("\t"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                current_vendor = parts[0].upper()
                data[current_vendor] = {"name": parts[1], "devices": {}}
        elif current_vendor:
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                device_id, device_name = parts
                data[current_vendor]["devices"][device_id.upper()] = device_name

    return data
