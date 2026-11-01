import unittest

from PIL import Image

from auto_trader_iq.capture import ScreenRegion
from auto_trader_iq.screen_mask import (
    mask_screen_regions,
    point_is_masked,
    point_is_masked_with_margin,
)


class ScreenMaskTests(unittest.TestCase):
    def test_masks_absolute_screen_intersection_before_processing(self):
        image = Image.new("RGB", (100, 80), "white")
        capture = ScreenRegion(100, 200, 100, 80)
        excluded = ScreenRegion(130, 220, 20, 15)

        mask_screen_regions(image, capture, [excluded])

        self.assertEqual(image.getpixel((35, 25)), (0, 0, 0))
        self.assertEqual(image.getpixel((49, 34)), (0, 0, 0))
        self.assertEqual(image.getpixel((29, 25)), (255, 255, 255))
        self.assertEqual(image.getpixel((50, 25)), (255, 255, 255))

    def test_masking_clips_to_capture_and_ignores_non_intersecting_area(self):
        image = Image.new("RGB", (20, 20), "white")
        capture = ScreenRegion(10, 10, 20, 20)
        mask_screen_regions(
            image,
            capture,
            [ScreenRegion(25, 25, 20, 20), ScreenRegion(100, 100, 5, 5)],
        )
        self.assertEqual(image.getpixel((15, 15)), (0, 0, 0))
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_point_is_masked_only_inside_excluded_screen_area(self):
        excluded = [ScreenRegion(100, 200, 30, 40)]
        self.assertTrue(point_is_masked(100, 200, excluded))
        self.assertTrue(point_is_masked(129, 239, excluded))
        self.assertFalse(point_is_masked(130, 239, excluded))
        self.assertFalse(point_is_masked(99, 200, excluded))

    def test_button_target_requires_mask_margin_around_calibrated_center(self):
        excluded = [ScreenRegion(100, 200, 120, 120)]
        self.assertTrue(point_is_masked_with_margin(160, 260, excluded))
        self.assertFalse(point_is_masked_with_margin(145, 245, excluded))


if __name__ == "__main__":
    unittest.main()
