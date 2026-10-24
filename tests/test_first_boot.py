"""First boot is advice, with no button that could perform any of it."""

from __future__ import annotations

from blackdream.core import first_boot

TITLES = [
    "Use a spare USB drive",
    "Check firmware settings",
    "Keep a way back",
    "Expect the OpenCore picker",
    "Use verbose boot for the first run",
    "Plan recovery",
]
ICONS = ["usb", "gear", "clock", "logs", "book", "shield"]
BOUNDARY = ("This is advice. BlackDream has no boot button and writes no "
            "firmware.")


def test_there_are_six_steps_in_the_stated_order():
    assert len(first_boot.STEPS) == 6
    assert [step.title for step in first_boot.STEPS] == TITLES
    assert [step.icon for step in first_boot.STEPS] == ICONS


def test_every_step_has_a_title_body_and_icon():
    for step in first_boot.STEPS:
        assert step.title.strip()
        assert step.body.strip()
        assert step.icon.strip()


def test_the_export_contains_every_step_and_ends_with_the_boundary():
    text = first_boot.to_text()

    for step in first_boot.STEPS:
        assert step.title in text
        assert step.body in text
    assert text.splitlines()[-1] == BOUNDARY
    assert text.count("This is advice.") == 1
    assert text.endswith("\n")
