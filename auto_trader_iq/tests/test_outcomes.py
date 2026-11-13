import unittest
from datetime import datetime, timezone

from auto_trader_iq.grade_report import (
    ADVERSE,
    _breakeven,
    _expected_value,
    _one_per_bar,
    FAVORABLE,
    NEUTRAL,
    compute_baseline,
    compute_flow_rule,
    compute_outcomes,
    compute_session_comparison,
    format_baseline,
    format_flow_rule,
    format_outcomes,
    format_session_comparison,
    _flow_edge_verdict,
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

    def test_horizon_uses_the_frame_at_the_horizon_not_the_first_past_it(self):
        # Com quadros a cada 10 s, aceitar o primeiro quadro depois de 80% do
        # horizonte media 0,83 vela e chamava de 1 vela.
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:00:50+00:00", "NO_TRADE", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:01:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 140.0, 140.0, 140.0, 140.0]),
        ]
        result = compute_outcomes(frames, bar_seconds=60, horizon_bars=1)
        self.assertEqual(result["evaluated"], 1)
        # O quadro de 60 s mostra alta; o de 50 s mostra preço parado.
        self.assertEqual(result["by_grade"]["A"][FAVORABLE], 1)
        self.assertEqual(result["by_grade"]["A"][NEUTRAL], 0)

    def test_horizon_not_reached_is_skipped(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:00:30+00:00", "A", "BUY", 0, [140.0] * 5),
        ]
        result = compute_outcomes(frames, bar_seconds=60, horizon_bars=3)
        self.assertEqual(result["evaluated"], 0)
        # Os dois quadros são do MESMO candle: o segundo não é uma aposta nova.
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["repeated_frames"], 1)

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

    def test_grade_direction_cross_tab_keeps_directions_apart(self):
        frames = [
            # A compra e acerta; A vende e erra.
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [140.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 140.0, 140.0, 140.0]),
            frame("2026-11-11T18:10:00+00:00", "A", "SELL", 0, [100.0] * 5),
            frame("2026-11-11T18:13:00+00:00", "NO_TRADE", "SELL", 0,
                  [100.0, 140.0, 140.0, 140.0]),
        ]
        result = compute_outcomes(frames)
        self.assertEqual(result["by_grade_direction"]["A"]["BUY"]["favorável"], 1)
        self.assertEqual(result["by_grade_direction"]["A"]["SELL"]["adversa"], 1)

    def test_cross_tab_is_rendered_with_mix(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "C", "SELL", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "SELL", 0,
                  [180.0, 100.0, 100.0, 100.0]),
        ]
        text = format_outcomes(compute_outcomes(frames))
        self.assertIn("Por classe e direção", text)
        self.assertIn("Mistura de direção por classe", text)
        self.assertIn("C: SELL 1/1 (100%)", text)

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


class AlignmentTests(unittest.TestCase):
    """O sinal só vale se não for apenas repetição do que já andou."""

    def probe(self, direction, code, closes):
        signal = frame("2026-11-11T18:00:00+00:00", code, direction, 0, [100.0] * 7)
        reference = frame("2026-11-11T18:03:00+00:00", "NO_TRADE", direction, 0, closes)
        return compute_outcomes([signal, reference])

    def test_buy_after_a_rise_is_aligned(self):
        # closes[6]=180 (preço mais baixo antes) -> subiu; entrada em closes[3]=100.
        result = self.probe("BUY", "A", [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 180.0])
        self.assertEqual(result["by_alignment"]["a favor do movimento anterior"]["adversa"], 1)

    def test_sell_after_a_fall_is_aligned(self):
        # entrada em closes[3]=180, preço cai até closes[0]=220 (y maior) e já
        # vinha caindo (closes[6]=100, y menor = preço mais alto antes).
        result = self.probe("SELL", "C", [220.0, 220.0, 220.0, 180.0, 180.0, 180.0, 100.0])
        self.assertEqual(
            result["by_alignment"]["a favor do movimento anterior"]["favorável"], 1
        )

    def test_buy_after_a_fall_contradicts_the_move(self):
        result = self.probe("BUY", "A", [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 60.0])
        self.assertEqual(result["by_alignment"]["contra o movimento anterior"]["adversa"], 1)

    def test_short_ladder_is_counted_as_missing_history(self):
        result = self.probe("BUY", "A", [140.0, 140.0, 140.0, 100.0])
        self.assertEqual(result["by_alignment"]["sem histórico no quadro"]["adversa"], 1)

    def test_alignment_keeps_directions_apart(self):
        # Um BUY a favor do movimento tem que aparecer como BUY, não somado ao SELL.
        result = self.probe("BUY", "A", [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 180.0])
        split = result["by_alignment_direction"]["a favor do movimento anterior"]
        self.assertEqual(split["BUY"]["adversa"], 1)
        self.assertNotIn("SELL", split)

    def test_alignment_block_is_rendered(self):
        result = self.probe("BUY", "A", [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 180.0])
        text = format_outcomes(result)
        self.assertIn("SINAL SEGUE OU CONTRARIA O MOVIMENTO ANTERIOR", text)
        self.assertIn("a favor do movimento anterior", text)
        self.assertIn("separadas por direção", text)
        text.encode("cp1252")


