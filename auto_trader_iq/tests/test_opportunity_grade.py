import unittest
from types import SimpleNamespace

from auto_trader_iq.opportunity_grade import (
    DEFAULT_CRITERIA,
    GRADE_CRITERIA_VERSION,
    GRADE_GOOD,
    GRADE_IMMEDIATE,
    GRADE_NO_TRADE,
    GRADE_RISKY,
    GradeCriteria,
    SignalFeatures,
    migrate_criteria,
    build_features,
    grade_opportunity,
    validate_grade_criteria,
)


def features(**overrides):
    base = dict(
        direction="BUY",
        age_bars=0,
        body=50.0,
        candle_range=80.0,
        upper_wick=10.0,
        lower_wick=20.0,
        body_vs_median=1.0,
        close_from_extreme=0.6,
        distance_to_level=0.55,
        context_regime="flow",
        context_direction="BUY",
    )
    base.update(overrides)
    return SignalFeatures(**base)


class CriteriaValidationTests(unittest.TestCase):
    def test_default_criteria_are_valid(self):
        self.assertEqual(validate_grade_criteria(DEFAULT_CRITERIA), [])

    def test_fresh_age_above_max_age_is_rejected(self):
        problems = validate_grade_criteria(
            GradeCriteria(**{**DEFAULT_CRITERIA.as_dict(), "fresh_age_bars": 3})
        )
        self.assertTrue(any("fresh_age_bars" in problem for problem in problems))

    def test_inverted_body_limits_are_rejected(self):
        problems = validate_grade_criteria(
            GradeCriteria(
                **{
                    **DEFAULT_CRITERIA.as_dict(),
                    "max_body_vs_median_a": 3.0,
                    "max_body_vs_median_b": 2.0,
                }
            )
        )
        self.assertTrue(any("max_body_vs_median_a" in problem for problem in problems))

    def test_undefined_criteria_block_grading(self):
        grade = grade_opportunity(features(), GradeCriteria())
        self.assertEqual(grade.code, "CRITERIA_UNDEFINED")


class MigrationTests(unittest.TestCase):
    def test_legacy_default_freshness_is_corrected(self):
        legacy = GradeCriteria(**{**DEFAULT_CRITERIA.as_dict(), "fresh_age_bars": 0})
        migrated, changed = migrate_criteria(legacy, None)
        self.assertTrue(changed)
        self.assertEqual(migrated.fresh_age_bars, 1)

    def test_explicit_non_default_freshness_is_preserved(self):
        chosen = GradeCriteria(**{**DEFAULT_CRITERIA.as_dict(), "fresh_age_bars": 2})
        migrated, changed = migrate_criteria(chosen, 1)
        self.assertFalse(changed)
        self.assertEqual(migrated.fresh_age_bars, 2)

    def test_current_version_is_untouched(self):
        legacy = GradeCriteria(**{**DEFAULT_CRITERIA.as_dict(), "fresh_age_bars": 0})
        migrated, changed = migrate_criteria(legacy, GRADE_CRITERIA_VERSION)
        self.assertFalse(changed)
        self.assertEqual(migrated.fresh_age_bars, 0)

    def test_other_fields_survive_migration(self):
        legacy = GradeCriteria(**{
            **DEFAULT_CRITERIA.as_dict(),
            "fresh_age_bars": 0,
            "min_distance_to_level": 0.22,
        })
        migrated, _changed = migrate_criteria(legacy, 1)
        self.assertEqual(migrated.min_distance_to_level, 0.22)


