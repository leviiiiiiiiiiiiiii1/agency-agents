"""Heurística visual para reduzir OCR de etiquetas em velas históricas.

Detecta corpos coloridos de candles no gráfico e mantém somente rótulos associados
à última vela ou à vela imediatamente anterior. É um filtro visual experimental,
não um identificador de candle de produção.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .signal_detector import SignalCandidate


@dataclass(frozen=True, slots=True)
class CandleBar:
    center_x: float
    color: str
    top: int
    bottom: int


def _candle_pixel_color(r: int, g: int, b: int) -> str | None:
    """Recognize common candle palettes, including white/purple chart themes."""
    if g >= 90 and g >= r * 1.32 and g >= b * 1.12:
        return "green"
    if r >= 125 and r >= g * 1.32 and r >= b * 1.25:
        return "red"
    if b >= 120 and r >= 80 and b >= r * 1.12 and r >= g * 1.35:
        return "purple"
    if min(r, g, b) >= 190 and max(r, g, b) - min(r, g, b) <= 42:
        return "white"
    return None


def detect_candle_bars(image, downscale: int = 2) -> list[CandleBar]:
    """Localiza corpos/pavios em paletas verde/vermelha ou branca/roxa.

    Reduz a imagem para acelerar a varredura; exige largura, área e altura mínimas
    para rejeitar, na maioria dos casos, textos, setas e linhas horizontais. Se houver
    pelo menos duas barras brancas/roxas, prioriza essa paleta para não confundir
    setas de sinal vermelhas/verdes com velas.
    """
    if downscale < 1:
        raise ValueError("downscale precisa ser pelo menos 1.")
    from PIL import Image

    width = max(1, image.width // downscale)
    height = max(1, image.height // downscale)
    sample = image.convert("RGB").resize((width, height), Image.Resampling.NEAREST)
    pixels = sample.load()

    column_color: dict[int, str] = {}
    for x in range(width):
        positions_by_color: dict[str, list[int]] = {}
        for y in range(height):
            color = _candle_pixel_color(*pixels[x, y])
            if color is not None:
                positions_by_color.setdefault(color, []).append(y)
        if not positions_by_color:
            continue
        dominant, positions = max(positions_by_color.items(), key=lambda item: len(item[1]))
        # Corpo/pavio ocupa muitas linhas no mesmo x; letras e retículos, poucas.
        if len(positions) >= 5:
            column_color[x] = dominant

    runs: list[tuple[int, int, str]] = []
    active = sorted(column_color)
    if not active:
        return []
    start = previous = active[0]
    current_color = column_color[start]
    for x in active[1:]:
        color = column_color[x]
        if x - previous > 2 or color != current_color:
            runs.append((start, previous, current_color))
            start = x
            current_color = color
        previous = x
    runs.append((start, previous, current_color))

    bars: list[CandleBar] = []
    for left, right, color in runs:
        run_width = right - left + 1
        if run_width < 3:
            continue
        ys: list[int] = []
        color_pixels = 0
        for x in range(left, right + 1):
            for y in range(height):
                if _candle_pixel_color(*pixels[x, y]) == color:
                    ys.append(y)
                    color_pixels += 1
        if not ys:
            continue
        top, bottom = min(ys), max(ys)
        if bottom - top + 1 < 9 or color_pixels < 24:
            continue
        bars.append(CandleBar(
            center_x=((left + right + 1) / 2) * downscale,
            color=color,
            top=top * downscale,
            bottom=(bottom + 1) * downscale,
        ))
    light_palette_bars = [bar for bar in bars if bar.color in {"white", "purple"}]
    if len(light_palette_bars) >= 2:
        bars = light_palette_bars
    else:
        bars = [bar for bar in bars if bar.color in {"green", "red"}]
    return sorted(bars, key=lambda bar: bar.center_x)


def filter_to_recent_candle(
    candidates: list[SignalCandidate],
    bars: list[CandleBar],
    recent_bars: int = 2,
) -> list[SignalCandidate]:
    """Retorna candidatos alinhados às últimas N barras e à mais recente delas.

    Mantemos a última vela e a imediatamente anterior porque o indicador mostra o
    sinal quando a vela de referência fechou; a vela seguinte pode já estar visível.
    Se não for possível detectar pelo menos duas barras, falha fechado e não libera
    candidatos ao simulador.
    """
    if recent_bars < 1:
        raise ValueError("recent_bars precisa ser pelo menos 1.")
    if len(bars) < 2 or not candidates:
        return []

    gaps = [bars[i + 1].center_x - bars[i].center_x for i in range(len(bars) - 1)]
    normal_gaps = [gap for gap in gaps if gap >= 8]
    tolerance = max(18.0, (median(normal_gaps) if normal_gaps else 24.0) * 0.65)
    first_recent_index = max(0, len(bars) - recent_bars)

    matched: list[tuple[int, float, SignalCandidate]] = []
    for candidate in candidates:
        text_center = candidate.left + candidate.width / 2
        candle_index, candle = min(
            enumerate(bars), key=lambda pair: abs(pair[1].center_x - text_center)
        )
        distance = abs(candle.center_x - text_center)
        if distance <= tolerance and candle_index >= first_recent_index:
            matched.append((candle_index, distance, candidate))

    if not matched:
        return []
    # Entre rótulos recentes, use somente o mais à direita (mais próximo do candle atual).
    newest_signal_bar = max(index for index, _distance, _candidate in matched)
    return [candidate for index, _distance, candidate in matched if index == newest_signal_bar]
