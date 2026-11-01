import sys
import unittest
from unittest.mock import Mock

from auto_trader_iq.demo_click import (
    ClickTarget,
    click_demo_direction,
    demo_entry_deadline_open,
    windows_mouse_click,
    windows_mouse_position,
)


class DemoClickTests(unittest.TestCase):
    def test_demo_entry_deadline_allows_at_most_fifteen_seconds_from_arm(self):
        self.assertTrue(demo_entry_deadline_open(50.0, 50.0))
        self.assertTrue(demo_entry_deadline_open(50.0, 65.0))
        self.assertFalse(demo_entry_deadline_open(50.0, 65.001))
        self.assertFalse(demo_entry_deadline_open(50.0, 49.9))
        self.assertFalse(demo_entry_deadline_open(None, 51.0))
        self.assertFalse(demo_entry_deadline_open(50.0, float("nan")))

    def test_direction_maps_only_to_calibrated_target(self):
        clicker = Mock()
        buy = ClickTarget(100, 200)
        sell = ClickTarget(300, 400)

        returned = click_demo_direction(
            "SELL", buy_target=buy, sell_target=sell,
            enabled=True, demo_confirmed=True, clicker=clicker,
        )

        self.assertEqual(returned, sell)
        clicker.assert_called_once_with(300, 400)

    def test_requires_session_opt_in_and_demo_confirmation(self):
        clicker = Mock()
        for enabled, confirmed in ((False, True), (True, False)):
            with self.subTest(enabled=enabled, confirmed=confirmed):
                with self.assertRaises(PermissionError):
                    click_demo_direction(
                        "BUY", buy_target=ClickTarget(10, 20), sell_target=None,
                        enabled=enabled, demo_confirmed=confirmed, clicker=clicker,
                    )
        clicker.assert_not_called()

    def test_unknown_direction_and_missing_target_fail_without_click(self):
        clicker = Mock()
        with self.assertRaises(ValueError):
            click_demo_direction(
                "HOLD", buy_target=ClickTarget(10, 20), sell_target=None,
                enabled=True, demo_confirmed=True, clicker=clicker,
            )
        with self.assertRaisesRegex(ValueError, "calibrado"):
            click_demo_direction(
                "SELL", buy_target=ClickTarget(10, 20), sell_target=None,
                enabled=True, demo_confirmed=True, clicker=clicker,
            )
        clicker.assert_not_called()

    def test_target_rejects_negative_or_non_integer_coordinates(self):
        for coordinates in ((-1, 0), (0, -1), (1.5, 2), (True, 3)):
            with self.subTest(coordinates=coordinates):
                with self.assertRaises(ValueError):
                    ClickTarget(*coordinates)

    @unittest.skipIf(sys.platform == "win32", "testa apenas o bloqueio fora do Windows")
    def test_native_mouse_api_is_unavailable_off_windows(self):
        with self.assertRaisesRegex(RuntimeError, "Windows"):
            windows_mouse_position()
        with self.assertRaisesRegex(RuntimeError, "Windows"):
            windows_mouse_click(100, 100)


if __name__ == "__main__":
    unittest.main()
