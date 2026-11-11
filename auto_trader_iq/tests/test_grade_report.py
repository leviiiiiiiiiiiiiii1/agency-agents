import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from auto_trader_iq.grade_report import (
    default_journal_path,
    load_tracks,
    format_report,
    load_frames,
    main,
    summarize,
    sweep,
)
from auto_trader_iq.opportunity_grade import DEFAULT_CRITERIA


def frame(code="A", features=True, palette=True, age=0, body=1.0, distance=0.5,
          close=0.6, regime="flow", context="BUY", direction="BUY",
          reasons=(), raw=1, recent=1):
    payload = {
        "grade": {
            "code": code,
            "criteria_hash": "abc",
            "reasons": list(reasons),
            "context_regime": regime,
            "context_direction": context,
            "features": None
            if not features
            else {
                "direction": direction,
                "age_bars": age,
                "body": 20.0,
                "candle_range": 40.0,
                "upper_wick": 5.0,
                "lower_wick": 15.0,
                "body_vs_median": body,
                "close_from_extreme": close,
                "distance_to_level": distance,
                "context_regime": regime,
                "context_direction": context,
            },
        },
        "association": {"palette_calibrated": palette},
        "raw_candidate_count": raw,
        "recent_candidate_count": recent,
    }
    return {
        "occurred_at_utc": "2026-10-30T12:00:00Z",
        "session_id": "s1",
        "schema_version": 3,
        "code": code,
        "criteria_hash": "abc",
        "features": payload["grade"]["features"],
        "reasons": payload["grade"]["reasons"],
        "context_regime": regime,
        "context_direction": context,
        "raw_candidate_count": raw,
        "recent_candidate_count": recent,
        "palette_calibrated": palette,
    }


class SummarizeTests(unittest.TestCase):
    def test_counts_and_coverage(self):
        result = summarize([frame("A"), frame("C", body=3.0), frame("NO_CANDIDATE", features=False)])
        self.assertEqual(result["frames"], 3)
        self.assertEqual(result["frames_with_features"], 2)
        self.assertEqual(result["counts"]["A"], 1)
        self.assertEqual(result["counts"]["C"], 1)
        self.assertEqual(result["counts"]["NO_CANDIDATE"], 1)
        for name, count in result["coverage"].items():
            self.assertEqual(count, 2, name)

    def test_percentiles_describe_the_sample(self):
        frames = [frame("A", body=value) for value in (0.5, 1.0, 1.5)]
        stats = summarize(frames)["distributions"]["body_vs_median"]
        self.assertEqual(stats["n"], 3)
        self.assertEqual(stats["p50"], 1.0)

    def test_age_above_two_is_grouped(self):
        result = summarize([frame("NO_TRADE", age=5), frame("A", age=0)])
        self.assertEqual(result["age_bars_counts"]["3+"], 1)
        self.assertEqual(result["age_bars_counts"]["0"], 1)

    def test_empty_journal_is_reported_not_crashed(self):
        text = format_report(summarize([]))
        self.assertIn("Nenhum quadro", text)


