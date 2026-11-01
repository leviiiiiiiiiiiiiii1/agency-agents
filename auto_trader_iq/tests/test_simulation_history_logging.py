import unittest
from unittest.mock import Mock

from auto_trader_iq.simulation_history import append_event_best_effort


class AppHistoryLoggingTests(unittest.TestCase):
    def test_storage_error_is_reported_without_raising(self):
        store = Mock()
        store.append_event.side_effect = OSError("disk full")

        error = append_event_best_effort(
            store,
            event="entrada_simulada",
            direction="BUY",
            platform_clock="23:44:21",
        )

        self.assertEqual(error, "disk full")

    def test_success_returns_none_and_forwards_event(self):
        store = Mock()
        error = append_event_best_effort(
            store,
            event="entrada_simulada",
            direction="SELL",
            platform_clock="23:44:21",
        )

        self.assertIsNone(error)
        store.append_event.assert_called_once_with(
            event="entrada_simulada",
            direction="SELL",
            platform_clock="23:44:21",
        )


if __name__ == "__main__":
    unittest.main()
