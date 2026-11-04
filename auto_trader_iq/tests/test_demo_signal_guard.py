import unittest

from auto_trader_iq.demo_signal_guard import DemoSignalRepeatGuard
from auto_trader_iq.signal_detector import SignalCandidate


class DemoSignalRepeatGuardTests(unittest.TestCase):
    @staticmethod
    def candidate(direction="BUY", left=300, top=200):
        return SignalCandidate(direction, 95.0, left, top, 40, 20, "COMPRA")

    def test_blocks_same_consumed_signal_with_small_ocr_coordinate_jitter(self):
        guard = DemoSignalRepeatGuard()
        guard.mark_consumed("BUY", 300, 200)

        self.assertTrue(guard.blocks(self.candidate(left=385, top=245)))
        self.assertFalse(guard.blocks(self.candidate("SELL", left=300, top=200)))

    def test_requires_thirty_seconds_and_three_missing_reads_before_release(self):
        guard = DemoSignalRepeatGuard()
        entered = self.candidate()
        guard.mark_consumed(entered.direction, entered.left, entered.top, consumed_at=100.0)

        guard.observe([], now=101.0)
        guard.observe([self.candidate(left=310, top=205)], now=102.0)
        self.assertTrue(guard.blocks(entered))
        guard.observe([], now=103.0)
        guard.observe([], now=104.0)
        guard.observe([], now=129.0)
        self.assertTrue(guard.blocks(entered))
        guard.observe([], now=130.0)
        self.assertFalse(guard.blocks(entered))

    def test_a_distinct_direction_or_distant_signal_is_not_blocked(self):
        guard = DemoSignalRepeatGuard()
        guard.mark_consumed("BUY", 300, 200)

        self.assertFalse(guard.blocks(self.candidate("SELL", 300, 200)))
        self.assertFalse(guard.blocks(self.candidate("BUY", 500, 200)))

    def test_new_confirmed_candle_releases_same_position_but_same_candle_stays_locked(self):
        guard = DemoSignalRepeatGuard()
        candidate = self.candidate()
        self.assertTrue(guard.advance_candle(10))
        guard.mark_consumed(candidate.direction, candidate.left, candidate.top)
        self.assertTrue(guard.blocks(candidate))

        self.assertFalse(guard.advance_candle(10))
        self.assertTrue(guard.blocks(candidate))
        self.assertTrue(guard.advance_candle(11))

        self.assertFalse(guard.blocks(candidate))

    def test_missing_candle_id_does_not_release_consumed_signal(self):
        guard = DemoSignalRepeatGuard()
        candidate = self.candidate()
        guard.advance_candle(10)
        guard.mark_consumed(candidate.direction, candidate.left, candidate.top)

        self.assertFalse(guard.advance_candle(None))
        self.assertTrue(guard.blocks(candidate))

    def test_invalid_guard_limits_are_rejected(self):
        for options in (
            {"tolerance_x": -1},
            {"tolerance_y": -1},
            {"minimum_lock_seconds": -1},
            {"missing_observations_to_release": 0},
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    DemoSignalRepeatGuard(**options)


if __name__ == "__main__":
    unittest.main()
