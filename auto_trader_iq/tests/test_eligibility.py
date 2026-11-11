import unittest

from auto_trader_iq.eligibility import (
    BALANCED_CRITERIA,
    CONSERVATIVE_CRITERIA,
    PROFILES,
    SELECTIVE_CRITERIA,
    EligibilityCriteria,
    evaluate_eligibility,
    validate_criteria,
)

OCR_FLOOR = 70.0

COMPLETE = dict(
    min_confidence=80.0,
    allowed_directions=("BUY", "SELL"),
    require_calibrated_palette=True,
    min_bars=8,
    max_label_age_bars=1,
    require_directional_context=True,
    require_context_alignment=False,
)

OBSERVATION = {
    "confidence": 91.0,
    "direction": "SELL",
    "palette_calibrated": True,
    "bar_count": 12,
    "label_age_bars": 0,
    "context_direction": "SELL",
}


class FailClosedTests(unittest.TestCase):
    def test_undefined_criteria_never_approve(self):
        decision = evaluate_eligibility(EligibilityCriteria(), OBSERVATION)
        self.assertEqual(decision.code, "CRITERIA_UNDEFINED")
        self.assertFalse(decision.eligible)
        self.assertIn("critérios não definidos", decision.reasons[0])

    def test_partial_criteria_list_every_missing_field(self):
        decision = evaluate_eligibility(
            EligibilityCriteria(min_confidence=70.0), OBSERVATION
        )
        self.assertEqual(decision.code, "CRITERIA_UNDEFINED")
        for field in ("allowed_directions", "max_label_age_bars", "require_context_alignment"):
            self.assertIn(field, decision.reasons[0])

    def test_zero_is_a_real_threshold_not_a_default(self):
        criteria = EligibilityCriteria(**{**COMPLETE, "min_confidence": 0.0})
        self.assertNotIn("min_confidence", criteria.missing_fields())


class ValidationTests(unittest.TestCase):
    def problems(self, **overrides):
        base = dict(COMPLETE)
        base.update(overrides)
        return validate_criteria(EligibilityCriteria(**base), ocr_floor=OCR_FLOOR)

    def test_balanced_profile_is_valid(self):
        self.assertEqual(validate_criteria(BALANCED_CRITERIA, ocr_floor=OCR_FLOOR), [])

    def test_all_profiles_are_valid(self):
        for name, criteria in PROFILES.items():
            with self.subTest(profile=name):
                self.assertEqual(validate_criteria(criteria, ocr_floor=OCR_FLOOR), [])

    def test_threshold_below_ocr_floor_is_rejected_as_ineffective(self):
        problems = self.problems(min_confidence=60.0)
        self.assertTrue(any("não filtraria nada" in problem for problem in problems))

    def test_min_bars_below_context_floor_is_rejected(self):
        problems = self.problems(min_bars=4)
        self.assertTrue(any("waiting" in problem for problem in problems))

    def test_label_age_above_structural_limit_is_rejected(self):
        problems = self.problems(max_label_age_bars=3)
        self.assertTrue(any("contradiz o filtro" in problem for problem in problems))

    def test_alignment_without_directional_requirement_is_contradictory(self):
        problems = self.problems(
            require_context_alignment=True, require_directional_context=False
        )
        self.assertTrue(any("require_directional_context" in problem for problem in problems))

    def test_directional_context_without_calibrated_palette_is_contradictory(self):
        problems = self.problems(
            require_directional_context=True, require_calibrated_palette=False
        )
        self.assertTrue(any("contraditório" in problem for problem in problems))

    def test_unknown_direction_is_rejected(self):
        problems = self.problems(allowed_directions=("BUY", "HOLD"))
        self.assertTrue(any("inválidas" in problem for problem in problems))

    def test_empty_directions_are_rejected(self):
        problems = self.problems(allowed_directions=())
        self.assertTrue(any("vazio" in problem for problem in problems))

    def test_boolean_fields_reject_strings(self):
        problems = self.problems(require_calibrated_palette="sim")
        self.assertTrue(any("booleano" in problem for problem in problems))


