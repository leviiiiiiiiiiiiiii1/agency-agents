import unittest

from auto_trader_iq.demo_signal_guard import DemoSignalRepeatGuard
from auto_trader_iq.signal_detector import SignalCandidate


class DemoSignalRepeatGuardTests(unittest.TestCase):
    @staticmethod
    def candidate(direction="BUY", left=300, top=200):
        return SignalCandidate(direction, 95.0, left, top, 40, 20, "COMPRA")

    def test_blocks_same_entered_signal_with_small_ocr_coordinate_jitter(self):
        guard = DemoSignalRepeatGuard()
        guard.mark_entered("BUY", 300, 200)

        self.assertTrue(guard.blocks(self.candidate(left=385, top=245)))
        self.assertFalse(guard.blocks(self.candidate("SELL", left=300, top=200)))

    def test_releases_only_after_three_consecutive_missing_recent_candidates(self):
        guard = DemoSignalRepeatGuard()
        entered = self.candidate()
        guard.mark_entered(entered.direction, entered.left, entered.top)

        guard.observe([])
        guard.observe([self.candidate(left=310, top=205)])
        self.assertTrue(guard.blocks(entered))
        guard.observe([])
        guard.observe([])
        self.assertTrue(guard.blocks(entered))
        guard.observe([])
        self.assertFalse(guard.blocks(entered))

    def test_a_distinct_direction_or_distant_signal_is_not_blocked(self):
        guard = DemoSignalRepeatGuard()
        guard.mark_entered("BUY", 300, 200)

        self.assertFalse(guard.blocks(self.candidate("SELL", 300, 200)))
        self.assertFalse(guard.blocks(self.candidate("BUY", 500, 200)))

    def test_invalid_guard_limits_are_rejected(self):
        for options in (
            {"tolerance_x": -1},
            {"tolerance_y": -1},
            {"missing_observations_to_release": 0},
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    DemoSignalRepeatGuard(**options)


if __name__ == "__main__":
    unittest.main()
