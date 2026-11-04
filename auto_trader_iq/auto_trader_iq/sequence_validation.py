"""Offline checks of platform-clock continuity in a recorded sequence manifest.

This module reads CSV metadata only. It does not open images, inspect signals,
interpret candles, or confirm a simulated/real entry.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ClockSample:
    row_number: int
    frame: str
    elapsed_seconds: float | None
    clock_text: str
    confidence: float
    minute_of_day: int


@dataclass(frozen=True, slots=True)
class MinuteTransition:
    previous: ClockSample
    current: ClockSample
    minute_step: int
    recorder_gap_seconds: float | None


@dataclass(frozen=True, slots=True)
class SequenceValidationReport:
    manifest_path: Path
    total_rows: int
    valid_clock_rows: int
    unreadable_or_low_confidence_rows: int
    transitions: tuple[MinuteTransition, ...]

    @property
    def observed_next_minute(self) -> tuple[MinuteTransition, ...]:
        return tuple(item for item in self.transitions if item.minute_step == 1)

    @property
    def skipped_minutes(self) -> tuple[MinuteTransition, ...]:
        return tuple(item for item in self.transitions if item.minute_step > 1)


def _parse_hms(value: str) -> tuple[int, int, int] | None:
    parts = value.strip().split(":")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return None
    hour, minute, second = (int(part) for part in parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return hour, minute, second


def validate_sequence_manifest(
    path: str | Path,
    *,
    minimum_clock_confidence: float = 70.0,
) -> SequenceValidationReport:
    """Summarize adjacent, confident HORA ATUAL readings from a manifest CSV.

    `path` may be the manifest itself or its containing sequence folder. A
    missing/low-confidence clock row breaks adjacency; the validator never
    bridges over an unreadable frame when deciding whether a rollover was seen.
    """
    if not 0 <= minimum_clock_confidence <= 100:
        raise ValueError("minimum_clock_confidence deve ficar entre 0 e 100.")
    source = Path(path)
    manifest = source / "manifest.csv" if source.is_dir() else source
    if not manifest.is_file():
        raise FileNotFoundError(f"Manifesto não encontrado: {manifest}")

    with manifest.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"frame", "elapsed_seconds", "platform_clock", "clock_confidence"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Colunas ausentes no manifesto: {', '.join(sorted(missing))}")

        samples_by_row: list[ClockSample | None] = []
        valid_rows = 0
        total_rows = 0
        for row_number, row in enumerate(reader, start=2):
            total_rows += 1
            clock_text = (row.get("platform_clock") or "").strip()
            parsed = _parse_hms(clock_text)
            try:
                confidence = float(row.get("clock_confidence") or "")
            except (TypeError, ValueError):
                confidence = -1.0
            try:
                elapsed = float(row.get("elapsed_seconds") or "")
                if not math.isfinite(elapsed):
                    elapsed = None
            except (TypeError, ValueError):
                elapsed = None
            if (
                parsed is None
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 100
                or confidence < minimum_clock_confidence
            ):
                samples_by_row.append(None)
                continue
            hour, minute, _second = parsed
            samples_by_row.append(ClockSample(
                row_number=row_number,
                frame=(row.get("frame") or "").strip(),
                elapsed_seconds=elapsed,
                clock_text=clock_text,
                confidence=confidence,
                minute_of_day=hour * 60 + minute,
            ))
            valid_rows += 1

    transitions: list[MinuteTransition] = []
    for previous, current in zip(samples_by_row, samples_by_row[1:]):
        if previous is None or current is None:
            continue
        minute_step = (current.minute_of_day - previous.minute_of_day) % (24 * 60)
        recorder_gap = None
        if previous.elapsed_seconds is not None and current.elapsed_seconds is not None:
            recorder_gap = current.elapsed_seconds - previous.elapsed_seconds
        transitions.append(MinuteTransition(previous, current, minute_step, recorder_gap))

    return SequenceValidationReport(
        manifest_path=manifest,
        total_rows=total_rows,
        valid_clock_rows=valid_rows,
        unreadable_or_low_confidence_rows=total_rows - valid_rows,
        transitions=tuple(transitions),
    )
