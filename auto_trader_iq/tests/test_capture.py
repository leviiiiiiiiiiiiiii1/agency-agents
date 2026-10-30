import unittest

from auto_trader_iq.capture import ScreenRegion


class ScreenRegionTests(unittest.TestCase):
    def test_exports_mss_region(self):
        region = ScreenRegion(left=-1280, top=0, width=800, height=600)
        self.assertEqual(
            region.as_mss_dict(),
            {"left": -1280, "top": 0, "width": 800, "height": 600},
        )

    def test_rejects_non_positive_dimensions(self):
        for width, height in ((0, 10), (10, 0), (-1, 10), (10, -1)):
            with self.subTest(width=width, height=height):
                with self.assertRaises(ValueError):
                    ScreenRegion(0, 0, width, height)

    def test_rejects_non_integer_coordinates(self):
        with self.assertRaises(TypeError):
            ScreenRegion(0.5, 0, 10, 10)  # type: ignore[arg-type]

    def test_from_dict(self):
        region = ScreenRegion.from_dict({"left": "10", "top": "20", "width": "300", "height": "200"})
        self.assertEqual(region, ScreenRegion(10, 20, 300, 200))


if __name__ == "__main__":
    unittest.main()
