"""Prevent repeated DEMO entries from one still-visible OCR signal."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math
import time

from .signal_detector import SignalCandidate


@dataclass(slots=True)
class _ConsumedSignal:
    direction: str
    left: int
    top: int
    consumed_at: float
    missing_observations: int = 0

    def matches(self, candidate: SignalCandidate, tolerance_x: int, tolerance_y: int) -> bool:
        return (
            candidate.direction == self.direction
            and abs(candidate.left - self.left) <= tolerance_x
            and abs(candidate.top - self.top) <= tolerance_y
        )


class DemoSignalRepeatGuard:
    """Latch a consumed signal until its OCR tag disappears.

    OCR coordinate jitter is tolerated. A consumed signal stays locked for at
    least 30 seconds, and also until several consecutive OCR updates no longer
    show a nearby candidate.
    """

    def __init__(
        self,
        *,
        tolerance_x: int = 128,
        tolerance_y: int = 64,
        minimum_lock_seconds: float = 30.0,
        missing_observations_to_release: int = 3,
    ) -> None:
        if (
            tolerance_x < 0
            or tolerance_y < 0
            or not math.isfinite(minimum_lock_seconds)
            or minimum_lock_seconds < 0
            or missing_observations_to_release < 1
        ):
            raise ValueError("Os limites do bloqueio de sinal precisam ser válidos.")
        self.tolerance_x = tolerance_x
        self.tolerance_y = tolerance_y
        self.minimum_lock_seconds = minimum_lock_seconds
        self.missing_observations_to_release = missing_observations_to_release
        self._consumed: list[_ConsumedSignal] = []

    def mark_consumed(
        self, direction: str, left: int, top: int, *, consumed_at: float | None = None
    ) -> None:
        """Remember a signal after entry or after it expires without an entry."""
        observed_at = time.monotonic() if consumed_at is None else consumed_at
        if not math.isfinite(observed_at):
            raise ValueError("O instante de consumo precisa ser finito.")
        for signal in self._consumed:
            if (
                signal.direction == direction
                and abs(signal.left - left) <= self.tolerance_x
                and abs(signal.top - top) <= self.tolerance_y
            ):
                signal.consumed_at = max(signal.consumed_at, observed_at)
                signal.missing_observations = 0
                return
        self._consumed.append(_ConsumedSignal(direction, left, top, observed_at))

    def observe(
        self, candidates: Iterable[SignalCandidate], *, now: float | None = None
    ) -> None:
        """Update signal-presence latches from the filtered recent-candidate list."""
        observed_at = time.monotonic() if now is None else now
        if not math.isfinite(observed_at):
            raise ValueError("O instante da observação precisa ser finito.")
        current = list(candidates)
        retained: list[_ConsumedSignal] = []
        for signal in self._consumed:
            if any(signal.matches(candidate, self.tolerance_x, self.tolerance_y) for candidate in current):
                signal.missing_observations = 0
                retained.append(signal)
                continue
            signal.missing_observations += 1
            lock_elapsed = observed_at - signal.consumed_at
            can_release = (
                signal.missing_observations >= self.missing_observations_to_release
                and lock_elapsed >= self.minimum_lock_seconds
            )
            if not can_release:
                retained.append(signal)
        self._consumed = retained

    def blocks(self, candidate: SignalCandidate) -> bool:
        """Whether this candidate resembles a signal already entered."""
        return any(
            signal.matches(candidate, self.tolerance_x, self.tolerance_y)
            for signal in self._consumed
        )
