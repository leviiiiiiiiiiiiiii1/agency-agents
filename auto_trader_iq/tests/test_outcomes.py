import unittest

from auto_trader_iq.grade_report import (
    ADVERSE,
    FAVORABLE,
    NEUTRAL,
    compute_outcomes,
    format_outcomes,
)


def frame(at, code, direction, age, closes, typical=40.0, session="s1"):
    return {
        "occurred_at_utc": at,
        "session_id": session,
        "code": code,
        "features": {"direction": direction, "age_bars": age},
        "price_ladder": {"closes_px": closes, "median_range_px": typical},
    }


class ComputeOutcomeTests(unittest.TestCase):
    def test_buy_that_falls_in_price_is_adverse(self):
        # y menor = preço maior: fechamento sobe de 140 para 100 = preço subiu.
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [140.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [100.0, 140.0, 140.0, 140.0]),
        ]
        result = compute_outcomes(frames, bar_seconds=60, horizon_bars=3)
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["by_grade"]["A"][FAVORABLE], 1)

    def test_buy_that_drops_is_adverse(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "C", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "C", "BUY", 0, [180.0, 100.0, 100.0, 100.0]),
        ]
        result = compute_outcomes(frames, bar_seconds=60, horizon_bars=3)
        self.assertEqual(result["by_grade"]["C"][ADVERSE], 1)

    def test_sell_reverses_the_sign(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "SELL", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "SELL", 0, [180.0, 100.0, 100.0, 100.0]),
        ]
        self.assertEqual(compute_outcomes(frames)["by_grade"]["A"][FAVORABLE], 1)

    def test_small_move_is_neutral(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "B", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "B", "BUY", 0,
                  [105.0, 100.0, 100.0, 100.0, 100.0]),
        ]
        self.assertEqual(compute_outcomes(frames)["by_grade"]["B"][NEUTRAL], 1)

    def test_entry_bar_is_located_by_age(self):
        # sinal com idade 1: a vela de entrada está na posição 1 da escada.
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 1, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 1,
                  [140.0, 140.0, 100.0, 100.0, 100.0]),
        ]
        result = compute_outcomes(frames, bar_seconds=60, horizon_bars=3)
        # idade 1 + 3 velas = índice 4 da escada (100); atual 140 -> preço caiu.
        self.assertEqual(result["by_grade"]["A"][ADVERSE], 1)

    def test_horizon_not_reached_is_skipped(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:00:30+00:00", "A", "BUY", 0, [140.0] * 5),
        ]
        result = compute_outcomes(frames, bar_seconds=60, horizon_bars=3)
        self.assertEqual(result["evaluated"], 0)
        # nenhum dos dois quadros tem um posterior que alcance o horizonte
        self.assertEqual(result["skipped"], 2)

    def test_ladder_too_shallow_is_skipped(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 1, [100.0, 100.0]),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 1, [140.0, 140.0]),
        ]
        self.assertEqual(compute_outcomes(frames)["evaluated"], 0)

    def test_missing_closes_are_skipped(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [None, 100.0, 100.0, 100.0]),
        ]
        self.assertEqual(compute_outcomes(frames)["evaluated"], 0)

    def test_frames_without_grade_are_not_evaluated(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0, [140.0] * 5),
        ]
        self.assertEqual(compute_outcomes(frames)["evaluated"], 0)

    def test_reference_frame_does_not_need_to_be_graded(self):
        later = frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0, [140.0] * 5)
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            later,
        ]
        result = compute_outcomes(frames, bar_seconds=60, horizon_bars=3)
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["signals_with_ladder"], 1)
        self.assertEqual(result["frames_with_ladder"], 2)

    def test_counters_expose_missing_ladders(self):
        frames = [frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5)]
        frames[0]["price_ladder"] = None
        result = compute_outcomes(frames)
        self.assertEqual(result["evaluated"], 0)
        self.assertEqual(result["signals_graded"], 1)
        self.assertEqual(result["frames_with_ladder"], 0)
        self.assertIn("sessões antigas", format_outcomes(result))

    def test_sessions_are_not_mixed(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:05:00+00:00", "A", "BUY", 0, [140.0] * 5, session="s2"),
        ]
        self.assertEqual(compute_outcomes(frames)["evaluated"], 0)


class BreakdownTests(unittest.TestCase):
    def test_reasons_are_aggregated_with_minimum_sample(self):
        probes = []
        for offset, closes in enumerate(([140.0] * 5, [140.0] * 5, [140.0] * 5)):
            signal = frame(f"2026-11-11T18:0{offset}:00+00:00", "C", "BUY", 0, [100.0] * 5)
            signal["reasons"] = ["corpo esticado"]
            reference = frame(f"2026-11-11T18:0{offset + 1}:00+00:00", "NO_TRADE", "BUY", 0, closes)
            probes.append((signal, reference))
        single = frame("2026-11-11T19:00:00+00:00", "C", "BUY", 0, [100.0] * 5)
        single["reasons"] = ["motivo raro"]
        probes.append((single, frame("2026-11-11T19:01:00+00:00", "NO_TRADE", "BUY", 0, [140.0] * 5)))
        # cada sinal precisa de um quadro futuro a pelo menos 0.8 * 3 velas
        frames = []
        for signal, reference in probes:
            frames.extend([signal, reference])
        result = compute_outcomes(frames, bar_seconds=60, horizon_bars=1)
        self.assertIn("corpo esticado", result["by_reason"])
        self.assertNotIn("motivo raro", result["by_reason"])

    def test_direction_breakdown_is_reported(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [100.0, 140.0, 140.0, 140.0]),
        ]
        result = compute_outcomes(frames)
        self.assertEqual(result["by_direction"]["BUY"]["favorável"], 1)

    def test_reason_table_is_rendered(self):
        text = format_outcomes({
            "evaluated": 3, "skipped": 0, "horizon_bars": 3, "bar_seconds": 60,
            "min_move_units": 0.5, "signals_graded": 3, "signals_with_ladder": 3,
            "frames_with_ladder": 6, "by_direction": {},
            "by_reason": {"corpo esticado": {"total": 3, FAVORABLE: 2, NEUTRAL: 0,
                                             ADVERSE: 1, "median_move_units": 0.9}},
            "by_grade": {"C": {"total": 3, FAVORABLE: 2, NEUTRAL: 0, ADVERSE: 1,
                               "median_move_units": 0.9}},
        })
        self.assertIn("Por motivo registrado", text)
        self.assertIn("corpo esticado", text)


class FormatTests(unittest.TestCase):
    def test_report_states_it_is_not_a_hit_rate(self):
        text = format_outcomes(compute_outcomes([]))
        self.assertIn("NÃO é taxa de acerto", text)
        self.assertIn("Nenhum sinal", text)

    def test_table_lists_each_class(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [140.0] * 5),
        ]
        text = format_outcomes(compute_outcomes(frames))
        self.assertIn("classe", text)
        self.assertIn("favorável", text)
        self.assertIn("--bar-seconds", text)


if __name__ == "__main__":
    unittest.main()
