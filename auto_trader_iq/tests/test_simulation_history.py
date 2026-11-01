import csv
import tempfile
import unittest
from pathlib import Path

from auto_trader_iq.simulation_history import SimulationHistoryStore


class SimulationHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "history.csv"
        self.store = SimulationHistoryStore(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def append(self, event, direction="BUY", elapsed=None):
        self.store.append_event(
            platform_clock="23:44:21",
            event=event,
            timeframe="M1",
            direction=direction,
            observed_text="COMPRA" if direction == "BUY" else "VENDER",
            ocr_confidence=94.5,
            signal_x=100,
            signal_y=200,
            elapsed_seconds_m1=elapsed,
            clock_confidence=91.0,
        )

    def test_append_creates_csv_with_metadata_only(self):
        self.append("sinal_armado")
        self.append("entrada_simulada", elapsed=15)

        with self.path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual([row["event"] for row in rows], ["sinal_armado", "entrada_simulada"])
        self.assertEqual(rows[1]["platform_clock"], "23:44:21")
        self.assertEqual(rows[1]["elapsed_seconds_m1"], "15")
        self.assertEqual(rows[1]["ocr_confidence"], "94.5")
        self.assertNotIn("image", " ".join(rows[1].keys()).lower())

    def test_recent_entries_filters_events_and_returns_latest_limit(self):
        self.append("entrada_simulada", elapsed=10)
        self.append("sinal_armado", direction="SELL")
        self.append("entrada_simulada", direction="SELL", elapsed=15)
        self.append("entrada_simulada", elapsed=20)

        rows = self.store.load_recent_entries(limit=2)

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["elapsed_seconds_m1"] for row in rows], ["15", "20"])

    def test_missing_file_and_nonpositive_limit_return_empty(self):
        self.assertEqual(self.store.load_recent_entries(), [])
        self.append("entrada_simulada")
        self.assertEqual(self.store.load_recent_entries(limit=0), [])

    def test_append_is_append_only(self):
        self.append("sinal_armado")
        self.append("entrada_simulada", elapsed=15)
        with self.path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)

    def test_recent_entries_includes_demo_click_but_ignores_other_events(self):
        self.append("sinal_armado_demo")
        self.append("entrada_demo_clicada", direction="SELL", elapsed=15)

        rows = self.store.load_recent_entries()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "entrada_demo_clicada")


if __name__ == "__main__":
    unittest.main()
