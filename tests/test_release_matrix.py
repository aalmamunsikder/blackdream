"""The release grid copies the device table's verdicts and adds no judgement.

These tests pin the two promises the window depends on: a cell is exactly what
``verdicts.target_status`` says for that release, and the export repeats the
table's boundary rather than turning a range into a boot guarantee.
"""

from __future__ import annotations

from blackdream.core import release_matrix, verdicts, versions

BOUNDARY = ("These statuses use the same compatibility ranges as the device table. "
            "They do not test firmware, hardware or whether macOS boots.")

ALWAYS = ("25.99.99", "17.99.99")
UP_TO_VENTURA = ("22.99.99", "17.99.99")
OCLP_RANGE = ("24.99.99", "20.99.99")


def option(major: int, name: str | None = None) -> versions.VersionOption:
    return versions.VersionOption(darwin_major=major,
                                  name=name or "macOS {}".format(major),
                                  requires_oclp=False, is_suggested=False)


def verdict(name: str, compatibility, *, oclp=None, compatible=True,
            section: str = "GPU", class_label: str | None = None) -> verdicts.Verdict:
    return verdicts.Verdict(section=section, name=name, text="Supported",
                            compatible=compatible,
                            class_label=section if class_label is None else class_label,
                            compatibility=compatibility, oclp=oclp)


def test_a_device_supported_on_one_release_and_not_the_next():
    grid = release_matrix.build(
        [verdict("Intel UHD 630", UP_TO_VENTURA)],
        [option(21), option(23)])

    assert [column.option.darwin_major for column in grid.columns] == [21, 23]
    assert [cell.key for cell in grid.rows[0].cells] == ["supported", "unsupported"]
    assert grid.status(0, 0).label == "Supported"
    assert grid.status(0, 1).label == "Not supported"


def test_a_release_past_the_native_ceiling_falls_back_to_the_device_oclp_range():
    grid = release_matrix.build(
        [verdict("AMD Radeon RX 580", UP_TO_VENTURA, oclp=OCLP_RANGE)],
        [option(21), option(23), option(24), option(25)])

    assert [cell.key for cell in grid.rows[0].cells] == [
        "supported", "limited", "limited", "unsupported"]
    assert grid.status(0, 1).label == "Limited support"


def test_the_oclp_range_argument_stands_in_when_a_device_has_none():
    grid = release_matrix.build(
        [verdict("AMD Radeon RX 580", UP_TO_VENTURA)],
        [option(23)],
        oclp_range=OCLP_RANGE)

    assert grid.status(0, 0).key == "limited"


def test_an_ungraded_device_is_unknown_on_every_release():
    grid = release_matrix.build(
        [verdict("Mystery Card", None, compatible=None)],
        [option(21), option(25)])

    assert [cell.key for cell in grid.rows[0].cells] == ["unknown", "unknown"]
    assert grid.rows[0].cells[0].label == "Not graded"


def test_each_release_counts_its_own_column():
    items = [
        verdict("Native everywhere", ALWAYS),
        verdict("Native up to Ventura", UP_TO_VENTURA),
        verdict("Ungraded", None, compatible=None),
        verdict("Rejected by the engine", None, compatible=False),
    ]

    grid = release_matrix.build(items, [option(21), option(25)])
    early, late = grid.columns

    assert (early.supported, early.limited, early.unsupported, early.unknown) == (2, 0, 1, 1)
    assert (late.supported, late.limited, late.unsupported, late.unknown) == (1, 0, 2, 1)
    for column in grid.columns:
        total = column.supported + column.limited + column.unsupported + column.unknown
        assert total == len(grid.rows) == 4


def test_no_devices_or_no_releases_is_an_empty_matrix_not_an_error():
    assert release_matrix.build([], []).empty
    assert release_matrix.build([], [option(21)]).empty
    assert release_matrix.build([verdict("A", ALWAYS)], []).empty


def test_the_export_ends_with_the_boundary_sentence_verbatim():
    grid = release_matrix.build([verdict("A", ALWAYS)], [option(21)])

    text = release_matrix.to_text(grid)

    assert text.endswith(BOUNDARY + "\n")
    assert text.count(BOUNDARY) == 1
    assert text.splitlines()[-1] == BOUNDARY
    assert not text.endswith("\n\n")


def test_the_export_lists_releases_then_devices_with_tabs():
    items = [
        verdict("Intel UHD 630", UP_TO_VENTURA, section="GPU", class_label="GPU"),
        verdict("BCM94360", UP_TO_VENTURA, section="Network", class_label="Wi-Fi"),
    ]
    grid = release_matrix.build(
        items,
        [option(21, "macOS Monterey 12"), option(25, "macOS Tahoe 26")])

    lines = release_matrix.to_text(grid).splitlines()

    assert "BlackDream" in lines[0]
    assert "Hardware compatibility by macOS release" in lines[0]
    assert lines[1] == ("macOS Monterey 12: Supported 2, Limited support 0, "
                        "Not supported 0, Not graded 0")
    assert lines[2] == ("macOS Tahoe 26: Supported 0, Limited support 0, "
                        "Not supported 2, Not graded 0")
    assert lines[3].split("\t") == ["Intel UHD 630", "GPU", "Supported", "Not supported"]
    assert lines[4].split("\t") == ["BCM94360", "Wi-Fi", "Supported", "Not supported"]
    assert lines[5] == BOUNDARY
    assert len(lines) == 6


def test_rows_and_columns_keep_the_order_they_were_given():
    items = [verdict("Second", ALWAYS), verdict("First", ALWAYS)]
    releases = [option(25), option(21)]

    grid = release_matrix.build(items, releases)

    assert [row.verdict.name for row in grid.rows] == ["Second", "First"]
    assert [column.option.darwin_major for column in grid.columns] == [25, 21]
    for row_index, row in enumerate(grid.rows):
        for column_index, column in enumerate(grid.columns):
            assert grid.status(row_index, column_index) == row.cells[column_index]
            assert row.cells[column_index] == column.statuses[row_index]
