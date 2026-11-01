"""Fluxo de simulação assistida do sinal até a abertura da vela seguinte.

A confirmação de abertura é manual nesta etapa. O módulo nunca envia ordens.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from .signal_detector import SignalCandidate


@dataclass(frozen=True, slots=True)
class PendingSignal:
    signal_id: str
    fingerprint: str
    direction: str
    observed_text: str
    confidence: float
    x: int
    y: int
    detected_at: datetime


@dataclass(frozen=True, slots=True)
class SimulatedEntry:
    signal_id: str
    direction: str
    signal_text: str
    confidence: float
    signal_x: int
    signal_y: int
    signal_detected_at: datetime
    next_candle_confirmed_at: datetime
    elapsed_seconds_after_open: int | None = None


class SimulationWorkflow:
    """Arma um candidato OCR e registra uma entrada simulada após confirmação humana.

    O fingerprint direcional/espacial reduz cliques repetidos sobre o mesmo rótulo
    durante uma sessão. Não representa identidade real de vela e não persiste após
    fechar o programa.
    """

    def __init__(self, position_bucket_px: int = 24) -> None:
        if position_bucket_px <= 0:
            raise ValueError("position_bucket_px precisa ser maior que zero.")
        self.position_bucket_px = position_bucket_px
        self.pending: PendingSignal | None = None
        self.entries: list[SimulatedEntry] = []
        self._processed_fingerprints: set[str] = set()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _fingerprint(self, candidate: SignalCandidate) -> str:
        center_x = candidate.left + candidate.width // 2
        center_y = candidate.top + candidate.height // 2
        bucket_x = center_x // self.position_bucket_px
        bucket_y = center_y // self.position_bucket_px
        return f"{candidate.direction}:{bucket_x}:{bucket_y}"

    def arm(self, candidate: SignalCandidate, detected_at: datetime | None = None) -> PendingSignal:
        if self.pending is not None:
            raise ValueError("Já existe um sinal aguardando a confirmação da próxima vela.")
        fingerprint = self._fingerprint(candidate)
        if fingerprint in self._processed_fingerprints:
            raise ValueError("Este sinal já foi usado nesta sessão; duplicata ignorada.")
        detected_at = detected_at or self._now()
        signal_id = hashlib.blake2b(fingerprint.encode("utf-8"), digest_size=8).hexdigest()
        pending = PendingSignal(
            signal_id=signal_id,
            fingerprint=fingerprint,
            direction=candidate.direction,
            observed_text=candidate.observed_text,
            confidence=candidate.confidence,
            x=candidate.left,
            y=candidate.top,
            detected_at=detected_at,
        )
        self.pending = pending
        self._processed_fingerprints.add(fingerprint)
        return pending

    def confirm_next_candle(
        self,
        confirmed_at: datetime | None = None,
        elapsed_seconds_after_open: int | None = None,
    ) -> SimulatedEntry:
        if self.pending is None:
            raise ValueError("Não há sinal armado para confirmar.")
        pending = self.pending
        entry = SimulatedEntry(
            signal_id=pending.signal_id,
            direction=pending.direction,
            signal_text=pending.observed_text,
            confidence=pending.confidence,
            signal_x=pending.x,
            signal_y=pending.y,
            signal_detected_at=pending.detected_at,
            next_candle_confirmed_at=confirmed_at or self._now(),
            elapsed_seconds_after_open=elapsed_seconds_after_open,
        )
        self.entries.append(entry)
        self.pending = None
        return entry

    def cancel_pending(self) -> PendingSignal:
        if self.pending is None:
            raise ValueError("Não há sinal aguardando confirmação.")
        pending = self.pending
        self.pending = None
        # Mantém fingerprint consumido para a sessão: cancelar não deve permitir
        # rearmar acidentalmente a mesma etiqueta persistente.
        return pending
