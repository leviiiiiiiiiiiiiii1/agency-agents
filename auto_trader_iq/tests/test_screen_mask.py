import unittest

from PIL import Image

from auto_trader_iq.capture import ScreenRegion
from auto_trader_iq.screen_mask import mask_screen_regions


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




if __name__ == "__main__":
    unittest.main()
