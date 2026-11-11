"""Relatório das medidas de classificação gravadas no journal.

Lê o banco em modo somente-leitura e responde três perguntas:

1. as medidas estão sendo capturadas de fato (cobertura)?
2. como os quadros se distribuem entre A / B / C / NO TRADE hoje?
3. o que aconteceria com a distribuição se um limiar fosse outro?

O relatório **não** calcula taxa de acerto: os quadros do journal não têm desfecho
vinculado, porque nenhuma ordem é enviada. Dizer o contrário seria inventar número.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from statistics import median
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .opportunity_grade import (
    DEFAULT_CRITERIA,
    GRADE_METHOD,
    GradeCriteria,
    SignalFeatures,
    grade_opportunity,
    validate_grade_criteria,
)

FEATURE_FIELDS = tuple(field.name for field in fields(SignalFeatures))
NUMERIC_FEATURES = ("body_vs_median", "distance_to_level", "close_from_extreme")
GRADE_ORDER = (
    "A",
    "B",
    "C",
    "NO_TRADE",
    "NO_LABEL",
    "LABEL_OUTSIDE_WINDOW",
    "NO_CANDIDATE",  # registros anteriores à separação dos dois casos acima
    "CRITERIA_UNDEFINED",
)


def default_journal_path() -> Path:
    """Mesmo diretório de dados que o app usa, sem criar nada em disco."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "AutoTraderIQ" / "opportunities.sqlite3"
    return Path.home() / ".auto_trader_iq" / "opportunities.sqlite3"


def load_frames(db_path: str | Path) -> list[dict[str, Any]]:
    """Quadros ``OCR_COMPLETED`` do journal, sem escrever nada no banco."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Banco não encontrado: {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        try:
            rows = connection.execute(
                "SELECT occurred_at_utc, session_id, payload_json "
                "FROM opportunity_events WHERE event_type = 'OCR_COMPLETED' "
                "ORDER BY occurred_at_utc"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError(f"Journal sem eventos legíveis: {exc}") from exc
    finally:
        connection.close()

    frames: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        grade = payload.get("grade")
        if not isinstance(grade, dict):
            continue
        features = grade.get("features")
        frames.append(
            {
                "occurred_at_utc": row["occurred_at_utc"],
                "session_id": row["session_id"],
                "schema_version": version,
                "code": grade.get("code"),
                "criteria_hash": grade.get("criteria_hash"),
                "method": grade.get("method"),
                "features": features if isinstance(features, dict) else None,
                "reasons": [str(item) for item in (grade.get("reasons") or [])],
                "context_regime": grade.get("context_regime"),
                "context_direction": grade.get("context_direction"),
                "raw_candidate_count": payload.get("raw_candidate_count"),
                "recent_candidate_count": payload.get("recent_candidate_count"),
                "label_geometry": (payload.get("association") or {}).get("label_geometry"),
                "price_ladder": (payload.get("association") or {}).get("price_ladder"),
                "age_reference": (payload.get("association") or {}).get("age_reference"),
                "bars_detected": (payload.get("association") or {}).get("bars_detected"),
                "palette_calibrated": bool(
                    (payload.get("association") or {}).get("palette_calibrated")
                ),
            }
        )
    return frames


def load_tracks(db_path: str | Path) -> list[dict[str, Any]]:
    """Sinais distintos rastreados pelo app, também em modo somente-leitura."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Banco não encontrado: {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        return _read_tracks(connection)
    finally:
        connection.close()


