"""A regra de fluxo como código: entrar na direção das velas seguidas.

Ela foi medida antes de existir aqui. Em 208 apostas elegíveis a vantagem
estratificada passou de z = 1,91 para z = 2,53, mantendo 1,91 ao remover a
melhor célula - os dois critérios de adoção que já estavam combinados. O que
este módulo faz é transformar a regra medida em decisão explícita, para que o
app possa emitir exatamente a mesma coisa que foi medida.

Duas travas vêm da calibração do gráfico do usuário, não do gosto de quem lê:

- verde = alta (COMPRA), vermelha e branca = baixa (VENDER);
- roxa não foi calibrada, então vale desconhecida. Paleta não calibrada não
  vira sinal: seria inventar direção onde ninguém confirmou nada.

A janela é de cinco velas, e a aposta é sempre na direção da sequência, nunca
na reversão: o que foi medido é a continuação, e é só isso que este código
autoriza.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

FLOW_WINDOW = 5
FLOW_MIN_STREAK = 2

BUY = "BUY"
SELL = "SELL"

_HIGH_COLOURS = frozenset({"green"})
_LOW_COLOURS = frozenset({"red", "white"})


@dataclass(frozen=True, slots=True)
class FlowSignal:
    """Uma aposta de fluxo: a direção e quantas velas seguidas a sustentam."""

    direction: str
    streak: int
    window: int

    @property
    def reason(self) -> str:
        candles = "vela" if self.streak == 1 else "velas"
        return f"{self.streak} {candles} seguidas na direção de {self.direction}"


def direction_of_colour(colour: str) -> str | None:
    """Direção calibrada de uma cor de vela; ``None`` quando não há calibração."""
    if colour in _HIGH_COLOURS:
        return BUY
    if colour in _LOW_COLOURS:
        return SELL
    return None


def flow_signal(
    colours: Sequence[str],
    *,
    window: int = FLOW_WINDOW,
    min_streak: int = FLOW_MIN_STREAK,
) -> FlowSignal | None:
    """Sinal de fluxo a partir das cores das velas, da mais antiga à mais nova.

    Devolve ``None`` quando a sequência tem menos de ``min_streak`` velas na
    mesma direção, ou quando a vela mais nova tem cor não calibrada - nesse
    caso a direção do fluxo é desconhecida, e desconhecido não gera aposta.
    """
    if window < 1:
        raise ValueError("window precisa ser pelo menos 1.")
    if min_streak < 1:
        raise ValueError("min_streak precisa ser pelo menos 1.")
    recent = list(colours)[-window:]
    if not recent:
        return None
    newest = direction_of_colour(recent[-1])
    if newest is None:
        return None
    streak = 0
    for colour in reversed(recent):
        if direction_of_colour(colour) != newest:
            break
        streak += 1
    if streak < min_streak:
        return None
    return FlowSignal(direction=newest, streak=streak, window=window)
