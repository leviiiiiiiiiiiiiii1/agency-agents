import unittest

from auto_trader_iq.candle_timer import (
    PlatformClockReading,
    PlatformMinuteTracker,
    m1_entry_window_open,
    m1_next_candle_entry_window_open,
    parse_platform_clock,
    parse_platform_clock_line,
    platform_minute_advanced,
    platform_minute_key,
    platform_minute_offset,
)


class PlatformClockTests(unittest.TestCase):
    def make_rows(self, clock="21:23:02", include_anchor=True, top=450):
        texts = (["HORA", "ATUAL"] if include_anchor else ["OUTUBRO"]) + [clock]
        left = ([780, 835] if include_anchor else [835]) + [930]
        return {
            "text": texts,
            "conf": [96] * len(texts),
            "left": left,
            "top": [top] * len(texts),
            "width": [40] * len(texts),
            "height": [16] * len(texts),
        }

    def test_reads_platform_clock_and_elapsed_m1_seconds(self):
        reading = parse_platform_clock(self.make_rows(), 1200, 500)
        self.assertIsNotNone(reading)
        self.assertEqual((reading.hour, reading.minute, reading.second), (21, 23, 2))
        self.assertEqual(reading.elapsed_seconds_in_m1, 2)
        self.assertTrue(m1_entry_window_open(reading))

    def test_accepts_only_first_30_seconds(self):
        at_cutoff = parse_platform_clock(self.make_rows("21:23:30"), 1200, 500)
        after_cutoff = parse_platform_clock(self.make_rows("21:23:31"), 1200, 500)
        self.assertTrue(m1_entry_window_open(at_cutoff))
        self.assertFalse(m1_entry_window_open(after_cutoff))

    def test_accepts_exact_minute_rollover(self):
        at_open = parse_platform_clock(self.make_rows("21:24:00"), 1200, 500)
        self.assertEqual(at_open.elapsed_seconds_in_m1, 0)
        self.assertTrue(m1_entry_window_open(at_open))

    def test_parses_focused_bottom_status_line_with_split_words(self):
        data = {
            "text": ["HORA", "ATUAL:", "31", "OUTUBRO,", "21:44:50"],
            "conf": [82, 76, 60, 58, 91],
            "left": [30, 100, 210, 250, 410],
            "top": [20, 20, 20, 20, 20],
        }
        reading = parse_platform_clock_line(
            data, origin_left=800, origin_top=720, scale=4
        )
        self.assertIsNotNone(reading)
        self.assertEqual((reading.hour, reading.minute, reading.second), (21, 44, 50))
        self.assertEqual((reading.left, reading.top), (902, 725))
        self.assertEqual(reading.confidence, 91)

    def test_focused_parser_accepts_time_split_into_separate_numeric_tokens(self):
        data = {
            "text": ["HORA", "ATUAL", "31", "OUTUBRO", "22", "50", "29"],
            "conf": [85, 82, 70, 68, 91, 84, 88],
            "left": [10, 40, 110, 150, 300, 350, 390],
            "top": [10] * 7,
        }
        reading = parse_platform_clock_line(data, origin_left=800, origin_top=720, scale=4)
        self.assertIsNotNone(reading)
        self.assertEqual((reading.hour, reading.minute, reading.second), (22, 50, 29))
        self.assertEqual(reading.confidence, 84)
        self.assertEqual(reading.left, 875)

    def test_focused_parser_fails_closed_without_anchor_or_confident_valid_time(self):
        base = {
            "text": ["HORA", "ATUAL", "21:44:50"],
            "conf": [90, 90, 90],
            "left": [10, 40, 100],
            "top": [10, 10, 10],
        }
        no_anchor = {**base, "text": ["OUTUBRO", "21:44:50"]}
        low_confidence = {**base, "conf": [90, 90, 45]}
        malformed = {**base, "text": ["HORA", "ATUAL", "21:4450"]}
        invalid_hour = {**base, "text": ["HORA", "ATUAL", "24:44:50"]}
        self.assertIsNone(parse_platform_clock_line(no_anchor, origin_left=800, origin_top=720, scale=4))
        self.assertIsNone(parse_platform_clock_line(low_confidence, origin_left=800, origin_top=720, scale=4))
        self.assertIsNone(parse_platform_clock_line(malformed, origin_left=800, origin_top=720, scale=4))
        self.assertIsNone(parse_platform_clock_line(invalid_hour, origin_left=800, origin_top=720, scale=4))
        self.assertIsNone(parse_platform_clock_line(base, origin_left=800, origin_top=720, scale=0))

    def test_requires_bottom_right_clock_and_hora_anchor(self):
        self.assertIsNone(parse_platform_clock(self.make_rows(include_anchor=False), 1200, 500))
        self.assertIsNone(parse_platform_clock(self.make_rows(top=100), 1200, 500))
        self.assertIsNone(parse_platform_clock(self.make_rows("26:23:10"), 1200, 500))
        self.assertFalse(m1_entry_window_open(None))


