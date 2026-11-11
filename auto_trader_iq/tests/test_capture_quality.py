import unittest

from auto_trader_iq.capture_quality import classify_frame_rejection


class FrameRejectionTests(unittest.TestCase):
    def test_fresh_frame_with_valid_quality_is_accepted(self):
        self.assertIsNone(
            classify_frame_rejection(0.9, max_age_seconds=1.5, quality_fresh=True)
        )

    def test_late_frame_is_reported_as_stale(self):
        rejection = classify_frame_rejection(2.1, max_age_seconds=1.5, quality_fresh=True)
        self.assertEqual(rejection.reason, "STALE_FRAME")
        self.assertTrue(rejection.stale)
        self.assertFalse(rejection.quality_invalid)

    def test_poor_quality_frame_is_distinguished_from_latency(self):
        rejection = classify_frame_rejection(0.8, max_age_seconds=1.5, quality_fresh=False)
        self.assertEqual(rejection.reason, "CAPTURE_QUALITY_INVALID")
        self.assertFalse(rejection.stale)
        self.assertTrue(rejection.quality_invalid)

    def test_late_and_poor_quality_frame_reports_both_causes(self):
        rejection = classify_frame_rejection(3.0, max_age_seconds=1.5, quality_fresh=False)
        self.assertEqual(rejection.reason, "STALE_FRAME")
        self.assertTrue(rejection.stale)
        self.assertTrue(rejection.quality_invalid)

    def test_age_exactly_at_limit_is_not_stale(self):
        self.assertIsNone(
            classify_frame_rejection(1.5, max_age_seconds=1.5, quality_fresh=True)
        )


if __name__ == "__main__":
    unittest.main()
