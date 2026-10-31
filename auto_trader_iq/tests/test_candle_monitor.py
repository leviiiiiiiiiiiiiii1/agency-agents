import unittest

from PIL import Image, ImageDraw

from auto_trader_iq.candle_monitor import CandleBar, detect_candle_bars, filter_to_recent_candle
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


if __name__ == "__main__":
    unittest.main()
