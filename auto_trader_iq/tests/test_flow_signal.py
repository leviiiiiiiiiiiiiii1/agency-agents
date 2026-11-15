import unittest

from auto_trader_iq.flow_signal import (
    BUY,
    SELL,
    direction_of_colour,
    entry_from_ladder,
    flow_decision,
    flow_entry,
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
    def test_two_candles_in_the_same_direction_are_a_signal(self):
        # Duas é o piso medido: é o único que passa o equilíbrio em toda
        # expiração (57,2% em uma vela, 68,3% em duas).
        signal = flow_signal(["green", "red", "green", "green"])
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, BUY)
        self.assertEqual(signal.streak, 2)

    def test_three_candles_report_three(self):
        signal = flow_signal(["red", "green", "green", "green"])
        self.assertEqual(signal.streak, 3)

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

    def test_the_entry_refuses_a_one_candle_expiry(self):
        # 57,2% com +/-5pp cruza o equilíbrio de 54,1%: não é entrada.
        self.assertIsNone(flow_entry(["green", "red", "red"], expiry_bars=1))

    def test_the_entry_carries_direction_streak_and_expiry(self):
        entry = flow_entry(["green", "red", "red"], expiry_bars=2)
        self.assertEqual(entry.direction, SELL)
        self.assertEqual(entry.streak, 2)
        self.assertEqual(entry.expiry_bars, 2)
        self.assertIn("expiração de 2 velas", entry.reason)

    def test_the_entry_needs_a_streak_before_it_needs_an_expiry(self):
        self.assertIsNone(flow_entry(["red", "green"], expiry_bars=2))

    def test_the_entry_refuses_an_uncalibrated_newest_candle(self):
        self.assertIsNone(flow_entry(["red", "red", "purple"], expiry_bars=2))

    def test_invalid_window_is_refused(self):
        with self.assertRaises(ValueError):
            flow_signal(["green"], window=0)
        with self.assertRaises(ValueError):
            flow_signal(["green"], min_streak=0)


if __name__ == "__main__":
    unittest.main()


class FlowDecisionTests(unittest.TestCase):
    def test_an_entry_says_why_it_is_allowed(self):
        decision = flow_decision(["green", "red", "red"], expiry_bars=2)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.entry.direction, SELL)
        self.assertIn("2 velas seguidas", decision.reason)

    def test_a_one_candle_expiry_says_what_is_missing(self):
        decision = flow_decision(["green", "red", "red"], expiry_bars=1)
        self.assertFalse(decision.allowed)
        self.assertIn("não medida", decision.reason)

    def test_a_short_streak_says_how_short_it_is(self):
        decision = flow_decision(["red", "green"], expiry_bars=2)
        self.assertFalse(decision.allowed)
        self.assertIn("abaixo do piso", decision.reason)

    def test_an_uncalibrated_candle_says_so(self):
        decision = flow_decision(["red", "red", "purple"], expiry_bars=2)
        self.assertIn("sem cor calibrada", decision.reason)

    def test_an_empty_reading_is_not_an_entry(self):
        self.assertIn("nenhuma vela lida", flow_decision([], expiry_bars=2).reason)

    def test_the_decision_can_be_taken_from_the_ladder_the_app_already_saves(self):
        decision = entry_from_ladder({"colors": ["green", "red", "red"]}, expiry_bars=2)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.entry.direction, SELL)

    def test_a_frame_without_colours_says_it_cannot_read(self):
        decision = entry_from_ladder({"closes_px": [1.0, 2.0]}, expiry_bars=2)
        self.assertFalse(decision.allowed)
        self.assertIn("sem cores gravadas", decision.reason)

