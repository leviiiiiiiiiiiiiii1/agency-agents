import csv
import tempfile
import unittest
from pathlib import Path

from auto_trader_iq.sequence_validation import validate_sequence_manifest


class SequenceValidationTests(unittest.TestCase):
    FIELDS = (
        "frame", "elapsed_seconds", "platform_clock", "clock_confidence",
        "clock_ocr_excerpt", "candle_count", "candidates",
    )

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sequence_dir = Path(self.temp_dir.name) / "sequence-test"
        self.sequence_dir.mkdir()
        self.manifest = self.sequence_dir / "manifest.csv"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_rows(self, rows):
        with self.manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def row(frame, elapsed, clock, confidence="90"):
        return {
            "frame": frame,
            "elapsed_seconds": elapsed,
            "platform_clock": clock,
            "clock_confidence": confidence,
            "clock_ocr_excerpt": "",
            "candle_count": "",
            "candidates": "",
        }

    def test_detects_next_minute_across_midnight_using_adjacent_confident_rows(self):
        self.write_rows([
            self.row("frame-0001.jpg", "0.0", "23:59:59"),
            self.row("frame-0002.jpg", "2.0", "00:00:01"),
        ])

        report = validate_sequence_manifest(self.sequence_dir)

        self.assertEqual(report.valid_clock_rows, 2)
        self.assertEqual(len(report.observed_next_minute), 1)
        transition = report.observed_next_minute[0]
        self.assertEqual(transition.minute_step, 1)
        self.assertEqual(transition.recorder_gap_seconds, 2.0)

    def test_reports_multi_minute_jump_without_calling_it_one_minute(self):
        self.write_rows([
            self.row("frame-0001.jpg", "0.0", "23:58:59"),
            self.row("frame-0002.jpg", "3.0", "00:01:02"),
        ])

        report = validate_sequence_manifest(self.manifest)

        self.assertEqual(report.observed_next_minute, ())
        self.assertEqual(len(report.skipped_minutes), 1)
        self.assertEqual(report.skipped_minutes[0].minute_step, 3)

    def test_unreadable_or_low_confidence_row_breaks_adjacency(self):
        self.write_rows([
            self.row("frame-0001.jpg", "0.0", "23:59:59"),
            self.row("frame-0002.jpg", "1.0", "", ""),
            self.row("frame-0003.jpg", "2.0", "00:00:01"),
        ])

        report = validate_sequence_manifest(self.manifest)

        self.assertEqual(report.valid_clock_rows, 2)
        self.assertEqual(report.unreadable_or_low_confidence_rows, 1)
        self.assertEqual(report.transitions, ())

    def test_invalid_clock_text_is_not_counted(self):
        self.write_rows([self.row("frame-0001.jpg", "0.0", "25:61:99")])
        report = validate_sequence_manifest(self.manifest)
        self.assertEqual(report.valid_clock_rows, 0)
        self.assertEqual(report.unreadable_or_low_confidence_rows, 1)

    def test_invalid_confidence_threshold_is_rejected(self):
        self.write_rows([])
        with self.assertRaises(ValueError):
            validate_sequence_manifest(self.manifest, minimum_clock_confidence=101)


if __name__ == "__main__":
    unittest.main()
