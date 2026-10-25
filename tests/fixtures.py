"""Synthetic hardware reports for the engine's own schema.

The engine consumes a ``Report.json`` produced by a separate Windows-only tool
(Hardware Sniffer), so nothing in the upstream repo contains a fixture and there
is no way to test the pipeline without inventing one. These reports are built
from values checked against the engine's real datasets, not invented shapes:
device ids are members of ``pci_data`` pools, codecs exist in
``codec_layouts.data``, chipsets and CPU codenames exist in their own lists.

That matters because the compatibility checks key off exact ids. A plausible
looking but unlisted id silently grades as unsupported and the test passes for
the wrong reason.
"""

from __future__ import annotations

import json
import os

_INTEL_SIMD = "SSE3,SSE4.1,SSE4.2,AVX,AVX2"
_LEGACY_INTEL_SIMD = "SSE2,SSE3"


def _pci(root: int, device: int, function: int) -> str:
    return "PciRoot(0x{:X})/Pci(0x{:X},0x{:X})".format(root, device, function)


def coffee_lake_laptop() -> dict:
    """8th-gen laptop: UHD 630 iGPU driving an internal eDP panel, AX201 Wi-Fi.

    The internal display must report the iGPU as its Connected GPU. Upstream
    nullifies iGPU compatibility when an Internal monitor is attached to a
    different card, so a fixture that gets this wrong grades unsupported for an
    unrelated reason.
    """
    return {
        "Motherboard": {"Name": "DELL XPS 15 9570", "Chipset": "CM246", "Platform": "Laptop"},
        "BIOS": {
            "Version": "1.14.0",
            "Release Date": "08/12/2021",
            "System Type": "x64",
            "Firmware Type": "UEFI",
            "Secure Boot": "Disabled",
        },
        "CPU": {
            "Manufacturer": "Intel",
            "Processor Name": "Intel Core i7-8550U",
            "Codename": "Coffee Lake-U",
            "Core Count": "4",
            "CPU Count": "1",
            "SIMD Features": _INTEL_SIMD,
        },
        "GPU": {
            "Intel UHD Graphics 630": {
                "Manufacturer": "Intel",
                "Codename": "Coffee Lake-U",
                "Device ID": "8086-3E9B",
                "Device Type": "Integrated GPU",
                "Subsystem ID": "0x12345678",
                "PCI Path": _pci(0, 2, 0),
                "ACPI Path": "\\_SB.PCI0.GFX0",
                "Resizable BAR": "Disabled",
            }
        },
        "Monitor": {
            "CMO Integrated Camera": {"Connector Type": "eDP", "Resolution": "1920x1080",
                                      "Connected GPU": "Intel UHD Graphics 630"},
            "Dell USB-C Dock": {"Connector Type": "DP", "Resolution": "2560x1440",
                                "Connected GPU": "Intel UHD Graphics 630"},
        },
        "Network": {
            "Intel I219-V": {
                "Bus Type": "PCI",
                "Device ID": "8086-15B8",
                "Subsystem ID": "0x08401028",
                "PCI Path": _pci(0, 31, 6),
                "ACPI Path": "\\_SB.PCI0.LANC",
            },
            "Intel Wi-Fi 6 AX201": {
                "Bus Type": "PCI",
                "Device ID": "8086-24F3",
                "Subsystem ID": "0x00708086",
                "PCI Path": _pci(0, 20, 2),
                "ACPI Path": "\\_SB.PCI0.RP01.PXSX",
            },
        },
        "Bluetooth": {
            "Intel Bluetooth AX201": {"Bus Type": "USB", "Device ID": "8087-0AAA"},
        },
        "Sound": {
            "Intel Cannon Lake-HDMI": {
                "Bus Type": "PCI",
                "Device ID": "8086-A2F0",
                "Controller Device ID": "8086-A170",
                "Audio Endpoints": ["Internal Speakers", "HDMI/DP"],
            },
            "Realtek ALC236": {
                "Bus Type": "HDA",
                "Device ID": "10EC-0236",
                "Subsystem ID": "0x10281234",
                "Audio Endpoints": ["ALC236 Analog"],
            },
        },
        "USB Controllers": {
            "Intel Cannon Lake USB": {
                "Bus Type": "PCI",
                "Device ID": "8086-A134",
                "PCI Path": _pci(0, 20, 0),
                "ACPI Path": "\\_SB.PCI0.XHC",
            },
        },
        "Input": {
            "Synaptics TouchPad": {"Bus Type": "ACPI", "Device": "PS2M", "Device Type": "TouchPad"},
            "ATK0100 Keyboard": {"Bus Type": "ACPI", "Device": "ATKD", "Device Type": "Keyboard"},
        },
        "Storage Controllers": {
            "Intel Cannon Lake AHCI": {
                "Bus Type": "PCI",
                "Device ID": "8086-A282",
                "PCI Path": _pci(0, 23, 0),
                "ACPI Path": "\\_SB.PCI0.SATA",
                "Disk Drives": ["Samsung SSD 970 EVO 500GB", "Micron 2200S 256GB"],
            },
        },
        "SD Controller": {
            "Realtek Card Reader": {
                "Bus Type": "PCI",
                "Device ID": "10EC-525A",
                "Subsystem ID": "0x08401028",
                "PCI Path": _pci(0, 1, 0),
                "ACPI Path": "\\_SB.PCI0.RP05.PXSA",
            },
        },
        "System Devices": {
            "Intel Management Engine": {
                "Bus Type": "PCI",
                "Device": "HECI",
                "Device ID": "8086-A1BA",
                "PCI Path": _pci(0, 22, 0),
                "ACPI Path": "\\_SB.PCI0.HECI",
            },
            "Intel SMBus": {
                "Bus Type": "PCI",
                "Device": "SBUS",
                "Device ID": "8086-A123",
                "PCI Path": _pci(0, 31, 4),
                "ACPI Path": "\\_SB.PCI0.SBUS",
            },
        },
    }


