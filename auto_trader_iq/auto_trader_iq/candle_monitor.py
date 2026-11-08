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

    column_stats: dict[int, tuple[str, int, int, int]] = {}
    for x in range(width):
        counts: dict[str, int] = {}
        bounds: dict[str, list[int]] = {}
        for y in range(height):
            color = _candle_pixel_color(*pixels[x, y])
            if color is None:
                continue
            counts[color] = counts.get(color, 0) + 1
            if color not in bounds:
                bounds[color] = [y, y]
            else:
                bounds[color][1] = y
        if not counts:
            continue
        dominant = max(counts, key=counts.get)
        # Corpo/pavio ocupa muitas linhas no mesmo x; letras e retículos, poucas.
        if counts[dominant] >= 5:
            top, bottom = bounds[dominant]
            column_stats[x] = (dominant, top, bottom, counts[dominant])
    column_color = {x: stats[0] for x, stats in column_stats.items()}

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
        run_stats = [
            column_stats[x]
            for x in range(left, right + 1)
            if x in column_stats and column_stats[x][0] == color
        ]
        if not run_stats:
            continue
        top = min(stats[1] for stats in run_stats)
        bottom = max(stats[2] for stats in run_stats)
        color_pixels = sum(stats[3] for stats in run_stats)
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


@dataclass(frozen=True, slots=True)
class MarketCandle:
    center_x: float
    high: int
    low: int
    body_top: int
    body_bottom: int
    open_y: int
    close_y: int
    upper_wick: int
    lower_wick: int


def _market_candles_from_bars(image, bars: list[CandleBar]) -> list[MarketCandle]:
    """Estimate candle bodies/wicks from color density around detected bars."""
    if len(bars) < 2:
        return []
    from math import ceil
    from PIL import Image

    source = image.convert("RGB")
    pixels = source.load()
    gaps = [bars[i + 1].center_x - bars[i].center_x for i in range(len(bars) - 1)]
    spacing = median([gap for gap in gaps if gap > 0]) if any(gap > 0 for gap in gaps) else 24
    radius = max(2, min(10, round(spacing * 0.12)))
    observations: list[MarketCandle] = []

    for bar in bars:
        left = max(0, int(round(bar.center_x)) - radius)
        right = min(source.width, int(round(bar.center_x)) + radius + 1)
        top = max(0, bar.top)
        bottom = min(source.height, bar.bottom)
        if right <= left or bottom <= top:
            continue
        row_counts = [0] * (bottom - top)
        for x in range(left, right):
            for y in range(top, bottom):
                if _candle_pixel_color(*pixels[x, y]) == bar.color:
                    row_counts[y - top] += 1
        threshold = max(2, ceil((right - left) * 0.35))
        segments: list[tuple[int, int]] = []
        start: int | None = None
        for row, count in enumerate(row_counts):
            if count >= threshold and start is None:
                start = row
            elif count < threshold and start is not None:
                segments.append((start, row - 1))
                start = None
        if start is not None:
            segments.append((start, len(row_counts) - 1))
        if not segments:
            continue
        body_start, body_end = max(
            segments,
            key=lambda segment: sum(row_counts[segment[0]:segment[1] + 1]),
        )
        body_top = top + body_start
        body_bottom = top + body_end
        if body_bottom < body_top:
            continue
        # Follow colored pixels contiguous to the body; isolated horizontal chart
        # levels elsewhere in the candle's x-band must not inflate its wick/range.
        high_index = body_start
        while high_index > 0 and row_counts[high_index - 1] > 0:
            high_index -= 1
        low_index = body_end
        while low_index + 1 < len(row_counts) and row_counts[low_index + 1] > 0:
            low_index += 1
        candle_high = top + high_index
        candle_low = top + low_index
        # Green/white candles conventionally close at their top; red/purple at bottom.
        bullish_color = bar.color in {"green", "white"}
        open_y = body_bottom if bullish_color else body_top
        close_y = body_top if bullish_color else body_bottom
        observations.append(MarketCandle(
            center_x=bar.center_x,
            high=candle_high,
            low=candle_low,
            body_top=body_top,
            body_bottom=body_bottom,
            open_y=open_y,
            close_y=close_y,
            upper_wick=max(0, body_top - candle_high),
            lower_wick=max(0, candle_low - body_bottom),
        ))
    return observations


def classify_market_context(image, bars: list[CandleBar] | None = None, lookback: int = 12) -> str:
    """Describe recent chart structure; heuristic/read-only, never a trade signal."""
    if lookback < 6:
        raise ValueError("lookback precisa ser pelo menos 6 velas.")
    bars = detect_candle_bars(image) if bars is None else bars
    candles = _market_candles_from_bars(image, bars)[-lookback:]
    if len(candles) < 6:
        return f"Contexto visual: aguardando velas suficientes ({len(candles)}/6)."

    ranges = [max(1, candle.low - candle.high) for candle in candles]
    typical_range = max(1.0, median(ranges))
    flat_tolerance = max(2.0, typical_range * 0.12)
    upward_steps = downward_steps = 0
    for previous, current in zip(candles, candles[1:]):
        move = previous.close_y - current.close_y
        if move > flat_tolerance:
            upward_steps += 1
        elif move < -flat_tolerance:
            downward_steps += 1
    steps = max(1, len(candles) - 1)
    net_move = candles[0].close_y - candles[-1].close_y
    net_strength = abs(net_move) / typical_range
    direction_count = upward_steps if net_move > 0 else downward_steps
    direction_ratio = direction_count / steps

    long_wicks = 0
    for candle in candles:
        body = max(1, candle.body_bottom - candle.body_top + 1)
        longest_wick = max(candle.upper_wick, candle.lower_wick)
        if longest_wick >= max(6, body * 1.25) or (
            candle.upper_wick + candle.lower_wick >= max(8, body * 1.8)
        ):
            long_wicks += 1
    wick_ratio = long_wicks / len(candles)

    overlaps: list[float] = []
    for previous, current in zip(candles, candles[1:]):
        overlap = max(0, min(previous.low, current.low) - max(previous.high, current.high))
        smaller_range = max(1, min(previous.low - previous.high, current.low - current.high))
        overlaps.append(overlap / smaller_range)
    overlapping_pairs = sum(value >= 0.35 for value in overlaps)
    overlap_ratio = sum(overlaps) / max(1, len(overlaps))

    evidence = f"pavios longos em {long_wicks}/{len(candles)} velas"
    if wick_ratio >= 0.45:
        return f"PAVIOS/RETRAÇÕES FREQUENTES · {evidence}"
    if direction_ratio >= 0.65 and net_strength >= 1.15:
        direction = "COMPRADOR" if net_move > 0 else "VENDEDOR"
        note = f" · {evidence}" if long_wicks else ""
        return (
            f"FLUXO {direction} · {direction_count}/{steps} fechamentos alinhados; "
            f"deslocamento {net_strength:.1f}× a faixa típica{note}"
        )
    if overlap_ratio >= 0.4 or (net_strength < 1.0 and overlapping_pairs >= steps // 2):
        return (
            f"LATERALIZADO · faixas sobrepostas em {overlapping_pairs}/{steps} pares; "
            f"{evidence}"
        )
    return f"MISTO/INDEFINIDO · sem direção consistente; {evidence}"


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
