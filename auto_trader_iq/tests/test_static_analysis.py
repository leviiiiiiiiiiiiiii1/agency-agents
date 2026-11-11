"""Rede de segurança estática.

A interface não pode ser importada em máquina sem Tk, então um nome indefinido só
aparece quando o app já está rodando — foi assim que `detect_candle_bars_detailed`
quebrou o OCR em produção. Este teste roda o analisador estático sobre o pacote.
"""

import os
import subprocess
import sys
import unittest

try:  # pragma: no cover - presença opcional
    import pyflakes  # noqa: F401
except ImportError:  # pragma: no cover
    pyflakes = None

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(pyflakes is not None, "pyflakes não instalado; instale para checar nomes indefinidos")
class StaticAnalysisTests(unittest.TestCase):
    def test_no_undefined_names_or_redefinitions(self):
        for target in ("auto_trader_iq", "tests"):
            completed = subprocess.run(
                [sys.executable, "-m", "pyflakes", os.path.join(PACKAGE_ROOT, target)],
                capture_output=True,
                text=True,
                check=False,
            )
            blocking = [
                line
                for line in completed.stdout.splitlines()
                if "undefined name" in line or "redefinition" in line
            ]
            self.assertEqual(blocking, [], f"problemas em {target}:\n" + "\n".join(blocking))


class GradingWiringTests(unittest.TestCase):
    """A classificação só é útil se o motivo e o regime chegarem ao journal."""

    def setUp(self):
        path = os.path.join(PACKAGE_ROOT, "auto_trader_iq", "app.py")
        with open(path, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_journal_payload_carries_reasons_and_context(self):
        for needle in (
            '"reasons": list(self.grade_reasons)',
            '"context_regime": self.market_context_regime',
            '"context_direction": self.market_context_direction',
        ):
            self.assertIn(needle, self.source)

    def test_label_outside_window_is_distinguished_from_absent_label(self):
        self.assertIn('"LABEL_OUTSIDE_WINDOW"', self.source)
        self.assertIn('"NO_LABEL"', self.source)
        self.assertIn(
            "self._grade_candidates(candidates, label_ages, market_candles, raw_count)",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