def tiger_lake_laptop() -> dict:
    """11th-gen laptop whose Iris Xe iGPU exists only with WhateverXe.

    Apple never shipped a driver for Xe-LP, so the engine grades this panel as
    Big Sur 11.7.11 or newer through the WhateverXe patch rather than "Unsupported".
    The internal eDP panel connects to the iGPU, which is what makes the report
    realistic: a report that leaves the panel on another card nullifies it.
    """
    return {
        "Motherboard": {"Name": "Lenovo ThinkPad X1 Carbon Gen 9", "Chipset": "Tiger Lake-LP",
                        "Platform": "Laptop"},
        "BIOS": {
            "Version": "N32ET75W",
            "Release Date": "11/10/2022",
            "System Type": "x64",
            "Firmware Type": "UEFI",
            "Secure Boot": "Disabled",
        },
        "CPU": {
            "Manufacturer": "Intel",
            "Processor Name": "Intel Core i7-1165G7",
            "Codename": "Tiger Lake-UP3",
            "Core Count": "4",
            "CPU Count": "1",
            "SIMD Features": _INTEL_SIMD,
        },
        "GPU": {
            "Intel Iris Xe Graphics": {
                "Manufacturer": "Intel",
                "Codename": "Tiger Lake-UP3",
                "Device ID": "8086-9A49",
                "Device Type": "Integrated GPU",
                "Subsystem ID": "0x22C617AA",
                "PCI Path": _pci(0, 2, 0),
                "ACPI Path": "\\_SB.PCI0.GFX0",
                "Resizable BAR": "Disabled",
            }
        },
        "Monitor": {
            "BOE 0x095F": {"Connector Type": "eDP", "Resolution": "1920x1200",
                           "Connected GPU": "Intel Iris Xe Graphics"},
        },
        "Network": {
            "Intel I219-V": {
                "Bus Type": "PCI",
                "Device ID": "8086-15B8",
                "Subsystem ID": "0x22C617AA",
                "PCI Path": _pci(0, 31, 6),
                "ACPI Path": "\\_SB.PCI0.LANC",
            },
            "Intel Wi-Fi 6 AX201": {
                "Bus Type": "PCI",
                "Device ID": "8086-24F3",
                "Subsystem ID": "0x00708086",
                "PCI Path": _pci(0, 20, 2),
                "ACPI Path": "\\_SB.PCI0.RP01.PXSX",
            },
        },
        "Bluetooth": {
            "Intel Bluetooth AX201": {"Bus Type": "USB", "Device ID": "8087-0AAA"},
        },
        "Sound": {
            "Intel Tiger Lake-HDMI": {
                "Bus Type": "PCI",
                "Device ID": "8086-A0C8",
                "Controller Device ID": "8086-A0C8",
                "Audio Endpoints": ["Internal Speakers", "HDMI/DP"],
            },
            "Realtek ALC256": {
                "Bus Type": "HDA",
                "Device ID": "10EC-0256",
                "Subsystem ID": "0x22C617AA",
                "Audio Endpoints": ["ALC256 Analog"],
            },
        },
        "USB Controllers": {
            "Intel Tiger Lake USB": {
                "Bus Type": "PCI",
                "Device ID": "8086-9A13",
                "PCI Path": _pci(0, 20, 0),
                "ACPI Path": "\\_SB.PCI0.XHC",
            },
        },
        "Input": {
            "Synaptics TouchPad": {"Bus Type": "ACPI", "Device": "PS2M", "Device Type": "TouchPad"},
            "ThinkPad Keyboard": {"Bus Type": "ACPI", "Device": "ATKD", "Device Type": "Keyboard"},
        },
        "Storage Controllers": {
            "Intel Cannon Lake AHCI": {
                "Bus Type": "PCI",
                "Device ID": "8086-A282",
                "PCI Path": _pci(0, 23, 0),
                "ACPI Path": "\\_SB.PCI0.SATA",
                "Disk Drives": ["Samsung SSD 860 EVO 1TB"],
            },
        },
        "SD Controller": {
            "Realtek Card Reader": {
                "Bus Type": "PCI",
                "Device ID": "10EC-525A",
                "Subsystem ID": "0x22C617AA",
                "PCI Path": _pci(0, 1, 0),
                "ACPI Path": "\\_SB.PCI0.RP05.PXSA",
            },
        },
    }


