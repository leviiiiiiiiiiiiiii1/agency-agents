"""Clock source selected for automatic DEMO entry timing."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from .candle_timer import PlatformClockReading


UTC_MINUS_THREE = timezone(timedelta(hours=-3), name="UTC-03:00")


def demo_entry_second_action(current_second: int, target_second: int) -> str:
    """Classify a DEMO signal as waiting, on-time, or late for its fixed M1 second."""
    if not 0 <= current_second <= 59 or not 0 <= target_second <= 30:
        raise ValueError("Os segundos precisam estar dentro dos limites do minuto M1.")
    if current_second < target_second:
        return "wait"
    if current_second == target_second:
        return "enter"
    return "late"


def windows_utc_minus_three_reading(instant: datetime | None = None) -> PlatformClockReading:
    """Return the system UTC instant represented in the broker's fixed UTC-3 zone.

    The Windows system clock must be synchronized separately. A timezone conversion
    sets the offset; it does not synchronize the underlying clock with the broker.
    """
    if instant is None:
        instant = datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("A data/hora precisa incluir um fuso horário.")
    local = instant.astimezone(UTC_MINUS_THREE)
    text = f"{local.hour:02d}:{local.minute:02d}:{local.second:02d}"
    return PlatformClockReading(
        local.hour,
        local.minute,
        local.second,
        100.0,
        0,
        0,
        text,
    )


class WindowsUtcMinusThreeClock:
    """Anchor to Windows UTC at activation, then advance monotonically.

    This avoids a wall-clock correction moving backward during an active DEMO
    session. The initial Windows time still needs synchronization with a time
    service; monotonic progression does not synchronize it with the broker.
    """

    def __init__(
        self,
        *,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._anchor_utc: datetime | None = None
        self._anchor_monotonic = 0.0
        self.reset()

    def reset(self) -> None:
        anchor = self._wall_clock()
        if anchor.tzinfo is None:
            raise ValueError("A data/hora precisa incluir um fuso horário.")
        self._anchor_utc = anchor.astimezone(timezone.utc)
        self._anchor_monotonic = self._monotonic_clock()

    def reading(self) -> PlatformClockReading:
        if self._anchor_utc is None:
            raise RuntimeError("O relógio DEMO ainda não foi inicializado.")
        elapsed = self._monotonic_clock() - self._anchor_monotonic
        if elapsed < 0:
            raise RuntimeError("O relógio monotônico do Windows recuou.")
        return windows_utc_minus_three_reading(
            self._anchor_utc + timedelta(seconds=elapsed)
        )
