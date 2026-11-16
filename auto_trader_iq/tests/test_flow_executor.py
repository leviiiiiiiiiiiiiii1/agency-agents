import unittest

from auto_trader_iq.flow_executor import ENTRY, NONE, WAIT, FlowExecutor


def executor(**kwargs):
    settings = {"expiry_bars": 2, "entry_second": 5}
    settings.update(kwargs)
    return FlowExecutor(**settings)


class EntryRuleTests(unittest.TestCase):
    def test_a_streak_enters_on_the_fixed_second(self):
        command = executor().evaluate(["green", "red", "red"], candle_id="c1", second=5)
        self.assertEqual(command.kind, ENTRY)
        self.assertEqual(command.direction, "SELL")
        self.assertEqual(command.expiry_bars, 2)

    def test_before_the_fixed_second_it_waits_and_does_not_spend_the_candle(self):
        flow = executor()
        self.assertEqual(flow.evaluate(["green", "red", "red"], candle_id="c1", second=3).kind, WAIT)
        self.assertEqual(flow.evaluate(["green", "red", "red"], candle_id="c1", second=5).kind, ENTRY)

    def test_a_thin_streak_before_the_second_does_not_spend_the_candle(self):
        # A vela abre com a última ainda de corpo curto: se a sequência só
        # amadurece em :12, a decisão de :02 não pode fechar a vela.
        flow = executor(entry_second=15)
        early = flow.evaluate(["green", "red"], candle_id="c1", second=2)
        self.assertEqual(early.kind, WAIT)
        mature = flow.evaluate(["green", "red", "red", "red"], candle_id="c1", second=15)
        self.assertEqual(mature.kind, ENTRY)
        self.assertEqual(mature.direction, "SELL")

    def test_after_the_fixed_second_the_candle_is_lost(self):
        flow = executor()
        command = flow.evaluate(["green", "red", "red"], candle_id="c1", second=9)
        self.assertEqual(command.kind, NONE)
        self.assertIn("passou do segundo", command.reason)


class OneDecisionPerCandleTests(unittest.TestCase):
    def test_the_same_candle_is_never_decided_twice(self):
        flow = executor()
        first = flow.evaluate(["green", "red", "red"], candle_id="c1", second=5)
        second = flow.evaluate(["green", "red", "red"], candle_id="c1", second=6)
        self.assertTrue(first.allowed)
        self.assertEqual(second.kind, NONE)
        self.assertIn("já houve decisão", second.reason)
        self.assertEqual(flow.entries, 1)

    def test_a_refusal_also_closes_the_candle(self):
        flow = executor()
        flow.evaluate(["red", "green"], candle_id="c1", second=5)
        again = flow.evaluate(["green", "red", "red"], candle_id="c1", second=5)
        self.assertEqual(again.kind, NONE)

    def test_the_next_candle_is_a_new_decision(self):
        flow = executor()
        flow.evaluate(["green", "red", "red"], candle_id="c1", second=5)
        self.assertEqual(flow.evaluate(["green", "red", "red"], candle_id="c2", second=5).kind, ENTRY)
        self.assertEqual(flow.entries, 2)


class RefusalAccountingTests(unittest.TestCase):
    def test_refusals_are_counted_by_reason(self):
        flow = executor()
        flow.evaluate(["red", "green"], candle_id="c1", second=5)
        flow.evaluate(["red", "green"], candle_id="c2", second=5)
        self.assertEqual(len(flow.refusals), 1)
        self.assertEqual(list(flow.refusals.values()), [2])

    def test_the_summary_says_entries_and_the_main_refusals(self):
        flow = executor()
        flow.evaluate(["green", "red", "red"], candle_id="c1", second=5)
        flow.evaluate(["red", "green"], candle_id="c2", second=5)
        text = flow.summary()
        self.assertIn("1 entrada(s)", text)
        self.assertIn("abaixo do piso", text)

    def test_the_session_cap_stops_further_entries(self):
        flow = executor(max_entries=1)
        self.assertEqual(flow.evaluate(["green", "red", "red"], candle_id="c1", second=5).kind, ENTRY)
        second = flow.evaluate(["green", "red", "red"], candle_id="c2", second=5)
        self.assertEqual(second.kind, NONE)
        self.assertIn("limite", second.reason)


class RefusedConfigurationTests(unittest.TestCase):
    def test_a_one_candle_expiry_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            FlowExecutor(expiry_bars=1)

    def test_an_impossible_second_is_refused(self):
        with self.assertRaises(ValueError):
            FlowExecutor(entry_second=60)

    def test_a_zero_cap_is_refused(self):
        with self.assertRaises(ValueError):
            FlowExecutor(max_entries=0)


if __name__ == "__main__":
    unittest.main()
