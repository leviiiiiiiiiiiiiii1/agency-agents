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
import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .opportunity_grade import (
    DEFAULT_CRITERIA,
    GradeCriteria,
    SignalFeatures,
    grade_opportunity,
    validate_grade_criteria,
)

FEATURE_FIELDS = tuple(field.name for field in fields(SignalFeatures))
NUMERIC_FEATURES = ("body_vs_median", "distance_to_level", "close_from_extreme")
GRADE_ORDER = ("A", "B", "C", "NO_TRADE", "NO_CANDIDATE", "CRITERIA_UNDEFINED")


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
                "features": features if isinstance(features, dict) else None,
                "palette_calibrated": bool(
                    (payload.get("association") or {}).get("palette_calibrated")
                ),
            }
        )
    return frames


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("sem valores")
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def summarize(frames: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    frames = list(frames)
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

    return {
        "frames": len(frames),
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

    if summary["age_bars_counts"]:
        ages = " · ".join(
            f"{age} vela(s)={count}" for age, count in sorted(summary["age_bars_counts"].items())
        )
        lines += ["", f"Idade do rótulo: {ages}"]

    if summary["distributions"]:
        lines += ["", "Percentis das medidas (somente quadros com candidato):"]
        for name, stats in summary["distributions"].items():
            lines.append(
                f"    {name:<22} n={stats['n']:<5} p10={stats['p10']:<7} "
                f"p50={stats['p50']:<7} p90={stats['p90']}"
            )

    for parameter, results in sweeps:
        lines += ["", f"Sensibilidade de {parameter}:"]
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
    parser.add_argument("--db", required=True, help="Caminho do banco do journal.")
    parser.add_argument(
        "--sweep",
        action="append",
        default=[],
        metavar="PARAM=V1,V2",
        help="Varre valores de um limiar, ex.: --sweep max_body_vs_median_b=2,2.5,3",
    )
    parser.add_argument("--json", action="store_true", help="Saída em JSON.")
    args = parser.parse_args(argv)

    try:
        frames = load_frames(args.db)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Erro: {exc}")
        return 2

    summary = summarize(frames)
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
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report(summary, sweeps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
