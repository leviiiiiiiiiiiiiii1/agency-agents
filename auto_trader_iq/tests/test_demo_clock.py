import unittest
from datetime import datetime, timezone

from auto_trader_iq.demo_clock import (
    WindowsUtcMinusThreeClock,
    demo_entry_second_action,
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

    def test_fixed_entry_second_waits_enters_on_target_and_skips_late_signal(self):
        self.assertEqual(demo_entry_second_action(3, 5), "wait")
        self.assertEqual(demo_entry_second_action(5, 5), "enter")
        self.assertEqual(demo_entry_second_action(6, 5), "late")

    def test_fixed_entry_second_rejects_out_of_range_values(self):
        for current, target in ((-1, 5), (60, 5), (1, -1), (1, 31)):
            with self.subTest(current=current, target=target):
                with self.assertRaises(ValueError):
                    demo_entry_second_action(current, target)

    def test_rejects_naive_datetime_instead_of_guessing_timezone(self):
        with self.assertRaisesRegex(ValueError, "fuso horário"):
            windows_utc_minus_three_reading(datetime(2026, 1, 2, 2, 15, 42))


if __name__ == "__main__":
    unittest.main()
