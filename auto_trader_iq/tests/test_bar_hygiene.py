import unittest
from types import SimpleNamespace

from PIL import Image, ImageDraw

from auto_trader_iq.bar_hygiene import (
    bar_width_px,
    consolidate_bars,
    summarize_consolidation,
    typical_gap,
)

GREEN = (0, 200, 80)
WHITE = (222, 220, 215)
BACKGROUND = (20, 20, 20)


def bar(center_x, color="green", top=40, bottom=90):
    return SimpleNamespace(center_x=float(center_x), color=color, top=top, bottom=bottom)


class BarWidthTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (200, 120), BACKGROUND)
        draw = ImageDraw.Draw(self.image)
        draw.rectangle([40, 40, 69, 90], fill=GREEN)      # corpo de 30 px
        draw.line([(110, 20), (110, 110)], fill=WHITE, width=2)  # cursor tracejado

    def test_body_width_is_measured(self):
        self.assertGreaterEqual(bar_width_px(self.image, bar(55)), 20)

    def test_thin_line_has_small_width(self):
        self.assertLessEqual(bar_width_px(self.image, bar(110, color="white")), 3)


class ConsolidateTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (400, 120), BACKGROUND)
        draw = ImageDraw.Draw(self.image)
        for center in (40, 80, 120, 160):
            draw.rectangle([center - 13, 40, center + 13, 90], fill=GREEN)
        draw.line([(205, 20), (205, 110)], fill=WHITE, width=2)

    def test_dashed_line_is_dropped(self):
        bars = [bar(c) for c in (40, 80, 120, 160)] + [bar(205, color="white")]
        kept = consolidate_bars(self.image, bars)
        self.assertEqual([b.center_x for b in kept], [40.0, 80.0, 120.0, 160.0])

    def test_split_bars_inside_one_candle_become_one(self):
        bars = [bar(35), bar(40), bar(45), bar(80), bar(120)]
        kept = consolidate_bars(self.image, bars)
        # três barras dentro do mesmo candle viram uma só
        self.assertEqual(len(kept), 3)
        self.assertAlmostEqual(kept[0].center_x, 40.0, delta=5.0)

    def test_legitimate_bars_are_untouched(self):
        bars = [bar(c) for c in (40, 80, 120, 160)]
        self.assertEqual([b.center_x for b in consolidate_bars(self.image, bars)],
                         [40.0, 80.0, 120.0, 160.0])

    def test_without_body_evidence_nothing_survives(self):
        empty = Image.new("RGB", (200, 120), BACKGROUND)
        self.assertEqual(consolidate_bars(empty, [bar(c) for c in (40, 80)]), [])

    def test_single_bar_is_returned(self):
        self.assertEqual(len(consolidate_bars(self.image, [bar(40)])), 1)

    def test_typical_gap_ignores_phantoms(self):
        self.assertEqual(typical_gap([bar(c) for c in (0, 36, 72, 300)]), 36.0)

    def test_summary_reports_counts(self):
        bars = [bar(40), bar(80), bar(205, color="white")]
        summary = summarize_consolidation(bars, consolidate_bars(self.image, bars))
        self.assertEqual(summary["detected"], 3)
        self.assertEqual(summary["kept"], 2)


if __name__ == "__main__":
    unittest.main()
