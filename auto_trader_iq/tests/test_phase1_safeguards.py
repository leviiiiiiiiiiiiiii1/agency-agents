import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from auto_trader_iq.capture_quality import FrameFreshnessMonitor, assess_frame
from auto_trader_iq.operation_modes import (
    ModeDecision,
    OperationMode,
    actual_order_execution_allowed,
    mode_decision,
)
from auto_trader_iq.opportunity_store import OpportunityStore
from auto_trader_iq.signal_detector import SignalCandidate
from auto_trader_iq.signal_lifecycle import SignalLifecycle, SignalLifecycleTracker


class CaptureQualityTests(unittest.TestCase):
    def test_rejects_small_and_stale_frames(self):
        image = Image.new("RGB", (80, 60), "black")
        quality = assess_frame(image, age_seconds=2.0)
        self.assertFalse(quality.usable)
        self.assertTrue(any("pequena" in reason for reason in quality.reasons))
        self.assertTrue(any("desatualizado" in reason for reason in quality.reasons))

    def test_static_market_frame_is_not_rejected_as_frozen(self):
        image = Image.new("RGB", (320, 240), "white")
        draw = ImageDraw.Draw(image)
        draw.line((10, 20, 280, 180), fill="black", width=5)
        quality = assess_frame(image, age_seconds=0.2)
        self.assertTrue(quality.usable, quality.reasons)
        self.assertGreaterEqual(quality.grayscale_variance, 2.0)

    def test_rejects_nearly_uniform_frame(self):
        image = Image.new("RGB", (320, 240), (70, 70, 70))
        quality = assess_frame(image, age_seconds=0.1)
        self.assertFalse(quality.usable)
        self.assertTrue(any("uniforme" in reason for reason in quality.reasons))


class FrameFreshnessTests(unittest.TestCase):
    def test_exact_repeats_are_not_independent_and_eventually_block(self):
        monitor = FrameFreshnessMonitor(freeze_after_seconds=1.0)
        image = Image.new("RGB", (320, 240), "#111111")
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 30, 100, 100), fill="#35c45a")
        first = monitor.observe(image, observed_at=0.0)
        repeated = monitor.observe(image.copy(), observed_at=0.5)
        frozen = monitor.observe(image.copy(), observed_at=1.0)
        self.assertTrue(first.independent)
        self.assertFalse(repeated.independent)
        self.assertEqual(repeated.change_sequence, first.change_sequence)
        self.assertTrue(frozen.frozen)
        self.assertEqual(frozen.repeated_frames, 2)

    def test_material_visual_change_advances_sequence(self):
        monitor = FrameFreshnessMonitor()
        first_image = Image.new("RGB", (320, 240), "#111111")
        first = monitor.observe(first_image, observed_at=1.0)
        second_image = first_image.copy()
        ImageDraw.Draw(second_image).rectangle((20, 20, 180, 150), fill="#35c45a")
        second = monitor.observe(second_image, observed_at=1.25)
        self.assertTrue(second.independent)
        self.assertGreater(second.change_sequence, first.change_sequence)
        self.assertGreater(second.changed_fraction, 0.001)

    def test_rejects_non_monotonic_observation_clock(self):
        monitor = FrameFreshnessMonitor()
        image = Image.new("RGB", (320, 240), "#111111")
        monitor.observe(image, observed_at=2.0)
        with self.assertRaises(ValueError):
            monitor.observe(image, observed_at=1.0)


class OperationModeTests(unittest.TestCase):
    def test_modes_are_distinct_and_fail_closed(self):
        self.assertEqual(mode_decision(OperationMode.OBSERVATION), ModeDecision.OBSERVE_ONLY)
        self.assertEqual(mode_decision(OperationMode.SIMULATION), ModeDecision.SIMULATION_ONLY)
        self.assertEqual(
            mode_decision(OperationMode.DEMO), ModeDecision.BLOCKED_NO_ACCOUNT_VERIFICATION
        )
        self.assertEqual(mode_decision(OperationMode.REAL), ModeDecision.BLOCKED_REAL_MODE)
        for mode in OperationMode:
            with self.subTest(mode=mode):
                self.assertFalse(actual_order_execution_allowed(mode))


