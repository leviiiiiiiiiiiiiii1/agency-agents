import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from auto_trader_iq import geometry_diagnostics as diagnostics


def bars(centers):
    return [SimpleNamespace(center_x=float(center)) for center in centers]


def label(left, top=40, width=40, height=14):
    return SimpleNamespace(left=left, top=top, width=width, height=height)


class SummarizeTests(unittest.TestCase):
    def test_bars_to_the_right_is_measured(self):
        summary = diagnostics.summarize(bars([0, 40, 80, 120]), [label(30)])
        self.assertEqual(summary["bar_count"], 4)
        self.assertEqual(summary["rightmost_label_index"], 1)
        self.assertEqual(summary["bars_to_the_right"], 2)
        self.assertEqual(summary["median_gap_px"], 40.0)

    def test_label_near_the_right_edge(self):
        summary = diagnostics.summarize(bars([0, 40, 80]), [label(160)])
        self.assertEqual(summary["bars_to_the_right"], 0)

    def test_without_bars_there_is_no_geometry(self):
        self.assertIsNone(diagnostics.summarize([], [label(30)]))

    def test_without_labels_geometry_is_partial(self):
        summary = diagnostics.summarize(bars([0, 40]), [])
        self.assertIsNone(summary["bars_to_the_right"])
        self.assertEqual(summary["bar_count"], 2)

    def test_irregular_gaps_use_the_median(self):
        summary = diagnostics.summarize(bars([0, 40, 41, 81]), [label(35)])
        self.assertEqual(summary["median_gap_px"], 40.0)


class GridTests(unittest.TestCase):
    def test_off_grid_bars_do_not_age_the_label(self):
        # grade regular de 40 px até 160, depois duas detecções fora da grade.
        on_grid = bars([0, 40, 80, 120, 160])
        noisy = bars([0, 40, 80, 120, 160, 300, 420])
        plain = diagnostics.summarize(on_grid, [label(150)])
        noisy_summary = diagnostics.summarize(noisy, [label(150)])
        self.assertEqual(plain["bars_to_the_right_ongrid"], 0)
        self.assertEqual(noisy_summary["bars_to_the_right"], 2)
        self.assertEqual(noisy_summary["bars_to_the_right_ongrid"], 0)

    def test_regular_gap_share_detects_irregular_grid(self):
        self.assertEqual(
            diagnostics.summarize(bars([0, 40, 80, 120]), [label(30)])["regular_gap_share"],
            1.0,
        )
        irregular = diagnostics.summarize(bars([0, 40, 41, 200]), [label(30)])
        self.assertLess(irregular["regular_gap_share"], 0.6)

    def test_missing_ongrid_measure_is_none_without_gap(self):
        summary = diagnostics.summarize(bars([0, 1, 2]), [label(0)])
        self.assertIsNone(summary["median_gap_px"])
        self.assertIsNone(summary["bars_to_the_right_ongrid"])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        diagnostics.reset_rate_limit()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.image = Image.new("RGB", (200, 120), (16, 16, 16))

    def test_snapshot_when_label_is_far_from_the_last_bar(self):
        path = diagnostics.save_snapshot(
            self.image, bars([0, 40, 80, 120, 160]), [label(30)], self.dir
        )
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        payload = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(payload["bars_to_the_right"], 3)
        self.assertEqual(Image.open(path).size, (200, 120))

    def test_snapshot_json_carries_per_bar_detail(self):
        path = diagnostics.save_snapshot(
            self.image, bars([0, 40, 80, 120, 160.0]), [label(30)], self.dir
        )
        payload = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(payload["gaps_px"], [40.0, 40.0, 40.0, 40.0])
        self.assertEqual(payload["bar_centers_x"], [0.0, 40.0, 80.0, 120.0, 160.0])
        self.assertEqual(payload["image_size"], [200, 120])

    def test_no_snapshot_when_label_is_recent(self):
        path = diagnostics.save_snapshot(
            self.image, bars([0, 40, 80]), [label(50)], self.dir
        )
        self.assertIsNone(path)

    def test_rate_limit_blocks_a_second_snapshot(self):
        first = diagnostics.save_snapshot(
            self.image, bars([0, 40, 80, 120, 160]), [label(30)], self.dir
        )
        second = diagnostics.save_snapshot(
            self.image, bars([0, 40, 80, 120, 160]), [label(30)], self.dir
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_force_ignores_rate_limit(self):
        diagnostics.save_snapshot(self.image, bars([0, 40, 80, 160]), [label(30)], self.dir)
        forced = diagnostics.save_snapshot(
            self.image, bars([0, 40, 80, 160]), [label(30)], self.dir, force=True
        )
        self.assertIsNotNone(forced)

    def test_annotation_marks_bars_and_never_mutates_input(self):
        original = self.image.copy()
        annotated = diagnostics.save_snapshot(
            self.image, bars([0, 40, 80, 160]), [label(30)], self.dir, force=True
        )
        self.assertIsNotNone(annotated)
        self.assertEqual(list(self.image.getdata()), list(original.getdata()))

    def test_failure_does_not_raise(self):
        self.assertIsNone(
            diagnostics.save_snapshot("não é imagem", bars([0, 1, 2, 3]), [label(0)], self.dir)
        )


if __name__ == "__main__":
    unittest.main()


class GridEndTests(unittest.TestCase):
    def test_grid_end_stops_at_the_first_break(self):
        from auto_trader_iq.geometry_diagnostics import grid_end_index

        noisy = bars([0, 40, 80, 120, 300, 420])
        self.assertEqual(grid_end_index(noisy, 1), 3)
        self.assertEqual(grid_end_index(noisy, 4), 4)

    def test_grid_end_is_none_without_regular_spacing(self):
        from auto_trader_iq.geometry_diagnostics import grid_end_index

        self.assertIsNone(grid_end_index(bars([0, 1, 2]), 0))
        self.assertIsNone(grid_end_index(bars([5]), 0))
        self.assertIsNone(grid_end_index(bars([0, 40]), 7))
