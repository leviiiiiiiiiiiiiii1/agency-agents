import unittest

from auto_trader_iq.flow_signal import (
    BUY,
    SELL,
    direction_of_colour,
    flow_signal,
)


class ColourDirectionTests(unittest.TestCase):
    def test_white_is_a_falling_candle_in_the_calibrated_chart(self):
        # Correção explícita do usuário: no gráfico dele, branca é baixa.
        self.assertEqual(direction_of_colour("white"), SELL)
        self.assertEqual(direction_of_colour("red"), SELL)
        self.assertEqual(direction_of_colour("green"), BUY)

    def test_an_uncalibrated_colour_does_not_become_a_direction(self):
        self.assertIsNone(direction_of_colour("purple"))


class FlowSignalTests(unittest.TestCase):
    def test_three_candles_in_the_same_direction_are_a_signal(self):
        signal = flow_signal(["red", "green", "green", "green"])
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, BUY)
        self.assertEqual(signal.streak, 3)

    def test_two_candles_are_not_enough_by_default(self):
        # Medido: exatamente duas seguidas ficaram em 56% com margem de +/-8pp,
        # indistinguível do equilíbrio. O piso subiu para três por isso.
        self.assertIsNone(flow_signal(["green", "red", "green", "green"]))

    def test_two_candles_still_work_when_the_caller_asks_for_two(self):
        signal = flow_signal(["green", "red", "green", "green"], min_streak=2)
        self.assertEqual(signal.streak, 2)

    def test_one_candle_is_not_a_signal(self):
        self.assertIsNone(flow_signal(["red", "green"]))

    def test_the_streak_stops_at_the_first_different_candle(self):
        # Vermelha e branca são as duas de baixa: uma seguida da outra não
        # interrompe a sequência - só a vela verde interrompe.
        # Uma vela verde sozinha depois de duas vermelhas: sequência de 1,
        # que não é fluxo em direção nenhuma.
        self.assertIsNone(flow_signal(["green", "green", "red", "red", "green"]))

    def test_red_followed_by_white_is_still_the_same_direction(self):
        signal = flow_signal(["green", "green", "red", "white"], min_streak=2)
        self.assertEqual(signal.direction, SELL)
        self.assertEqual(signal.streak, 2)

    def test_only_the_last_five_candles_are_read(self):
        colours = ["green"] * 6 + ["red", "red", "red"]
        signal = flow_signal(colours)
        self.assertEqual(signal.direction, SELL)
        self.assertEqual(signal.streak, 3)

    def test_an_uncalibrated_newest_candle_blocks_the_signal(self):
        self.assertIsNone(flow_signal(["green", "green", "purple"]))

    def test_the_signal_says_how_many_candles_hold_it(self):
        signal = flow_signal(["green", "green", "white", "white", "white"])
        self.assertEqual(signal.streak, 3)
        self.assertIn("3 velas seguidas", signal.reason)

    def test_window_smaller_than_the_run_caps_the_streak(self):
        signal = flow_signal(["green"] * 9, window=3)
        self.assertEqual(signal.streak, 3)
        self.assertEqual(signal.window, 3)

    def test_invalid_window_is_refused(self):
        with self.assertRaises(ValueError):
            flow_signal(["green"], window=0)
        with self.assertRaises(ValueError):
            flow_signal(["green"], min_streak=0)


if __name__ == "__main__":
    unittest.main()