class SignalLifecycleTests(unittest.TestCase):
    @staticmethod
    def candidate(left=100, top=80, direction="BUY", text="COMPRA"):
        return SignalCandidate(direction, 91.0, left, top, 40, 20, text)

    @staticmethod
    def observe(tracker, candidates, second, frame_id=None):
        return tracker.observe(
            candidates,
            observed_at=second,
            frame_id=frame_id or f"frame-{second}",
            observed_at_utc=f"2026-10-30T12:00:{int(second * 10):02d}.000+00:00",
        )

    def test_first_read_is_preexisting_then_new_signal_needs_three_distinct_reads(self):
        tracker = SignalLifecycleTracker()
        old = self.candidate()
        first = self.observe(tracker, [old], 10.0)
        self.assertEqual(first[0].lifecycle, SignalLifecycle.PREEXISTING)

        new = self.candidate(left=220)
        second = self.observe(tracker, [old, new], 10.5)
        by_left = {item.candidate.left: item.lifecycle for item in second}
        tracking_ids = {item.candidate.left: item.tracking_id for item in second}
        self.assertEqual(tracking_ids[100], first[0].tracking_id)
        self.assertNotEqual(tracking_ids[100], tracking_ids[220])
        self.assertEqual(by_left[100], SignalLifecycle.PREEXISTING)
        self.assertEqual(by_left[220], SignalLifecycle.NEWLY_DETECTED)

        third = self.observe(tracker, [old, new], 11.0)
        by_left = {item.candidate.left: item.lifecycle for item in third}
        self.assertEqual(by_left[220], SignalLifecycle.PENDING_CONFIRMATION)
        fourth = self.observe(tracker, [old, new], 11.5)
        confirmed = next(item for item in fourth if item.candidate.left == 220)
        self.assertEqual(confirmed.lifecycle, SignalLifecycle.CONFIRMED)
        self.assertTrue(tracker.mark_eligible(confirmed.tracking_id))
        eligible = self.observe(tracker, [old, new], 12.0)
        self.assertEqual(
            next(item.lifecycle for item in eligible if item.candidate.left == 220),
            SignalLifecycle.ELIGIBLE,
        )

    def test_repeated_frame_id_does_not_advance_confirmation(self):
        tracker = SignalLifecycleTracker()
        self.observe(tracker, [], 0.0, "frame-0")
        candidate = self.candidate()
        first = self.observe(tracker, [candidate], 0.5, "frame-1")
        repeated = self.observe(tracker, [candidate], 0.75, "frame-1")
        self.assertEqual(first[0].lifecycle, SignalLifecycle.NEWLY_DETECTED)
        self.assertEqual(repeated, [])
        next_frame = self.observe(tracker, [candidate], 1.0, "frame-2")
        self.assertEqual(next_frame[0].lifecycle, SignalLifecycle.PENDING_CONFIRMATION)
        third = self.observe(tracker, [candidate], 1.25, "frame-3")
        self.assertEqual(third[0].lifecycle, SignalLifecycle.CONFIRMED)

    def test_missing_observation_breaks_consecutive_confirmation(self):
        tracker = SignalLifecycleTracker()
        self.observe(tracker, [], 0.0)
        candidate = self.candidate()
        self.observe(tracker, [candidate], 0.5)
        self.observe(tracker, [], 0.75)
        result = self.observe(tracker, [candidate], 1.0)
        self.assertEqual(result[0].lifecycle, SignalLifecycle.INDETERMINATE)
        self.assertEqual(result[0].consecutive_observations, 0)

    def test_reset_starts_a_new_baseline(self):
        tracker = SignalLifecycleTracker()
        self.observe(tracker, [self.candidate()], 1.0)
        tracker.reset()
        result = self.observe(tracker, [self.candidate(left=260)], 2.0)
        self.assertEqual(result[0].lifecycle, SignalLifecycle.PREEXISTING)

    def test_long_gap_does_not_confirm_pending_signal(self):
        tracker = SignalLifecycleTracker(maximum_confirmation_gap_seconds=1.0)
        self.observe(tracker, [], 0.0)
        candidate = self.candidate()
        self.observe(tracker, [candidate], 1.0)
        result = self.observe(tracker, [candidate], 3.0)
        self.assertEqual(result[0].lifecycle, SignalLifecycle.NEWLY_DETECTED)
        self.assertEqual(result[0].consecutive_observations, 1)

    def test_repaint_and_direction_change_are_separate_blocked_tracks(self):
        tracker = SignalLifecycleTracker()
        first = self.candidate()
        self.observe(tracker, [], 0.0)
        self.observe(tracker, [first], 0.5)
        repainted = self.observe(tracker, [self.candidate(text="COMPRA2")], 1.0)
        self.assertEqual(repainted[0].lifecycle, SignalLifecycle.REPINTED)
        changed = self.observe(tracker, [self.candidate(direction="SELL", text="VENDA")], 1.5)
        self.assertEqual(changed[0].lifecycle, SignalLifecycle.DIRECTION_CHANGED)
        self.assertIsNotNone(changed[0].related_tracking_id)

    def test_duplicate_boxes_are_counted_and_not_independent_tracks(self):
        tracker = SignalLifecycleTracker()
        self.observe(tracker, [], 0.0)
        result = self.observe(
            tracker,
            [self.candidate(), self.candidate(left=102)],
            0.5,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].duplicate_count, 1)

    def test_restore_rebases_visible_track_as_preexisting(self):
        tracker = SignalLifecycleTracker()
        self.observe(tracker, [], 0.0)
        snapshot = self.observe(tracker, [self.candidate()], 0.5)
        restored = SignalLifecycleTracker()
        restored.restore(tracker.export_state())
        baseline = self.observe(restored, [self.candidate()], 50.0)
        self.assertEqual(baseline[0].tracking_id, snapshot[0].tracking_id)
        self.assertEqual(baseline[0].lifecycle, SignalLifecycle.PREEXISTING)


class OpportunityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpportunityStore(Path(self.temp.name) / "journal.sqlite3")
        self.opportunity_id, created = self.store.record_signal(
            fingerprint="M1:BUY:10:20:COMPRA",
            mode="OBSERVATION",
            direction="BUY",
            ocr_text="COMPRA",
            ocr_confidence=92.0,
            signal_at_utc="2026-10-30T12:00:00.000+00:00",
            frame_quality={"usable": True},
            market_features={"signal_lifecycle": "PREEXISTING"},
        )
        self.assertTrue(created)

    def tearDown(self):
        self.temp.cleanup()

    def test_unknown_financial_fields_remain_null(self):
        row = self.store.get_opportunity(self.opportunity_id)
        self.assertIsNone(row["payout"])
        self.assertIsNone(row["stake"])
        self.assertIsNone(row["order_confirmed"])
        self.assertIsNone(row["outcome"])
        self.assertIsNone(row["pnl"])

    def test_click_is_not_order_confirmation_and_cannot_be_settled(self):
        self.store.record_click_sent(
            self.opportunity_id,
            occurred_at_utc="2026-10-30T12:00:01+00:00",
            delay_ms=125.0,
        )
        row = self.store.get_opportunity(self.opportunity_id)
        self.assertEqual(row["status"], "CLICK_SENT")
        self.assertIsNone(row["order_confirmed"])
        with self.assertRaises(ValueError):
            self.store.settle_trade(
                self.opportunity_id,
                outcome="WIN",
                pnl=1.0,
                source="MANUAL",
            )

    def test_manual_confirmation_is_distinct_from_click(self):
        self.store.record_click_sent(
            self.opportunity_id,
            occurred_at_utc="2026-10-30T12:00:01+00:00",
            delay_ms=125.0,
        )
        self.store.confirm_order(self.opportunity_id, source="MANUAL", confirmed=True)
        row = self.store.get_opportunity(self.opportunity_id)
        self.assertEqual(row["status"], "ORDER_CONFIRMED")
        self.assertEqual(row["order_confirmed"], 1)
        self.assertIsNone(row["pnl"])

    def test_tracker_snapshots_and_duplicate_events_are_persisted_transactionally(self):
        track = {
            "tracking_id": "track-1", "fingerprint": "track-1",
            "opportunity_id": self.opportunity_id, "direction": "BUY",
            "observed_text": "COMPRA", "left": 10, "top": 20,
            "width": 30, "height": 12, "confidence": 91.0,
            "first_seen_at_utc": "2026-10-30T12:00:00.000+00:00",
            "last_seen_at_utc": "2026-10-30T12:00:01.000+00:00",
            "lifecycle": "CONFIRMED", "consecutive_observations": 3,
            "missing_observations": 0, "active": True,
            "duplicate_count": 0, "related_tracking_id": None,
            "last_frame_id": "frame-a", "detector_version": "test-v1",
        }
        self.store.save_signal_tracks(profile_id="profile-a", timeframe="M1", tracks=[track])
        track["duplicate_count"] = 2
        track["last_frame_id"] = "frame-b"
        track["last_seen_at_utc"] = "2026-10-30T12:00:02.000+00:00"
        self.store.save_signal_tracks(profile_id="profile-a", timeframe="M1", tracks=[track])
        loaded = self.store.load_signal_tracks(profile_id="profile-a", timeframe="M1")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["duplicate_count"], 2)
        self.assertEqual(loaded[0]["last_frame_id"], "frame-b")
        events = self.store.list_events(self.opportunity_id)
        self.assertIn("SIGNAL_DUPLICATE_DETECTED", [event["event_type"] for event in events])

    def test_lifecycle_change_is_a_separate_journal_event(self):
        refreshed_id, created = self.store.record_signal(
            fingerprint="M1:BUY:10:20:COMPRA",
            mode="OBSERVATION",
            direction="BUY",
            ocr_text="COMPRA",
            ocr_confidence=92.0,
            signal_at_utc="2026-10-30T12:00:00.500+00:00",
            market_features={"signal_lifecycle": "CONFIRMED_NEW"},
        )
        self.assertFalse(created)
        self.assertEqual(refreshed_id, self.opportunity_id)
        events = self.store.list_events(self.opportunity_id)
        lifecycle_events = [event for event in events if event["event_type"] == "SIGNAL_LIFECYCLE_CHANGED"]
        self.assertEqual(len(lifecycle_events), 1)
        payload = json.loads(lifecycle_events[0]["payload_json"])
        self.assertEqual(payload["previous"], "PREEXISTING")
        self.assertEqual(payload["current"], "CONFIRMED_NEW")


if __name__ == "__main__":
    unittest.main()
