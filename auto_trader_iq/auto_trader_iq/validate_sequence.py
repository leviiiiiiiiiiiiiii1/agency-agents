"""Command-line audit of HORA ATUAL readings in a local test sequence."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .sequence_validation import validate_sequence_manifest


def _format_gap(seconds: float | None) -> str:
    if seconds is None:
        return "intervalo do gravador desconhecido"
    return f"intervalo do gravador {seconds:.1f} s"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verifica apenas a continuidade do relógio HORA ATUAL no manifest.csv local. "
            "Não abre imagens, avalia sinais ou confirma velas/entradas."
        )
    )
    parser.add_argument("sequencia", type=Path, help="pasta da sequência ou caminho de manifest.csv")
    parser.add_argument(
        "--confianca-minima", type=float, default=70.0,
        help="confiança OCR mínima para contar uma leitura (padrão: 70)",
    )
    args = parser.parse_args(argv)

    try:
        report = validate_sequence_manifest(
            args.sequencia, minimum_clock_confidence=args.confianca_minima
        )
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Não foi possível validar o manifesto: {exc}", file=sys.stderr)
        return 2

    sequence_name = report.manifest_path.parent.name or report.manifest_path.name
    print(f"Validação local do relógio M1 · sequência {sequence_name}")
    print(f"Quadros no manifesto: {report.total_rows}")
    print(
        f"Leituras válidas (confiança >= {args.confianca_minima:g}%): "
        f"{report.valid_clock_rows}/{report.total_rows}"
    )
    print(f"Quadros sem relógio válido: {report.unreadable_or_low_confidence_rows}")
    print(f"Pares de quadros adjacentes legíveis: {len(report.transitions)}")

    rollovers = report.observed_next_minute
    if rollovers:
        print(f"Avanços observados de exatamente um minuto: {len(rollovers)}")
        for transition in rollovers:
            print(
                f"  linha {transition.previous.row_number} {transition.previous.clock_text}"
                f" -> linha {transition.current.row_number} {transition.current.clock_text}"
                f" ({_format_gap(transition.recorder_gap_seconds)})"
            )
    else:
        print("Avanços observados de exatamente um minuto: nenhum")

    discontinuities = report.skipped_minutes
    if discontinuities:
        print(f"Transições com salto/recuo de minuto para revisar: {len(discontinuities)}")
        for transition in discontinuities:
            print(
                f"  linha {transition.previous.row_number} {transition.previous.clock_text}"
                f" -> linha {transition.current.row_number} {transition.current.clock_text}"
                f" ({_format_gap(transition.recorder_gap_seconds)})"
            )

    print(
        "Conclusão: este relatório verifica somente leituras e avanço do relógio da plataforma. "
        "Não confirma nascimento/identidade de N+1, não valida sinais e não autoriza operações."
    )
    return 0 if rollovers else 1


if __name__ == "__main__":
    raise SystemExit(main())
