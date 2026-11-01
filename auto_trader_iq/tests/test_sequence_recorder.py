import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from auto_trader_iq.sequence_recorder import SequenceRecorder


class SequenceRecorderTests(unittest.TestCase):
    def test_records_frames_at_interval_and_stops_at_duration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = SequenceRecorder(Path(temp_dir), duration_seconds=2, interval_seconds=1)
            output_dir = recorder.start(now=10.0)
            frame = Image.new("RGB", (12, 8), "white")

            self.assertTrue(recorder.record_frame(
                frame, 10.0, platform_clock="21:23:59", clock_confidence=92.5,
                candle_count=4, candidates=["COMPRA 88%@500,220"],
            ))
            self.assertFalse(recorder.record_frame(frame, 10.5, platform_clock="21:23:59"))
            self.assertTrue(recorder.record_frame(frame, 11.0, platform_clock="21:24:00"))
            self.assertFalse(recorder.record_frame(frame, 12.0, platform_clock="21:24:01"))

            self.assertFalse(recorder.active)
            self.assertEqual(recorder.frames_saved, 2)
            self.assertTrue((output_dir / "frame-0001.jpg").is_file())
            self.assertTrue((output_dir / "frame-0002.jpg").is_file())
            with (output_dir / "manifest.csv").open(encoding="utf-8", newline="") as manifest:
                rows = list(csv.DictReader(manifest))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["platform_clock"], "21:23:59")
            self.assertEqual(rows[0]["clock_confidence"], "92.5")
            self.assertEqual(rows[0]["candle_count"], "4")
            self.assertEqual(rows[0]["candidates"], "COMPRA 88%@500,220")

    def test_stop_closes_manifest_and_returns_output_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = SequenceRecorder(Path(temp_dir), duration_seconds=10)
            output_dir = recorder.start(now=0)
            self.assertEqual(recorder.stop(), output_dir)
            self.assertFalse(recorder.active)
            self.assertFalse(recorder.record_frame(Image.new("RGB", (1, 1)), 1))
            self.assertEqual(recorder.stop(), output_dir)

    def test_rejects_unbounded_or_invalid_recording_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                SequenceRecorder(Path(temp_dir), duration_seconds=121)
            with self.assertRaises(ValueError):
                SequenceRecorder(Path(temp_dir), duration_seconds=0)
            with self.assertRaises(ValueError):
                SequenceRecorder(Path(temp_dir), duration_seconds=2, interval_seconds=3)


if __name__ == "__main__":
    unittest.main()