class ContextTests(unittest.TestCase):
    def signal(self, direction, context):
        signal = frame("2026-11-11T18:00:00+00:00", "C", direction, 0, [100.0] * 7)
        signal["features"]["context_direction"] = context
        return [
            signal,
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", direction, 0, [140.0] * 7),
        ]

    def test_opposed_context_is_its_own_bucket(self):
        result = compute_outcomes(self.signal("SELL", "BUY"))
        self.assertEqual(result["by_context"]["contra o contexto"]["total"], 1)

    def test_missing_context_is_not_counted_as_opposed(self):
        result = compute_outcomes(self.signal("SELL", None))
        self.assertEqual(result["by_context"]["sem contexto no quadro"]["total"], 1)

    def test_veto_by_context_removes_the_opposed_signal(self):
        result = compute_outcomes(self.signal("SELL", "BUY"))
        veto = next(v for v in result["vetoes"] if v["rule"] == "contra o contexto")
        self.assertEqual(veto["removed"]["total"], 1)
        self.assertEqual(veto["kept"]["total"], 0)


class VetoSimulationTests(unittest.TestCase):
    def test_veto_reports_what_is_discarded_and_what_remains(self):
        # Um sinal contra o movimento e um a favor; vetar o primeiro deixa o segundo.
        against = frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 7)
        with_it = frame("2026-11-11T18:10:00+00:00", "A", "BUY", 0, [100.0] * 7)
        frames = [
            against,
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 60.0]),
            with_it,
            frame("2026-11-11T18:13:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 180.0]),
        ]
        result = compute_outcomes(frames, horizon_bars=3)
        veto = next(v for v in result["vetoes"] if v["rule"] == "contra o movimento anterior")
        self.assertEqual(veto["removed"]["total"], 1)
        self.assertEqual(veto["kept"]["total"], 1)
        self.assertEqual(veto["kept"]["favorável"], 1)

    def test_veto_block_is_rendered(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 180.0]),
        ]
        text = format_outcomes(compute_outcomes(frames, horizon_bars=3))
        self.assertIn("SIMULAÇÃO DE ABSTENÇÃO", text)
        text.encode("cp1252")


class BaselineTests(unittest.TestCase):
    def test_baseline_has_no_classifier_and_uses_every_frame(self):
        # Nenhum quadro é sinal: a linha de base não depende de A/B/C.
        frames = [
            frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [180.0, 100.0, 100.0, 100.0]),
        ]
        baseline = compute_baseline(frames)
        self.assertEqual(baseline["frames_with_ladder"], 2)
        self.assertEqual(baseline["BUY"][ADVERSE], 1)
        self.assertEqual(baseline["SELL"][FAVORABLE], 1)

    def test_baseline_reports_both_directions_on_a_trend(self):
        frames = [frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "SELL", 0, [100.0] * 5)]
        for minute in range(1, 4):
            frames.append(frame(
                f"2026-11-11T18:0{minute}:00+00:00", "NO_TRADE", "SELL", 0,
                [180.0, 140.0, 110.0, 100.0, 100.0],
            ))
        baseline = compute_baseline(frames, horizon_bars=3)
        self.assertEqual(baseline["SELL"][FAVORABLE], 1)
        self.assertEqual(baseline["BUY"][ADVERSE], 1)

    def test_baseline_following_the_prior_move(self):
        # Antes da entrada o preço subiu (closes[6]=180 -> closes[3]=140) e depois
        # continuou subindo (closes[0]=100): seguir o movimento acerta.
        frames = [
            frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 120.0, 130.0, 140.0, 150.0, 160.0, 180.0]),
        ]
        baseline = compute_baseline(frames, horizon_bars=3)
        following = baseline["by_situation"]["seguindo o movimento anterior"]
        against = baseline["by_situation"]["contra o movimento anterior"]
        self.assertEqual(following[FAVORABLE], 1)
        self.assertEqual(against[ADVERSE], 1)

    def test_baseline_situation_keeps_the_bet_direction(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 120.0, 130.0, 140.0, 150.0, 160.0, 180.0]),
        ]
        baseline = compute_baseline(frames, horizon_bars=3)
        split = baseline["by_situation_direction"]["seguindo o movimento anterior"]
        self.assertEqual(split["BUY"][FAVORABLE], 1)
        self.assertNotIn("SELL", split)

    def test_baseline_separates_regimes(self):
        lateral = frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7)
        lateral["context_regime"] = "lateral"
        flow = frame("2026-11-11T18:10:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7)
        flow["context_regime"] = "flow"
        frames = [
            lateral,
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 180.0]),
            flow,
            frame("2026-11-11T18:13:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 180.0]),
        ]
        baseline = compute_baseline(frames, horizon_bars=3)
        self.assertEqual(baseline["by_regime"]["lateral"]["seguir"]["total"], 1)
        self.assertEqual(baseline["by_regime"]["flow"]["seguir"]["total"], 1)

    def test_regime_block_is_rendered(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 180.0]),
        ]
        text = format_baseline(compute_baseline(frames, horizon_bars=3))
        self.assertIn("REGIME LIDO", text)
        text.encode("cp1252")

    def test_baseline_situation_block_is_rendered(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 120.0, 130.0, 140.0, 150.0, 160.0, 180.0]),
        ]
        text = format_baseline(compute_baseline(frames, horizon_bars=3))
        self.assertIn("seguindo (ou contrariando) o movimento anterior", text)
        self.assertIn("seguindo o movimento anterior", text)
        self.assertIn("com a direção de cada aposta", text)
        text.encode("cp1252")

    def test_baseline_text_is_rendered_and_printable(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [140.0] * 5),
        ]
        text = format_baseline(compute_baseline(frames))
        self.assertIn("LINHA DE BASE", text)
        self.assertIn("BUY", text)
        text.encode("cp1252")

    def test_baseline_is_empty_when_no_frame_has_a_ladder(self):
        text = format_baseline(compute_baseline([]))
        self.assertIn("Nenhum quadro", text)


