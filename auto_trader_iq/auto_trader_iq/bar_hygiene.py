"""Higiene das barras detectadas.

O detector trabalha por colunas de cor. Num candle largo ele pode encontrar mais de
uma coluna âncora, e uma linha tracejada do gráfico (cursor de tempo, eixo) pode
render uma "barra" de 2 px. Medir idade e preço contra essas barras inventa velas
que não existem — foi visto numa captura real: três barras dentro de um único candle.

Este módulo remove o que não é corpo de vela e junta duplicatas do mesmo candle.
"""

from __future__ import annotations

from typing import Any, Sequence

from .candle_monitor import _candle_pixel_color

MIN_WIDTH_RATIO = 0.3
DEDUPE_RATIO = 0.5
MIN_DEDUPE_PX = 4.0


def bar_width_px(image, bar: Any) -> int:
    """Largura do corpo da barra na altura média, na cor da própria barra."""
    source = image.convert("RGB")
    pixels = source.load()
    x = int(round(float(bar.center_x)))
    y = int((int(bar.top) + int(bar.bottom)) // 2)
    if x < 0 or x >= source.width or y < 0 or y >= source.height:
        return 0
    if _candle_pixel_color(*pixels[x, y]) != bar.color:
        # A altura média pode cair no meio de uma sombra; procura a cor na coluna.
        found = None
        for candidate in range(int(bar.top), int(bar.bottom) + 1):
            if 0 <= candidate < source.height and _candle_pixel_color(
                *pixels[x, candidate]
            ) == bar.color:
                found = candidate
                break
        if found is None:
            return 0
        y = found
    width = 1
    for step in (-1, 1):
        cursor = x + step
        while 0 <= cursor < source.width and _candle_pixel_color(
            *pixels[cursor, y]
        ) == bar.color:
            width += 1
            cursor += step
    return width


def typical_gap(bars: Sequence[Any]) -> float | None:
    gaps = [bars[i + 1].center_x - bars[i].center_x for i in range(len(bars) - 1)]
    usable = sorted(gap for gap in gaps if gap >= 8)
    if not usable:
        return None
    index = max(0, min(len(usable) - 1, round(0.25 * (len(usable) - 1))))
    return float(usable[index])


def consolidate_bars(image, bars: Sequence[Any]) -> list[Any]:
    """Remove barras que não têm corpo de vela e junta duplicatas do mesmo candle.

    Não reordena nem altera barras legítimas: cada grupo de barras mais próximas
    que meia vela vira uma só, a de maior largura de corpo.
    """
    if not bars:
        return []
    gap = typical_gap(bars)
    ordered = sorted(bars, key=lambda item: float(item.center_x))
    if gap is None:
        return ordered
    min_width = max(3.0, gap * MIN_WIDTH_RATIO)
    widths = {id(bar): bar_width_px(image, bar) for bar in ordered}
    kept = [bar for bar in ordered if widths[id(bar)] >= min_width]
    if not kept:
        return []

    merge_distance = max(MIN_DEDUPE_PX, gap * DEDUPE_RATIO)
    grouped: list[list[Any]] = [[kept[0]]]
    for bar in kept[1:]:
        if float(bar.center_x) - float(grouped[-1][-1].center_x) < merge_distance:
            grouped[-1].append(bar)
        else:
            grouped.append([bar])
    return [
        max(group, key=lambda item: (widths[id(item)], -float(item.center_x)))
        for group in grouped
    ]


def summarize_consolidation(bars: Sequence[Any], kept: Sequence[Any]) -> dict[str, int]:
    return {
        "detected": len(bars),
        "kept": len(kept),
        "median_gap_px": round(typical_gap(kept) or 0.0, 1),
    }
