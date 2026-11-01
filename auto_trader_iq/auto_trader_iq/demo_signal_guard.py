"""Prevent repeated DEMO entries from one still-visible OCR signal."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .signal_detector import SignalCandidate


@dataclass(slots=True)
class _ConsumedSignal:
    direction: str
    left: int
    top: int
    missing_observations: int = 0

    def matches(self, candidate: SignalCandidate, tolerance_x: int, tolerance_y: int) -> bool:
        return (
            candidate.direction == self.direction
            and abs(candidate.left - self.left) <= tolerance_x
            and abs(candidate.top - self.top) <= tolerance_y
        )


class DemoSignalRepeatGuard:
    """Latch a successfully entered signal until its OCR tag disappears.

    Small OCR coordinate jitter is tolerated. A consumed signal is released only
    after several consecutive OCR updates no longer show a nearby candidate.
    """

    def __init__(
        self,
        *,
        tolerance_x: int = 96,
        tolerance_y: int = 48,
        missing_observations_to_release: int = 3,
    ) -> None:
        if tolerance_x < 0 or tolerance_y < 0 or missing_observations_to_release < 1:
            raise ValueError("Os limites do bloqueio de sinal precisam ser válidos.")
        self.tolerance_x = tolerance_x
        self.tolerance_y = tolerance_y
        self.missing_observations_to_release = missing_observations_to_release
        self._consumed: list[_ConsumedSignal] = []

    def mark_entered(self, direction: str, left: int, top: int) -> None:
        """Remember a signal only after its DEMO click was sent."""
        for signal in self._consumed:
            if (
                signal.direction == direction
                and abs(signal.left - left) <= self.tolerance_x
                and abs(signal.top - top) <= self.tolerance_y
            ):
                signal.missing_observations = 0
                return
        self._consumed.append(_ConsumedSignal(direction, left, top))

    def observe(self, candidates: Iterable[SignalCandidate]) -> None:
        """Update signal-presence latches from the filtered recent-candidate list."""
        current = list(candidates)
        retained: list[_ConsumedSignal] = []
        for signal in self._consumed:
            if any(signal.matches(candidate, self.tolerance_x, self.tolerance_y) for candidate in current):
                signal.missing_observations = 0
                retained.append(signal)
                continue
            signal.missing_observations += 1
            if signal.missing_observations < self.missing_observations_to_release:
                retained.append(signal)
        self._consumed = retained

    def blocks(self, candidate: SignalCandidate) -> bool:
        """Whether this candidate resembles a signal already entered."""
        return any(
            signal.matches(candidate, self.tolerance_x, self.tolerance_y)
            for signal in self._consumed
        )
