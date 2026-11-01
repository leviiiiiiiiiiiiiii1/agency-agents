import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from auto_trader_iq.signal_detector import TesseractSignalDetector, parse_ocr_rows


def rows(text, conf, left=None, top=None, width=None, height=None):
    count = len(text)
    return {
        "text": text,
        "conf": conf,
        "left": left or [10] * count,
        "top": top or [20] * count,
        "width": width or [30] * count,
        "height": height or [12] * count,
    }


class ParseOcrRowsTests(unittest.TestCase):
    def test_accepts_only_buy_sell_at_threshold(self):
        found = parse_ocr_rows(rows(["BUY", "SELL", "BUY?", "HOLD"], [70, 94.5, 69, 99]))
        self.assertEqual([candidate.direction for candidate in found], ["BUY", "SELL"])
        self.assertEqual(found[0].confidence, 70)

    def test_rejects_low_confidence_and_invalid_boxes(self):
        found = parse_ocr_rows(rows(["BUY", "SELL"], [69.9, 99], width=[30, 0]))
        self.assertEqual(found, [])

    def test_case_and_surrounding_punctuation_are_normalized(self):
        found = parse_ocr_rows(rows(["sell!", "B-U-Y"], [90, 90]))
        self.assertEqual([candidate.direction for candidate in found], ["SELL", "BUY"])

    def test_maps_portuguese_labels_to_buy_sell_directions(self):
        found = parse_ocr_rows(rows(["COMPRA", "COMPRAR", "VENDER", "VENDA"], [95, 91, 90, 89]))
        self.assertEqual([candidate.direction for candidate in found], ["BUY", "BUY", "SELL", "SELL"])

    def test_rejects_out_of_range_threshold(self):
        with self.assertRaises(ValueError):
            parse_ocr_rows(rows(["BUY"], [90]), 101)


class FocusedClockOcrTests(unittest.TestCase):
    def test_detect_frame_uses_bottom_right_focused_ocr_when_full_frame_misses_clock(self):
        line_data = rows(
            ["HORA", "ATUAL", "31", "OUTUBRO", "21:44:50"],
            [80, 80, 55, 60, 92],
            left=[10, 90, 180, 220, 400],
            top=[10, 10, 10, 10, 10],
        )
        ocr = SimpleNamespace(
            Output=SimpleNamespace(DICT="dict"),
            pytesseract=SimpleNamespace(),
            image_to_data=Mock(side_effect=[{"text": []}, line_data]),
        )
        with patch.dict(sys.modules, {"pytesseract": ocr}):
            candidates, clock = TesseractSignalDetector().detect_frame(Image.new("RGB", (1156, 814)))

        self.assertEqual(candidates, [])
        self.assertIsNotNone(clock)
        self.assertEqual((clock.hour, clock.minute, clock.second), (21, 44, 50))
        self.assertEqual(clock.confidence, 92)
        self.assertEqual(ocr.image_to_data.call_count, 2)
        focused_config = ocr.image_to_data.call_args.kwargs["config"]
        self.assertIn("--psm 7", focused_config)


if __name__ == "__main__":
    unittest.main()
