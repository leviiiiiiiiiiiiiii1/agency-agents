"""Explicit, bounded local recording of chart-region sequences for validation."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import time
from typing import Iterable

from PIL import Image


class SequenceRecorder:
    """Save user-requested screen frames and OCR metadata to a local session folder.

    The duration is bounded to two minutes. Timing here only spaces diagnostic
    screenshots; trade-window logic must use the platform clock instead.
    """

    MAX_DURATION_SECONDS = 120

    def __init__(
        self,
        output_root: Path,
        duration_seconds: float = 75.0,
        interval_seconds: float = 1.0,
    ) -> None:
        if not 1 <= duration_seconds <= self.MAX_DURATION_SECONDS:
            raise ValueError(f"duration_seconds must be between 1 and {self.MAX_DURATION_SECONDS}")
        if not 0.1 <= interval_seconds <= duration_seconds:
            raise ValueError("interval_seconds must be positive and no longer than the recording")
        self.output_root = Path(output_root)
        self.duration_seconds = float(duration_seconds)
        self.interval_seconds = float(interval_seconds)
        self.output_dir: Path | None = None
        self.started_at: float | None = None
        self.last_frame_at: float | None = None
        self.frames_saved = 0
        self._manifest_file = None
        self._manifest_writer = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def elapsed_seconds(self) -> float:
        if not self._active or self.started_at is None:
            return 0.0
        # Monotonic time is used only for local recorder duration/cadence.
        return max(0.0, time.monotonic() - self.started_at)

    def start(self, now: float) -> Path:
        if self._active:
            raise RuntimeError("recording is already active")
        self.output_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = self.output_root / f"sequence-{stamp}"
        suffix = 1
        while output_dir.exists():
            output_dir = self.output_root / f"sequence-{stamp}-{suffix}"
            suffix += 1
        output_dir.mkdir()
        manifest_file = (output_dir / "manifest.csv").open("w", newline="", encoding="utf-8")
        writer = csv.writer(manifest_file)
        writer.writerow((
            "frame", "elapsed_seconds", "platform_clock", "clock_confidence",
            "candle_count", "candidates",
        ))
        manifest_file.flush()

        self.output_dir = output_dir
        self.started_at = float(now)
        self.last_frame_at = None
        self.frames_saved = 0
        self._manifest_file = manifest_file
        self._manifest_writer = writer
        self._active = True
        return output_dir

    def record_frame(
        self,
        image: Image.Image,
        now: float,
        *,
        platform_clock: str = "",
        clock_confidence: float | None = None,
        candle_count: int | None = None,
        candidates: Iterable[str] = (),
    ) -> bool:
        """Save a due frame; return True if a frame was written."""
        if not self._active or self.started_at is None or self.output_dir is None:
            return False
        elapsed = max(0.0, float(now) - self.started_at)
        if elapsed >= self.duration_seconds:
            self.stop()
            return False
        if self.last_frame_at is not None and float(now) - self.last_frame_at < self.interval_seconds:
            return False

        frame_number = self.frames_saved + 1
        filename = f"frame-{frame_number:04d}.jpg"
        image.save(self.output_dir / filename, format="JPEG", quality=90, optimize=True)
        candidate_summary = "; ".join(str(candidate) for candidate in candidates)
        assert self._manifest_writer is not None and self._manifest_file is not None
        self._manifest_writer.writerow((
            filename,
            f"{elapsed:.3f}",
            platform_clock,
            "" if clock_confidence is None else f"{clock_confidence:.1f}",
            "" if candle_count is None else int(candle_count),
            candidate_summary,
        ))
        self._manifest_file.flush()
        self.frames_saved = frame_number
        self.last_frame_at = float(now)
        return True

    def stop(self) -> Path | None:
        if self._manifest_file is not None:
            self._manifest_file.close()
        self._manifest_file = None
        self._manifest_writer = None
        self._active = False
        return self.output_dir
