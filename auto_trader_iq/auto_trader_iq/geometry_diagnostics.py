"""Diagnóstico visual da geometria entre rótulos e velas.

O relatório mostrou rótulos sempre 3 a 13 velas à esquerda da última vela
detectada, enquanto 93% dos quadros têm algum rótulo na tela. Sem ver o quadro,
não há como separar três explicações muito diferentes: velas fantasmas detectadas
à direita, rótulos desenhados longe do candle que marcam, ou sinais realmente
antigos. Este módulo grava a imagem com as velas e as caixas desenhadas.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from statistics import median
from typing import Any, Sequence

DEFAULT_MIN_BARS_TO_THE_RIGHT = 3
SNAPSHOT_INTERVAL_SECONDS = 60.0

_last_snapshot_at: float | None = None


def summarize(bars: Sequence[Any], candidates: Sequence[Any]) -> dict[str, Any] | None:
    """Geometria do rótulo mais à direita em relação às velas detectadas."""
    if not bars:
        return None
    gaps = [bars[i + 1].center_x - bars[i].center_x for i in range(len(bars) - 1)]
    normal_gaps = [gap for gap in gaps if gap >= 8]
    summary: dict[str, Any] = {
        "bar_count": len(bars),
        "median_gap_px": round(median(normal_gaps), 1) if normal_gaps else None,
        "first_bar_x": round(float(bars[0].center_x), 1),
        "last_bar_x": round(float(bars[-1].center_x), 1),
        "rightmost_label_x": None,
        "rightmost_label_index": None,
        "bars_to_the_right": None,
        "offset_px": None,
    }
    if not candidates:
        return summary
    newest = max(candidates, key=lambda item: item.left + item.width / 2)
    text_center = newest.left + newest.width / 2
    index = min(range(len(bars)), key=lambda i: abs(bars[i].center_x - text_center))
    summary.update(
        {
            "rightmost_label_x": round(float(text_center), 1),
            "rightmost_label_index": index,
            "bars_to_the_right": len(bars) - 1 - index,
            "offset_px": round(abs(float(bars[index].center_x) - text_center), 1),
        }
    )
    return summary


def annotate(image, bars: Sequence[Any], candidates: Sequence[Any]):
    """Cópia da imagem com centros de vela e caixas de rótulo destacados."""
    from PIL import ImageDraw

    canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)
    for position, bar in enumerate(bars):
        x = float(bar.center_x)
        color = (0, 120, 255) if position < len(bars) - 1 else (255, 0, 255)
        draw.line([(x, 0), (x, canvas.height)], fill=color, width=1)
    newest = (
        max(candidates, key=lambda item: item.left + item.width / 2)
        if candidates
        else None
    )
    for candidate in candidates:
        draw.rectangle(
            [candidate.left, candidate.top, candidate.left + candidate.width,
             candidate.top + candidate.height],
            outline=(255, 140, 0),
            width=2,
        )
    if newest is not None:
        draw.rectangle(
            [newest.left, newest.top, newest.left + newest.width,
             newest.top + newest.height],
            outline=(255, 0, 0),
            width=3,
        )
    return canvas


def save_snapshot(
    image,
    bars: Sequence[Any],
    candidates: Sequence[Any],
    directory: str | Path,
    *,
    min_bars_to_the_right: int = DEFAULT_MIN_BARS_TO_THE_RIGHT,
    force: bool = False,
) -> Path | None:
    """Grava PNG + JSON quando a geometria merece inspeção. Nunca levanta exceção."""
    global _last_snapshot_at
    try:
        summary = summarize(bars, candidates)
        if summary is None:
            return None
        bars_to_right = summary.get("bars_to_the_right")
        if not force and (bars_to_right is None or bars_to_right < min_bars_to_the_right):
            return None
        now = time.monotonic()
        if not force and _last_snapshot_at is not None and now - _last_snapshot_at < SNAPSHOT_INTERVAL_SECONDS:
            return None
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        image_path = target / f"geometry_{stamp}.png"
        annotate(image, bars, candidates).save(image_path)
        image_path.with_suffix(".json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _last_snapshot_at = now
        return image_path
    except Exception:  # pragma: no cover - diagnóstico jamais derruba o OCR
        return None


def reset_rate_limit() -> None:
    global _last_snapshot_at
    _last_snapshot_at = None