class SerializationTests(unittest.TestCase):
    def test_round_trip_preserves_values_and_hash(self):
        restored = EligibilityCriteria.from_dict(BALANCED_CRITERIA.as_dict())
        self.assertEqual(restored, BALANCED_CRITERIA)
        self.assertEqual(restored.criteria_hash(), BALANCED_CRITERIA.criteria_hash())

    def test_hash_is_stable_and_differs_between_profiles(self):
        hashes = {
            criteria.criteria_hash()
            for criteria in (
                CONSERVATIVE_CRITERIA,
                BALANCED_CRITERIA,
                SELECTIVE_CRITERIA,
            )
        }
        self.assertEqual(len(hashes), 3)
        self.assertEqual(
            BALANCED_CRITERIA.criteria_hash(), BALANCED_CRITERIA.criteria_hash()
        )

    def test_unknown_key_is_rejected(self):
        payload = BALANCED_CRITERIA.as_dict()
        payload["min_confianca"] = 90
        with self.assertRaises(ValueError):
            EligibilityCriteria.from_dict(payload)

    def test_directions_accepts_list_from_json(self):
        payload = BALANCED_CRITERIA.as_dict()
        payload["allowed_directions"] = ["BUY", "SELL"]
        self.assertEqual(EligibilityCriteria.from_dict(payload), BALANCED_CRITERIA)


class EligibilityRuleTests(unittest.TestCase):
    def test_complete_criteria_and_matching_observation_is_eligible_for_review(self):
        decision = evaluate_eligibility(EligibilityCriteria(**COMPLETE), OBSERVATION)
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.code, "ELIGIBLE_FOR_REVIEW")
        self.assertIn("revisão humana", decision.display_text)
        self.assertEqual(decision.criteria_hash, EligibilityCriteria(**COMPLETE).criteria_hash())

    def test_low_confidence_blocks(self):
        decision = evaluate_eligibility(
            EligibilityCriteria(**COMPLETE), {**OBSERVATION, "confidence": 55.0}
        )
        self.assertFalse(decision.eligible)
        self.assertIn("abaixo do mínimo", decision.reasons[0])

    def test_uncalibrated_palette_blocks_when_required(self):
        decision = evaluate_eligibility(
            EligibilityCriteria(**COMPLETE), {**OBSERVATION, "palette_calibrated": False}
        )
        self.assertFalse(decision.eligible)
        self.assertIn("paleta", decision.reasons[0])

    def test_label_too_old_blocks(self):
        decision = evaluate_eligibility(
            EligibilityCriteria(**COMPLETE), {**OBSERVATION, "label_age_bars": 3}
        )
        self.assertFalse(decision.eligible)
        self.assertIn("acima do limite", decision.reasons[0])

    def test_missing_measurement_is_not_assumed_ok(self):
        observation = dict(OBSERVATION)
        observation.pop("label_age_bars")
        decision = evaluate_eligibility(EligibilityCriteria(**COMPLETE), observation)
        self.assertFalse(decision.eligible)
        self.assertIn("indisponível", decision.reasons[0])

    def test_context_without_direction_blocks_when_required(self):
        decision = evaluate_eligibility(
            EligibilityCriteria(**COMPLETE), {**OBSERVATION, "context_direction": None}
        )
        self.assertFalse(decision.eligible)
        self.assertIn("sem direção", decision.reasons[0])

    def test_alignment_blocks_counter_trend_signal(self):
        criteria = EligibilityCriteria(**{**COMPLETE, "require_context_alignment": True})
        decision = evaluate_eligibility(
            criteria, {**OBSERVATION, "context_direction": "BUY"}
        )
        self.assertFalse(decision.eligible)
        self.assertIn("não confirma", decision.reasons[0])

    def test_balanced_profile_accepts_directional_context_without_alignment(self):
        observation = {**OBSERVATION, "context_direction": "BUY"}
        decision = evaluate_eligibility(BALANCED_CRITERIA, observation)
        self.assertTrue(decision.eligible)


if __name__ == "__main__":
    unittest.main()
