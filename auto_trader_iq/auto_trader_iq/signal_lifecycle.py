"""Persistent-friendly lifecycle tracking for OCR labels.

The tracker proves only that a label was/was not visible in distinct accepted
frames. It does not prove that the broker created a new signal or identify its
candle; those claims require a validated platform identity source.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import math
import re

from .signal_detector import SignalCandidate


class SignalLifecycle(StrEnum):
    PREEXISTING = "PREEXISTING"
    NEWLY_DETECTED = "NEWLY_DETECTED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    ELIGIBLE = "ELIGIBLE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    DUPLICATE = "DUPLICATE"
    ALTERED = "ALTERED"
    REPINTED = "REPINTED"
    DIRECTION_CHANGED = "DIRECTION_CHANGED"
    INDETERMINATE = "INDETERMINATE"

    # Backward-compatible names used by the earlier prototype/UI.
    PENDING_NEW = "PENDING_CONFIRMATION"
    CONFIRMED_NEW = "CONFIRMED"


@dataclass(frozen=True, slots=True)
class TrackedSignal:
    candidate: SignalCandidate
    tracking_id: str
    fingerprint: str
    lifecycle: SignalLifecycle
    first_seen_at: float
    last_seen_at: float
    first_seen_at_utc: str
    last_seen_at_utc: str
    consecutive_observations: int
    missing_observations: int
    active: bool
    related_tracking_id: str | None = None
    duplicate_count: int = 0
    last_frame_id: str | None = None


@dataclass(slots=True)
class _SignalRecord:
    candidate: SignalCandidate
    tracking_id: str
    fingerprint: str
    first_seen_at: float
    last_seen_at: float
    first_seen_at_utc: str
    last_seen_at_utc: str
    consecutive_observations: int
    missing_observations: int
    active: bool
    lifecycle: SignalLifecycle
    related_tracking_id: str | None
    duplicate_count: int
    last_frame_id: str | None


class SignalLifecycleTracker:
    """Reconcile labels by profile, text, direction, and geometry.

    The first frame after starting/restarting a profile establishes a baseline:
    all labels present then are preexisting and cannot pass the new-signal gate.
    New labels require three distinct meaningful frames. A missing observation,
    long gap, repaint, direction change, or reappearance after expiry makes the
    track indeterminate/non-eligible rather than silently fresh.
    """

    def __init__(
        self,
        *,
        tolerance_x: int = 20,
        tolerance_y: int = 14,
        missing_observations_to_release: int = 3,
        maximum_confirmation_gap_seconds: float = 1.5,
        identity_namespace: str = "default",
        detector_version: str = "ocr-labels-v1",
        position_bucket_px: int = 12,
    ) -> None:
        if tolerance_x < 0 or tolerance_y < 0 or missing_observations_to_release < 1:
            raise ValueError("Parâmetros do ciclo de vida do sinal inválidos.")
        if not math.isfinite(maximum_confirmation_gap_seconds) or maximum_confirmation_gap_seconds <= 0:
            raise ValueError("maximum_confirmation_gap_seconds precisa ser positivo e finito.")
        if position_bucket_px < 1 or not identity_namespace.strip() or not detector_version.strip():
            raise ValueError("Namespace, versão do detector e bucket precisam ser válidos.")
        self.tolerance_x = tolerance_x
        self.tolerance_y = tolerance_y
        self.missing_observations_to_release = missing_observations_to_release
        self.maximum_confirmation_gap_seconds = maximum_confirmation_gap_seconds
        self.identity_namespace = identity_namespace
        self.detector_version = detector_version
        self.position_bucket_px = position_bucket_px
        self._baseline_complete = False
        self._records: list[_SignalRecord] = []
        self._last_frame_id: str | None = None

    def reset(self) -> None:
        self._baseline_complete = False
        self._records.clear()
        self._last_frame_id = None

    def mark_eligible(self, tracking_id: str) -> bool:
        """Promote a confirmed label for manual simulation only after caller gates.

        Eligibility here records that freshness, recent-candle association, and
        persistence gates were satisfied by the caller. It is not a strategy or
        broker authorization and never enables automatic or real execution.
        """
        record = next((item for item in self._records if item.tracking_id == tracking_id), None)
        if record is None or not record.active or record.lifecycle is not SignalLifecycle.CONFIRMED:
            return False
        record.lifecycle = SignalLifecycle.ELIGIBLE
        return True

    def restore(self, rows: list[dict[str, object]]) -> None:
        """Restore persistent records; startup still rebases visible tracks as old."""
        self._records.clear()
        self._baseline_complete = False
        self._last_frame_id = None
        for row in rows:
            try:
                direction = str(row["direction"])
                text = str(row["observed_text"])
                left = int(row.get("left_px", row.get("left")))
                top = int(row.get("top_px", row.get("top")))
                width = int(row.get("width_px", row.get("width")))
                height = int(row.get("height_px", row.get("height")))
                confidence_raw = row.get("confidence")
                confidence = float(confidence_raw) if confidence_raw is not None else 0.0
                lifecycle = SignalLifecycle(str(row["lifecycle"]))
                active = bool(int(row.get("active", 1)))
                tracking_id = str(row["tracking_id"])
                fingerprint = str(row["fingerprint"])
                first_utc = str(row["first_seen_at_utc"])
                last_utc = str(row["last_seen_at_utc"])
            except (KeyError, TypeError, ValueError):
                continue
            candidate = SignalCandidate(direction, confidence, left, top, width, height, text)
            # A new process has no meaningful monotonic relationship to the prior one.
            # Baseline reconciliation resets last_seen_at before any gap calculation.
            self._records.append(_SignalRecord(
                candidate=candidate,
                tracking_id=tracking_id,
                fingerprint=fingerprint,
                first_seen_at=0.0,
                last_seen_at=0.0,
                first_seen_at_utc=first_utc,
                last_seen_at_utc=last_utc,
                consecutive_observations=max(1, int(row.get("consecutive_observations", 1))),
                missing_observations=max(0, int(row.get("missing_observations", 0))),
                active=active,
                lifecycle=lifecycle,
                related_tracking_id=(
                    str(row["related_tracking_id"])
                    if row.get("related_tracking_id") else None
                ),
                duplicate_count=max(0, int(row.get("duplicate_count", 0))),
                last_frame_id=(str(row["last_frame_id"]) if row.get("last_frame_id") else None),
            ))

    def observe(
        self,
        candidates: list[SignalCandidate],
        *,
        observed_at: float,
        frame_id: str,
        observed_at_utc: str,
    ) -> list[TrackedSignal]:
        if not math.isfinite(observed_at):
            raise ValueError("observed_at precisa ser finito.")
        if not frame_id.strip() or not observed_at_utc.strip():
            raise ValueError("frame_id e observed_at_utc são obrigatórios.")
        if frame_id == self._last_frame_id:
            return []
        self._last_frame_id = frame_id

        candidates, duplicate_counts = self._deduplicate(candidates)
        if not self._baseline_complete:
            output = self._establish_baseline(candidates, observed_at, observed_at_utc, frame_id)
            for item in output:
                if duplicate_counts.get(self._candidate_key(item.candidate), 0):
                    self._set_duplicate_count(item.tracking_id, duplicate_counts[self._candidate_key(item.candidate)])
            self._baseline_complete = True
            return self._current_snapshots(candidates)

        matched_indices: set[int] = set()
        output: list[TrackedSignal] = []
        used_record_indices: set[int] = set()
        for candidate in candidates:
            match_index = self._find_match(candidate, used_record_indices, active_only=True)
            if match_index is not None:
                used_record_indices.add(match_index)
                record = self._records[match_index]
                self._update_match(record, candidate, observed_at, observed_at_utc, frame_id)
                matched_indices.add(match_index)
                output.append(self._snapshot(record))
                continue

            nearby = self._find_nearest(candidate, used_record_indices)
            lifecycle = SignalLifecycle.NEWLY_DETECTED
            related_id = None
            if nearby is not None:
                prior = self._records[nearby]
                used_record_indices.add(nearby)
                related_id = prior.tracking_id
                if prior.candidate.direction != candidate.direction:
                    lifecycle = SignalLifecycle.DIRECTION_CHANGED
                elif self._normalize_text(prior.candidate.observed_text) != self._normalize_text(candidate.observed_text):
                    lifecycle = SignalLifecycle.REPINTED
                elif not prior.active:
                    lifecycle = SignalLifecycle.INDETERMINATE
                else:
                    lifecycle = SignalLifecycle.INDETERMINATE
            record = self._new_record(
                candidate,
                observed_at=observed_at,
                observed_at_utc=observed_at_utc,
                frame_id=frame_id,
                lifecycle=lifecycle,
                related_tracking_id=related_id,
            )
            self._records.append(record)
            matched_indices.add(len(self._records) - 1)
            output.append(self._snapshot(record))

        for index, record in enumerate(self._records):
            if index in matched_indices or not record.active:
                continue
            self._mark_missing(record, observed_at)
        for item in output:
            item_key = self._candidate_key(item.candidate)
            self._set_duplicate_count(
                item.tracking_id, duplicate_counts.get(item_key, 0)
            )
        return self._current_snapshots(candidates)

    def _establish_baseline(
        self,
        candidates: list[SignalCandidate],
        observed_at: float,
        observed_at_utc: str,
        frame_id: str,
    ) -> list[TrackedSignal]:
        used: set[int] = set()
        output: list[TrackedSignal] = []
        matched: set[int] = set()
        for candidate in candidates:
            match_index = self._find_match(candidate, used, active_only=True)
            if match_index is None:
                nearby = self._find_nearest(candidate, used)
                related_id = None
                lifecycle = SignalLifecycle.PREEXISTING
                if nearby is not None:
                    prior = self._records[nearby]
                    used.add(nearby)
                    related_id = prior.tracking_id
                    if prior.candidate.direction != candidate.direction:
                        lifecycle = SignalLifecycle.DIRECTION_CHANGED
                    elif self._normalize_text(prior.candidate.observed_text) != self._normalize_text(candidate.observed_text):
                        lifecycle = SignalLifecycle.REPINTED
                    else:
                        lifecycle = SignalLifecycle.INDETERMINATE
                record = self._new_record(
                    candidate,
                    observed_at=observed_at,
                    observed_at_utc=observed_at_utc,
                    frame_id=frame_id,
                    lifecycle=lifecycle,
                    related_tracking_id=related_id,
                )
                self._records.append(record)
                output.append(self._snapshot(record))
                matched.add(len(self._records) - 1)
                continue

            used.add(match_index)
            matched.add(match_index)
            record = self._records[match_index]
            if self._normalize_text(record.candidate.observed_text) != self._normalize_text(candidate.observed_text):
                record.lifecycle = SignalLifecycle.REPINTED
                record.related_tracking_id = record.tracking_id
            elif record.candidate.direction != candidate.direction:
                record.lifecycle = SignalLifecycle.DIRECTION_CHANGED
                record.related_tracking_id = record.tracking_id
            else:
                record.lifecycle = SignalLifecycle.PREEXISTING
            record.candidate = candidate
            record.first_seen_at = observed_at
            record.last_seen_at = observed_at
            record.last_seen_at_utc = observed_at_utc
            record.missing_observations = 0
            record.consecutive_observations = 1
            record.active = True
            record.last_frame_id = frame_id
            output.append(self._snapshot(record))

        for index, record in enumerate(self._records):
            if index in matched or not record.active:
                continue
            self._mark_missing(record, observed_at)
        return output

    def _update_match(
        self,
        record: _SignalRecord,
        candidate: SignalCandidate,
        observed_at: float,
        observed_at_utc: str,
        frame_id: str,
    ) -> None:
        gap = observed_at - record.last_seen_at
        was_missing = record.missing_observations > 0
        old_text = self._normalize_text(record.candidate.observed_text)
        new_text = self._normalize_text(candidate.observed_text)
        if old_text != new_text:
            record.lifecycle = SignalLifecycle.REPINTED
            record.related_tracking_id = record.tracking_id
            record.consecutive_observations = 1
        elif record.lifecycle in {SignalLifecycle.NEWLY_DETECTED, SignalLifecycle.PENDING_CONFIRMATION}:
            if was_missing or gap < 0 or gap > self.maximum_confirmation_gap_seconds:
                record.lifecycle = SignalLifecycle.NEWLY_DETECTED
                record.consecutive_observations = 1
            else:
                record.consecutive_observations += 1
                if record.consecutive_observations == 2:
                    record.lifecycle = SignalLifecycle.PENDING_CONFIRMATION
                elif record.consecutive_observations >= 3:
                    record.lifecycle = SignalLifecycle.CONFIRMED
        elif record.lifecycle is SignalLifecycle.CONFIRMED and (
            was_missing or gap < 0 or gap > self.maximum_confirmation_gap_seconds
        ):
            record.lifecycle = SignalLifecycle.INDETERMINATE
            record.consecutive_observations = 1
        elif record.lifecycle in {
            SignalLifecycle.PREEXISTING,
            SignalLifecycle.REPINTED,
            SignalLifecycle.ALTERED,
            SignalLifecycle.DIRECTION_CHANGED,
            SignalLifecycle.INDETERMINATE,
            SignalLifecycle.DUPLICATE,
            SignalLifecycle.CANCELLED,
            SignalLifecycle.ELIGIBLE,
        }:
            if record.lifecycle is SignalLifecycle.ELIGIBLE and (was_missing or gap > self.maximum_confirmation_gap_seconds):
                record.lifecycle = SignalLifecycle.INDETERMINATE
        record.candidate = candidate
        record.last_seen_at = observed_at
        record.last_seen_at_utc = observed_at_utc
        record.missing_observations = 0
        record.active = True
        record.last_frame_id = frame_id

    def _mark_missing(self, record: _SignalRecord, observed_at: float) -> None:
        record.missing_observations += 1
        if record.lifecycle in {
            SignalLifecycle.NEWLY_DETECTED,
            SignalLifecycle.PENDING_CONFIRMATION,
            SignalLifecycle.CONFIRMED,
            SignalLifecycle.ELIGIBLE,
        }:
            record.lifecycle = SignalLifecycle.INDETERMINATE
            record.consecutive_observations = 0
        if record.missing_observations >= self.missing_observations_to_release:
            record.lifecycle = SignalLifecycle.EXPIRED
            record.active = False
        record.last_seen_at = observed_at

    def _new_record(
        self,
        candidate: SignalCandidate,
        *,
        observed_at: float,
        observed_at_utc: str,
        frame_id: str,
        lifecycle: SignalLifecycle,
        related_tracking_id: str | None = None,
    ) -> _SignalRecord:
        tracking_id = self._stable_id(candidate, observed_at_utc)
        return _SignalRecord(
            candidate=candidate,
            tracking_id=tracking_id,
            fingerprint=tracking_id,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            first_seen_at_utc=observed_at_utc,
            last_seen_at_utc=observed_at_utc,
            consecutive_observations=1,
            missing_observations=0,
            active=True,
            lifecycle=lifecycle,
            related_tracking_id=related_tracking_id,
            duplicate_count=0,
            last_frame_id=frame_id,
        )

    def _stable_id(self, candidate: SignalCandidate, first_seen_at_utc: str) -> str:
        center_x = candidate.left + candidate.width // 2
        center_y = candidate.top + candidate.height // 2
        payload = {
            "namespace": self.identity_namespace,
            "direction": candidate.direction,
            "text": self._normalize_text(candidate.observed_text),
            "x_bucket": center_x // self.position_bucket_px,
            "y_bucket": center_y // self.position_bucket_px,
            "first_seen_at_utc": first_seen_at_utc,
            "detector_version": self.detector_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _find_match(
        self, candidate: SignalCandidate, used: set[int], *, active_only: bool
    ) -> int | None:
        choices = [
            (abs(record.candidate.left - candidate.left) + abs(record.candidate.top - candidate.top), index)
            for index, record in enumerate(self._records)
            if index not in used
            and (record.active or not active_only)
            and record.candidate.direction == candidate.direction
            and abs(record.candidate.left - candidate.left) <= self.tolerance_x
            and abs(record.candidate.top - candidate.top) <= self.tolerance_y
        ]
        return min(choices)[1] if choices else None

    def _find_nearest(self, candidate: SignalCandidate, used: set[int]) -> int | None:
        choices = [
            (abs(record.candidate.left - candidate.left) + abs(record.candidate.top - candidate.top), index)
            for index, record in enumerate(self._records)
            if index not in used
            and abs(record.candidate.left - candidate.left) <= self.tolerance_x
            and abs(record.candidate.top - candidate.top) <= self.tolerance_y
        ]
        return min(choices)[1] if choices else None

    def _deduplicate(
        self, candidates: list[SignalCandidate]
    ) -> tuple[list[SignalCandidate], dict[tuple[str, int, int, str], int]]:
        representatives: list[SignalCandidate] = []
        counts: list[int] = []
        for candidate in candidates:
            match_index = next((
                index for index, existing in enumerate(representatives)
                if existing.direction == candidate.direction
                and self._normalize_text(existing.observed_text) == self._normalize_text(candidate.observed_text)
                and abs(existing.left - candidate.left) <= self.tolerance_x // 2
                and abs(existing.top - candidate.top) <= self.tolerance_y // 2
            ), None)
            if match_index is None:
                representatives.append(candidate)
                counts.append(0)
            else:
                counts[match_index] += 1
                if candidate.confidence > representatives[match_index].confidence:
                    representatives[match_index] = candidate
        duplicate_counts = {
            self._candidate_key(candidate): count
            for candidate, count in zip(representatives, counts)
            if count
        }
        return representatives, duplicate_counts

    @staticmethod
    def _candidate_key(candidate: SignalCandidate) -> tuple[str, int, int, str]:
        return (
            candidate.direction,
            candidate.left,
            candidate.top,
            SignalLifecycleTracker._normalize_text(candidate.observed_text),
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(text).upper())

    def _set_duplicate_count(self, tracking_id: str, count: int) -> None:
        record = next((item for item in self._records if item.tracking_id == tracking_id), None)
        if record is not None:
            record.duplicate_count = count

    def _current_snapshots(self, candidates: list[SignalCandidate]) -> list[TrackedSignal]:
        snapshots = []
        for candidate in candidates:
            match = self._find_match(candidate, set(), active_only=True)
            if match is not None:
                snapshots.append(self._snapshot(self._records[match]))
        return snapshots

    def export_state(self) -> list[dict[str, object]]:
        return [
            {
                "tracking_id": record.tracking_id,
                "fingerprint": record.fingerprint,
                "opportunity_id": record.tracking_id,
                "direction": record.candidate.direction,
                "observed_text": record.candidate.observed_text,
                "left": record.candidate.left,
                "top": record.candidate.top,
                "width": record.candidate.width,
                "height": record.candidate.height,
                "confidence": record.candidate.confidence,
                "first_seen_at_utc": record.first_seen_at_utc,
                "last_seen_at_utc": record.last_seen_at_utc,
                "lifecycle": record.lifecycle.value,
                "consecutive_observations": record.consecutive_observations,
                "missing_observations": record.missing_observations,
                "active": record.active,
                "related_tracking_id": record.related_tracking_id,
                "duplicate_count": record.duplicate_count,
                "last_frame_id": record.last_frame_id,
                "detector_version": self.detector_version,
            }
            for record in self._records
        ]

    @staticmethod
    def _snapshot(record: _SignalRecord) -> TrackedSignal:
        return TrackedSignal(
            candidate=record.candidate,
            tracking_id=record.tracking_id,
            fingerprint=record.fingerprint,
            lifecycle=record.lifecycle,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
            first_seen_at_utc=record.first_seen_at_utc,
            last_seen_at_utc=record.last_seen_at_utc,
            consecutive_observations=record.consecutive_observations,
            missing_observations=record.missing_observations,
            active=record.active,
            related_tracking_id=record.related_tracking_id,
            duplicate_count=record.duplicate_count,
            last_frame_id=record.last_frame_id,
        )