def alder_lake_desktop() -> dict:
    """12th-gen desktop with a Navi 23 dGPU.

    There is deliberately no iGPU here: Alder Lake's UHD 770 (device id 46xx) is
    not macOS-compatible and upstream grades it unsupported. A Navi 23 card is
    the realistic configuration for this machine.
    """
    report = coffee_lake_laptop()
    report.update({
        "Motherboard": {"Name": "ASUS PRIME Z690-A", "Chipset": "Z690", "Platform": "Desktop"},
        "BIOS": {
            "Version": "1803",
            "Release Date": "03/21/2023",
            "System Type": "x64",
            "Firmware Type": "UEFI",
            "Secure Boot": "Disabled",
        },
        "CPU": {
            "Manufacturer": "Intel",
            "Processor Name": "Intel Core i5-12600K",
            "Codename": "Alder Lake-S",
            "Core Count": "10",
            "CPU Count": "1",
            "SIMD Features": _INTEL_SIMD,
        },
        "GPU": {
            "AMD Radeon RX 6600": {
                "Manufacturer": "AMD",
                "Codename": "Navi 23",
                "Device ID": "1002-73FF",
                "Device Type": "Discrete GPU",
                "Subsystem ID": "0x01231DA5",
                "PCI Path": _pci(0, 1, 0),
                "ACPI Path": "\\_SB.PCI0.PEG0.PEGP",
                "Resizable BAR": "Enabled",
            }
        },
        "Monitor": {
            "LG 27GP850": {"Connector Type": "DP", "Resolution": "2560x1440",
                           "Connected GPU": "AMD Radeon RX 6600"},
        },
        "Network": {
            "Intel I225-V": {
                "Bus Type": "PCI",
                "Device ID": "8086-15F8",
                "Subsystem ID": "0x00001B21",
                "PCI Path": _pci(0, 30, 6),
                "ACPI Path": "\\_SB.PCI0.GCXH",
            },
            "Realtek RTL8125": {
                "Bus Type": "PCI",
                "Device ID": "10EC-8125",
                "Subsystem ID": "0x81251B21",
                "PCI Path": _pci(0, 30, 6),
                "ACPI Path": "\\_SB.PCI0.GCXH",
            },
        },
        "Bluetooth": {},
        "Sound": {
            "AMD Navi HDMI": {
                "Bus Type": "PCI",
                "Device ID": "1002-AB28",
                "Controller Device ID": "1002-AB28",
                "Audio Endpoints": ["DP Audio"],
            },
            "Realtek ALC897": {
                "Bus Type": "HDA",
                "Device ID": "10EC-0236",
                "Subsystem ID": "0x88901458",
                "Audio Endpoints": ["ALC897 Analog"],
            },
        },
        "USB Controllers": {
            "Intel Z690 USB": {
                "Bus Type": "PCI",
                "Device ID": "8086-7A4C",
                "PCI Path": _pci(0, 20, 0),
                "ACPI Path": "\\_SB.PCI0.XHCX",
            },
        },
        "Input": {
            "USB Keyboard": {"Bus Type": "USB", "Device": "HID", "Device Type": "Keyboard"},
            "USB Mouse": {"Bus Type": "USB", "Device": "HID", "Device Type": "Mouse"},
        },
        "Storage Controllers": {
            "Intel Z690 AHCI": {
                "Bus Type": "PCI",
                "Device ID": "8086-4602",
                "PCI Path": _pci(0, 23, 0),
                "ACPI Path": "\\_SB.PCI0.SATA",
                "Disk Drives": ["WD_BLACK SN850 1TB"],
            },
        },
        "SD Controller": {},
    })
    report.pop("System Devices", None)
    return report


