"""Conta da banca com stop de ganho e de perda por dia.

A banca é do app, não da tela: cada entrada que ele emitiu tem um valor e um
desfecho medido, então o saldo pode ser escrito aqui sem ler número nenhum por
OCR. Ler o saldo do print seria pedir ao OCR o único número que já se sabe.

O dia é o dia local de quem opera (o journal grava UTC), e o stop vale até a
virada: bateu o limite, o app para de emitir sinal naquele dia e registra
quantas entradas deixou passar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

STOP_NONE = "nenhum"
STOP_WIN = "meta de ganho"
STOP_LOSS = "limite de perda"
STOP_BROKE = "sem banca"


@dataclass(frozen=True)
class StopRules:
    """Limites do dia, em fração da banca com que o dia começou."""

    stop_loss_fraction: float = 0.20
    stop_win_fraction: float = 0.30

    def __post_init__(self) -> None:
        if self.stop_loss_fraction <= 0:
            raise ValueError("o limite de perda precisa ser maior que zero")
        if self.stop_win_fraction <= 0:
            raise ValueError("a meta de ganho precisa ser maior que zero")


def day_of(when: str | datetime) -> str:
    """Dia local da entrada. O journal grava UTC; quem opera vive no fuso da máquina."""
    moment = when
    if isinstance(when, str):
        moment = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().date().isoformat()


def run_days(
    entries: Sequence[Mapping[str, Any]],
    *,
    bankroll: float = 200.0,
    stake_amount: float = 5.0,
    payout: float = 0.86,
    rules: StopRules | None = None,
) -> dict[str, Any]:
    """Aplica as entradas em ordem e corta o dia quando o stop bate.

    `entries` precisa vir em ordem cronológica e cada item precisa de `win`
    (True/False; empate conta como perda, como a corretora liquida) e `when`.
    """
    stop = rules or StopRules()
    balance = float(bankroll)
    days: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    total_blocked = 0

    for entry in entries:
        key = day_of(str(entry.get("when") or ""))
        if current is None or current["day"] != key:
            current = {
                "day": key,
                "start_balance": balance,
                "end_balance": balance,
                "entries": 0,
                "wins": 0,
                "losses": 0,
                "blocked": 0,
                "stop": STOP_NONE,
                "ledger": [],
            }
            days.append(current)

        if current["stop"] != STOP_NONE:
            current["blocked"] += 1
            total_blocked += 1
            continue

        stake = float(stake_amount)
        if balance < stake:
            current["stop"] = STOP_BROKE
            current["blocked"] += 1
            total_blocked += 1
            continue

        won = bool(entry.get("win"))
        profit = stake * payout if won else -stake
        balance += profit
        current["entries"] += 1
        current["wins" if won else "losses"] += 1
        current["end_balance"] = balance
        current["ledger"].append(
            {
                "when": str(entry.get("when")),
                "direction": str(entry.get("direction") or ""),
                "stake": stake,
                "win": won,
                "profit": profit,
                "balance": balance,
            }
        )

        day_pnl = balance - current["start_balance"]
        if day_pnl <= -stop.stop_loss_fraction * current["start_balance"]:
            current["stop"] = STOP_LOSS
        elif day_pnl >= stop.stop_win_fraction * current["start_balance"]:
            current["stop"] = STOP_WIN

    taken = sum(day["entries"] for day in days)
    return {
        "days": days,
        "final": balance,
        "entries": taken,
        "blocked": total_blocked,
        "stopped_days": sum(1 for day in days if day["stop"] not in (STOP_NONE,)),
    }
