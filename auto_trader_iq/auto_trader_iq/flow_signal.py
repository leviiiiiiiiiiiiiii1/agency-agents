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

O piso é de duas velas, e a medição que o sustenta é a da expiração. Exigir
três velas só paga fechando em duas ou três: liquidando em uma vela, o piso 3
cai para 52,0% e o piso 4 para 52,1% - os dois abaixo do equilíbrio de 54,1% a
85%. O piso 2 faz 57,2% em uma, 68,3% em duas, 63,4% em três e 62,3% em quatro,
e é o único que passa o equilíbrio em todas elas. Com payout igual em todos os
tempos, o piso que vale para todas as expirações é o mais seguro.

A expiração também é decisão, não detalhe: em uma vela a regra fica dentro do
ruído; em duas, 68,3% com 328 apostas. Por isso `flow_entry` recusa expiração
de uma vela em vez de deixar o número parecer aprovado.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

FLOW_WINDOW = 5
FLOW_MIN_STREAK = 2

# Expirações liquidadas acima do equilíbrio na medição: 2, 3 e 4 velas.
# Uma vela fica de fora de propósito - 57,2% com margem de +/-5pp cruza o
# equilíbrio de 54,1%, e aprovar isso seria vender ruído como vantagem.
MIN_EXPIRY_BARS = 2
BEST_EXPIRY_BARS = 2

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


@dataclass(frozen=True, slots=True)
class FlowEntry:
    """A entrada como o app precisa ouvir: direção, quantas velas a sustentam, expiração."""

    direction: str
    streak: int
    expiry_bars: int
    reason: str


def flow_entry(
    colours: Sequence[str],
    *,
    expiry_bars: int,
    window: int = FLOW_WINDOW,
    min_streak: int = FLOW_MIN_STREAK,
) -> FlowEntry | None:
    """Decisão de entrada completa, ou ``None`` quando não há entrada.

    Recusa expiração de uma vela mesmo quando a sequência existe: o que foi
    medido nesse tempo não passa do equilíbrio, e um critério que aceita tudo o
    que aparece não é critério.
    """
    if expiry_bars < MIN_EXPIRY_BARS:
        return None
    signal = flow_signal(colours, window=window, min_streak=min_streak)
    if signal is None:
        return None
    candles = "vela" if expiry_bars == 1 else "velas"
    return FlowEntry(
        direction=signal.direction,
        streak=signal.streak,
        expiry_bars=expiry_bars,
        reason=f"{signal.reason}, expiração de {expiry_bars} {candles}",
    )


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