def rtx_desktop() -> dict:
    """12th-gen desktop with an RTX 5060, the card the NullMoth driver is tested on.

    Apple never shipped a Metal driver for Turing or newer, so upstream graded this
    machine unsupported. The NullMoth driver takes it from macOS 15.5 through the
    newest release. There is no iGPU for the same reason as ``alder_lake_desktop``.
    """
    report = alder_lake_desktop()
    report["GPU"] = {
        "NVIDIA GeForce RTX 5060": {
            "Manufacturer": "NVIDIA",
            "Codename": "Blackwell",
            "Device ID": "10DE-2D05",
            "Device Type": "Discrete GPU",
            "Subsystem ID": "0x892B1462",
            "PCI Path": _pci(0, 1, 0),
            "ACPI Path": "\\_SB.PCI0.PEG0.PEGP",
            "Resizable BAR": "Enabled",
        }
    }
    report["Monitor"] = {
        "LG 27GP850": {"Connector Type": "DP", "Resolution": "2560x1440",
                       "Connected GPU": "NVIDIA GeForce RTX 5060"},
    }
    return report


def raven_ridge_amd_laptop() -> dict:
    """Ryzen 5 2500U laptop: Vega 8 iGPU, the AMD Vanilla patch path."""
    report = coffee_lake_laptop()
    report.update({
        "Motherboard": {"Name": "HP Envy x360 15-bq100", "Chipset": "AMD FP5", "Platform": "Laptop"},
        "BIOS": {
            "Version": "F.25",
            "Release Date": "10/01/2020",
            "System Type": "x64",
            "Firmware Type": "UEFI",
            "Secure Boot": "Disabled",
        },
        "CPU": {
            "Manufacturer": "AMD",
            "Processor Name": "AMD Ryzen 5 2500U with Radeon Vega Mobile Gfx",
            "Codename": "Raven Ridge",
            "Core Count": "4",
            "CPU Count": "1",
            "SIMD Features": _INTEL_SIMD,
        },
        "GPU": {
            "AMD Radeon Vega 8": {
                "Manufacturer": "AMD",
                "Codename": "Vega 8",
                "Device ID": "1002-15D8",
                "Device Type": "Integrated GPU",
                "Subsystem ID": "0x846C103C",
                "PCI Path": _pci(0, 1, 0),
                "ACPI Path": "\\_SB.PCI0.GPP0.VGA",
                "Resizable BAR": "Disabled",
            }
        },
        "Monitor": {
            "BOE Integrated": {"Connector Type": "eDP", "Resolution": "1920x1080",
                              "Connected GPU": "AMD Radeon Vega 8"},
        },
    })
    return report


