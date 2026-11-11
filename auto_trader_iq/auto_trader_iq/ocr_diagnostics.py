"""Diagnóstico do rendimento de um quadro OCR.

Separa o que o quadro custou do que ele entregou. Um quadro descartado por idade
pode ter encontrado rótulos (problema de desempenho) ou nada (problema de leitura);
sem essa distinção as duas causas parecem idênticas no journal.
"""

from __future__ import annotations

from typing import Any


def summarize_ocr_yield(result: Any) -> dict[str, Any] | None:
    """Descreve o que a análise do quadro produziu, sem reinterpretar nada.

    O resultado esperado é a tupla devolvida por ``_analyze_ocr_frame``. Qualquer
    formato inesperado retorna ``None`` em vez de levantar, porque este resumo é
    apenas diagnóstico e nunca deve interromper a captura.
    """
    if not isinstance(result, tuple) or len(result) < 8:
        return None
    (
        candidates,
        clock,
        raw_candidate_count,
        color_rejected_count,
        bar_count,
        _clock_text,
        label_counts,
        raw_candidates,
    ) = result[:8]
    return {
        "raw_candidate_count": int(raw_candidate_count or 0),
        "recent_candidate_count": len(candidates or ()),
        "raw_box_count": len(raw_candidates or ()),
        "bar_count": int(bar_count or 0),
        "clock_readable": clock is not None,
        "color_rejected_count": int(color_rejected_count or 0),
        "label_counts": dict(label_counts) if isinstance(label_counts, dict) else None,
    }