class SessionComparisonTests(unittest.TestCase):
    def test_only_sessions_with_signals_are_listed(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 7, session="queda"),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 180.0], session="queda"),
            frame("2026-11-11T19:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7, session="alta"),
            frame("2026-11-11T19:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 120.0, 130.0, 140.0, 150.0, 160.0, 180.0], session="alta"),
        ]
        rows = compute_session_comparison(frames, horizon_bars=3)
        self.assertEqual([row["session"] for row in rows], ["queda"])
        self.assertEqual(rows[0]["signals"]["total"], 1)
        self.assertEqual(rows[0]["following"]["total"], 1)

    def test_session_signals_keep_the_direction(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 7, session="a"),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 180.0], session="a"),
            frame("2026-11-11T18:10:00+00:00", "C", "SELL", 0, [100.0] * 7, session="a"),
            frame("2026-11-11T18:13:00+00:00", "NO_TRADE", "SELL", 0,
                  [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 180.0], session="a"),
        ]
        rows = compute_session_comparison(frames, horizon_bars=3)
        split = rows[0]["signals_by_direction"]
        self.assertEqual(split["BUY"]["total"], 1)
        self.assertEqual(split["SELL"]["total"], 1)
        situations = rows[0]["signals_by_situation"]
        self.assertEqual({entry["direction"] for entry in situations}, {"BUY", "SELL"})
        self.assertTrue(all(entry["situation"] for entry in situations))

    def test_session_table_carries_the_flow_rule(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 120.0, 130.0, 140.0, 150.0, 160.0, 180.0], session="a"),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0, [140.0] * 7,
                  session="a"),
        ]
        rows = compute_session_comparison(frames, horizon_bars=3)
        self.assertEqual(rows[0]["flow"]["total"], 1)
        self.assertEqual(rows[0]["flow_by_direction"]["BUY"]["total"], 1)
        # A base cega da MESMA sessão é o único controle que separa regra de hora.
        self.assertEqual(rows[0]["base_by_direction"]["BUY"]["total"], 1)
        self.assertEqual(rows[0]["base_by_direction"]["SELL"]["total"], 1)

    def test_session_table_is_rendered(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 7, session="queda"),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 120.0, 140.0, 140.0, 140.0, 160.0, 180.0], session="queda"),
            frame("2026-11-11T18:06:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7,
                  session="queda"),
        ]
        text = format_session_comparison(compute_session_comparison(frames, horizon_bars=3))
        self.assertIn("POR BLOCO DE 60 MIN", text)
        self.assertIn("por situação e direção", text)
        self.assertIn("fluxo 2+ x base cega", text)
        self.assertIn("vs base", text)
        text.encode("cp1252")

    def test_flow_verdict_reads_the_stratified_edge(self):
        def row(flow_buy, base_buy):
            # O veredito usa o acerto na expiração: é ele que se compara com payout.
            return {
                "flow_by_direction": {"BUY": {"total": 100, "acerta": flow_buy}},
                "base_by_direction": {"BUY": {"total": 100, "acerta": base_buy}},
            }

        strong = _flow_edge_verdict([row(60, 30), row(60, 30), row(60, 30)])
        self.assertTrue(any("candidata a veredito" in line for line in strong))
        flat = _flow_edge_verdict([row(52, 50), row(52, 50), row(52, 50)])
        self.assertTrue(any("sem evidência" in line for line in flat))

    def test_flow_verdict_names_the_single_block_that_carries_it(self):
        def row(started, flow_wins, base_wins):
            return {
                "started_at_utc": started,
                "flow_by_direction": {"BUY": {"total": 40, "acerta": flow_wins}},
                "base_by_direction": {"BUY": {"total": 40, "acerta": base_wins}},
            }

        rows = [
            row("2026-11-12T10:00:00+00:00", 20, 20),
            row("2026-11-12T11:00:00+00:00", 20, 20),
            row("2026-11-12T12:00:00+00:00", 36, 20),
        ]
        verdict = _flow_edge_verdict(rows)
        # Duas horas neutras e uma boa: o número é dessa hora, e o relatório diz.
        self.assertTrue(any("falha o critério de 1.00" in line for line in verdict))
        self.assertTrue(any("12:00 BUY" in line for line in verdict))

    def test_flow_verdict_ignores_small_blocks(self):
        tiny = [
            {
                "flow_by_direction": {"BUY": {"total": 10, "acerta": 9}},
                "base_by_direction": {"BUY": {"total": 500, "acerta": 50}},
            }
            for _ in range(4)
        ]
        verdict = _flow_edge_verdict(tiny)
        # Sem bloco elegível o relatório não pode fingir que julgou.
        self.assertTrue(any("amostra insuficiente" in line for line in verdict))
        self.assertFalse(any("sem evidência" in line for line in verdict))

    def test_empty_session_list_says_so(self):
        self.assertIn("Nenhuma sessão", format_session_comparison([]))