class DiagnosisTests(unittest.TestCase):
    def test_regime_distribution_is_summarized(self):
        result = summarize([frame(regime="lateral"), frame(regime="flow"), frame(regime="flow")])
        self.assertEqual(result["context_regimes"], {"lateral": 1, "flow": 2})

    def test_reasons_are_ranked(self):
        result = summarize(
            [
                frame("C", reasons=("mercado lateralizado",)),
                frame("C", reasons=("mercado lateralizado",)),
                frame("B", reasons=("rótulo com 1 vela(s) de idade",)),
            ]
        )
        self.assertEqual(result["top_reasons"][0]["reason"], "mercado lateralizado")
        self.assertEqual(result["top_reasons"][0]["count"], 2)

    def test_reasons_of_good_grades_are_not_counted_as_blocks(self):
        result = summarize(
            [
                frame("A", reasons=("corpo 1.07× a mediana",)),
                frame("C", reasons=("preço a 3% da faixa até o nível contrário",)),
            ]
        )
        counted = [item["reason"] for item in result["top_reasons"]]
        self.assertEqual(counted, ["preço a 3% da faixa até o nível contrário"])

    def test_label_visibility_is_separated(self):
        result = summarize(
            [
                frame("NO_LABEL", features=False, raw=0, recent=0),
                frame("LABEL_OUTSIDE_WINDOW", features=False, raw=2, recent=0),
                frame("A"),
            ]
        )
        self.assertEqual(result["frames_with_raw_label"], 2)
        self.assertEqual(result["frames_with_recent_label"], 1)
        self.assertEqual(result["counts"]["NO_LABEL"], 1)
        self.assertEqual(result["counts"]["LABEL_OUTSIDE_WINDOW"], 1)

    def test_unreachable_fresh_age_is_flagged(self):
        result = summarize([frame("B", age=2), frame("B", age=2)])
        self.assertEqual(result["min_age_observed"], 2)
        text = format_report(result)
        self.assertIn("classe A é inalcançável", text)
        self.assertIn("decisão sua", text)

    def test_reachable_fresh_age_is_not_flagged(self):
        text = format_report(summarize([frame("A", age=1)]))
        self.assertNotIn("inalcançável", text)

    def test_report_prints_diagnosis_sections(self):
        text = format_report(
            summarize([frame("C", reasons=("mercado lateralizado",), regime="lateral")])
        )
        self.assertIn("Regime de contexto", text)
        self.assertIn("Motivos de bloqueio", text)
        self.assertIn("mercado lateralizado", text)


class TrackTests(unittest.TestCase):
    def test_tracks_are_not_presented_as_signals(self):
        tracks = [{"tracking_id": "t1"}, {"tracking_id": "t2"}]
        result = summarize([frame(raw=5)] * 40, tracks)
        self.assertEqual(result["tracked_positions"], 2)
        self.assertEqual(result["frames_per_track"], 20.0)
        text = format_report(result)
        self.assertIn("Rastro não é sinal", text)
        self.assertNotIn("sinais distintos", text)

    def test_missing_track_table_is_not_an_error(self):
        db = Path(tempfile.mkdtemp()) / "v1.db"
        connection = sqlite3.connect(db)
        connection.executescript(
            "CREATE TABLE opportunity_events (event_id INTEGER PRIMARY KEY,"
            " session_id TEXT, event_type TEXT, occurred_at_utc TEXT,"
            " payload_json TEXT, idempotency_key TEXT); PRAGMA user_version=1;"
        )
        connection.commit()
        connection.close()
        self.assertEqual(load_tracks(db), [])

    def test_ratio_absent_without_tracks(self):
        result = summarize([frame()])
        self.assertIsNone(result["frames_per_track"])
        self.assertNotIn("Rastro não é sinal", format_report(result))


class FreshRunTests(unittest.TestCase):
    def test_consecutive_fresh_frames_count_as_one_signal(self):
        frames = [
            frame(raw=1, recent=1),
            frame(raw=1, recent=1),
            frame(raw=1, recent=0),
            frame(raw=1, recent=1),
        ]
        self.assertEqual(summarize(frames)["fresh_signal_runs"], 2)

    def test_runs_do_not_span_sessions(self):
        first = frame(raw=1, recent=1)
        second = frame(raw=1, recent=1)
        second["session_id"] = "s2"
        self.assertEqual(summarize([first, second])["fresh_signal_runs"], 2)

    def test_hash_breakdown_separates_legacy_frames(self):
        old = frame("NO_CANDIDATE", features=False)
        old["criteria_hash"] = "8d50"
        new = frame("A")
        result = summarize([old, new])
        self.assertEqual(result["by_criteria_hash"][0]["hash"], "8d50")
        self.assertEqual(result["by_criteria_hash"][0]["frames"], 1)
        self.assertIn("Por versão de limiares", format_report(result))


