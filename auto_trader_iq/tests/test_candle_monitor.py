import unittest

from PIL import Image, ImageDraw

from auto_trader_iq.candle_monitor import (
    CandleBar,
    _market_candles_from_bars,
    detect_candle_bars,
    detect_candle_bars_detailed,
    filter_to_recent_candle,
    label_age_bars,
    price_ladder,
    resolve_age_reference,
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


class GridReferenceAgeTests(unittest.TestCase):
    def bars(self, centers):
        from types import SimpleNamespace

        return [SimpleNamespace(center_x=float(center)) for center in centers]

    def candidate(self, center):
        from types import SimpleNamespace

        return SimpleNamespace(left=center - 20, width=40, top=0, height=14)

    def test_detected_reference_counts_phantom_bars(self):
        noisy = self.bars([0, 40, 80, 120, 300, 420])
        self.assertEqual(
            label_age_bars(self.candidate(80), noisy, reference="detected"), 3
        )

    def test_grid_reference_ignores_them(self):
        noisy = self.bars([0, 40, 80, 120, 300, 420])
        self.assertEqual(label_age_bars(self.candidate(80), noisy, reference="grid"), 1)

    def test_unknown_reference_is_refused(self):
        self.assertIsNone(
            label_age_bars(self.candidate(80), self.bars([0, 40, 80]), reference="outra")
        )

    def test_filter_accepts_a_label_that_phantoms_pushed_out(self):
        noisy = self.bars([0, 40, 80, 120, 300, 420])
        candidate = self.candidate(120)
        self.assertEqual(
            filter_to_recent_candle([candidate], noisy, reference="detected"), []
        )
        self.assertEqual(
            filter_to_recent_candle([candidate], noisy, reference="grid"), [candidate]
        )


class AgeReferenceDefaultTests(unittest.TestCase):
    def test_default_reference_is_the_grid(self):
        from auto_trader_iq.candle_monitor import AGE_REFERENCE_DEFAULT

        self.assertEqual(AGE_REFERENCE_DEFAULT, "grid")

    def test_missing_value_uses_the_default(self):
        reference, migrated, note = resolve_age_reference(None, None)
        self.assertEqual(reference, "grid")
        self.assertFalse(migrated)
        self.assertIsNone(note)

    def test_legacy_detected_is_migrated(self):
        reference, migrated, note = resolve_age_reference("detected", None)
        self.assertEqual(reference, "grid")
        self.assertTrue(migrated)
        self.assertIn("grade", note)

    def test_explicit_grid_is_preserved(self):
        reference, migrated, note = resolve_age_reference("grid", 1)
        self.assertEqual(reference, "grid")
        self.assertFalse(migrated)
        self.assertIsNone(note)

    def test_current_version_detected_is_respected(self):
        reference, migrated, _note = resolve_age_reference("detected", 2)
        self.assertEqual(reference, "detected")
        self.assertFalse(migrated)

    def test_invalid_value_falls_back_with_notice(self):
        reference, migrated, note = resolve_age_reference("outra", 2)
        self.assertEqual(reference, "grid")
        self.assertFalse(migrated)
        self.assertIn("inválida", note)


class LabelAgeTests(unittest.TestCase):
    @staticmethod
    def candidate(center_x):
        return SignalCandidate("BUY", 95.0, center_x - 20, 30, 40, 12, "COMPRA")

    def setUp(self):
        self.age = staticmethod(label_age_bars)
        self.bars = [CandleBar(x, "green", 20, 80) for x in (80, 150, 220, 290, 360)]

    def test_label_on_last_candle_is_zero(self):
        self.assertEqual(self.age(self.candidate(360), self.bars), 0)

    def test_label_on_previous_candle_is_one(self):
        self.assertEqual(self.age(self.candidate(290), self.bars), 1)

    def test_historical_label_has_larger_age(self):
        self.assertEqual(self.age(self.candidate(150), self.bars), 3)

    def test_unmeasurable_label_returns_none(self):
        self.assertIsNone(self.age(self.candidate(20), self.bars))

    def test_without_bars_returns_none(self):
        self.assertIsNone(self.age(self.candidate(360), []))


if __name__ == "__main__":
    unittest.main()


class PriceLadderTests(unittest.TestCase):
    def bars(self, centers):
        return [CandleBar(center, "green", 10, 40) for center in centers]

    def candles(self, closes):
        from types import SimpleNamespace

        return [
            SimpleNamespace(
                center_x=float(index * 40),
                high=10.0,
                low=40.0,
                close_y=float(close),
            )
            for index, close in enumerate(closes)
        ]

    def test_index_zero_is_the_newest_bar(self):
        ladder = price_ladder(self.candles([1.0, 2.0, 3.0]), self.bars([0, 40, 80]))
        self.assertEqual(ladder["closes_px"][0], 3.0)
        self.assertEqual(ladder["closes_px"][2], 1.0)

    def test_median_range_is_reported(self):
        ladder = price_ladder(self.candles([1.0, 2.0, 3.0]), self.bars([0, 40, 80]))
        self.assertEqual(ladder["median_range_px"], 30.0)

    def test_phantom_bar_does_not_become_the_current_price(self):
        ladder = price_ladder(self.candles([1.0, 2.0]), self.bars([0, 40, 400]))
        self.assertEqual(ladder["closes_px"][0], 2.0)
        self.assertEqual(ladder["closes_px"][1], 1.0)

    def test_bar_without_candle_inside_the_run_is_missing(self):
        from types import SimpleNamespace

        candles = [
            SimpleNamespace(center_x=0.0, high=10.0, low=40.0, close_y=1.0),
            SimpleNamespace(center_x=80.0, high=10.0, low=40.0, close_y=3.0),
        ]
        ladder = price_ladder(candles, self.bars([0, 40, 80]))
        self.assertEqual(ladder["closes_px"][0], 3.0)
        self.assertIsNone(ladder["closes_px"][1])

    def test_empty_inputs_return_none(self):
        self.assertIsNone(price_ladder([], self.bars([0, 40])))
        self.assertIsNone(price_ladder(self.candles([1.0]), []))
