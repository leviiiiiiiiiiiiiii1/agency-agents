import unittest
from datetime import datetime, timezone

from auto_trader_iq.demo_clock import (
    WindowsUtcMinusThreeClock,
    windows_utc_minus_three_reading,
)


class WindowsUtcMinusThreeClockTests(unittest.TestCase):
    def test_converts_utc_into_fixed_utc_minus_three_across_previous_day(self):
        reading = windows_utc_minus_three_reading(
            datetime(2026, 1, 2, 2, 15, 42, tzinfo=timezone.utc)
        )

        self.assertEqual((reading.hour, reading.minute, reading.second), (23, 15, 42))
        self.assertEqual(reading.text, "23:15:42")
        self.assertEqual(reading.confidence, 100.0)

    def test_active_clock_advances_monotonically_after_wall_clock_correction(self):
        wall_time = [datetime(2026, 1, 2, 2, 15, 58, tzinfo=timezone.utc)]
        monotonic_time = [100.0]
        clock = WindowsUtcMinusThreeClock(
            wall_clock=lambda: wall_time[0],
            monotonic_clock=lambda: monotonic_time[0],
        )

        wall_time[0] = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        monotonic_time[0] = 103.2
        reading = clock.reading()

        self.assertEqual((reading.hour, reading.minute, reading.second), (23, 16, 1))

    def test_rejects_naive_datetime_instead_of_guessing_timezone(self):
        with self.assertRaisesRegex(ValueError, "fuso horário"):
            windows_utc_minus_three_reading(datetime(2026, 1, 2, 2, 15, 42))


if __name__ == "__main__":
    unittest.main()
