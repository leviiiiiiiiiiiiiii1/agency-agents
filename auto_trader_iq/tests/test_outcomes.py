import unittest

from auto_trader_iq.grade_report import (
    ADVERSE,
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

    def test_session_table_is_rendered(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [100.0] * 7, session="queda"),
            frame("2026-11-11T18:03:00+00:00", "NO_TRADE", "BUY", 0,
                  [140.0, 140.0, 140.0, 100.0, 100.0, 100.0, 180.0], session="queda"),
        ]
        text = format_session_comparison(compute_session_comparison(frames, horizon_bars=3))
        self.assertIn("POR SESSÃO", text)
        self.assertIn("por situação e direção", text)
        text.encode("cp1252")

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

    def test_flow_block_is_rendered(self):
        text = format_flow_rule(compute_flow_rule(self.closes_frames(), horizon_bars=3))
        self.assertIn("REGRA DE FLUXO", text)
        self.assertIn("Regra de 2+ velas seguidas", text)
        text.encode("cp1252")


class FormatTests(unittest.TestCase):
    def test_outcome_text_fits_the_windows_codepage(self):
        frames = [
            frame("2026-11-11T18:00:00+00:00", "A", "BUY", 0, [140.0] * 5),
            frame("2026-11-11T18:03:00+00:00", "A", "BUY", 0, [100.0, 140.0, 140.0, 140.0]),
        ]
        format_outcomes(compute_outcomes(frames)).encode("cp1252")

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