class GradeTests(unittest.TestCase):
    def grade(self, **overrides):
        return grade_opportunity(features(**overrides), DEFAULT_CRITERIA)

    def test_fresh_signal_with_normal_body_is_immediate(self):
        self.assertEqual(self.grade(age_bars=0).code, GRADE_IMMEDIATE)

    def test_freshness_default_matches_measured_screen_behaviour(self):
        self.assertEqual(DEFAULT_CRITERIA.fresh_age_bars, 1)

    def test_label_on_last_closed_candle_is_still_immediate(self):
        self.assertEqual(self.grade(age_bars=1).code, GRADE_IMMEDIATE)

    def test_label_two_candles_old_drops_to_good(self):
        self.assertEqual(self.grade(age_bars=2).code, GRADE_GOOD)

    def test_label_beyond_limit_is_no_trade(self):
        self.assertEqual(self.grade(age_bars=3).code, GRADE_NO_TRADE)

    def test_last_closed_candle_has_its_own_reason_text(self):
        grade = self.grade(age_bars=1, body_vs_median=1.0)
        self.assertEqual(grade.code, GRADE_IMMEDIATE)
        self.assertIn("vela fechada mais recente", grade.reasons[0])

    def test_lateral_market_is_no_trade(self):
        self.assertEqual(
            self.grade(age_bars=0, context_regime="lateral").code, GRADE_NO_TRADE
        )

    def test_stretched_body_is_risky(self):
        grade = self.grade(age_bars=0, body_vs_median=2.6)
        self.assertEqual(grade.code, GRADE_RISKY)
        self.assertIn("esticado", grade.reasons[0])

    def test_body_above_ideal_band_is_not_immediate(self):
        grade = self.grade(age_bars=0, body_vs_median=1.8)
        self.assertEqual(grade.code, GRADE_GOOD)
        self.assertIn("acima do ideal", grade.reasons[0])

    def test_weak_body_is_only_good(self):
        self.assertEqual(self.grade(age_bars=0, body_vs_median=0.2).code, GRADE_GOOD)

    def test_price_near_blocking_level_is_risky(self):
        grade = self.grade(age_bars=0, distance_to_level=0.08)
        self.assertEqual(grade.code, GRADE_RISKY)
        self.assertIn("nível contrário", grade.reasons[0])

    def test_close_at_own_extreme_is_risky(self):
        self.assertEqual(self.grade(age_bars=0, close_from_extreme=0.05).code, GRADE_RISKY)

    def test_signal_against_context_is_blocked(self):
        # 154 sinais assim acertaram 4% a uma vela: bloqueio, não nota de risco.
        grade = self.grade(age_bars=0, context_direction="SELL")
        self.assertEqual(grade.code, GRADE_NO_TRADE)
        self.assertIn("contra contexto", grade.reasons[0])

    def test_signal_with_context_still_graded(self):
        grade = self.grade(age_bars=0, context_direction="BUY")
        self.assertNotEqual(grade.code, GRADE_NO_TRADE)

    def test_unknown_candle_is_no_trade(self):
        self.assertEqual(
            grade_opportunity(None, DEFAULT_CRITERIA).code, GRADE_NO_TRADE
        )

    def test_unmeasured_metrics_are_declared(self):
        grade = grade_opportunity(features(), DEFAULT_CRITERIA)
        self.assertIn("rsi20", grade.unmeasured)
        self.assertIn("macd_histograma", grade.unmeasured)
        self.assertIn("distancia_ema20", grade.unmeasured)

    def test_display_text_never_hides_reasons(self):
        text = self.grade(distance_to_level=0.05).display_text
        self.assertIn("NÃO", text.upper() + "NÃO")  # rótulo legível
        self.assertIn("nível contrário", text)