def cpu_without_sse4() -> dict:
    """Triggers CpuNoSse4: a pre-Nehalem Core 2 Duo reports no SSE4.x."""
    report = coffee_lake_laptop()
    report["CPU"] = {
        "Manufacturer": "Intel",
        "Processor Name": "Intel Core 2 Duo T7300",
        "Codename": "Conroe",
        "Core Count": "2",
        "CPU Count": "1",
        "SIMD Features": _LEGACY_INTEL_SIMD,
    }
    return report


def intel_vmd_storage() -> dict:
    """Triggers StorageIntelVmdEnabled: the boot NVMe sits behind Intel VMD."""
    report = alder_lake_desktop()
    report["Storage Controllers"] = {
        "Intel VMD": {
            "Bus Type": "PCI",
            "Device ID": "8086-467F",
            "PCI Path": _pci(0, 23, 0),
            "ACPI Path": "\\_SB.PCI0.VMD",
            "Disk Drives": ["WD_BLACK SN850 1TB"],
        },
        "Intel Z690 AHCI": {
            "Bus Type": "PCI",
            "Device ID": "8086-4602",
            "PCI Path": _pci(0, 23, 5),
            "ACPI Path": "\\_SB.PCI0.SATA",
            "Disk Drives": [],
        },
    }
    return report


def gpu_missing_from_report() -> dict:
    """Upstream hole: an empty GPU section is skipped by check_compatibility,
    so no fatal fires and the EFI is built for a machine with no GPU."""
    report = coffee_lake_laptop()
    report["GPU"] = {}
    report["Monitor"] = {}
    return report


def gpu_unsupported() -> dict:
    """Triggers GpuUnsupported: a pre-Fermi NVIDIA GPU no rule covers.

    Turing and newer are no longer a fatal report - the NullMoth driver is graded
    for them - so this fixture uses a card that is neither listed by NullMoth nor
    inside the Kepler/Pascal/Maxwell/Tesla ranges.
    """
    report = coffee_lake_laptop()
    report["GPU"] = {
        "NVIDIA GeForce 8800 GT": {
            "Manufacturer": "NVIDIA",
            "Codename": "G92",
            "Device ID": "10DE-0193",
            "Device Type": "Discrete GPU",
            "PCI Path": _pci(0, 1, 0),
        },
    }
    report["Monitor"] = {
        "AOC 24G2": {"Connector Type": "HDMI", "Resolution": "1920x1080",
                     "Connected GPU": "NVIDIA GeForce 8800 GT"},
    }
    return report


def no_compatible_storage() -> dict:
    """Triggers NoCompatibleStorage: PM981 subsystem A811144D is on the deny list."""
    report = coffee_lake_laptop()
    report["Storage Controllers"] = {
        "Samsung NVMe Controller": {
            "Bus Type": "PCI",
            "Device ID": "144D-A808",
            "Subsystem ID": "A811144D",
            "PCI Path": _pci(0, 23, 0),
            "ACPI Path": "\\_SB.PCI0.NVMED",
            "Disk Drives": ["Samsung PM981 512GB"],
        },
    }
    return report


ALL_HEALTHY = {
    "coffee_lake_laptop": coffee_lake_laptop,
    "alder_lake_desktop": alder_lake_desktop,
    "raven_ridge_amd_laptop": raven_ridge_amd_laptop,
}

ALL_FATAL = {
    "cpu_without_sse4": cpu_without_sse4,
    "gpu_unsupported": gpu_unsupported,
    "intel_vmd_storage": intel_vmd_storage,
    "gpu_missing_from_report": gpu_missing_from_report,
    "no_compatible_storage": no_compatible_storage,
}


def write_report(directory: str, name: str, data: dict) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "{}.json".format(name))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
    return path
