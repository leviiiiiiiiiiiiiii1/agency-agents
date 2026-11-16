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

    def test_the_toggle_button_is_never_left_dead(self):
        # Um botão cinza escondeu o caminho inteiro: o pedido do usuário foi
        # "não tem esse botão". Quem recusa é o comando, com o motivo escrito.
        start = self.source.index("def _update_demo_toggle_text")
        block = self.source[start:start + 900]
        self.assertIn('state="normal"', block)
        self.assertNotIn('state="disabled"', block)
        self.assertEqual(
            self.source.count('text="Ligar cliques automáticos DEMO"'), 2
        )
        self.assertNotIn('text="Cliques bloqueados · sem verificação de conta"', self.source)

    def test_stopping_keeps_the_declaration_about_the_account(self):
        start = self.source.index("def _deactivate_demo_automation")
        block = self.source[start:start + 900]
        self.assertIn("self.demo_automation_enabled = False", block)
        self.assertNotIn("self.demo_account_confirmed = False", block)

    def test_the_switch_sits_next_to_the_demo_button_in_both_panels(self):
        # No rodapé do painel ele caía fora da janela, e a caixa ainda se
        # desmarcava sozinha: virou botão, colado no botão que arma os cliques.
        self.assertLess(
            self.source.index('text="Ligar regra de fluxo (2+ velas · 2 min)"'),
            self.source.index('text="Calibrar COMPRAR"'),
        )
        self.assertIn('text="Fluxo: ligar (2+ velas)"', self.source)

    def test_checking_it_without_the_automation_does_not_uncheck_itself(self):
        start = self.source.index("def _on_flow_entries_toggle")
        block = self.source[start:start + 1200]
        self.assertNotIn("self.flow_entries_var.set(False)", block)

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
