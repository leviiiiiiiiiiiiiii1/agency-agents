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

    def test_sessions_are_not_mixed(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:05:00+00:00", "A", "BUY", 0, [140.0] * 5, session="s2"),
        ]
        self.assertEqual(compute_outcomes(frames)["evaluated"], 0)


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
