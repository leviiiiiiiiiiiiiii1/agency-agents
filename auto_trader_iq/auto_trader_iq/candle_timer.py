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


def parse_platform_clock_line(
    data: dict[str, Any],
    *,
    origin_left: int,
    origin_top: int,
    scale: int,
    min_confidence: float = 55.0,
) -> PlatformClockReading | None:
    """Parse a focused OCR pass over the bottom-right HORA ATUAL status line."""
    if scale <= 0:
        return None
    raw_texts = data.get("text", [])
    line_parts: list[str] = []
    token_spans: list[tuple[int, int, int]] = []
    for index, raw in enumerate(raw_texts):
        token = str(raw).strip().upper()
        if not token:
            continue
        if line_parts:
            line_parts.append(" ")
        start = sum(len(part) for part in line_parts)
        line_parts.append(token)
        token_spans.append((start, start + len(token), index))
    line = "".join(line_parts)
    normalized = re.sub(r"[^A-Z]", "", line)
    if "HORA" not in normalized or "ATUAL" not in normalized:
        return None
    # Permite OCR que separa os dois-pontos ou os componentes numéricos em palavras.
    match = re.search(r"(?<!\d)(\d{1,2})[ :.,;|]{1,4}(\d{2})[ :.,;|]{1,4}(\d{2})(?!\d)", line)
    if match is None:
        return None

    hour, minute, second = map(int, match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None

    try:
        confidences = data.get("conf", [])
        lefts = data.get("left", [])
        tops = data.get("top", [])
        time_tokens: list[tuple[float, int, int]] = []
        for start, end, index in token_spans:
            if end <= match.start() or start >= match.end():
                continue
            token = str(raw_texts[index]).strip()
            if not any(character.isdigit() for character in token):
                continue
            confidence = float(confidences[index])
            if confidence < 0:
                continue
            time_tokens.append((confidence, int(lefts[index]), int(tops[index])))
        if not time_tokens:
            return None
        confidence = min(item[0] for item in time_tokens)
        if confidence < min_confidence:
            return None
    except (IndexError, TypeError, ValueError):
        return None

    left, top = min(time_tokens, key=lambda item: item[1])[1:]
    return PlatformClockReading(
        hour,
        minute,
        second,
        confidence,
        origin_left + left // scale,
        origin_top + top // scale,
        match.group(0),
    )


def platform_minute_key(reading: PlatformClockReading | None) -> tuple[int, int] | None:
    """Return the platform-clock M1 candle key, or None for an unreadable clock."""
    if reading is None:
        return None
    return reading.hour, reading.minute


class PlatformMinuteTracker:
    """Assign a session-unique sequence to each observed platform-clock minute."""

    def __init__(self) -> None:
        self._last_key: tuple[int, int] | None = None
        self._sequence = -1

    def update(self, reading: PlatformClockReading | None) -> int | None:
        key = platform_minute_key(reading)
        if key is None:
            return None
        if key != self._last_key:
            self._last_key = key
            self._sequence += 1
        return self._sequence


def platform_minute_offset(
    previous: PlatformClockReading | None,
    current: PlatformClockReading | None,
) -> int | None:
    """Return elapsed minute steps on the platform clock, including midnight wrap."""
    if previous is None or current is None:
        return None
    previous_minute = previous.hour * 60 + previous.minute
    current_minute = current.hour * 60 + current.minute
    return (current_minute - previous_minute) % (24 * 60)


def platform_clock_elapsed_seconds(
    previous: PlatformClockReading | None,
    current: PlatformClockReading | None,
) -> int | None:
    """Return elapsed whole seconds between HORA ATUAL readings, or None on a jump/backstep."""
    offset = platform_minute_offset(previous, current)
    if previous is None or current is None or offset not in {0, 1}:
        return None
    if offset == 0:
        elapsed = current.second - previous.second
        return elapsed if elapsed >= 0 else None
    return 60 - previous.second + current.second


def platform_minute_advanced(
    previous: PlatformClockReading | None,
    current: PlatformClockReading | None,
) -> bool:
    """Return True only when HORA ATUAL advances by exactly one minute."""
    return platform_minute_offset(previous, current) == 1


def m1_entry_window_open(reading: PlatformClockReading | None, max_elapsed_seconds: int = 30) -> bool:
    """M1: permite entrada apenas de 00 a max_elapsed segundos após a virada do minuto."""
    if reading is None or not 0 <= max_elapsed_seconds <= 60:
        return False
    return 0 <= reading.elapsed_seconds_in_m1 <= max_elapsed_seconds


def m1_next_candle_entry_window_open(
    armed_clock: PlatformClockReading | None,
    current_clock: PlatformClockReading | None,
    max_elapsed_seconds: int = 30,
) -> bool:
    """Require exactly one platform-minute advance and an open N+1 M1 window."""
    return (
        platform_minute_offset(armed_clock, current_clock) == 1
        and m1_entry_window_open(current_clock, max_elapsed_seconds)
    )
