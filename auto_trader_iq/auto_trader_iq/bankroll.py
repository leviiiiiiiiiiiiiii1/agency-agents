"""Quanto uma sequência de apostas faria com uma banca, sem inventar mercado.

A conta é aritmética sobre o desfecho já medido: cada aposta arrisca uma fração
da banca atual, ganha o payout e perde a aposta inteira. Empate conta como
perda, porque é assim que a corretora liquida.

Nada aqui prevê o próximo resultado. O que esta conta mostra é o que teria
acontecido com ESTA sequência, e o quanto o resultado depende da taxa que você
acertou - que é a parte incerta.
"""

from __future__ import annotations

import random
from typing import Any, Sequence


def simulate(
    wins: Sequence[bool],
    *,
    bankroll: float = 200.0,
    payout: float = 0.85,
    stake_fraction: float = 0.02,
) -> dict[str, Any]:
    """Banca final, maior queda e se chegou a quebrar, apostando uma fração fixa."""
    equity = float(bankroll)
    peak = equity
    worst = 0.0
    bets = 0
    ruined = False
    for win in wins:
        if equity <= 0:
            ruined = True
            break
        amount = equity * stake_fraction
        bets += 1
        if win:
            equity += amount * payout
        else:
            equity -= amount
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return {
        "bankroll": float(bankroll),
        "final": equity,
        "bets": bets,
        "return": (equity / bankroll - 1.0) if bankroll else 0.0,
        "max_drawdown": worst,
        "ruined": ruined or equity <= 0,
    }


def bootstrap_by_block(
    blocks: Sequence[Sequence[bool]],
    *,
    bankroll: float = 200.0,
    payout: float = 0.85,
    stake_fraction: float = 0.02,
    runs: int = 2000,
    seed: int = 7,
) -> dict[str, Any]:
    """Bootstrap de blocos: sorteia horas com reposição e refaz a conta.

    Com aposta de fração fixa o resultado final não depende da ORDEM das
    apostas, só de quantas ganharam e perderam. Então não adianta embaralhar:
    o que se sorteia aqui são as horas. Cada reamostragem tem uma taxa
    diferente, e é essa variação - a de verdade, entre uma hora e outra - que
    aparece no intervalo. A ordem só importa para a maior queda.
    """
    usable = [list(block) for block in blocks if block]
    if not usable or runs <= 0:
        return {}
    rng = random.Random(seed)
    finals: list[float] = []
    drawdowns: list[float] = []
    ruins = 0
    for _ in range(runs):
        order = [rng.randrange(len(usable)) for _ in usable]
        sequence = [bet for index in order for bet in usable[index]]
        result = simulate(
            sequence,
            bankroll=bankroll,
            payout=payout,
            stake_fraction=stake_fraction,
        )
        finals.append(result["final"])
        drawdowns.append(result["max_drawdown"])
        if result["ruined"]:
            ruins += 1
    finals.sort()
    drawdowns.sort()

    def at(values: Sequence[float], fraction: float) -> float:
        index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
        return values[index]

    return {
        "runs": runs,
        "final_p05": at(finals, 0.05),
        "final_p50": at(finals, 0.50),
        "final_p95": at(finals, 0.95),
        "drawdown_p50": at(drawdowns, 0.50),
        # Queda é número negativo: o pior caso fica no começo da lista ordenada.
        "drawdown_p95": at(drawdowns, 0.05),
        "ruined": ruins / runs,
    }


def breakeven_rate(payout: float) -> float:
    """Acerto mínimo para empatar com esse payout (empate conta como perda)."""
    return 1.0 / (1.0 + payout)
