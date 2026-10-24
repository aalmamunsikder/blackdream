"""What to know before the first boot, said without offering to perform it.

The six steps are advice for the person at the machine. BlackDream has no boot
button, does not write firmware and does not install anything, so the text is the
whole feature: no action is exposed, only the boundary and the checks worth making
before a first attempt.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    title: str
    body: str
    icon: str


STEPS = (
    Step(
        "Use a spare USB drive",
        "Write the installer to a stick you can erase. Leave the machine's own "
        "disk out of the process until macOS runs.",
        "usb",
    ),
    Step(
        "Check firmware settings",
        "Turn Secure Boot off or enrol OpenCore the way your board's guide "
        "describes, and note every setting you change.",
        "gear",
    ),
    Step(
        "Keep a way back",
        "Know how to open the firmware boot menu and start the existing system "
        "before OpenCore is in the boot path.",
        "clock",
    ),
    Step(
        "Expect the OpenCore picker",
        "The picker lists the installer and any existing entries. If nothing "
        "appears, folder checks are the first place to look.",
        "logs",
    ),
    Step(
        "Use verbose boot for the first run",
        "Add -v to the boot arguments when a run stops early, so the last line "
        "names the driver that failed.",
        "book",
    ),
    Step(
        "Plan recovery",
        "A second machine and a working macOS installer are the recovery plan. "
        "BlackDream never boots, installs or writes firmware.",
        "shield",
    ),
)


def to_text() -> str:
    """The six steps, then the sentence that states what BlackDream will not do."""
    blocks = ["{}\n{}".format(step.title, step.body) for step in STEPS]
    blocks.append(
        "This is advice. BlackDream has no boot button and writes no firmware.")
    return "\n\n".join(blocks) + "\n"
