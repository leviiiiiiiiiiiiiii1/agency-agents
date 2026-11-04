import unittest
from datetime import datetime, timezone

from auto_trader_iq.signal_detector import SignalCandidate
from auto_trader_iq.simulation import SimulationWorkflow


class SimulationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = SimulationWorkflow()
        self.candidate = SignalCandidate("BUY", 94.0, 100, 200, 42, 18, "COMPRA")

    def test_entry_is_only_recorded_after_next_candle_confirmation(self):
        detected = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        opened = datetime(2026, 10, 31, 12, 1, tzinfo=timezone.utc)
        pending = self.workflow.arm(self.candidate, detected)
        self.assertEqual(pending.direction, "BUY")
        self.assertEqual(self.workflow.entries, [])

        entry = self.workflow.confirm_next_candle(opened)
        self.assertEqual(entry.direction, "BUY")
        self.assertEqual(entry.signal_text, "COMPRA")
        self.assertEqual(entry.signal_detected_at, detected)
        self.assertEqual(entry.next_candle_confirmed_at, opened)
        self.assertEqual(len(self.workflow.entries), 1)
        self.assertIsNone(self.workflow.pending)

    def test_duplicate_signal_position_cannot_be_armed_twice(self):
        self.workflow.arm(self.candidate)
        self.workflow.confirm_next_candle()
        near_duplicate = SignalCandidate("BUY", 99.0, 104, 204, 39, 18, "COMPRA")
        with self.assertRaisesRegex(ValueError, "duplicata"):
            self.workflow.arm(near_duplicate)

    def test_scoped_fingerprint_allows_same_chart_position_in_a_new_m1_candle(self):
        first = self.workflow.arm(self.candidate, dedupe_scope="23:17")
        self.workflow.confirm_next_candle()
        second = self.workflow.arm(self.candidate, dedupe_scope="23:18")
        self.assertNotEqual(first.fingerprint, second.fingerprint)

        self.workflow.cancel_pending()
        with self.assertRaisesRegex(ValueError, "duplicata"):
            self.workflow.arm(self.candidate, dedupe_scope="23:18")

    def test_only_one_signal_can_be_pending(self):
        self.workflow.arm(self.candidate)
        sell = SignalCandidate("SELL", 93.0, 300, 200, 40, 18, "VENDER")
        with self.assertRaisesRegex(ValueError, "Já existe"):
            self.workflow.arm(sell)

    def test_cancel_keeps_signal_fingerprint_consumed(self):
        self.workflow.arm(self.candidate)
        self.workflow.cancel_pending()
        with self.assertRaisesRegex(ValueError, "duplicata"):
            self.workflow.arm(self.candidate)

    def test_cannot_confirm_without_pending_signal(self):
        with self.assertRaisesRegex(ValueError, "Não há sinal"):
            self.workflow.confirm_next_candle()


if __name__ == "__main__":
    unittest.main()