def _read_tracks(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Sinais distintos já rastreados. Ausente em bancos anteriores à versão 2."""
    try:
        rows = connection.execute(
            "SELECT tracking_id, direction, left_px, top_px, first_seen_at_utc, "
            "last_seen_at_utc, lifecycle, consecutive_observations FROM signal_tracks"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(row) for row in rows]


def _fresh_signal_runs(frames: Sequence[Mapping[str, Any]]) -> int:
    """Séries de quadros consecutivos com rótulo recente, por sessão.

    A identidade de rastreio do app combina posição em pixels com o instante da
    primeira visão, então a rolagem do gráfico fragmenta o mesmo rótulo em vários
    rastros. Contar quadros recentes consecutivos é uma estimativa honesta de
    quantos sinais novos apareceram de fato.
    """
    runs = 0
    previous_fresh = False
    previous_session = object()
    for frame in sorted(
        frames, key=lambda item: (str(item.get("session_id")), str(item.get("occurred_at_utc")))
    ):
        session = frame.get("session_id")
        if session != previous_session:
            previous_fresh = False
            previous_session = session
        fresh = (frame.get("recent_candidate_count") or 0) > 0
        if fresh and not previous_fresh:
            runs += 1
        previous_fresh = fresh
    return runs


FAVORABLE = "favorável"
ADVERSE = "adversa"
NEUTRAL = "neutra"


def _parse_time(value: Any) -> Any:
    from datetime import datetime

    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_outcomes(
    frames: Sequence[Mapping[str, Any]],
    *,
    bar_seconds: float = 60.0,
    horizon_bars: int = 3,
    min_move_units: float = 0.5,
) -> dict[str, Any]:
    """O que o preço fez depois de cada sinal, em unidades de faixa.

    A vela do sinal é localizada na escada de idades de um quadro posterior, de modo
    que entrada e leitura atual ficam no mesmo quadro — imune a mudança de escala.
    Não há preço, nome de ativo nem payout aqui: é deslocamento relativo à faixa
    mediana do momento.
    """
    if horizon_bars < 1:
        raise ValueError("horizon_bars precisa ser pelo menos 1.")
    timeline = sorted(
        (frame for frame in frames if frame.get("price_ladder")),
        key=lambda item: str(item.get("occurred_at_utc")),
    )
    signals = [
        frame
        for frame in timeline
        if frame.get("code") in ("A", "B", "C") and (frame.get("features") or {}).get("age_bars") is not None
    ]
    graded_total = sum(1 for frame in frames if frame.get("code") in ("A", "B", "C"))
    results: list[dict[str, Any]] = []
    skipped = 0
    for frame in signals:
        features = frame.get("features") or {}
        direction = features.get("direction")
        age = features.get("age_bars")
        started = _parse_time(frame.get("occurred_at_utc"))
        if direction not in ("BUY", "SELL") or not isinstance(age, int) or started is None:
            skipped += 1
            continue
        target = None
        # O quadro de referência pode ser qualquer um com escada: exigir que ele
        # também esteja classificado descartava quase todos os sinais.
        for later in timeline:
            if later.get("session_id") != frame.get("session_id"):
                continue
            if str(later.get("occurred_at_utc")) <= str(frame.get("occurred_at_utc")):
                continue
            when = _parse_time(later.get("occurred_at_utc"))
            if when is None:
                continue
            elapsed = (when - started).total_seconds()
            if elapsed >= bar_seconds * horizon_bars * 0.8:
                target = (later, elapsed)
                break
        if target is None:
            skipped += 1
            continue
        later, elapsed = target
        bars_elapsed = max(1, round(elapsed / bar_seconds))
        ladder = later["price_ladder"]
        closes = ladder.get("closes_px") or []
        typical_range = ladder.get("median_range_px")
        entry_index = age + bars_elapsed
        if not typical_range or typical_range <= 0 or entry_index >= len(closes):
            skipped += 1
            continue
        entry_now = closes[entry_index]
        current = closes[0]
        if entry_now is None or current is None:
            skipped += 1
            continue
        # y menor = preço maior.
        move = (float(entry_now) - float(current)) / float(typical_range)
        if direction == "SELL":
            move = -move
        if move >= min_move_units:
            outcome = FAVORABLE
        elif move <= -min_move_units:
            outcome = ADVERSE
        else:
            outcome = NEUTRAL
        results.append(
            {
                "grade": frame.get("code"),
                "direction": direction,
                "outcome": outcome,
                "move_units": round(move, 3),
                "bars_elapsed": bars_elapsed,
            }
        )

    by_grade: dict[str, dict[str, Any]] = {}
    for item in results:
        bucket = by_grade.setdefault(
            item["grade"],
            {"favorável": 0, "neutra": 0, "adversa": 0, "moves": []},
        )
        bucket[item["outcome"]] += 1
        bucket["moves"].append(item["move_units"])

    summary: dict[str, Any] = {}
    for grade, bucket in sorted(by_grade.items()):
        total = bucket["favorável"] + bucket["neutra"] + bucket["adversa"]
        summary[grade] = {
            "total": total,
            "favorável": bucket["favorável"],
            "neutra": bucket["neutra"],
            "adversa": bucket["adversa"],
            "median_move_units": (
                round(median(bucket["moves"]), 3) if bucket["moves"] else None
            ),
        }

    return {
        "evaluated": len(results),
        "skipped": skipped,
        "signals_with_ladder": len(signals),
        "signals_graded": graded_total,
        "frames_with_ladder": len(timeline),
        "horizon_bars": horizon_bars,
        "bar_seconds": bar_seconds,
        "min_move_units": min_move_units,
        "by_grade": summary,
    }


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("sem valores")
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def summarize(
    frames: Iterable[Mapping[str, Any]],
    tracks: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    frames = list(frames)
    tracks = list(tracks or [])
    counts: dict[str, int] = {}
    for frame in frames:
        code = str(frame.get("code") or "DESCONHECIDO")
        counts[code] = counts.get(code, 0) + 1

    with_features = [frame for frame in frames if frame.get("features")]
    coverage = {
        name: sum(1 for frame in with_features if frame["features"].get(name) is not None)
        for name in FEATURE_FIELDS
    }
    distributions: dict[str, dict[str, float]] = {}
    for name in NUMERIC_FEATURES:
        values = [
            float(frame["features"][name])
            for frame in with_features
            if isinstance(frame["features"].get(name), (int, float))
        ]
        if values:
            distributions[name] = {
                "n": len(values),
                "p10": round(_percentile(values, 0.10), 3),
                "p50": round(_percentile(values, 0.50), 3),
                "p90": round(_percentile(values, 0.90), 3),
            }
    ages = [
        frame["features"].get("age_bars")
        for frame in with_features
        if isinstance(frame["features"].get("age_bars"), int)
    ]
    age_counts: dict[str, int] = {}
    for age in ages:
        key = str(age) if age <= 2 else "3+"
        age_counts[key] = age_counts.get(key, 0) + 1

    regimes: dict[str, int] = {}
    for frame in frames:
        key = str(frame.get("context_regime") or "desconhecido")
        regimes[key] = regimes.get(key, 0) + 1

    reason_counts: dict[str, int] = {}
    for frame in frames:
        # Motivos de A/B descrevem o que está bom; somá-los aqui os faria parecer
        # bloqueio.
        if str(frame.get("code")) in ("A", "B"):
            continue
        seen = set()
        for reason in frame.get("reasons") or []:
            if reason in seen:
                continue
            seen.add(reason)
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    top_reasons = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:6]

    raw_labels = sum(1 for frame in frames if (frame.get("raw_candidate_count") or 0) > 0)
    recent_labels = sum(
        1 for frame in frames if (frame.get("recent_candidate_count") or 0) > 0
    )

    raw_label_frames = raw_labels
    tracked = len(tracks)
    by_hash: dict[str, dict[str, Any]] = {}
    for frame in frames:
        key = str(frame.get("criteria_hash") or "sem-hash")
        bucket = by_hash.setdefault(
            key, {"hash": key, "frames": 0, "frames_with_features": 0, "counts": {}}
        )
        bucket["frames"] += 1
        if frame.get("features"):
            bucket["frames_with_features"] += 1
        code = str(frame.get("code") or "DESCONHECIDO")
        bucket["counts"][code] = bucket["counts"].get(code, 0) + 1

    methods: dict[str, int] = {}
    current_measured = 0
    for frame in frames:
        key = str(frame.get("method") or "sem-metodo")
        methods[key] = methods.get(key, 0) + 1
        if key == GRADE_METHOD and frame.get("features"):
            current_measured += 1

    gaps = [
        float(frame["label_geometry"]["median_gap_px"])
        for frame in frames
        if isinstance(frame.get("label_geometry"), dict)
        and isinstance(frame["label_geometry"].get("median_gap_px"), (int, float))
    ]
    right_counts = [
        int(frame["label_geometry"]["bars_to_the_right"])
        for frame in frames
        if isinstance(frame.get("label_geometry"), dict)
        and isinstance(frame["label_geometry"].get("bars_to_the_right"), int)
    ]
    ongrid_counts = [
        int(frame["label_geometry"]["bars_to_the_right_ongrid"])
        for frame in frames
        if isinstance(frame.get("label_geometry"), dict)
        and isinstance(frame["label_geometry"].get("bars_to_the_right_ongrid"), int)
    ]
    regular_shares = [
        float(frame["label_geometry"]["regular_gap_share"])
        for frame in frames
        if isinstance(frame.get("label_geometry"), dict)
        and isinstance(frame["label_geometry"].get("regular_gap_share"), (int, float))
    ]

    references: dict[str, int] = {}
    for frame in frames:
        key = str(frame.get("age_reference") or "detected")
        references[key] = references.get(key, 0) + 1

    detected_counts = [
        int(frame["bars_detected"])
        for frame in frames
        if isinstance(frame.get("bars_detected"), int)
    ]
    kept_counts = [
        int(frame["label_geometry"]["bar_count"])
        for frame in frames
        if isinstance(frame.get("label_geometry"), dict)
        and isinstance(frame["label_geometry"].get("bar_count"), int)
    ]

    return {
        "frames": len(frames),
        "bars_detected_p50": (
            _percentile([float(value) for value in detected_counts], 0.5)
            if detected_counts
            else None
        ),
        "bars_kept_p50": (
            _percentile([float(value) for value in kept_counts], 0.5) if kept_counts else None
        ),
        "age_references": references,
        "methods": methods,
        "current_method_measured": current_measured,
        "label_median_gap_px": round(median(gaps), 1) if gaps else None,
        "label_bars_to_the_right_ongrid": (
            {
                "min": min(ongrid_counts),
                "p50": _percentile([float(value) for value in ongrid_counts], 0.5),
                "max": max(ongrid_counts),
                "n": len(ongrid_counts),
            }
            if ongrid_counts
            else None
        ),
        "regular_gap_share_p50": (
            _percentile(regular_shares, 0.5) if regular_shares else None
        ),
        "label_bars_to_the_right": (
            {
                "min": min(right_counts),
                "p50": _percentile([float(value) for value in right_counts], 0.5),
                "max": max(right_counts),
                "n": len(right_counts),
            }
            if right_counts
            else None
        ),
        "by_criteria_hash": sorted(by_hash.values(), key=lambda item: item["hash"]),
        "tracked_positions": tracked,
        "frames_per_track": round(raw_label_frames / tracked, 1) if tracked else None,
        "fresh_signal_runs": _fresh_signal_runs(frames),
        "frames_with_raw_label": raw_labels,
        "frames_with_recent_label": recent_labels,
        "context_regimes": regimes,
        "top_reasons": [{"reason": reason, "count": count} for reason, count in top_reasons],
        "frames_with_features": len(with_features),
        "palette_calibrated_frames": sum(1 for frame in frames if frame.get("palette_calibrated")),
        "sessions": len({frame.get("session_id") for frame in frames if frame.get("session_id")}),
        "first_frame_at_utc": frames[0]["occurred_at_utc"] if frames else None,
        "last_frame_at_utc": frames[-1]["occurred_at_utc"] if frames else None,
        "counts": {code: counts.get(code, 0) for code in GRADE_ORDER if code in counts},
        "other_codes": {
            code: count for code, count in sorted(counts.items()) if code not in GRADE_ORDER
        },
        "coverage": coverage,
        "age_bars_counts": age_counts,
        "min_age_observed": min(ages) if ages else None,
        "max_age_observed": max(ages) if ages else None,
        "distributions": distributions,
        "criteria_hashes": sorted(
            {str(frame["criteria_hash"]) for frame in frames if frame.get("criteria_hash")}
        ),
    }


def _features_from_dict(data: Mapping[str, Any]) -> SignalFeatures:
    return SignalFeatures(**{name: data.get(name) for name in FEATURE_FIELDS})


def sweep(
    frames: Iterable[Mapping[str, Any]],
    parameter: str,
    values: Sequence[Any],
    base: GradeCriteria = DEFAULT_CRITERIA,
) -> list[dict[str, Any]]:
    """Recalcula as classes variando um limiar, sobre os quadros já gravados."""
    if parameter not in base.as_dict():
        raise ValueError(f"Limiar desconhecido: {parameter}")
    with_features = [frame for frame in frames if frame.get("features")]
    results: list[dict[str, Any]] = []
    for value in values:
        criteria = GradeCriteria(**{**base.as_dict(), parameter: value})
        problems = validate_grade_criteria(criteria)
        if problems:
            results.append({"value": value, "invalid": "; ".join(problems)})
            continue
        counts = {code: 0 for code in GRADE_ORDER}
        for frame in with_features:
            grade = grade_opportunity(
                _features_from_dict(frame["features"]), criteria
            )
            counts[grade.code] = counts.get(grade.code, 0) + 1
        results.append(
            {
                "value": value,
                "graded": len(with_features),
                "counts": {code: count for code, count in counts.items() if count},
            }
        )
    return results


def _format_counts(counts: Mapping[str, int], total: int) -> str:
    if not total:
        return "    (sem quadros)"
    parts = []
    for code, count in counts.items():
        parts.append(f"{code}={count} ({count / total:.0%})")
    return "    " + " · ".join(parts)


def format_outcomes(outcomes: Mapping[str, Any]) -> str:
    lines = ["", "DESFECHO OBSERVADO DEPOIS DOS SINAIS"]
    lines.append(
        f"    horizonte: {outcomes['horizon_bars']} vela(s) · "
        f"vela de {outcomes['bar_seconds']:.0f} s · "
        f"movimento mínimo: {outcomes['min_move_units']} faixa(s)"
    )
    lines.append(
        f"    sinais classificados: {outcomes.get('signals_graded', 0)} · "
        f"com escada de preço: {outcomes.get('signals_with_ladder', 0)} · "
        f"quadros com escada: {outcomes.get('frames_with_ladder', 0)}"
    )
    if not outcomes["evaluated"]:
        lines.append("    Nenhum sinal pôde ser acompanhado até o horizonte.")
        lines.append(
            f"    ({outcomes['skipped']} sinal(is) sem quadro posterior suficiente.)"
        )
        if outcomes.get("frames_with_ladder", 0) == 0:
            lines.append(
                "    A escada de preço só passou a ser gravada depois desta versão: "
                "sessões antigas não podem ser avaliadas."
            )
    else:
        lines.append(
            f"    sinais acompanhados: {outcomes['evaluated']} · "
            f"descartados: {outcomes['skipped']}"
        )
        lines.append("")
        lines.append("    classe   n     favorável   neutra   adversa   movimento mediano")
        for grade, bucket in outcomes["by_grade"].items():
            total = bucket["total"] or 1
            lines.append(
                f"    {grade:<7} {bucket['total']:>4}   "
                f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})   "
                f"{bucket['neutra']:>4}   {bucket['adversa']:>4}   "
                f"{bucket['median_move_units']:>7}"
            )
    lines += [
        "",
        "    Isto NÃO é taxa de acerto. Mede deslocamento relativo à faixa mediana,",
        "    sem custo, sem spread, sem payout e sem resultado financeiro. Serve para",
        "    comparar classes entre si na mesma amostra, não para prever nada.",
        "    A conversão de tempo em velas assume o período informado em --bar-seconds;",
        "    se o gráfico não for de 1 minuto, o horizonte medido estará errado.",
    ]
    return "\n".join(lines)


def format_report(summary: Mapping[str, Any], sweeps: Sequence[tuple[str, Sequence[Mapping[str, Any]]]] = ()) -> str:
    lines = ["RELATÓRIO DE CALIBRAÇÃO DA CLASSIFICAÇÃO", ""]
    if not summary["frames"]:
        lines.append("Nenhum quadro OCR_COMPLETED com classificação no journal.")
        lines.append("Ative a captura com a paleta calibrada e rode de novo.")
        return "\n".join(lines)

    lines.append(f"Quadros classificados: {summary['frames']}")
    lines.append(f"Quadros com medidas de vela: {summary['frames_with_features']}")
    lines.append(f"Quadros com paleta calibrada: {summary['palette_calibrated_frames']}")
    lines.append(f"Sessões: {summary['sessions']}")
    lines.append(
        f"Período: {summary['first_frame_at_utc']} → {summary['last_frame_at_utc']}"
    )
    if summary["criteria_hashes"]:
        lines.append(f"Hash(es) dos limiares: {', '.join(summary['criteria_hashes'])}")
    lines += ["", "Distribuição atual das classes:"]
    lines.append(_format_counts(summary["counts"], summary["frames"]))

    lines += ["", "Cobertura das medidas (quadros com candidato):"]
    base = summary["frames_with_features"]
    for name, count in summary["coverage"].items():
        share = f"{count / base:.0%}" if base else "—"
        lines.append(f"    {name:<22} {count:>6}  ({share})")

    lines += ["", "Rótulos vistos pelo OCR:"]
    lines.append(f"    com algum rótulo no quadro   {summary['frames_with_raw_label']}")
    lines.append(f"    com rótulo nas 2 últimas     {summary['frames_with_recent_label']}")

    if summary.get("fresh_signal_runs") is not None:
        lines.append(f"    séries de rótulo recente     {summary['fresh_signal_runs']}")
    if summary.get("tracked_positions"):
        lines.append(f"    rastros de posição           {summary['tracked_positions']}")
        lines.append(
            f"    quadros por rastro           {summary['frames_per_track']}"
        )
        lines.append(
            "    Rastro não é sinal: a identidade usa posição em pixels e o instante da"
        )
        lines.append(
            "    primeira visão, então a rolagem do gráfico fragmenta o mesmo rótulo."
        )

    if summary["context_regimes"]:
        ordered = sorted(
            summary["context_regimes"].items(), key=lambda item: (-item[1], item[0])
        )
        lines += ["", "Regime de contexto nos quadros:"]
        lines.append(
            "    " + " · ".join(f"{name}={count}" for name, count in ordered)
        )

    if summary["top_reasons"]:
        lines += ["", "Motivos de bloqueio mais frequentes:"]
        for item in summary["top_reasons"]:
            lines.append(f"    {item['count']:>5}  {item['reason']}")

    if summary["age_bars_counts"]:
        ages = " · ".join(
            f"{age} vela(s)={count}" for age, count in sorted(summary["age_bars_counts"].items())
        )
        lines += ["", f"Idade do rótulo: {ages}"]

    observed_min = summary.get("min_age_observed")
    if observed_min is not None:
        lines.append(
            f"    idade mínima observada: {observed_min} vela(s); "
            f"máxima: {summary.get('max_age_observed')}"
        )
        if DEFAULT_CRITERIA.fresh_age_bars is not None and observed_min > DEFAULT_CRITERIA.fresh_age_bars:
            lines.append(
                f"ATENÇÃO: fresh_age_bars={DEFAULT_CRITERIA.fresh_age_bars} exige idade "
                f"{DEFAULT_CRITERIA.fresh_age_bars}, mas nenhum quadro observado ficou abaixo de "
                f"{observed_min}. Com esse limite a classe A é inalcançável nesta tela."
            )
            lines.append(
                "    Nada foi alterado automaticamente: mudar o limite é decisão sua."
            )

    if summary["distributions"]:
        lines += ["", "Percentis das medidas (somente quadros com candidato):"]
        for name, stats in summary["distributions"].items():
            lines.append(
                f"    {name:<22} n={stats['n']:<5} p10={stats['p10']:<7} "
                f"p50={stats['p50']:<7} p90={stats['p90']}"
            )

    if summary.get("age_references"):
        rendered = " · ".join(
            f"{name}={count}" for name, count in sorted(summary["age_references"].items())
        )
        lines += ["", f"Referência da idade do rótulo: {rendered}"]

    if summary.get("methods"):
        lines += ["", "Método de medição (como a geometria foi lida):"]
        for name, count in sorted(summary["methods"].items(), key=lambda item: (-item[1], item[0])):
            state = "atual" if name == GRADE_METHOD else "anterior — não comparável"
            lines.append(f"    {name:<18} {count:>6}  ({state})")
        if not summary.get("current_method_measured"):
            lines.append(
                "    Nenhum quadro medido com o método atual: esta amostra ainda não "
                "testou a correção do setup."
            )

    if summary.get("bars_detected_p50") is not None:
        kept = summary.get("bars_kept_p50")
        kept_text = f"{kept:.0f}" if kept is not None else "—"
        lines.append(
            f"    velas por quadro: detector {summary['bars_detected_p50']:.0f} · "
            f"após higiene {kept_text}"
        )

    if summary.get("label_median_gap_px"):
        lines.append(
            f"    espaçamento mediano entre velas: {summary['label_median_gap_px']} px"
        )
    geometry = summary.get("label_bars_to_the_right")
    if geometry:
        lines.append(
            f"    velas à direita do rótulo: min={geometry['min']} "
            f"p50={geometry['p50']:.0f} máx={geometry['max']} (n={geometry['n']})"
        )
    ongrid = summary.get("label_bars_to_the_right_ongrid")
    if ongrid:
        lines.append(
            f"    à direita, só na grade regular: min={ongrid['min']} "
            f"p50={ongrid['p50']:.0f} máx={ongrid['max']} (n={ongrid['n']})"
        )
    if summary.get("regular_gap_share_p50") is not None:
        share = summary["regular_gap_share_p50"]
        lines.append(f"    espaçamentos regulares: {share:.0%} dos intervalos")
        if share < 0.8:
            lines.append(
                "    Grade irregular: parte das velas detectadas pode ser detecção "
                "fora da grade (eixo, linha, outro painel)."
            )

    if summary.get("by_criteria_hash"):
        lines += ["", "Por versão de limiares (a mais recente aparece por último):"]
        for item in summary["by_criteria_hash"]:
            lines.append(
                f"    {item['hash']}  quadros={item['frames']}  "
                f"com medida={item['frames_with_features']}"
            )
            lines.append("      " + _format_counts(item["counts"], item["frames"]).strip())

    for parameter, results in sweeps:
        lines += ["", f"Sensibilidade de {parameter}:"]
        fingerprints = {
            json.dumps(result.get("counts", {}), sort_keys=True) for result in results
        }
        if len(results) > 1 and len(fingerprints) == 1:
            lines.append(
                "    todos os valores dão o mesmo resultado: outro critério "
                "(idade, regime ou distância) bloqueia antes deste limiar"
            )
        for result in results:
            if "invalid" in result:
                lines.append(f"    {result['value']!r:<8} inválido: {result['invalid']}")
                continue
            lines.append(f"    {result['value']!r:<8}")
            lines.append(
                _format_counts(result["counts"], result["graded"] or 1).replace("    ", "      ", 1)
            )

    lines += [
        "",
        "LIMITES DESTE RELATÓRIO",
        "    · Sem desfecho vinculado aos quadros: nenhuma taxa de acerto pode ser",
        "      calculada, e nenhuma coluna abaixo deve ser lida como probabilidade.",
        "    · Percentis descrevem a amostra observada, não o mercado.",
        "    · Amostra pequena (< 200 quadros com candidato) não sustenta mudança de",
        "      limiar; use os números como ponto de partida, não como conclusão.",
    ]
    return "\n".join(lines)


def _parse_sweep(spec: str) -> tuple[str, list[Any]]:
    if "=" not in spec:
        raise ValueError(f"Formato esperado parametro=v1,v2: {spec}")
    parameter, raw = spec.split("=", 1)
    parameter = parameter.strip()
    if parameter not in DEFAULT_CRITERIA.as_dict():
        raise ValueError(f"Limiar desconhecido: {parameter}")
    default = DEFAULT_CRITERIA.as_dict()[parameter]
    values: list[Any] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if isinstance(default, bool):
            values.append(item.lower() in ("1", "true", "sim"))
        elif isinstance(default, int):
            values.append(int(item))
        else:
            values.append(float(item))
    if not values:
        raise ValueError(f"Nenhum valor em: {spec}")
    return parameter, values


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resume as medidas de classificação gravadas no journal (somente leitura)."
    )
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "Caminho do banco do journal. Padrão: o mesmo do app "
            "(%%LOCALAPPDATA%%\\AutoTraderIQ\\opportunities.sqlite3)."
        ),
    )
    parser.add_argument(
        "--sweep",
        action="append",
        default=[],
        metavar="PARAM=V1,V2",
        help="Varre valores de um limiar, ex.: --sweep max_body_vs_median_b=2,2.5,3",
    )
    parser.add_argument("--json", action="store_true", help="Saída em JSON.")
    parser.add_argument(
        "--bar-seconds",
        type=float,
        default=60.0,
        help="Duração da vela em segundos (padrão: 60, gráfico de 1 minuto).",
    )
    parser.add_argument(
        "--horizon-bars",
        type=int,
        default=3,
        help="Quantas velas depois do sinal avaliar (padrão: 3).",
    )
    parser.add_argument(
        "--min-move",
        type=float,
        default=0.5,
        help="Movimento mínimo, em faixas medianas, para contar como desfecho (padrão: 0.5).",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else default_journal_path()
    if not db_path.exists():
        print(f"Erro: Banco não encontrado: {db_path}")
        print("       Informe outro caminho com --db, ou abra o app uma vez para criar o journal.")
        return 2

    try:
        frames = load_frames(db_path)
        tracks = load_tracks(db_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Erro: {exc}")
        return 2

    summary = summarize(frames, tracks)
    outcomes = compute_outcomes(
        frames,
        bar_seconds=args.bar_seconds,
        horizon_bars=args.horizon_bars,
        min_move_units=args.min_move,
    )
    sweeps: list[tuple[str, list[dict[str, Any]]]] = []
    for spec in args.sweep:
        try:
            parameter, values = _parse_sweep(spec)
        except ValueError as exc:
            print(f"Erro: {exc}")
            return 2
        sweeps.append((parameter, sweep(frames, parameter, values)))

    if args.json:
        print(
            json.dumps(
                {
                    "summary": summary,
                    "sweeps": {parameter: results for parameter, results in sweeps},
                    "accuracy_available": False,
                    "outcomes": outcomes,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report(summary, sweeps))
        print(format_outcomes(outcomes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
