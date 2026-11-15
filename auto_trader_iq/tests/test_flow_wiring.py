"""A ligação da regra de fluxo no app não pode ser importada sem Tk.

Estes testes leem o código-fonte: garantem que a entrada por fluxo continua
chamada, que ela não fica fora do caminho DEMO e que as checagens de rótulo OCR
continuam sendo puladas para um sinal que não tem rótulo. São pobres, mas
pegam a remoção acidental de uma linha num arquivo que nenhum teste importa.
"""

import os
import unittest

SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "auto_trader_iq",
    "app.py",
)


class FlowWiringTests(unittest.TestCase):
    def setUp(self):
        with open(SOURCE, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_the_flow_entry_runs_after_each_reading(self):
        self.assertIn("self._maybe_auto_arm_demo_signal()\n        self._maybe_auto_flow_entry()",
                      self.source)

    def test_the_flow_entry_needs_the_demo_automation_on(self):
        start = self.source.index("def _maybe_auto_flow_entry")
        block = self.source[start:start + 700]
        self.assertIn("not self.flow_entries_enabled", block)
        self.assertIn("not self.demo_automation_enabled", block)

    def test_a_flow_signal_skips_the_label_checks(self):
        self.assertIn('self.pending_source != "flow" and not self._pending_demo_candidate_is_current', self.source)
        self.assertIn('self.pending_source != "flow" and not self._market_context_allows_direction(', self.source)

    def test_the_expiry_is_the_measured_one(self):
        self.assertIn("FLOW_ENTRY_EXPIRY_BARS = 2", self.source)
        self.assertIn("FlowExecutor(\n            expiry_bars=FLOW_ENTRY_EXPIRY_BARS", self.source)

    def test_the_click_still_asks_the_user_about_the_account(self):
        self.assertIn("actual_order_execution_allowed(\n", self.source)
        self.assertIn("demo_confirmed=self.demo_account_confirmed", self.source)

    def test_the_switch_is_not_restored_on_startup(self):
        # Opt-in a cada sessão: nada de clicar sozinho porque ficou salvo.
        self.assertNotIn('"flow_entries_enabled"', self.source)


if __name__ == "__main__":
    unittest.main()
