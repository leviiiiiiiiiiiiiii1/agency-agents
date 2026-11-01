"""Leitura do relógio da plataforma e janela temporal de entrada M1."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class PlatformClockReading:
    hour: int
    minute: int
    second: int
    confidence: float
    left: int
    top: int
    text: str

    @property
    def elapsed_seconds_in_m1(self) -> int:
        # As velas M1 da plataforma alinham ao minuto; usar o relógio da plataforma,
        # nunca o relógio do computador.
        return self.second


def parse_platform_clock(
    data: dict[str, Any], image_width: int, image_height: int, min_confidence: float = 70.0
) -> PlatformClockReading | None:
    """Localiza HH:MM:SS perto do rótulo HORA ATUAL no canto inferior direito.

    Retorna None se faltar o rótulo/horário ou se a geometria não for plausível;
    essa falha bloqueia a confirmação M1.
    """
    texts = data.get("text", [])
    anchors: list[tuple[float, float]] = []
    clocks: list[tuple[float, int, int, int, int, int, str]] = []
    for index, raw in enumerate(texts):
        text = str(raw).strip().upper()
        try:
            left = int(data["left"][index])
            top = int(data["top"][index])
            width = int(data["width"][index])
            height = int(data["height"][index])
            confidence = float(data["conf"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        # Rodapé/canto direito: evita confundir horários de eixo/preços com o relógio.
        if top < image_height * 0.60 or left < image_width * 0.30:
            continue
        normalized = re.sub(r"[^A-Z]", "", text)
        if normalized in {"HORA", "ATUAL", "HORAATUAL"}:
            anchors.append((left + width / 2, top + height / 2))
        match = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})", text)
        if match and confidence >= min_confidence:
            hour, minute, second = map(int, match.groups())
            if 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59:
                clocks.append((confidence, hour, minute, second, left, top, text))

    if not anchors or not clocks:
        return None
    max_distance = max(180.0, image_width * 0.30)
    plausible: list[tuple[float, float, int, int, int, int, int, str]] = []
    for confidence, hour, minute, second, left, top, text in clocks:
        distance = min(math.hypot(left - ax, top - ay) for ax, ay in anchors)
        if distance <= max_distance:
            plausible.append((distance, -confidence, hour, minute, second, left, top, text))
    if not plausible:
        return None
    distance, negative_confidence, hour, minute, second, left, top, text = min(plausible)
    return PlatformClockReading(hour, minute, second, -negative_confidence, left, top, text)


def m1_entry_window_open(reading: PlatformClockReading | None, max_elapsed_seconds: int = 30) -> bool:
    """M1: permite entrada apenas de 00 a max_elapsed segundos após a virada do minuto."""
    if reading is None or not 0 <= max_elapsed_seconds <= 60:
        return False
    return 0 <= reading.elapsed_seconds_in_m1 <= max_elapsed_seconds
