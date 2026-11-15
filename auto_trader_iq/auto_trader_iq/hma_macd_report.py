"""Relatório da estratégia HMA + MACD sobre os candles gravados pelo app.

Somente leitura: nada aqui escreve no journal, nada aqui manda ordem. O app
guarda, por quadro, os fechamentos das últimas velas em pixels; este módulo
remonta a série M1 por sessão e roda a estratégia quatro vezes — sem filtro,
com cada filtro isolado e com todos — porque a única pergunta que importa
antes de adotar uma estratégia é se os filtros pagam o que custam.

O que este relatório não faz: prever. Ele mede o que já aconteceu.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from .grade_report import default_journal_path, load_frames
from .hma_macd import (
    HmaMacdConfig,
    StrategyStats,
    backtest,
    confirmation_lags,
    series_from_ladder,
)

MIN_SIGNALS_FOR_READING = 30


def _timing_lines(series: Sequence[Any], config: HmaMacdConfig) -> list[str]:
    """Quanto o MACD demora para confirmar a virada da HMA, medido."""
    lags: list[int] = []
    turns = 0
    for item in series:
        found = confirmation_lags(item.closes, config)
        turns += int(found["turns"])
        lags.extend(found["lags"])
    if not turns:
        return ["", "    Nenhuma virada de HMA na amostra."]
    ordered = sorted(lags)
    lines = [""]
    if not ordered:
        return lines + [
            f"    Viradas da HMA: {turns} · nenhuma confirmada pelo MACD depois da virada."
        ]
    within = sum(1 for lag in ordered if lag <= config.confirm_window)
    median_lag = ordered[len(ordered) // 2]
    half = next(
        (window for window in range(0, max(ordered) + 1) if sum(1 for l in ordered if l <= window) * 2 >= len(ordered)),
        None,
    )
    lines.append(
        f"    Viradas da HMA: {turns} · confirmadas depois: {len(ordered)}"
        f" · atraso mediano {median_lag} vela(s)"
    )
    lines.append(
        f"    Na janela de {config.confirm_window} vela(s): {within} de {turns}"
        f" ({within / turns:.0%}) confirmam; metade das viradas exigiria janela de"
        f" {half} vela(s)."
    )
    return lines


def _variants(base: HmaMacdConfig) -> list[tuple[str, HmaMacdConfig]]:
    clean = base.without_filters()
    return [
        ("sem filtro", clean),
        (
            "só lateralização",
            replace(clean, block_lateral=True, max_direction_changes=base.max_direction_changes),
        ),
        ("só força do MACD", replace(clean, block_weak_hist=True, min_hist_strength=base.min_hist_strength)),
        ("só volatilidade", replace(clean, block_volatility=True, max_range_units=base.max_range_units)),
        ("todos os filtros", base),
    ]


def _merge(total: StrategyStats, part: StrategyStats) -> None:
    total.total += part.total
    total.executed += part.executed
    total.blocked += part.blocked
    total.wins += part.wins
    total.losses += part.losses
    total.draws += part.draws
    total.net += part.net
    for reason, count in part.by_reason.items():
        total.by_reason[reason] = total.by_reason.get(reason, 0) + count
    for source, target in (
        (part.by_hour, total.by_hour),
        (part.by_expiry, total.by_expiry),
        (part.by_asset, total.by_asset),
        (part.by_direction, total.by_direction),
    ):
        for key, bucket in source.items():
            merged = target.setdefault(key, {"n": 0, "wins": 0, "net": 0.0})
            merged["n"] += bucket["n"]
            merged["wins"] += bucket["wins"]
            merged["net"] += bucket["net"]
    total.peak = max(total.peak, part.peak)
    total.max_drawdown = min(total.max_drawdown, part.max_drawdown)


def evaluate(
    series: Sequence[Any],
    config: HmaMacdConfig,
    *,
    payout: float,
    expiry: int | None = None,
) -> StrategyStats:
    total = StrategyStats()
    for item in series:
        part = backtest(
            item.closes,
            config,
            payout=payout,
            expiry_bars=expiry,
            hours=item.hours,
            asset=item.label,
        )
        _merge(total, part)
    return total


def _ev(stats: StrategyStats) -> float | None:
    return stats.net / stats.executed if stats.executed else None


def format_report(
    series: Sequence[Any],
    *,
    config: HmaMacdConfig,
    payout: float,
    expiry: int,
) -> list[str]:
    bars = sum(len(item) for item in series)
    lines = [
        "",
        "HMA + MACD SCALPING M1 - medição sobre os candles gravados",
        f"    séries: {len(series)} · velas: {bars} · payout {payout:.0%}"
        f" · expiração {expiry} vela(s)",
        f"    HMA {config.hma_period} · MACD {config.macd_fast}/{config.macd_slow}"
        f"/{config.macd_signal} · janela de confirmação {config.confirm_window} vela(s)",
        "",
        "    variante            sinais  executadas  bloqueadas  acerto   EV/op   líquido  queda",
    ]
    results: dict[str, StrategyStats] = {}
    for name, variant in _variants(config):
        stats = evaluate(series, variant, payout=payout, expiry=expiry)
        results[name] = stats
        accuracy = stats.accuracy
        ev = _ev(stats)
        lines.append(
            f"    {name:<18} {stats.total:>6} {stats.executed:>11} {stats.blocked:>11}"
            f"   {'-' if accuracy is None else f'{accuracy:>5.0%}'}"
            f"  {'-' if ev is None else f'{ev:>+6.2f}'}"
            f" {stats.net:>+9.2f} {stats.max_drawdown:>+6.2f}"
        )
    lines.extend(_timing_lines(series, config))
    everything = results["todos os filtros"]
    lines.append("")
    lines.append("    Motivos de bloqueio (todos os filtros):")
    if everything.by_reason:
        for reason, count in sorted(everything.by_reason.items(), key=lambda pair: -pair[1]):
            lines.append(f"      {count:>5}  {reason}")
    else:
        lines.append("      nenhum bloqueio")
    if everything.by_hour:
        lines.append("")
        lines.append("    Por hora local (todos os filtros):")
        for hour, bucket in sorted(everything.by_hour.items()):
            if not isinstance(hour, int):
                continue
            total = bucket["n"] or 1
            lines.append(
                f"      {hour:02d}h  n={int(bucket['n']):>4}  acerto"
                f" {bucket['wins'] / total:>4.0%}  líquido {bucket['net']:>+8.2f}"
            )
    if everything.executed < MIN_SIGNALS_FOR_READING:
        lines.append("")
        lines.append(
            f"    Amostra insuficiente: {everything.executed} operação(ões) executada(s)."
            " Abaixo de "
            f"{MIN_SIGNALS_FOR_READING} não há leitura, nem a favor nem contra."
        )
    lines.append("")
    lines.append(
        "    O sinal nasce na vela da confirmação e entra na abertura da seguinte:"
        " nenhuma vela futura é lida, e a série é reconstruída do que foi gravado."
    )
    lines.append(
        "    Sessões não são emendadas e a série é em pixels: ela mede direção,"
        " não preço. Um empate no fechamento conta como perda."
    )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mede a estratégia HMA+MACD sobre os candles gravados (somente leitura)."
    )
    parser.add_argument("--db", default=None, help="Caminho do journal (padrão: o do app).")
    parser.add_argument("--payout", type=float, default=0.86, help="Payout por operação.")
    parser.add_argument("--expiry", type=int, default=1, help="Expiração em velas (padrão: 1).")
    parser.add_argument("--bar-seconds", type=float, default=60.0, help="Duração da vela.")
    parser.add_argument(
        "--confirm-window",
        type=int,
        default=1,
        help="Quantas velas depois da virada da HMA o MACD pode confirmar.",
    )
    parser.add_argument("--json", action="store_true", help="Saída em JSON.")
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else default_journal_path()
    if not db_path.exists():
        print(f"Erro: banco não encontrado: {db_path}")
        return 2
    try:
        frames = load_frames(db_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Erro: {exc}")
        return 2

    series = series_from_ladder(frames, bar_seconds=args.bar_seconds)
    if not series:
        print("Nenhuma série com escada de preço no journal: nada a medir.")
        return 1

    config = HmaMacdConfig(confirm_window=args.confirm_window, expiry_bars=args.expiry)
    if args.json:
        payload = {
            name: evaluate(series, variant, payout=args.payout, expiry=args.expiry).__dict__
            for name, variant in _variants(config)
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0

    print("\n".join(format_report(series, config=config, payout=args.payout, expiry=args.expiry)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
