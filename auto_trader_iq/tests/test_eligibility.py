import unittest

from auto_trader_iq.eligibility import (
    EligibilityCriteria,
    evaluate_eligibility,
)

COMPLETE = dict(
    min_confidence=70.0,
    allowed_directions=("BUY", "SELL"),
    require_calibrated_palette=True,
    min_bars=6,
    max_label_age_bars=1,
    required_context_direction="SELL",
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
        for field in (
            "allowed_directions",
            "max_label_age_bars",
            "required_context_direction",
        ):
            self.assertIn(field, decision.reasons[0])

    def test_zero_is_a_real_threshold_not_a_default(self):
        criteria = EligibilityCriteria(**{**COMPLETE, "min_confidence": 0.0})
        self.assertNotIn("min_confidence", criteria.missing_fields())


class EligibilityRuleTests(unittest.TestCase):
    def test_complete_criteria_and_matching_observation_is_eligible_for_review(self):
        decision = evaluate_eligibility(EligibilityCriteria(**COMPLETE), OBSERVATION)
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.code, "ELIGIBLE_FOR_REVIEW")
        self.assertIn("revisão humana", decision.display_text)

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

    def test_context_mismatch_blocks(self):
        decision = evaluate_eligibility(
            EligibilityCriteria(**COMPLETE), {**OBSERVATION, "context_direction": "BUY"}
        )
        self.assertFalse(decision.eligible)
        self.assertIn("difere do exigido", decision.reasons[0])


if __name__ == "__main__":
    unittest.main()
