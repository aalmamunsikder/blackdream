from . import utils
import os

class LinuxDeviceLocator:
    def __init__(self):
        self.utils = utils.Utils()

    def get_device_location_paths(self, device_dir):
        device_location_paths = {}

        uevent = self.utils.read_file(os.path.join(device_dir, "uevent")) or "\n"
        device_slot_name = None

        for line in uevent.split("\n"):
            lower_line = line.lower()

            if "pci_slot_name" in lower_line:
                device_slot_name = line.split("=")[1]
                break

        pci_path = None

        if device_slot_name:
            device_path = os.path.join("/sys/bus/pci/devices", device_slot_name)

            if os.path.exists(device_path):
                real_path = os.path.realpath(device_path)
                
                pci_segments = []
                path_parts = real_path.split("/")
                
                domain = None
                for part in path_parts:
                    if part.startswith("pci") and ":" in part:
                        domain = int(part[3:].split(":")[0], 16)
                    elif ":" in part and "." in part:
                        segments = part.replace(":", ".").split(".")
                        if len(segments) >= 4:
                            device = int(segments[2], 16)
                            function = int(segments[3], 16)
                            pci_segments.append("Pci(0x{:x},0x{:x})".format(device, function))
                
                if domain is not None and pci_segments:
                    pci_path = "PciRoot(0x{:x})/{}".format(domain, "/".join(pci_segments))

        if pci_path:
            device_location_paths["PCI Path"] = pci_path

        acpi_path = self.utils.read_file(os.path.join(device_dir, "firmware_node", "path"))
        if acpi_path:
            acpi_path = acpi_path.strip()
            if acpi_path.startswith("\\_SB_."):
                acpi_path = "\\_SB." + acpi_path[6:]
            device_location_paths["ACPI Path"] = acpi_path

        return device_location_paths