import unittest
from unittest.mock import patch

from auto_trader_iq.windows_power import (
    ES_CONTINUOUS,
    ES_DISPLAY_REQUIRED,
    ES_SYSTEM_REQUIRED,
    set_windows_keep_awake,
)


class WindowsPowerTests(unittest.TestCase):
    def test_keep_awake_flags_include_display_and_system_requirements(self):
        self.assertEqual(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED, 0x80000003)

    @patch("auto_trader_iq.windows_power.sys.platform", "linux")
    def test_refuses_to_change_execution_state_off_windows(self):
        with self.assertRaisesRegex(RuntimeError, "Windows"):
            set_windows_keep_awake(True)


if __name__ == "__main__":
    unittest.main()
