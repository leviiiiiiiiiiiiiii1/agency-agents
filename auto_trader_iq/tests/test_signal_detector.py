import unittest

from auto_trader_iq.signal_detector import parse_ocr_rows


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

    def test_rejects_out_of_range_threshold(self):
        with self.assertRaises(ValueError):
            parse_ocr_rows(rows(["BUY"], [90]), 101)


if __name__ == "__main__":
    unittest.main()