class SweepTests(unittest.TestCase):
    def test_moving_body_limit_reclassifies_recorded_frames(self):
        frames = [frame("B", body=1.5), frame("B", body=2.5)]
        results = sweep(frames, "max_body_vs_median_b", [2.0, 3.0])
        self.assertEqual(results[0]["counts"].get("C"), 1)
        self.assertEqual(results[1]["counts"].get("B"), 1)
        self.assertNotIn("C", results[1]["counts"])

    def test_invalid_combination_is_flagged(self):
        results = sweep([frame()], "max_body_vs_median_a", [99.0])
        self.assertIn("invalid", results[0])

    def test_unknown_parameter_is_rejected(self):
        with self.assertRaises(ValueError):
            sweep([frame()], "nao_existe", [1])

    def test_identical_sweep_results_are_explained(self):
        frames = [frame("NO_TRADE", regime="lateral", body=1.0)]
        text = format_report(
            summarize(frames),
            [("max_body_vs_median_b", sweep(frames, "max_body_vs_median_b", [2.0, 3.0]))],
        )
        self.assertIn("outro critério", text)

    def test_sweep_ignores_frames_without_features(self):
        results = sweep([frame(features=False), frame()], "fresh_age_bars", [0])
        self.assertEqual(results[0]["graded"], 1)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "journal.db"
        connection = sqlite3.connect(self.db)
        connection.executescript(
            """
            CREATE TABLE opportunity_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT,
                session_id TEXT,
                event_type TEXT NOT NULL,
                occurred_at_utc TEXT NOT NULL,
                source TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT NOT NULL UNIQUE
            );
            PRAGMA user_version = 3;
            """
        )
        self.connection = connection

    def insert(self, event_type="OCR_COMPLETED", payload=None, key=None):
        self.connection.execute(
            "INSERT INTO opportunity_events (session_id, event_type, occurred_at_utc,"
            " source, payload_json, idempotency_key) VALUES (?,?,?,?,?,?)",
            ("s1", event_type, "2026-10-30T12:00:00Z", "TEST",
             json.dumps(payload if payload is not None else {}), key or str(id(payload))),
        )
        self.connection.commit()

    def test_only_ocr_completed_events_are_read(self):
        self.insert(payload={"grade": {"code": "A", "features": {"age_bars": 0}}}, key="a")
        self.insert(event_type="CAPTURE_FRAME_ACCEPTED", payload={"x": 1}, key="b")
        frames = load_frames(self.db)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["code"], "A")

    def test_malformed_payload_does_not_break_reading(self):
        self.insert(payload={"grade": "texto"}, key="a")
        self.connection.execute(
            "INSERT INTO opportunity_events (session_id, event_type, occurred_at_utc,"
            " source, payload_json, idempotency_key) VALUES (?,?,?,?,?,?)",
            ("s1", "OCR_COMPLETED", "2026-10-30T12:00:01Z", "TEST", "{nao-json", "b"),
        )
        self.connection.commit()
        self.assertEqual(load_frames(self.db), [])

    def test_missing_database_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_frames(Path(self.tmp.name) / "ausente.db")

    def test_cli_json_output_flags_absent_accuracy(self):
        self.insert(payload={"grade": {"code": "A", "features": {"age_bars": 0}}}, key="a")
        import contextlib, io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--db", str(self.db), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertFalse(payload["accuracy_available"])
        self.assertEqual(payload["summary"]["frames"], 1)

    def test_cli_reports_missing_db_without_traceback(self):
        import contextlib, io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--db", str(Path(self.tmp.name) / "nada.db")])
        self.assertEqual(code, 2)
        self.assertIn("Erro", buffer.getvalue())

    def test_report_runs_without_explicit_db(self):
        self.insert(payload={"grade": {"code": "A", "features": {"age_bars": 0}}}, key="a")
        import contextlib, io

        buffer = io.StringIO()
        with mock.patch(
            "auto_trader_iq.grade_report.default_journal_path", return_value=self.db
        ), contextlib.redirect_stdout(buffer):
            code = main(["--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["summary"]["frames"], 1)

    def test_missing_default_journal_explains_where_it_looked(self):
        import contextlib, io

        absent = Path(self.tmp.name) / "sem_journal.sqlite3"
        buffer = io.StringIO()
        with mock.patch(
            "auto_trader_iq.grade_report.default_journal_path", return_value=absent
        ), contextlib.redirect_stdout(buffer):
            code = main([])
        self.assertEqual(code, 2)
        self.assertIn(str(absent), buffer.getvalue())
        self.assertIn("--db", buffer.getvalue())

    def test_default_path_points_to_app_journal(self):
        self.assertEqual(default_journal_path().name, "opportunities.sqlite3")

    def test_default_criteria_are_used_by_sweep(self):
        self.assertFalse(DEFAULT_CRITERIA.missing_fields())


if __name__ == "__main__":
    unittest.main()
