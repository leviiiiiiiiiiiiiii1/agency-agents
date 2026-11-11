"""Heurística visual para reduzir OCR de etiquetas em velas históricas.

Detecta corpos coloridos de candles no gráfico e mantém somente rótulos associados
à última vela ou à vela imediatamente anterior. É um filtro visual experimental,
não um identificador de candle de produção.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
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


def detect_candle_bars(
    image, downscale: int = 2, *, palette_colors: Collection[str] | None = None
) -> list[CandleBar]:
    """Versão de produção: apenas as barras, sem estatísticas."""
    bars, _stats = detect_candle_bars_detailed(
        image, downscale, palette_colors=palette_colors
    )
    return bars


def detect_candle_bars_detailed(
    image, downscale: int = 2, *, palette_colors: Collection[str] | None = None
) -> tuple[list[CandleBar], dict[str, object]]:
    """Mesma detecção, devolvendo por que barras foram aceitas ou descartadas.

    Sem esse detalhamento, "0 velas" é indistinguível entre cor não reconhecida
    (paleta do gráfico fora das faixas) e geometria insuficiente (barra estreita ou
    curta). São causas com correções opostas, então o número precisa ser medido.
    """
    """Localiza corpos/pavios em paletas verde/vermelha ou branca/roxa.

    Reduz a imagem para acelerar a varredura; exige largura, área e altura mínimas
    para rejeitar, na maioria dos casos, textos, setas e linhas horizontais. Se houver
    pelo menos duas barras brancas/roxas, prioriza essa paleta para não confundir
    setas de sinal vermelhas/verdes com velas.
    """
    if downscale < 1:
        raise ValueError("downscale precisa ser pelo menos 1.")
    allowed_colors = {"green", "red", "white", "purple"}
    if palette_colors is not None and not set(palette_colors) <= allowed_colors:
        raise ValueError("palette_colors contém uma cor não suportada.")
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
    dominant_by_color: dict[str, int] = {}
    for stats in column_stats.values():
        dominant_by_color[stats[0]] = dominant_by_color.get(stats[0], 0) + 1

    runs: list[tuple[int, int, str]] = []
    active = sorted(column_color)
    if not active:
        return [], {
            "dominant_columns_by_color": dominant_by_color,
            "runs": 0,
            "rejected_narrow": 0,
            "rejected_short_or_sparse": 0,
            "bars_before_palette": 0,
            "bars_after_palette": 0,
            "palette": sorted(palette_colors) if palette_colors else None,
        }
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
    rejected_narrow = 0
    rejected_short_or_sparse = 0
    for left, right, color in runs:
        run_width = right - left + 1
        # Keep narrower candle bodies, especially the forming bar at the right edge.
        if run_width < 2:
            rejected_narrow += 1
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
            rejected_short_or_sparse += 1
            continue
        bars.append(CandleBar(
            center_x=((left + right + 1) / 2) * downscale,
            color=color,
            top=top * downscale,
            bottom=(bottom + 1) * downscale,
        ))
    bars_before_palette = len(bars)
    if palette_colors is not None:
        bars = [bar for bar in bars if bar.color in palette_colors]
    else:
        # Sem calibração explícita, mantém apenas a heurística de geometria antiga
        # para associação espacial; não atribui direção de mercado às cores claras.
        light_palette_bars = [bar for bar in bars if bar.color in {"white", "purple"}]
        if len(light_palette_bars) >= 2:
            bars = light_palette_bars
        else:
            bars = [bar for bar in bars if bar.color in {"green", "red"}]
    stats_summary = {
        "dominant_columns_by_color": dominant_by_color,
        "runs": len(runs),
        "rejected_narrow": rejected_narrow,
        "rejected_short_or_sparse": rejected_short_or_sparse,
        "bars_before_palette": bars_before_palette,
        "bars_after_palette": len(bars),
        "palette": sorted(palette_colors) if palette_colors else None,
    }
    return sorted(bars, key=lambda bar: bar.center_x), stats_summary


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


@dataclass(frozen=True, slots=True)
class MarketContext:
    regime: str
    direction: str | None
    evidence: str

    @property
    def display_text(self) -> str:
        if self.regime == "waiting":
            return f"Contexto visual: aguardando velas suficientes ({self.evidence})."
        if self.regime == "flow":
            label = "FLUXO COMPRADOR" if self.direction == "BUY" else "FLUXO VENDEDOR"
            return f"{label} · {self.evidence}"
        if self.regime == "wicks":
            return f"PAVIOS/RETRAÇÕES FREQUENTES · {self.evidence}"
        if self.regime == "lateral":
            return f"LATERALIZADO · {self.evidence}"
        return f"MISTO/INDEFINIDO · {self.evidence}"


def _market_candles_from_bars(
    image,
    bars: list[CandleBar],
    *,
    color_direction_map: Mapping[str, str] | None = None,
) -> list[MarketCandle]:
    """Estimate candle bodies/wicks using only explicitly calibrated color semantics."""
    direction_map = dict(color_direction_map or {})
    if any(color not in {"green", "red", "white", "purple"} for color in direction_map):
        raise ValueError("color_direction_map contém uma cor não suportada.")
    if any(direction not in {"BUY", "SELL"} for direction in direction_map.values()):
        raise ValueError("direções da paleta devem ser BUY ou SELL.")
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
        direction = direction_map.get(bar.color)
        if direction is None:
            # A geometrically detected candle without user-confirmed semantics
            # must not influence a directional market-context estimate.
            continue
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
        bullish_color = direction == "BUY"
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


def classify_market_context(
    image,
    bars: list[CandleBar] | None = None,
    lookback: int = 12,
    *,
    color_direction_map: Mapping[str, str] | None = None,
) -> MarketContext:
    """Describe chart structure only for colors with explicit calibrated direction."""
    if lookback < 6:
        raise ValueError("lookback precisa ser pelo menos 6 velas.")
    bars = detect_candle_bars(image) if bars is None else bars
    candles = _market_candles_from_bars(
        image, bars, color_direction_map=color_direction_map
    )[-lookback:]
    if len(candles) < 6:
        return MarketContext("waiting", None, f"{len(candles)}/6")

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
    close_moves = [previous.close_y - current.close_y for previous, current in zip(candles, candles[1:])]
    net_move = candles[0].close_y - candles[-1].close_y
    net_strength = abs(net_move) / typical_range
    direction_count = upward_steps if net_move > 0 else downward_steps
    direction_ratio = direction_count / steps
    total_path = sum(abs(move) for move in close_moves)
    directional_efficiency = abs(net_move) / max(1.0, total_path)

    # Confirm trend with the candle ranges too, not just a run of inferred closes.
    # Compare smoothed first/last thirds to discount individual spikes and pullbacks.
    group_size = max(2, len(candles) // 3)
    first_group = candles[:group_size]
    last_group = candles[-group_size:]
    first_high = median(candle.high for candle in first_group)
    last_high = median(candle.high for candle in last_group)
    first_low = median(candle.low for candle in first_group)
    last_low = median(candle.low for candle in last_group)
    structure_tolerance = max(2.0, typical_range * 0.12)
    if net_move > 0:
        structure_aligned = (
            last_high < first_high - structure_tolerance
            and last_low < first_low - structure_tolerance
        )
    elif net_move < 0:
        structure_aligned = (
            last_high > first_high + structure_tolerance
            and last_low > first_low + structure_tolerance
        )
    else:
        structure_aligned = False

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
    if (
        structure_aligned
        and direction_ratio >= 0.55
        and net_strength >= 0.9
        and directional_efficiency >= 0.45
    ):
        direction = "BUY" if net_move > 0 else "SELL"
        structure_label = "máximas/mínimas ascendentes" if direction == "BUY" else "máximas/mínimas descendentes"
        direction_evidence = (
            f"{direction_count}/{steps} fechamentos alinhados; "
            f"deslocamento {net_strength:.1f}× a faixa típica; "
            f"eficiência {directional_efficiency:.0%}; {structure_label}"
        )
        return MarketContext("flow", direction, direction_evidence)
    if wick_ratio >= 0.45:
        return MarketContext("wicks", None, evidence)
    if overlap_ratio >= 0.4 or (net_strength < 1.0 and overlapping_pairs >= steps // 2):
        lateral_evidence = (
            f"faixas sobrepostas em {overlapping_pairs}/{steps} pares; {evidence}"
        )
        return MarketContext("lateral", None, lateral_evidence)
    return MarketContext("mixed", None, f"sem direção consistente; {evidence}")


def count_signal_labels_by_candle(
    candidates: list[SignalCandidate],
    bars: list[CandleBar],
    lookback: int = 12,
) -> dict[str, int]:
    """Count distinct recent candles carrying BUY/SELL OCR labels.

    Multiple OCR boxes on one candle count once. This is a separate context signal;
    the trading candidate filter below still selects only the newest eligible label.
    """
    if lookback < 1:
        raise ValueError("lookback precisa ser pelo menos 1 vela.")
    counts = {"BUY": 0, "SELL": 0}
    if len(bars) < 1 or not candidates:
        return counts

    gaps = [bars[i + 1].center_x - bars[i].center_x for i in range(len(bars) - 1)]
    normal_gaps = [gap for gap in gaps if gap >= 8]
    tolerance = max(18.0, (median(normal_gaps) if normal_gaps else 24.0) * 0.65)
    first_index = max(0, len(bars) - lookback)
    labeled_bars: dict[str, set[int]] = {"BUY": set(), "SELL": set()}

    for candidate in candidates:
        text_center = candidate.left + candidate.width / 2
        candle_index, candle = min(
            enumerate(bars), key=lambda pair: abs(pair[1].center_x - text_center)
        )
        if (
            candle_index >= first_index
            and abs(candle.center_x - text_center) <= tolerance
            and candidate.direction in labeled_bars
        ):
            labeled_bars[candidate.direction].add(candle_index)

    return {direction: len(indices) for direction, indices in labeled_bars.items()}


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


def label_age_bars(candidate, bars) -> int | None:
    """Distância em velas entre o rótulo e a vela mais recente.

    Zero significa "está na última vela". Retorna ``None`` quando não há velas ou o
    rótulo está longe demais de qualquer uma para ser contado, porque nesse caso a
    idade não é desconhecida por acaso: ela não pode ser medida.
    """
    if not bars or candidate is None:
        return None
    gaps = [bars[i + 1].center_x - bars[i].center_x for i in range(len(bars) - 1)]
    normal_gaps = [gap for gap in gaps if gap >= 8]
    tolerance = max(18.0, (median(normal_gaps) if normal_gaps else 24.0) * 0.65)
    text_center = candidate.left + candidate.width / 2
    index, bar = min(
        enumerate(bars), key=lambda pair: abs(pair[1].center_x - text_center)
    )
    if abs(bar.center_x - text_center) > tolerance:
        return None
    return len(bars) - 1 - index
