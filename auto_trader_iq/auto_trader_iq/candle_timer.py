"""Validação do limite temporal M1 a partir do contador da plataforma."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class CandleTimerReading:
    remaining_seconds: int
    confidence: float
    left: int
    top: int
    text: str

    @property
    def elapsed_seconds(self) -> int:
        return 60 - self.remaining_seconds


def parse_platform_candle_timer(
    data: dict[str, Any], image_width: int, image_height: int, min_confidence: float = 35.0
) -> CandleTimerReading | None:
    """Aceita um cronômetro MM:SS no alto do gráfico, próximo ao rótulo HORA/COMPRA.

    A âncora textual ajuda a não confundir horário/preço dos eixos com o timer M1.
    Retorna None quando a associação não é suficientemente clara (fail-closed).
    """
    texts = data.get("text", [])
    anchors: list[tuple[float, float]] = []
    timers: list[tuple[int, float, int, int, str]] = []
    row_count = len(texts)
    for index in range(row_count):
        text = str(texts[index]).strip().upper()
        try:
            left, top = int(data["left"][index]), int(data["top"][index])
            width, height = int(data["width"][index]), int(data["height"][index])
            confidence = float(data["conf"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if top > image_height * 0.35:
            continue
        normalized = re.sub(r"[^A-Z]", "", text)
        if normalized == "HORA":
            anchors.append((left + width / 2, top + height / 2))
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
        if match and confidence >= min_confidence:
            minutes, seconds = int(match.group(1)), int(match.group(2))
            total_seconds = minutes * 60 + seconds
            if seconds < 60 and total_seconds <= 60:
                timers.append((total_seconds, confidence, left, top, text))

    if not anchors or not timers:
        return None
    max_distance = max(120.0, image_width * 0.16)
    plausible = []
    for seconds, confidence, left, top, text in timers:
        center = (left, top)
        distance = min(math.hypot(center[0] - ax, center[1] - ay) for ax, ay in anchors)
        if distance <= max_distance:
            plausible.append((distance, -confidence, seconds, left, top, text))
    if not plausible:
        return None
    distance, negative_confidence, seconds, left, top, text = min(plausible)
    return CandleTimerReading(seconds, -negative_confidence, left, top, text)


def m1_entry_window_open(reading: CandleTimerReading | None, max_elapsed_seconds: int = 30) -> bool:
    """M1: só permite confirmar N+1 nos primeiros 30 s, com timer legível."""
    if reading is None or not 0 <= max_elapsed_seconds <= 60:
        return False
    return 0 <= reading.elapsed_seconds <= max_elapsed_seconds
