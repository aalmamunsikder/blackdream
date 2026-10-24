"""Which devices work on each macOS release, arranged as a read-only grid.

The Compatibility table answers for the one release the user has selected; this lays
every selectable release beside every graded device so the window can show the
trade-off at once. Each cell is copied from
:func:`blackdream.core.verdicts.target_status` with the same OCLP range -- the engine
is never called and nothing is re-graded here. The export repeats the table's
boundary: these ranges are not a boot test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from blackdream.core import verdicts, versions

_HEADER = "BlackDream - Hardware compatibility by macOS release"
BOUNDARY = ("These statuses use the same compatibility ranges as the device table. "
             "They do not test firmware, hardware or whether macOS boots.")


def _count(statuses: tuple[verdicts.Status, ...], key: str) -> int:
    return sum(1 for status in statuses if status.key == key)


@dataclass(frozen=True)
class Column:
    """One selectable macOS release, with every row's answer in row order."""

    option: versions.VersionOption
    statuses: tuple[verdicts.Status, ...]

    @property
    def supported(self) -> int:
        return _count(self.statuses, "supported")

    @property
    def limited(self) -> int:
        return _count(self.statuses, "limited")

    @property
    def unsupported(self) -> int:
        return _count(self.statuses, "unsupported")

    @property
    def unknown(self) -> int:
        return _count(self.statuses, "unknown")


@dataclass(frozen=True)
class Row:
    """One graded device, with its answer for every column in column order."""

    verdict: verdicts.Verdict
    cells: tuple[verdicts.Status, ...]


@dataclass(frozen=True)
class Matrix:
    """The grid as built; both axes carry the statuses, so neither is recomputed."""

    columns: tuple[Column, ...]
    rows: tuple[Row, ...]

    @property
    def empty(self) -> bool:
        return not self.rows or not self.columns

    def status(self, row_index: int, column_index: int) -> verdicts.Status:
        return self.rows[row_index].cells[column_index]


def build(items: Sequence[verdicts.Verdict],
          options: Sequence[versions.VersionOption],
          oclp_range: tuple[str, str] | None = None) -> Matrix:
    """Call ``target_status`` for every device and release pair.

    Nothing is graded here, so either selection being empty gives an empty matrix
    rather than a cell with no answer.
    """
    devices = tuple(items)
    releases = tuple(options)
    if not devices or not releases:
        return Matrix(columns=(), rows=())

    columns = []
    for option in releases:
        columns.append(Column(option, tuple(
            verdicts.target_status(device, option.value, oclp_range)
            for device in devices)))
    rows = tuple(
        Row(device, tuple(column.statuses[index] for column in columns))
        for index, device in enumerate(devices)
    )
    return Matrix(columns=tuple(columns), rows=rows)


def to_text(matrix: Matrix) -> str:
    """The clipboard export: header, per-release counts, per-device cells, boundary."""
    lines = [_HEADER]
    for column in matrix.columns:
        lines.append(
            "{}: Supported {}, Limited support {}, Not supported {}, Not graded {}".format(
                column.option.name, column.supported, column.limited,
                column.unsupported, column.unknown))
    for row in matrix.rows:
        cells = [row.verdict.name, row.verdict.class_label]
        cells.extend(status.label for status in row.cells)
        lines.append("\t".join(cells))
    lines.append(BOUNDARY)
    return "\n".join(lines) + "\n"
