"""A regra de fluxo decidindo uma entrada por vela, sem tocar no mouse.

O que este módulo faz é transformar a decisão medida em comandos explícitos e
contáveis — "clicar COMPRA agora", "esperar o segundo fixo", "não clicar porque
a sequência tem uma vela só". Ele não clica, não lê a tela e não sabe o que é
DEMO ou REAL: quem executa decide isso. É essa separação que permite testar a
regra sem arriscar conta nenhuma.

Uma decisão por vela é o limite mais importante daqui. A regra foi medida
contando uma aposta por vela e uma entrada por candle; clicar duas vezes no
mesmo candle transformaria as 339 apostas medidas em outra coisa que ninguém
mediu. Por isso, depois de qualquer decisão terminal, a mesma vela não volta a
ser avaliada.

A expiração entra na decisão porque foi ela que separou os resultados: dois
minutos dão 68,3%, um minuto dá 57,2% e não passa do equilíbrio. O executor
recusa o que não foi medido em vez de deixar o número parecer melhor do que é.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .flow_signal import (
    BEST_EXPIRY_BARS,
    FLOW_MIN_STREAK,
    FLOW_WINDOW,
    MIN_EXPIRY_BARS,
    flow_decision,
)

ENTRY = "entry"
WAIT = "wait"
NONE = "none"


@dataclass(frozen=True, slots=True)
class EntryCommand:
    """O que fazer nesta leitura, com o motivo junto."""

    kind: str
    reason: str
    candle_id: str | None = None
    direction: str | None = None
    expiry_bars: int = BEST_EXPIRY_BARS

    @property
    def allowed(self) -> bool:
        return self.kind == ENTRY

    @property
    def terminal(self) -> bool:
        """Decisão que encerra esta vela; ``wait`` ainda vai virar entrada."""
        return self.kind != WAIT


@dataclass
class FlowExecutor:
    """Um estado por sessão: última vela decidida, entradas e recusas contadas."""

    expiry_bars: int = BEST_EXPIRY_BARS
    entry_second: int = 5
    min_streak: int = FLOW_MIN_STREAK
    window: int = FLOW_WINDOW
    max_entries: int | None = None
    last_candle_id: str | None = None
    entries: int = 0
    refusals: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.expiry_bars < MIN_EXPIRY_BARS:
            raise ValueError(
                f"expiração de {self.expiry_bars} vela(s) não foi medida acima do equilíbrio."
            )
        if not 0 <= self.entry_second <= 59:
            raise ValueError("entry_second precisa estar entre 0 e 59.")
        if self.max_entries is not None and self.max_entries < 1:
            raise ValueError("max_entries precisa ser pelo menos 1 quando informado.")

    def evaluate(
        self,
        colours: Sequence[str],
        *,
        candle_id: str | None,
        second: int,
    ) -> EntryCommand:
        """Decide o que fazer com a leitura desta vela."""
        if candle_id is None:
            return self._refuse("vela sem identificador")
        if self.last_candle_id == candle_id:
            return EntryCommand(NONE, "já houve decisão nesta vela", candle_id=candle_id)
        if self.max_entries is not None and self.entries >= self.max_entries:
            return self._refuse("limite de entradas da sessão atingido", candle_id)
        if not 0 <= second <= 59:
            return self._refuse("segundo inválido", candle_id)
        if second > self.entry_second:
            return self._refuse(
                f"passou do segundo :{self.entry_second:02d}; a vela seguinte é outra leitura",
                candle_id,
            )
        decision = flow_decision(
            colours,
            expiry_bars=self.expiry_bars,
            window=self.window,
            min_streak=self.min_streak,
        )
        if second < self.entry_second:
            # Antes do segundo fixo nada é terminal. A vela abre com a última
            # vela ainda de corpo curto, e a sequência pode amadurecer até :SS;
            # encerrar aqui gastava a vela antes de a regra poder agir.
            if decision.allowed:
                return EntryCommand(
                    WAIT,
                    f"sequência formada; aguardando :{self.entry_second:02d}",
                    candle_id=candle_id,
                    direction=decision.entry.direction,
                    expiry_bars=self.expiry_bars,
                )
            return EntryCommand(WAIT, decision.reason, candle_id=candle_id)
        if not decision.allowed:
            return self._refuse(decision.reason, candle_id)
        self.last_candle_id = candle_id
        self.entries += 1
        return EntryCommand(
            ENTRY,
            decision.reason,
            candle_id=candle_id,
            direction=decision.entry.direction,
            expiry_bars=self.expiry_bars,
        )

    def _refuse(self, reason: str, candle_id: str | None = None) -> EntryCommand:
        if candle_id is not None:
            self.last_candle_id = candle_id
        self.refusals[reason] = self.refusals.get(reason, 0) + 1
        return EntryCommand(NONE, reason, candle_id=candle_id)

    def summary(self) -> str:
        """Uma linha para o painel: quantas entradas e por que não houve mais."""
        parts = [f"{self.entries} entrada(s)"]
        if self.refusals:
            top = sorted(self.refusals.items(), key=lambda item: -item[1])[:3]
            parts.append("recusas: " + " · ".join(f"{count} {reason}" for reason, count in top))
        return "; ".join(parts)
