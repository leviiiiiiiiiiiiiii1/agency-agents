import unittest

from auto_trader_iq.ocr_diagnostics import (
    classify_association_outcome,
    summarize_ocr_yield,
)


class OcrYieldSummaryTests(unittest.TestCase):
    def result(self, *, candidates, clock, raw_count, color_rejected, bars, labels, raw_boxes):
        return (
            candidates,
            clock,
            raw_count,
            color_rejected,
            bars,
            "full:14:05:01",
            labels,
            raw_boxes,
            {"total_seconds": 3.1},
        )

    def test_reports_labels_found_by_a_discarded_frame(self):
        summary = summarize_ocr_yield(
            self.result(
                candidates=[object(), object()],
                clock=object(),
                raw_count=5,
                color_rejected=1,
                bars=42,
                labels={"BUY": 3, "SELL": 2},
                raw_boxes=[object()] * 5,
            )
        )
        self.assertEqual(summary["raw_candidate_count"], 5)
        self.assertEqual(summary["recent_candidate_count"], 2)
        self.assertEqual(summary["raw_box_count"], 5)
        self.assertEqual(summary["bar_count"], 42)
        self.assertTrue(summary["clock_readable"])
        self.assertEqual(summary["color_rejected_count"], 1)
        self.assertEqual(summary["label_counts"], {"BUY": 3, "SELL": 2})

    def test_reports_empty_frame_without_inventing_values(self):
        summary = summarize_ocr_yield(
            self.result(
                candidates=[],
                clock=None,
                raw_count=0,
                color_rejected=0,
                bars=0,
                labels={},
                raw_boxes=[],
            )
        )
        self.assertEqual(summary["raw_candidate_count"], 0)
        self.assertEqual(summary["recent_candidate_count"], 0)
        self.assertFalse(summary["clock_readable"])
        self.assertEqual(summary["label_counts"], {})

    def test_unexpected_result_shape_returns_none(self):
        self.assertIsNone(summarize_ocr_yield(None))
        self.assertIsNone(summarize_ocr_yield(("curto",)))
        self.assertIsNone(summarize_ocr_yield([1, 2, 3, 4, 5, 6, 7, 8]))

    def test_non_dict_label_counts_is_not_coerced(self):
        summary = summarize_ocr_yield(
            self.result(
                candidates=[],
                clock=None,
                raw_count=0,
                color_rejected=0,
                bars=1,
                labels=["BUY"],
                raw_boxes=[],
            )
        )
        self.assertIsNone(summary["label_counts"])


class AssociationOutcomeTests(unittest.TestCase):
    def classify(self, **overrides):
        base = dict(
            raw_count=4,
            recent_count=0,
            color_rejected_count=0,
            bar_count=12,
            palette_calibrated=True,
        )
        base.update(overrides)
        return classify_association_outcome(**base)

    def test_association_succeeds(self):
        code, text = self.classify(recent_count=2)
        self.assertEqual(code, "ASSOCIATED")
        self.assertIn("2 rótulo", text)

    def test_uncalibrated_palette_is_named_instead_of_historical_labels(self):
        code, text = self.classify(palette_calibrated=False)
        self.assertEqual(code, "PALETTE_NOT_CALIBRATED")
        self.assertIn("não calibrada", text)

    def test_insufficient_bars_takes_precedence_over_palette(self):
        code, _text = self.classify(bar_count=0, palette_calibrated=False)
        self.assertEqual(code, "INSUFFICIENT_BARS")

    def test_color_conflict_is_reported_first(self):
        code, _text = self.classify(color_rejected_count=3)
        self.assertEqual(code, "COLOR_CONFLICT")

    def test_historical_labels_when_palette_is_calibrated(self):
        code, _text = self.classify()
        self.assertEqual(code, "LABELS_HISTORICAL")

    def test_no_labels(self):
        code, _text = self.classify(raw_count=0)
        self.assertEqual(code, "NO_LABELS")


if __name__ == "__main__":
    unittest.main()