class BuildFeaturesTests(unittest.TestCase):
    @staticmethod
    def candle(center_x, body=(110, 130), high=100, low=140, direction="BUY"):
        open_y, close_y = (low, high) if direction == "BUY" else (high, low)
        return SimpleNamespace(
            center_x=center_x,
            high=high,
            low=low,
            body_top=body[0],
            body_bottom=body[1],
            open_y=open_y,
            close_y=close_y,
            upper_wick=body[0] - high,
            lower_wick=low - body[1],
        )

    def bars(self, centers):
        return [SimpleNamespace(center_x=center) for center in centers]

    def candidate(self, center):
        return SimpleNamespace(left=center - 20, width=40)

    def test_setup_candle_is_the_one_before_the_label(self):
        # setup estreito em 100, vela da seta gigante em 200: medir a seta
        # descreveria o que já aconteceu depois do sinal.
        candles = [
            self.candle(0),
            self.candle(100, body=(120, 125)),
            self.candle(200, body=(100, 140)),
        ]
        built = build_features(
            self.candidate(200),
            self.bars([0, 100, 200]),
            candles,
            direction="BUY",
            age_bars=1,
            context_regime="flow",
            context_direction="BUY",
        )
        self.assertIsNotNone(built)
        self.assertEqual(built.body, 5.0)

    def test_label_on_the_first_bar_has_no_setup(self):
        built = build_features(
            self.candidate(0),
            self.bars([0, 100]),
            [self.candle(0), self.candle(100)],
            direction="BUY",
            age_bars=0,
            context_regime="flow",
            context_direction="BUY",
        )
        self.assertIsNone(built)

    def test_entry_price_comes_from_the_label_candle(self):
        # setup fechado no fundo (close 140), entrada em 120 a meio caminho do topo.
        def explicit(center, body_top, body_bottom, high, low, close_y):
            return SimpleNamespace(
                center_x=center,
                high=high,
                low=low,
                body_top=body_top,
                body_bottom=body_bottom,
                open_y=low,
                close_y=close_y,
                upper_wick=body_top - high,
                lower_wick=low - body_bottom,
            )

        candles = [
            explicit(100, 120, 125, 120, 140, 140),
            explicit(200, 110, 130, 100, 140, 120),
        ]
        built = build_features(
            self.candidate(200),
            self.bars([100, 200]),
            candles,
            direction="BUY",
            age_bars=1,
            context_regime="flow",
            context_direction="BUY",
        )
        self.assertIsNotNone(built)
        self.assertAlmostEqual(built.close_from_extreme, 1.0)
        self.assertAlmostEqual(built.distance_to_level, 0.5)

    def test_features_use_the_nearest_candle(self):
        candles = [self.candle(0), self.candle(100), self.candle(200)]
        built = build_features(
            self.candidate(200),
            self.bars([0, 100, 200]),
            candles,
            direction="BUY",
            age_bars=1,
            context_regime="flow",
            context_direction="BUY",
        )
        self.assertIsNotNone(built)
        self.assertEqual(built.body, 20.0)
        self.assertEqual(built.candle_range, 40.0)
        self.assertAlmostEqual(built.close_from_extreme, 0.0)

    def test_candle_matched_with_small_offset(self):
        candles = [self.candle(0), self.candle(104), self.candle(200)]
        built = build_features(
            self.candidate(200),
            self.bars([0, 100, 200]),
            candles,
            direction="BUY",
            age_bars=1,
            context_regime="flow",
            context_direction="BUY",
        )
        self.assertIsNotNone(built)
        self.assertEqual(built.body, 20.0)

    def test_body_median_ignores_candles_to_the_right(self):
        # três velas pequenas à esquerda, uma grande à direita: a mediana do corpo
        # da vela analisada não pode ser contaminada pela vela futura.
        candles = [self.candle(0, body=(100, 110)), self.candle(100, body=(100, 110))]
        candles.append(self.candle(200, body=(100, 200)))
        built = build_features(
            self.candidate(100),
            self.bars([0, 100, 200]),
            candles,
            direction="BUY",
            age_bars=1,
            context_regime="flow",
            context_direction="BUY",
        )
        self.assertIsNotNone(built)
        self.assertAlmostEqual(built.body_vs_median, 1.0)

    def test_unknown_candle_returns_none(self):
        built = build_features(
            self.candidate(900),
            self.bars([900]),
            [self.candle(0)],
            direction="BUY",
            age_bars=0,
            context_regime=None,
            context_direction=None,
        )
        self.assertIsNone(built)

    def test_body_relative_to_recent_median(self):
        # nove velas pequenas e uma grande na posição de setup, com a seta depois.
        centers = [index * 100 for index in range(9)]
        candles = [self.candle(center, body=(100, 110)) for center in centers]
        candles.append(self.candle(900, body=(100, 150)))
        candles.append(self.candle(1000, body=(100, 110)))
        built = build_features(
            self.candidate(1000),
            self.bars(centers + [900, 1000]),
            candles,
            direction="BUY",
            age_bars=1,
            context_regime="flow",
            context_direction="BUY",
        )
        self.assertIsNotNone(built)
        self.assertGreater(built.body_vs_median, 2.0)


if __name__ == "__main__":
    unittest.main()
