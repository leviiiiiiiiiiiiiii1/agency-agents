import unittest

from auto_trader_iq.candle_timer import (
    m1_entry_window_open,
    parse_platform_clock,
    parse_platform_clock_line,
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


if __name__ == "__main__":
    unittest.main()
