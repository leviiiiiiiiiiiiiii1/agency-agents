"""Local-only append-only audit log for assisted simulation events."""

from __future__ import annotations

import csv
from pathlib import Path


def append_event_best_effort(store: "SimulationHistoryStore", **event: object) -> str | None:
    """Try to persist metadata; return errors instead of interrupting simulation."""
    try:
        store.append_event(**event)  # type: ignore[arg-type]
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        return str(exc)
    return None


class SimulationHistoryStore:
    """Persist simulation metadata locally; never stores screenshots or sends data."""

    FIELDNAMES = (
        "platform_clock",
        "event",
        "timeframe",
        "direction",
        "observed_text",
        "ocr_confidence",
        "signal_x",
        "signal_y",
        "elapsed_seconds_m1",
        "clock_confidence",
    )

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append_event(
        self,
        *,
        platform_clock: str = "",
        event: str,
        timeframe: str,
        direction: str,
        observed_text: str,
        ocr_confidence: float,
        signal_x: int,
        signal_y: int,
        elapsed_seconds_m1: int | None = None,
        clock_confidence: float | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            if write_header:
                writer.writeheader()
            writer.writerow({
                "platform_clock": platform_clock,
                "event": event,
                "timeframe": timeframe,
                "direction": direction,
                "observed_text": observed_text,
                "ocr_confidence": f"{ocr_confidence:.1f}",
                "signal_x": int(signal_x),
                "signal_y": int(signal_y),
                "elapsed_seconds_m1": (
                    "" if elapsed_seconds_m1 is None else int(elapsed_seconds_m1)
                ),
                "clock_confidence": (
                    "" if clock_confidence is None else f"{clock_confidence:.1f}"
                ),
            })

    def load_recent_entries(self, limit: int = 20) -> list[dict[str, str]]:
        """Return the latest persisted simulated entries for the UI table."""
        if limit <= 0 or not self.path.exists():
            return []
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            rows = [
                row for row in csv.DictReader(handle)
                if row.get("event") in {"entrada_simulada", "entrada_demo_clicada"}
            ]
        return rows[-limit:]
