import unittest

from PIL import Image, ImageDraw

from auto_trader_iq.candle_monitor import (
    CandleBar,
    _market_candles_from_bars,
    detect_candle_bars,
    detect_candle_bars_detailed,
    filter_to_recent_candle,
)
from auto_trader_iq.signal_detector import SignalCandidate


class CandleFilterTests(unittest.TestCase):
    def setUp(self):
        self.bars = [CandleBar(x, "green", 20, 80) for x in (80, 150, 220, 290, 360)]

    @staticmethod
    def candidate(direction, center_x, center_y=30):
        return SignalCandidate(direction, 95.0, center_x - 20, center_y - 6, 40, 12, "COMPRA")

    def test_keeps_only_signal_on_most_recent_bar_if_present(self):
        old = self.candidate("BUY", 80)
        previous = self.candidate("SELL", 290)
        newest = self.candidate("BUY", 360)
        kept = filter_to_recent_candle([old, previous, newest], self.bars)
        self.assertEqual(kept, [newest])

    def test_keeps_signal_on_previous_bar_when_current_bar_has_no_tag(self):
        old = self.candidate("BUY", 80)
        previous = self.candidate("SELL", 290)
        self.assertEqual(filter_to_recent_candle([old, previous], self.bars), [previous])

    def test_rejects_all_candidates_when_only_historical_candles_match(self):
        old = self.candidate("BUY", 220)
        self.assertEqual(filter_to_recent_candle([old], self.bars), [])

    def test_fails_closed_when_fewer_than_two_candles_detected(self):
        candidate = self.candidate("BUY", 360)
        self.assertEqual(filter_to_recent_candle([candidate], self.bars[-1:]), [])

    def test_detects_synthetic_green_and_red_candle_bodies(self):
        image = Image.new("RGB", (500, 240), "#111111")
        draw = ImageDraw.Draw(image)
        for x, color in ((70, "#55c63b"), (150, "#f02030"),
                         (230, "#55c63b"), (310, "#f02030"), (390, "#55c63b")):
            draw.line((x + 8, 35, x + 8, 200), fill=color, width=2)
            draw.rectangle((x, 75, x + 16, 160), fill=color)
        bars = detect_candle_bars(image)
        self.assertEqual(len(bars), 5)
        self.assertEqual([bar.color for bar in bars], ["green", "red", "green", "red", "green"])

    def test_calibrated_mixed_palette_keeps_white_and_green_candles(self):
        image = Image.new("RGB", (110, 100), "#111111")
        draw = ImageDraw.Draw(image)
        for x, color in ((18, "#55c63b"), (58, "#f5f5f5")):
            draw.line((x + 4, 10, x + 4, 90), fill=color, width=2)
            draw.rectangle((x, 30, x + 8, 65), fill=color)
        bars = detect_candle_bars(
            image, downscale=1, palette_colors={"green", "white"}
        )
        self.assertEqual([bar.color for bar in bars], ["green", "white"])

    def test_white_candle_direction_requires_explicit_calibration(self):
        image = Image.new("RGB", (100, 100), "#111111")
        draw = ImageDraw.Draw(image)
        for x, top, bottom in ((20, 20, 40), (60, 50, 70)):
            draw.line((x, 10, x, 80), fill="white", width=2)
            draw.rectangle((x - 3, top, x + 3, bottom), fill="white")
        bars = [CandleBar(20, "white", 10, 80), CandleBar(60, "white", 10, 80)]
        self.assertEqual(_market_candles_from_bars(image, bars), [])
        bearish = _market_candles_from_bars(
            image, bars, color_direction_map={"white": "SELL"}
        )
        bullish = _market_candles_from_bars(
            image, bars, color_direction_map={"white": "BUY"}
        )
        self.assertEqual(len(bearish), 2)
        self.assertGreater(bearish[0].close_y, bearish[0].open_y)
        self.assertLess(bullish[0].close_y, bullish[0].open_y)


class CandleDetectionDiagnosticsTests(unittest.TestCase):
    @staticmethod
    def chart(body_colors):
        image = Image.new("RGB", (400, 200), (12, 16, 22))
        draw = ImageDraw.Draw(image)
        for index, color in enumerate(body_colors):
            left = 40 + index * 60
            draw.rectangle((left, 80, left + 20, 150), fill=color)
        return image

    def test_reports_detected_bars_and_palette(self):
        bars, stats = detect_candle_bars_detailed(
            self.chart([(0, 200, 80), (0, 200, 80)]),
            palette_colors=["green"],
        )
        self.assertEqual(len(bars), 2)
        self.assertEqual(stats["bars_before_palette"], 2)
        self.assertEqual(stats["bars_after_palette"], 2)
        self.assertEqual(stats["palette"], ["green"])
        self.assertEqual(stats["dominant_columns_by_color"].get("green", 0) > 0, True)

    def test_reports_empty_chart_without_bars(self):
        bars, stats = detect_candle_bars_detailed(
            self.chart([]), palette_colors=["green"]
        )
        self.assertEqual(bars, [])
        self.assertEqual(stats["runs"], 0)
        self.assertEqual(stats["bars_after_palette"], 0)
        self.assertEqual(stats["dominant_columns_by_color"], {})

    def test_reports_bars_dropped_by_palette_calibration(self):
        bars, stats = detect_candle_bars_detailed(
            self.chart([(0, 200, 80), (0, 200, 80)]),
            palette_colors=["white"],
        )
        self.assertEqual(bars, [])
        self.assertEqual(stats["bars_before_palette"], 2)
        self.assertEqual(stats["bars_after_palette"], 0)
        self.assertEqual(stats["palette"], ["white"])

    def test_legacy_helper_still_returns_plain_bars(self):
        bars = detect_candle_bars(self.chart([(0, 200, 80)]), palette_colors=["green"])
        self.assertEqual([bar.color for bar in bars], ["green"])


if __name__ == "__main__":
    unittest.main()