class PlatformMinuteTransitionTests(unittest.TestCase):
    @staticmethod
    def clock(hour, minute, second):
        return PlatformClockReading(hour, minute, second, 95.0, 0, 0, f"{hour:02d}:{minute:02d}:{second:02d}")

    def test_detects_observed_next_minute_across_hour_and_day_boundaries(self):
        self.assertTrue(platform_minute_advanced(self.clock(23, 14, 59), self.clock(23, 15, 1)))
        self.assertTrue(platform_minute_advanced(self.clock(23, 59, 59), self.clock(0, 0, 1)))

    def test_rejects_same_minute_skipped_minutes_and_missing_readings(self):
        self.assertFalse(platform_minute_advanced(self.clock(23, 14, 30), self.clock(23, 14, 59)))
        self.assertFalse(platform_minute_advanced(self.clock(23, 14, 59), self.clock(23, 16, 1)))
        self.assertFalse(platform_minute_advanced(None, self.clock(23, 15, 1)))
        self.assertFalse(platform_minute_advanced(self.clock(23, 14, 59), None))

    def test_platform_minute_key_supports_one_entry_per_m1_candle(self):
        first = self.clock(23, 14, 3)
        same_minute = self.clock(23, 14, 58)
        next_minute = self.clock(23, 15, 0)
        next_day = self.clock(0, 0, 0)

        self.assertEqual(platform_minute_key(first), platform_minute_key(same_minute))
        self.assertNotEqual(platform_minute_key(first), platform_minute_key(next_minute))
        self.assertEqual(platform_minute_key(next_day), (0, 0))
        self.assertIsNone(platform_minute_key(None))

    def test_minute_tracker_keeps_same_candle_id_and_advances_for_new_minutes(self):
        tracker = PlatformMinuteTracker()
        self.assertIsNone(tracker.update(None))
        self.assertEqual(tracker.update(self.clock(23, 59, 50)), 0)
        self.assertEqual(tracker.update(self.clock(23, 59, 59)), 0)
        self.assertEqual(tracker.update(self.clock(0, 0, 0)), 1)
        self.assertEqual(tracker.update(self.clock(0, 1, 0)), 2)
        # A repeated HH:MM after a full platform-clock cycle is still a new candle.
        self.assertEqual(tracker.update(self.clock(23, 59, 0)), 3)
        self.assertEqual(tracker.update(self.clock(23, 59, 59)), 3)

    def test_minute_offset_distinguishes_waiting_from_n_plus_one_and_skips(self):
        armed = self.clock(23, 14, 40)
        self.assertEqual(platform_minute_offset(armed, self.clock(23, 14, 59)), 0)
        self.assertEqual(platform_minute_offset(armed, self.clock(23, 15, 15)), 1)
        self.assertEqual(platform_minute_offset(armed, self.clock(23, 16, 1)), 2)
        self.assertIsNone(platform_minute_offset(None, self.clock(23, 15, 15)))

    def test_n_plus_one_window_requires_exact_next_minute_and_first_30_seconds(self):
        armed = self.clock(23, 14, 40)
        self.assertFalse(m1_next_candle_entry_window_open(armed, self.clock(23, 14, 29)))
        self.assertTrue(m1_next_candle_entry_window_open(armed, self.clock(23, 15, 0)))
        self.assertTrue(m1_next_candle_entry_window_open(armed, self.clock(23, 15, 30)))
        self.assertFalse(m1_next_candle_entry_window_open(armed, self.clock(23, 15, 31)))
        self.assertFalse(m1_next_candle_entry_window_open(armed, self.clock(23, 16, 5)))
        self.assertTrue(m1_next_candle_entry_window_open(
            self.clock(23, 59, 50), self.clock(0, 0, 10)
        ))


if __name__ == "__main__":
    unittest.main()
