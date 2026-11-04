"""Local-only CSV audit log for assisted simulation events and entries."""

from __future__ import annotations

import csv
import os
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
        "armed_platform_clock",
        "entry_delay_platform_seconds",
        "clock_source",
        "armed_clock",
        "entry_delay_seconds",
    )

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _upgrade_schema_if_needed(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            old_fields = reader.fieldnames or []
            if all(name in old_fields for name in self.FIELDNAMES):
                return
            rows = list(reader)
        fieldnames = list(dict.fromkeys([*old_fields, *self.FIELDNAMES]))
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") or "" for name in fieldnames})
        os.replace(temporary, self.path)

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
        armed_platform_clock: str = "",
        entry_delay_platform_seconds: int | None = None,
        clock_source: str = "",
        armed_clock: str = "",
        entry_delay_seconds: int | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._upgrade_schema_if_needed()
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
                "armed_platform_clock": armed_platform_clock,
                "entry_delay_platform_seconds": (
                    "" if entry_delay_platform_seconds is None
                    else int(entry_delay_platform_seconds)
                ),
                "clock_source": clock_source,
                "armed_clock": armed_clock,
                "entry_delay_seconds": (
                    "" if entry_delay_seconds is None else int(entry_delay_seconds)
                ),
            })

    def export_entries_csv(self, destination: Path) -> int:
        """Write all persisted entry rows to a separate CSV file and return their count."""
        target = Path(destination)
        if target.resolve() == self.path.resolve():
            raise ValueError("A exportação não pode sobrescrever o histórico original.")
        rows: list[dict[str, str]] = []
        if self.path.exists():
            with self.path.open("r", newline="", encoding="utf-8") as handle:
                rows = [
                    row for row in csv.DictReader(handle)
                    if row.get("event") == "entrada_simulada"
                ]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def clear(self) -> None:
        """Permanently remove the local event log if it exists."""
        self.path.unlink(missing_ok=True)

    def load_recent_entries(self, limit: int = 20) -> list[dict[str, str]]:
        """Return the latest persisted simulated entries for the UI table."""
        if limit <= 0 or not self.path.exists():
            return []
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            rows = [
                row for row in csv.DictReader(handle)
                if row.get("event") == "entrada_simulada"
            ]
        return rows[-limit:]