class FlowRuleTests(unittest.TestCase):
    def flow_frame(self, at, colors, closes, session="s"):
        item = frame(at, "NO_TRADE", "BUY", 0, closes, session=session)
        item["price_ladder"]["colors"] = list(colors)
        return item

    def test_streak_of_same_colour_is_counted(self):
        # Duas verdes seguidas e uma vermelha: fluxo de alta com 2 velas.
        frames = [
            self.flow_frame(
                "2026-11-11T18:00:00+00:00",
                ["green", "green", "red", "red", "red"],
                [100.0, 100.0, 100.0, 140.0, 140.0, 140.0, 140.0],
            ),
            self.flow_frame(
                "2026-11-11T18:03:00+00:00",
                ["green", "green", "red", "red", "red"],
                [100.0, 140.0, 140.0, 140.0, 140.0, 140.0, 140.0],
            ),
        ]
        flow = compute_flow_rule(frames, horizon_bars=3)
        self.assertEqual(flow["mode"], "cores")
        self.assertEqual(flow["by_streak_direction"][2]["BUY"]["total"], 1)

    def test_white_candle_counts_as_bearish(self):
        frames = [
            self.flow_frame(
                "2026-11-11T18:00:00+00:00",
                ["white", "white", "white", "green", "green"],
                [100.0] * 7,
            ),
            self.flow_frame(
                "2026-11-11T18:03:00+00:00",
                ["white", "white", "white", "green", "green"],
                [180.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            ),
        ]
        flow = compute_flow_rule(frames, horizon_bars=3)
        self.assertEqual(flow["by_streak_direction"][3]["SELL"]["favorável"], 1)

    def closes_frames(self):
        # Quadro antigo, sem cor gravada: a leitura cai para os fechamentos.
        return [
            frame("2026-11-11T18:00:00+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 120.0, 130.0, 140.0, 150.0, 160.0, 180.0]),
            frame("2026-11-11T18:06:00+00:00", "NO_TRADE", "BUY", 0, [140.0] * 7),
        ]

    def test_frames_without_colours_fall_back_to_closes(self):
        flow = compute_flow_rule(self.closes_frames(), horizon_bars=3)
        self.assertEqual(flow["mode"], "fechamentos")
        self.assertEqual(flow["by_streak_direction"][4]["BUY"]["total"], 1)

    def test_one_bet_per_candle_keeps_the_last_frame_of_the_minute(self):
        frames = [
            frame("2026-11-11T18:00:05+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:00:35+00:00", "NO_TRADE", "BUY", 0, [110.0] * 7),
            frame("2026-11-11T18:00:55+00:00", "NO_TRADE", "BUY", 0, [120.0] * 7),
            frame("2026-11-11T18:01:05+00:00", "NO_TRADE", "BUY", 0, [130.0] * 7),
        ]
        bets = _one_per_bar(frames, 60)
        self.assertEqual(len(bets), 2)
        self.assertIn(120.0, [bet["price_ladder"]["closes_px"][0] for bet in bets])

    def test_repeated_frames_of_one_candle_are_not_counted_twice(self):
        # Três quadros do mesmo minuto: a regra de fluxo tem uma aposta, não três.
        frames = [
            frame("2026-11-11T18:00:05+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:00:35+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:00:55+00:00", "NO_TRADE", "BUY", 0, [100.0] * 7),
            frame("2026-11-11T18:02:00+00:00", "NO_TRADE", "BUY", 0,
                  [100.0, 120.0, 130.0, 140.0, 150.0, 160.0, 180.0]),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0, [140.0] * 7),
        ]
        flow = compute_flow_rule(frames, horizon_bars=1)
        total = sum(bucket["total"] for bucket in flow["by_streak"].values())
        self.assertLessEqual(total, 2)

    def test_breakeven_follows_the_informed_payout(self):
        # Payout informado pelo usuário: 85% a 90% no que ele opera.
        self.assertAlmostEqual(_breakeven(0.85), 0.5405, places=4)
        self.assertAlmostEqual(_breakeven(0.90), 0.5263, places=4)
        self.assertAlmostEqual(_expected_value(_breakeven(0.85), 0.85), 0.0, places=6)
        self.assertAlmostEqual(_expected_value(0.60, 0.85), 0.11, places=6)

    def test_flow_block_is_rendered(self):
        text = format_flow_rule(compute_flow_rule(self.closes_frames(), horizon_bars=3))
        self.assertIn("REGRA DE FLUXO", text)
        self.assertIn("Regra de 2+ velas seguidas", text)
        text.encode("cp1252")

    def test_settlement_counts_what_happened_without_a_threshold(self):
        flow = compute_flow_rule(self.closes_frames(), horizon_bars=3)
        settle = flow["settlement"]["todas"]
        self.assertEqual(
            settle["acerta"] + settle["empata"] + settle["erra"], settle["total"]
        )
        streaks = flow["by_streak"]
        self.assertEqual(
            settle["total"],
            sum(bucket["total"] for streak, bucket in streaks.items() if streak >= 2),
        )
        text = format_flow_rule(flow)
        self.assertIn("LIQUIDAÇÃO", text)
        self.assertIn("equilíbrio: 54.1%", text)
        self.assertIn("EV 85%", text)


class FormatTests(unittest.TestCase):
    def test_outcome_text_fits_the_windows_codepage(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [140.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [100.0, 140.0, 140.0, 140.0]),
        ]
        format_outcomes(compute_outcomes(frames)).encode("cp1252")

    def test_report_states_that_acerto_is_not_profit(self):
        text = format_outcomes(compute_outcomes([]))
        self.assertIn("sem payout", text)
        self.assertIn("54.1%", text)
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


class BankrollTests(unittest.TestCase):
    def test_win_then_loss_compounds_on_the_current_bankroll(self):
        from auto_trader_iq.bankroll import simulate

        result = simulate([True, False], bankroll=100.0, payout=1.0, stake_fraction=0.1)
        # 100 -> +10 -> 110 -> -11 -> 99
        self.assertAlmostEqual(result["final"], 99.0)
        self.assertAlmostEqual(result["max_drawdown"], -0.1)
        self.assertFalse(result["ruined"])

    def test_payout_of_eighty_five_percent_moves_the_balance_by_less(self):
        from auto_trader_iq.bankroll import simulate

        result = simulate([True], bankroll=100.0, payout=0.85, stake_fraction=0.1)
        self.assertAlmostEqual(result["final"], 108.5)

    def test_breakeven_matches_the_payout(self):
        from auto_trader_iq.bankroll import breakeven_rate

        self.assertAlmostEqual(breakeven_rate(0.85), 1 / 1.85)
        self.assertAlmostEqual(breakeven_rate(0.90), 1 / 1.90)

    def test_bootstrap_keeps_the_observed_bets_and_orders_percentiles(self):
        from auto_trader_iq.bankroll import bootstrap_by_block

        blocks = [[True, True, False], [True, False], [False, True, True]]
        result = bootstrap_by_block(
            blocks, bankroll=200.0, payout=0.85, stake_fraction=0.02, runs=200
        )
        self.assertLessEqual(result["final_p05"], result["final_p50"])
        self.assertLessEqual(result["final_p50"], result["final_p95"])
        # Queda é negativa: o "p95" aqui é o extremo ruim, então é o menor número.
        self.assertLessEqual(result["drawdown_p95"], result["drawdown_p50"])
        self.assertGreater(result["final_p50"], 0)

    def test_bankroll_section_says_it_is_not_a_forecast(self):
        from auto_trader_iq.grade_report import format_bankroll

        flow = {
            "sequence": [
                {"block": 0, "win": True},
                {"block": 0, "win": False},
                {"block": 1, "win": True},
            ]
        }
        lines = format_bankroll(flow, bankroll=200.0, payout=0.85, stake=0.02)
        text = "\n".join(lines)
        self.assertIn("não prevê", text)
        self.assertIn("apostas 3", text)
        self.assertIn("horas 2", text)

    def test_fixed_stake_does_not_shrink_with_the_bankroll(self):
        from auto_trader_iq.bankroll import simulate

        # R$ 12 sobre R$ 200: sete perdas seguidas quebram a banca, porque a
        # aposta não acompanha a banca para baixo.
        result = simulate(
            [False] * 17, bankroll=200.0, payout=0.86, stake_amount=12.0
        )
        self.assertTrue(result["ruined"])
        self.assertEqual(result["bets"], 17)
        self.assertAlmostEqual(result["final"], 0.0)


class BankrollLedgerTests(unittest.TestCase):
    def _entry(self, when, win):
        return {"when": when, "win": win, "direction": "BUY"}

    def test_day_stops_at_the_loss_limit_and_the_rest_is_not_bet(self):
        from auto_trader_iq.bankroll_ledger import StopRules, run_days

        entries = [self._entry("2026-11-12T14:00:00+00:00", False) for _ in range(12)]
        result = run_days(
            entries,
            bankroll=200.0,
            stake_amount=5.0,
            payout=0.86,
            rules=StopRules(stop_loss_fraction=0.10, stop_win_fraction=0.50),
        )
        day = result["days"][0]
        self.assertEqual(day["stop"], "limite de perda")
        # Perde 5 por aposta: 10% de 200 = 20, então quatro apostas fecham o dia.
        self.assertEqual(day["entries"], 4)
        self.assertEqual(day["blocked"], 8)
        self.assertAlmostEqual(day["end_balance"], 180.0)

    def test_day_stops_at_the_win_target(self):
        from auto_trader_iq.bankroll_ledger import StopRules, run_days

        entries = [self._entry("2026-11-12T14:00:00+00:00", True) for _ in range(10)]
        result = run_days(
            entries,
            bankroll=200.0,
            stake_amount=5.0,
            payout=0.86,
            rules=StopRules(stop_loss_fraction=0.50, stop_win_fraction=0.05),
        )
        day = result["days"][0]
        self.assertEqual(day["stop"], "meta de ganho")
        # 5% de 200 = 10 de lucro; cada acerto rende 4,30.
        self.assertEqual(day["entries"], 3)
        self.assertGreater(day["blocked"], 0)

    def test_the_bankroll_carries_over_to_the_next_day(self):
        from auto_trader_iq.bankroll_ledger import StopRules, run_days

        entries = [
            self._entry("2026-11-12T14:00:00+00:00", True),
            self._entry("2026-11-13T14:00:00+00:00", True),
        ]
        result = run_days(
            entries,
            bankroll=200.0,
            stake_amount=5.0,
            payout=0.86,
            rules=StopRules(stop_loss_fraction=0.20, stop_win_fraction=0.50),
        )
        first, second = result["days"]
        self.assertEqual(second["start_balance"], first["end_balance"])
        self.assertAlmostEqual(result["final"], 200.0 + 2 * 5 * 0.86)

    def test_without_money_to_bet_the_day_stops_as_broke(self):
        from auto_trader_iq.bankroll_ledger import StopRules, run_days

        entries = [self._entry("2026-11-12T14:00:00+00:00", False) for _ in range(50)]
        result = run_days(
            entries,
            bankroll=12.0,
            stake_amount=5.0,
            payout=0.86,
            rules=StopRules(stop_loss_fraction=10.0, stop_win_fraction=10.0),
        )
        self.assertEqual(result["days"][0]["stop"], "sem banca")
        self.assertEqual(result["days"][0]["entries"], 2)

    def test_ledger_section_shows_the_day_and_the_blocked_entries(self):
        from auto_trader_iq.grade_report import format_ledger

        flow = {
            "sequence": [
                {"when": "2026-11-12T14:00:00+00:00", "win": False},
                {"when": "2026-11-12T14:05:00+00:00", "win": False},
                {"when": "2026-11-12T14:10:00+00:00", "win": False},
                {"when": "2026-11-12T14:15:00+00:00", "win": True},
            ]
        }
        lines = format_ledger(
            flow,
            bankroll=200.0,
            stake_amount=5.0,
            stake_fraction=0.02,
            payout=0.86,
            stop_loss=0.05,
            stop_win=0.50,
        )
        text = "\n".join(lines)
        self.assertIn("BANCA POR DIA", text)
        self.assertIn("limite de perda", text)
        self.assertIn("travadas", text)

    def test_win_target_zero_means_no_win_stop(self):
        from auto_trader_iq.bankroll_ledger import StopRules, run_days

        entries = [self._entry("2026-11-12T14:00:00+00:00", True) for _ in range(10)]
        result = run_days(
            entries,
            bankroll=200.0,
            stake_amount=5.0,
            payout=0.86,
            rules=StopRules(stop_loss_fraction=0.50, stop_win_fraction=0.0),
        )
        day = result["days"][0]
        self.assertEqual(day["stop"], "nenhum")
        self.assertEqual(day["entries"], 10)
        self.assertEqual(day["blocked"], 0)

    def test_streak_table_shows_the_margin_of_small_cells(self):
        from auto_trader_iq.grade_report import format_flow_rule

        flow = {
            "mode": "cores",
            "window": 5,
            "by_streak": {
                4: {
                    "total": 31,
                    "acerta": 23,
                    "favorável": 23,
                    "neutra": 3,
                    "adversa": 5,
                    "median_move_units": 0.6,
                }
            },
            "by_streak_direction": {},
            "settlement": {},
        }
        text = format_flow_rule(flow)
        # 74% com 31 casos não é uma taxa: o relatório mostra o quanto isso oscila.
        self.assertIn("74%", text)
        self.assertIn("+/- 15pp", text)

    def test_entries_spanning_more_than_a_day_warn_about_the_day_bucket(self):
        from auto_trader_iq.bankroll_ledger import StopRules, run_days

        entries = [
            self._entry("2026-11-11T20:48:00+00:00", True),
            self._entry("2026-11-12T20:48:00+00:00", True),
        ]
        result = run_days(
            entries,
            bankroll=200.0,
            stake_amount=5.0,
            payout=0.86,
            rules=StopRules(stop_loss_fraction=0.25, stop_win_fraction=0.0),
        )
        # Dois dias de calendário: o balde funcionou e não há aviso.
        self.assertEqual(len(result["days"]), 2)
        self.assertFalse(result["suspect_day_bucket"])
        self.assertGreaterEqual(result["span_hours"], 24)

    def test_ledger_states_the_period_it_booked(self):
        from auto_trader_iq.grade_report import format_ledger

        flow = {
            "sequence": [
                {"when": "2026-11-12T08:00:00+00:00", "win": True, "direction": "BUY"},
                {"when": "2026-11-13T00:37:00+00:00", "win": False, "direction": "SELL"},
            ]
        }
        text = "\n".join(
            format_ledger(
                flow,
                bankroll=200.0,
                stake_amount=5.0,
                stake_fraction=0.02,
                payout=0.86,
                stop_loss=0.25,
                stop_win=0.0,
                detail=1,
            )
        )
        self.assertIn("período:", text)
        self.assertIn("17 h", text)

    def test_ledger_shows_hours_in_local_time(self):
        from auto_trader_iq.grade_report import format_ledger

        flow = {
            "sequence": [
                {"when": "2026-11-12T08:00:00+00:00", "win": True, "direction": "BUY"},
                {"when": "2026-11-12T08:05:00+00:00", "win": True, "direction": "BUY"},
            ]
        }
        text = "\n".join(
            format_ledger(
                flow,
                bankroll=200.0,
                stake_amount=5.0,
                stake_fraction=0.02,
                payout=0.86,
                stop_loss=0.25,
                stop_win=0.0,
                detail=2,
            )
        )
        self.assertIn("hora local", text)
        self.assertNotIn("08:05:00", text)

    def test_signal_sequence_comes_in_the_order_it_happened(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [140.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [100.0, 140.0, 140.0, 140.0]),
            frame("2026-11-11T18:05:00+00:00", "A", "SELL", 0, [100.0] * 5),
            frame("2026-11-11T18:08:00+00:00", "A", "SELL", 0, [180.0, 100.0, 100.0, 100.0]),
        ]
        sequence = compute_outcomes(frames)["sequence"]
        self.assertEqual(len(sequence), 2)
        self.assertEqual([item["when"] for item in sequence],
                         sorted(item["when"] for item in sequence))
        self.assertEqual([item["direction"] for item in sequence], ["BUY", "SELL"])
        self.assertTrue(all(item["win"] for item in sequence))


class DayStopTests(unittest.TestCase):
    def test_day_stop_vetoes_the_rest_of_the_day(self):
        from auto_trader_iq.bankroll_ledger import StopRules, day_stop

        entries = [
            {"when": "2026-11-12T10:00:00+00:00", "win": False},
            {"when": "2026-11-12T10:05:00+00:00", "win": False},
            {"when": "2026-11-12T10:10:00+00:00", "win": True},
        ]
        state = day_stop(
            entries,
            bankroll=200.0,
            stake_amount=50.0,
            rules=StopRules(stop_loss_fraction=0.25, stop_win_fraction=0.0),
            now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
        )
        self.assertFalse(state["allowed"])
        self.assertEqual(state["stop"], "limite de perda")
        # Uma perda de 50 numa banca de 200 já bate o limite: a terceira entrada
        # não é apostada, e o app diria isso antes de mostrar o sinal.
        self.assertEqual(state["entries"], 1)
        self.assertEqual(state["blocked"], 2)

    def test_day_stop_starts_clean_on_the_next_day(self):
        from auto_trader_iq.bankroll_ledger import StopRules, day_stop

        entries = [{"when": "2026-11-12T10:00:00+00:00", "win": False}]
        state = day_stop(
            entries,
            bankroll=200.0,
            stake_amount=50.0,
            rules=StopRules(stop_loss_fraction=0.25, stop_win_fraction=0.0),
            now=datetime(2026, 11, 13, 9, tzinfo=timezone.utc),
        )
        self.assertTrue(state["allowed"])
        self.assertEqual(state["entries"], 0)

    def test_day_stop_never_blocks_with_the_win_target_off(self):
        from auto_trader_iq.bankroll_ledger import StopRules, day_stop

        entries = [{"when": "2026-11-12T10:00:00+00:00", "win": True}] * 20
        state = day_stop(
            entries,
            bankroll=200.0,
            stake_amount=5.0,
            rules=StopRules(stop_loss_fraction=0.25, stop_win_fraction=0.0),
            now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
        )
        self.assertTrue(state["allowed"])
        self.assertEqual(state["blocked"], 0)

    def test_ledger_names_the_sequence_and_the_floor_of_the_day(self):
        from auto_trader_iq.grade_report import format_ledger

        flow = {
            "sequence": [
                {"when": "2026-11-12T10:00:00+00:00", "win": False, "direction": "BUY"},
                {"when": "2026-11-12T10:05:00+00:00", "win": True, "direction": "BUY"},
            ]
        }
        text = "\n".join(
            format_ledger(
                flow,
                bankroll=200.0,
                stake_amount=5.0,
                stake_fraction=0.02,
                payout=0.86,
                stop_loss=0.25,
                stop_win=0.0,
                detail=0,
                label="regra de fluxo",
            )
        )
        self.assertIn("sequência: regra de fluxo", text)
        self.assertIn("pior", text)
        # Uma perda de cinco em 200 é -2,5%: é essa a distância que importa.
        self.assertIn("-3%", text)

    def test_same_candle_seen_by_two_sessions_counts_once(self):
        # App reiniciado no meio: a sessão nova vê a mesma vela que a antiga.
        # Sem deduplicar por relógio, a mesma aposta entrava duas vezes na banca.
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [140.0] * 5, session="s1"),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [100.0, 140.0, 140.0, 140.0],
                  session="s1"),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [100.0, 140.0, 140.0, 140.0],
                  session="s2"),
        ]
        result = compute_outcomes(frames)
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["repeated_across_sessions"], 1)
        self.assertEqual(len(result["sequence"]), 1)

    def test_ledger_says_when_the_stop_sits_inside_the_day_noise(self):
        from auto_trader_iq.grade_report import format_ledger

        # 300 apostas de 5 numa banca de 200: um desvio-padrão do dia passa de 40%,
        # então um stop de 25% corta por sorte, não por falha. O relatório diz isso.
        sequence = [
            {"when": f"2026-11-12T{h:02d}:{m:02d}:00+00:00",
             "win": (h + m) % 2 == 0, "direction": "BUY"}
            for h in range(6, 21) for m in range(0, 60, 3)
        ]
        text = "\n".join(
            format_ledger(
                {"sequence": sequence},
                bankroll=200.0,
                stake_amount=5.0,
                stake_fraction=0.02,
                payout=0.86,
                stop_loss=0.25,
                stop_win=0.0,
                detail=0,
            )
        )
        self.assertIn("ruído do dia", text)
        self.assertIn("DENTRO do ruído", text)

    def test_two_bets_in_the_same_minute_show_the_candle_they_bet(self):
        # Dois quadros do mesmo minuto apostando velas diferentes (idades 1 e 0):
        # a tabela mostrava a hora da leitura nas duas e parecia aposta dobrada.
        fall = [100.0, 140.0, 140.0, 140.0, 140.0, 140.0]
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 1, [140.0] * 6),
            frame("2026-11-11T18:00:30+00:00", "A", "BUY", 0, [140.0] * 6),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, fall),
            frame("2026-11-11T18:03:30+00:00", "A", "BUY", 0, fall),
        ]
        sequence = compute_outcomes(frames, bar_seconds=60)["sequence"]
        stamps = [item["when"] for item in sequence]
        self.assertEqual(len(stamps), 2, stamps)
        self.assertEqual(len(set(stamps)), 2, stamps)
        # A leitura dos dois foi no mesmo minuto; a aposta, não.
        self.assertEqual({item["read_at"][:16] for item in sequence},
                         {"2026-11-11T18:00"})

    def test_outcomes_say_which_threshold_version_produced_them(self):
        # Dois classificadores diferentes no mesmo banco: somar os dois e chamar
        # o resultado de "o app acerta 55%" mistura duas réguas.
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [140.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [100.0, 140.0, 140.0, 140.0]),
            frame("2026-11-11T18:10:00+00:00", "A", "BUY", 0, [140.0] * 5),
            frame("2026-11-11T18:13:00+00:00", "A", "BUY", 0, [180.0, 140.0, 140.0, 140.0]),
        ]
        frames[0]["criteria_hash"] = "cdde517363f504c8"
        frames[1]["criteria_hash"] = "cdde517363f504c8"
        frames[2]["criteria_hash"] = "29e7f80bf3066e89"
        frames[3]["criteria_hash"] = "29e7f80bf3066e89"
        result = compute_outcomes(frames)
        by_hash = result["by_criteria_hash"]
        self.assertEqual(set(by_hash), {"cdde517363f504c8", "29e7f80bf3066e89"})
        self.assertEqual(sum(bucket["n"] for bucket in by_hash.values()), 2)

    def test_flow_verdict_says_how_much_capture_is_missing(self):
        from auto_trader_iq.grade_report import _flow_edge_verdict

        # Vantagem pequena e z baixo: o relatório tem de dizer quanto tempo de
        # gráfico falta, não só quantas apostas.
        rows = [
            {
                "started_at_utc": f"2026-11-12T{9 + i:02d}:00:00+00:00",
                "flow_by_direction": {
                    "BUY": {"total": 22, "acerta": 12},
                    "SELL": {"total": 23, "acerta": 12},
                },
                "base_by_direction": {
                    "BUY": {"total": 40, "acerta": 20},
                    "SELL": {"total": 40, "acerta": 20},
                },
            }
            for i in range(8)
        ]
        text = "\n".join(_flow_edge_verdict(rows))
        self.assertIn("Faltam ~", text)
        self.assertIn("h de captura", text)

    def test_stake_ladder_shows_when_the_stop_stops_being_noise(self):
        from auto_trader_iq.grade_report import format_stake_ladder

        # Mesmo stream, três tamanhos: só em 0,5% o stop de 25% fica fora do
        # ruído do dia. É essa a decisão que a tabela existe para mostrar.
        sequence = [
            {"when": f"2026-11-12T{h:02d}:{m:02d}:00+00:00",
             "win": (h + m) % 5 < 3, "direction": "BUY"}
            for h in range(6, 18) for m in range(0, 60, 5)
        ]
        lines = format_stake_ladder(
            {"sequence": sequence}, bankroll=200.0, payout=0.86, stop_loss=0.25
        )
        text = "\n".join(lines)
        self.assertIn("2.5% = R$  5.00", text)
        self.assertIn("1.0% = R$  2.00", text)
        self.assertIn("0.5% = R$  1.00", text)
        self.assertIn("1.0σ", text)
        self.assertIn("4.8σ", text)
        # Cada linha é o mesmo stream com aposta menor: o final cai e o stop
        # deixa de ser ruído. Sem esse contraste a tabela não diria nada.
        self.assertIn("±      26%", text)
