import unittest

from auto_trader_iq.candle_timer import m1_entry_window_open, parse_platform_candle_timer


class CandleTimerTests(unittest.TestCase):
    def make_rows(self, timer="00:47", include_hour=True):
        words = (["HORA", "DE", "COMPRA"] if include_hour else ["COMPRA"])
        texts = words + [timer]
        left = [900, 930, 950, 1000] if include_hour else [950, 1000]
        return {
            "text": texts,
            "conf": [95, 94, 96, 92] if include_hour else [96, 92],
            "left": left,
            "top": [20] * len(texts),
            "width": [30] * len(texts),
            "height": [12] * len(texts),
        }

    def test_reads_remaining_timer_near_hora_anchor(self):
        reading = parse_platform_candle_timer(self.make_rows(), 1200, 500)
        self.assertIsNotNone(reading)
        self.assertEqual(reading.remaining_seconds, 47)
        self.assertEqual(reading.elapsed_seconds, 13)
        self.assertTrue(m1_entry_window_open(reading))

    def test_rejects_confirmation_after_first_30_seconds(self):
        reading = parse_platform_candle_timer(self.make_rows("00:29"), 1200, 500)
        self.assertIsNotNone(reading)
        self.assertEqual(reading.elapsed_seconds, 31)
        self.assertFalse(m1_entry_window_open(reading))

    def test_accepts_exact_open_and_cutoff_boundary(self):
        at_open = parse_platform_candle_timer(self.make_rows("01:00"), 1200, 500)
        at_cutoff = parse_platform_candle_timer(self.make_rows("00:30"), 1200, 500)
        self.assertEqual(at_open.elapsed_seconds, 0)
        self.assertEqual(at_cutoff.elapsed_seconds, 30)
        self.assertTrue(m1_entry_window_open(at_open))
        self.assertTrue(m1_entry_window_open(at_cutoff))

    def test_requires_hora_anchor_and_valid_timer(self):
        self.assertIsNone(parse_platform_candle_timer(self.make_rows(include_hour=False), 1200, 500))
        self.assertIsNone(parse_platform_candle_timer(self.make_rows("01:05"), 1200, 500))
        self.assertFalse(m1_entry_window_open(None))


if __name__ == "__main__":
    unittest.main()
