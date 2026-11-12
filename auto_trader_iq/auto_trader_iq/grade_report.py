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
import math
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


def _measure(
    timeline: Sequence[Mapping[str, Any]],
    start: Mapping[str, Any],
    direction: str,
    age: int,
    bar_seconds: float,
    horizon_bars: int,
    min_move_units: float,
) -> dict[str, Any] | None:
    """Localiza o quadro de referência e mede o deslocamento do preço.

    y menor = preço maior; o sinal de SELL é invertido para que "favorável"
    signifique sempre "andou a favor da aposta".
    """
    started = _parse_time(start.get("occurred_at_utc"))
    if started is None:
        return None
    # O quadro de referência tem que cair no instante do horizonte, não no
    # primeiro quadro depois de 80% dele: com quadros a cada 10 s, aceitar 80%
    # media 2,4 velas e chamava de 3, e 0,83 vela chamado de 1 (daí os empates).
    wanted = bar_seconds * horizon_bars
    tolerance = bar_seconds * 0.4
    target = None
    best_error = None
    # O quadro de referência pode ser qualquer um com escada: exigir que ele
    # também esteja classificado descartava quase todos os sinais.
    for later in timeline:
        if later.get("session_id") != start.get("session_id"):
            continue
        if str(later.get("occurred_at_utc")) <= str(start.get("occurred_at_utc")):
            continue
        when = _parse_time(later.get("occurred_at_utc"))
        if when is None:
            continue
        elapsed = (when - started).total_seconds()
        error = abs(elapsed - wanted)
        if best_error is None or error < best_error:
            best_error = error
            target = (later, elapsed)
        if elapsed > wanted + tolerance:
            break
    if target is None or best_error is None or best_error > tolerance:
        return None
    later, elapsed = target
    bars_elapsed = max(1, int(elapsed / bar_seconds + 0.5))
    ladder = later.get("price_ladder") or {}
    closes = ladder.get("closes_px") or []
    typical_range = ladder.get("median_range_px")
    entry_index = age + bars_elapsed
    if not typical_range or typical_range <= 0 or entry_index >= len(closes):
        return None
    entry_now = closes[entry_index]
    current = closes[0]
    if entry_now is None or current is None:
        return None
    move = (float(entry_now) - float(current)) / float(typical_range)
    if direction == "SELL":
        move = -move
    move = round(move, 3)
    if move == 0:
        move = 0.0  # evita imprimir -0.0 quando o preço não andou
    if move >= min_move_units:
        outcome = FAVORABLE
    elif move <= -min_move_units:
        outcome = ADVERSE
    else:
        outcome = NEUTRAL
    # Mesma janela, imediatamente ANTES da vela de entrada: o sinal só repete
    # um movimento que já aconteceu, ou está apostando contra ele?
    trailing = None
    trailing_index = entry_index + bars_elapsed
    if trailing_index < len(closes):
        older = closes[trailing_index]
        if older is not None:
            trailing = round((float(older) - float(entry_now)) / float(typical_range), 3)
            if trailing == 0:
                trailing = 0.0
    return {
        "outcome": outcome,
        "move_units": move,
        "bars_elapsed": bars_elapsed,
        "trailing_units": trailing,
    }


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
    repeated = 0
    seen_candles: set[tuple[Any, int]] = set()
    for frame in signals:
        features = frame.get("features") or {}
        direction = features.get("direction")
        age = features.get("age_bars")
        if direction not in ("BUY", "SELL") or not isinstance(age, int):
            skipped += 1
            continue
        candle = _entry_candle(frame, bar_seconds)
        if candle is not None:
            if candle in seen_candles:
                repeated += 1
                continue
            seen_candles.add(candle)
        measured = _measure(
            timeline,
            frame,
            direction,
            age,
            bar_seconds,
            horizon_bars,
            min_move_units,
        )
        if measured is None:
            skipped += 1
            continue
        results.append(
            {
                "grade": frame.get("code"),
                "direction": direction,
                "reasons": list(frame.get("reasons") or []),
                "context_opposed": _context_opposed(features),
                **measured,
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

    def _bucket(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        counts = {FAVORABLE: 0, NEUTRAL: 0, ADVERSE: 0}
        moves: list[float] = []
        wins = ties = 0
        for item in items:
            counts[item["outcome"]] += 1
            moves.append(item["move_units"])
            if item["move_units"] > 0:
                wins += 1
            elif item["move_units"] == 0:
                ties += 1
        return {
            "total": len(items),
            **counts,
            "acerta": wins,
            "empata": ties,
            "erra": len(items) - wins - ties,
            "median_move_units": round(median(moves), 3) if moves else None,
        }

    aligned: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        trailing = item.get("trailing_units")
        if trailing is None:
            aligned.setdefault("sem histórico no quadro", []).append(item)
        elif (trailing > 0 and item["direction"] == "BUY") or (
            trailing < 0 and item["direction"] == "SELL"
        ):
            aligned.setdefault("a favor do movimento anterior", []).append(item)
        elif trailing == 0:
            aligned.setdefault("movimento anterior parado", []).append(item)
        else:
            aligned.setdefault("contra o movimento anterior", []).append(item)
    by_alignment = {
        situation: _bucket(items)
        for situation, items in sorted(aligned.items(), key=lambda pair: -len(pair[1]))
    }
    # "A favor do movimento" num período de queda é quase todo SELL: sem separar
    # por direção, o alinhamento só repete o viés de direção já medido.
    by_alignment_direction: dict[str, dict[str, dict[str, Any]]] = {}
    for situation, items in sorted(aligned.items(), key=lambda pair: -len(pair[1])):
        per_direction: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            per_direction.setdefault(item["direction"], []).append(item)
        by_alignment_direction[situation] = {
            direction: _bucket(group) for direction, group in sorted(per_direction.items())
        }

    by_context: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        state = item.get("context_opposed")
        key = (
            "sem contexto no quadro"
            if state is None
            else "contra o contexto"
            if state
            else "a favor do contexto"
        )
        by_context.setdefault(key, []).append(item)
    context_summary = {
        key: _bucket(items)
        for key, items in sorted(by_context.items(), key=lambda pair: -len(pair[1]))
    }

    # Simulação: o que sobraria se o app se abstivesse em cada condição. Nada
    # muda no app — é a conta que precisa existir antes de qualquer regra nova.
    def _against_move(item: Mapping[str, Any]) -> bool:
        return _situation(item.get("trailing_units"), str(item["direction"])) == (
            "contra o movimento anterior"
        )

    def _unknown_move(item: Mapping[str, Any]) -> bool:
        return _situation(item.get("trailing_units"), str(item["direction"])) == (
            "sem histórico no quadro"
        )

    def _against_context(item: Mapping[str, Any]) -> bool:
        return item.get("context_opposed") is True

    veto_rules: list[tuple[str, Any]] = [
        ("contra o movimento anterior", _against_move),
        ("contra o movimento ou sem histórico", lambda item: _against_move(item) or _unknown_move(item)),
        ("contra o contexto", _against_context),
        (
            "contra o movimento anterior ou contra o contexto",
            lambda item: _against_move(item) or _against_context(item),
        ),
    ]
    vetoes: list[dict[str, Any]] = []
    for name, rule in veto_rules:
        if not results:
            break
        kept = [item for item in results if not rule(item)]
        removed = [item for item in results if rule(item)]
        vetoes.append(
            {
                "rule": name,
                "removed": _bucket(removed),
                "kept": _bucket(kept),
            }
        )

    by_reason: dict[str, dict[str, Any]] = {}
    for item in results:
        for reason in item["reasons"]:
            by_reason.setdefault(reason, []).append(item)
    reasons_summary = {
        reason: _bucket(items)
        for reason, items in by_reason.items()
        if len(items) >= 3
    }
    by_reason_direction: dict[str, dict[str, Any]] = {}
    for direction in ("BUY", "SELL"):
        items = [item for item in results if item["direction"] == direction]
        if items:
            by_reason_direction[direction] = _bucket(items)

    # Uma classe que quase só emite SELL não pode ser comparada com outra que
    # quase só emite BUY numa amostra com tendência: o cruzamento separa os dois.
    by_grade_direction_items: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in results:
        by_grade_direction_items.setdefault((item["grade"], item["direction"]), []).append(item)
    by_grade_direction: dict[str, dict[str, dict[str, Any]]] = {}
    for (grade, direction), items in sorted(by_grade_direction_items.items()):
        by_grade_direction.setdefault(grade, {})[direction] = _bucket(items)

    summary: dict[str, Any] = {}
    for grade, bucket in sorted(by_grade.items()):
        total = bucket["favorável"] + bucket["neutra"] + bucket["adversa"]
        moves = bucket["moves"]
        wins = sum(1 for move in moves if move > 0)
        ties = sum(1 for move in moves if move == 0)
        summary[grade] = {
            "total": total,
            "favorável": bucket["favorável"],
            "neutra": bucket["neutra"],
            "adversa": bucket["adversa"],
            "acerta": wins,
            "empata": ties,
            "erra": total - wins - ties,
            "median_move_units": (
                round(median(bucket["moves"]), 3) if bucket["moves"] else None
            ),
        }

    return {
        "evaluated": len(results),
        "by_direction": by_reason_direction,
        "by_grade_direction": by_grade_direction,
        "by_alignment": by_alignment,
        "by_context": context_summary,
        "vetoes": vetoes,
        "by_alignment_direction": by_alignment_direction,
        "by_reason": dict(
            sorted(reasons_summary.items(), key=lambda item: (-item[1]["total"], item[0]))
        ),
        "skipped": skipped,
        "repeated_frames": repeated,
        "signals_with_ladder": len(signals),
        "signals_graded": graded_total,
        "frames_with_ladder": len(timeline),
        "horizon_bars": horizon_bars,
        "bar_seconds": bar_seconds,
        "min_move_units": min_move_units,
        "by_grade": summary,
    }


def _context_opposed(features: Mapping[str, Any]) -> bool | None:
    context = features.get("context_direction")
    direction = features.get("direction")
    if context not in ("BUY", "SELL") or direction not in ("BUY", "SELL"):
        return None
    return context != direction


def _situation(trailing: float | None, direction: str) -> str:
    if trailing is None:
        return "sem histórico no quadro"
    if trailing == 0:
        return "movimento anterior parado"
    aligned = (trailing > 0 and direction == "BUY") or (trailing < 0 and direction == "SELL")
    return "a favor do movimento anterior" if aligned else "contra o movimento anterior"


def _summarize_items(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {FAVORABLE: 0, NEUTRAL: 0, ADVERSE: 0}
    moves: list[float] = []
    wins = ties = 0
    for item in items:
        counts[item["outcome"]] += 1
        move = float(item["move_units"])
        moves.append(move)
        # Liquidação sem limiar: na vela de expiração fechou a favor, empatou ou não.
        # É a única contagem que se compara com payout; "favorável" depende do sarrafo.
        if move > 0:
            wins += 1
        elif move == 0:
            ties += 1
    return {
        "total": len(items),
        **counts,
        "acerta": wins,
        "empata": ties,
        "erra": len(items) - wins - ties,
        "median_move_units": round(median(moves), 3) if moves else None,
    }


def _flip(measured: Mapping[str, Any]) -> dict[str, Any]:
    """Mesma medição vista pela aposta contrária."""
    flipped = {
        FAVORABLE: ADVERSE,
        ADVERSE: FAVORABLE,
        NEUTRAL: NEUTRAL,
    }[measured["outcome"]]
    return {
        "outcome": flipped,
        "move_units": -measured["move_units"] if measured["move_units"] else 0.0,
        "bars_elapsed": measured["bars_elapsed"],
        "trailing_units": measured["trailing_units"],
    }


def compute_baseline(
    frames: Sequence[Mapping[str, Any]],
    *,
    bar_seconds: float = 60.0,
    horizon_bars: int = 3,
    min_move_units: float = 0.5,
) -> dict[str, Any]:
    """O que aconteceria entrando em TODO quadro com escada, sem classificador.

    É o controle que faltava: se os sinais de uma classe acertam na mesma
    proporção que entrar sem critério nenhum na mesma direção, a classe não
    escolheu nada — só a direção do período pagou.
    """
    timeline = sorted(
        (frame for frame in frames if frame.get("price_ladder")),
        key=lambda item: str(item.get("occurred_at_utc")),
    )
    # Uma entrada por vela: cinco quadros do mesmo minuto não são cinco apostas.
    bets = _one_per_bar(timeline, bar_seconds)
    baseline: dict[str, Any] = {
        "frames_with_ladder": len(timeline),
        "bets": len(bets),
    }
    for direction in ("BUY", "SELL"):
        measured_items: list[dict[str, Any]] = []
        for frame in bets:
            measured = _measure(
                timeline,
                frame,
                direction,
                0,
                bar_seconds,
                horizon_bars,
                min_move_units,
            )
            if measured is None:
                continue
            measured_items.append(measured)
        baseline[direction] = _summarize_items(measured_items)

    # Mesma ideia, agora com a única condição que separou algo nos sinais:
    # apostar a favor do movimento anterior, em TODO quadro, sem classificador.
    situations: dict[str, list[dict[str, Any]]] = {}
    situations_by_direction: dict[str, dict[str, list[dict[str, Any]]]] = {}
    by_regime: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def _add(situation: str, measured: Mapping[str, Any]) -> None:
        situations.setdefault(situation, []).append(dict(measured))

    def _add_directed(situation: str, direction: str, measured: Mapping[str, Any]) -> None:
        situations_by_direction.setdefault(situation, {}).setdefault(direction, []).append(
            dict(measured)
        )

    for frame in bets:
        measured = _measure(
            timeline,
            frame,
            "BUY",
            0,
            bar_seconds,
            horizon_bars,
            min_move_units,
        )
        if measured is None:
            continue
        trailing = measured["trailing_units"]
        if trailing is None:
            _add("sem histórico no quadro", measured)
            continue
        if trailing == 0:
            _add("movimento anterior parado", measured)
            continue
        with_move = measured if trailing > 0 else _flip(measured)
        regime = str(frame.get("context_regime") or "desconhecido")
        by_regime.setdefault(regime, {"seguir": [], "contra": []})["seguir"].append(
            with_move
        )
        by_regime[regime]["contra"].append(_flip(with_move))
        ahead = "BUY" if trailing > 0 else "SELL"
        behind = "SELL" if ahead == "BUY" else "BUY"
        opposite = _flip(with_move)
        _add("seguindo o movimento anterior", with_move)
        _add("contra o movimento anterior", opposite)
        _add_directed("seguindo o movimento anterior", ahead, with_move)
        _add_directed("contra o movimento anterior", behind, opposite)

    baseline["by_regime"] = {
        regime: {
            "seguir": _summarize_items(groups["seguir"]),
            "contra": _summarize_items(groups["contra"]),
        }
        for regime, groups in by_regime.items()
    }
    baseline["by_situation"] = {
        situation: _summarize_items(items) for situation, items in situations.items()
    }
    baseline["by_situation_direction"] = {
        situation: {
            direction: _summarize_items(items) for direction, items in directions.items()
        }
        for situation, directions in situations_by_direction.items()
    }
    return baseline


def compute_session_comparison(
    frames: Sequence[Mapping[str, Any]],
    *,
    bar_seconds: float = 60.0,
    horizon_bars: int = 3,
    min_move_units: float = 0.5,
) -> list[dict[str, Any]]:
    """Sinais e linha de base medidos no MESMO período.

    Comparar sinal de uma hora de queda com base de um dia inteiro mistura
    regimes. Aqui cada sessão traz as três contagens feitas na mesma janela.
    """
    timeline = sorted(
        (frame for frame in frames if frame.get("price_ladder")),
        key=lambda item: str(item.get("occurred_at_utc")),
    )
    starts: dict[str, float] = {}
    for frame in timeline:
        session = str(frame.get("session_id") or "?")
        when = _parse_time(frame.get("occurred_at_utc"))
        if when is None:
            continue
        if session not in starts or when.timestamp() < starts[session]:
            starts[session] = when.timestamp()
    sessions: dict[tuple[str, int], dict[str, Any]] = {}
    bets = set(id(frame) for frame in _one_per_bar(timeline, bar_seconds))
    seen_signal_candles: set[tuple[Any, int]] = set()
    for frame in timeline:
        session = str(frame.get("session_id") or "?")
        when = _parse_time(frame.get("occurred_at_utc"))
        block = 0
        if when is not None and session in starts:
            block = int((when.timestamp() - starts[session]) // BLOCK_SECONDS)
        slot = sessions.setdefault(
            (session, block),
            {
                "signals": [],
                "following": [],
                "against": [],
                "flow": [],
                "base": [],
                "started_at_utc": None,
            },
        )
        if slot["started_at_utc"] is None:
            slot["started_at_utc"] = frame.get("occurred_at_utc")
        features = frame.get("features") or {}
        code = frame.get("code")
        age = features.get("age_bars")
        direction = features.get("direction")
        candle = _entry_candle(frame, bar_seconds)
        if candle is not None and candle in seen_signal_candles:
            candle = None
        elif code in ("A", "B", "C") and candle is not None:
            seen_signal_candles.add(candle)
        if (
            code in ("A", "B", "C")
            and isinstance(age, int)
            and direction in ("BUY", "SELL")
            and candle is not None
        ):
            measured = _measure(
                timeline, frame, direction, age, bar_seconds, horizon_bars, min_move_units
            )
            if measured is not None:
                slot["signals"].append(
                    {
                        **measured,
                        "direction": direction,
                        "situation": _situation(measured["trailing_units"], direction),
                    }
                )
        if id(frame) not in bets:
            # Mesma vela já votou neste minuto.
            continue
        # Fluxo é independente do movimento anterior: entra antes dos descartes.
        _, flow_directions = _flow_directions(frame.get("price_ladder") or {}, FLOW_WINDOW)
        if flow_directions and flow_directions[0] is not None:
            streak = 0
            for item in flow_directions:
                if item != flow_directions[0]:
                    break
                streak += 1
            if streak >= 2:
                flow_measured = _measure(
                    timeline,
                    frame,
                    flow_directions[0],
                    0,
                    bar_seconds,
                    horizon_bars,
                    min_move_units,
                )
                if flow_measured is not None:
                    slot["flow"].append(
                        {**flow_measured, "direction": flow_directions[0]}
                    )

        measured = _measure(
            timeline, frame, "BUY", 0, bar_seconds, horizon_bars, min_move_units
        )
        if measured is None:
            continue
        # Base cega por direção: a mesma sessão, sem escolher quadro.
        slot["base"].append({**measured, "direction": "BUY"})
        slot["base"].append({**_flip(measured), "direction": "SELL"})
        trailing = measured["trailing_units"]
        if trailing is None or trailing == 0:
            continue
        with_move = measured if trailing > 0 else _flip(measured)
        slot["following"].append(with_move)
        slot["against"].append(_flip(with_move))
    rows = []
    for (session, block), slot in sorted(
        sessions.items(), key=lambda pair: str(pair[1]["started_at_utc"])
    ):
        # Sessão sem sinal ainda interessa: mostra o que a regra de fluxo faria ali.
        if not slot["signals"] and not slot["flow"]:
            continue
        by_direction: dict[str, list[Mapping[str, Any]]] = {}
        by_situation: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for item in slot["signals"]:
            by_direction.setdefault(str(item["direction"]), []).append(item)
            by_situation.setdefault(
                (str(item["situation"]), str(item["direction"])), []
            ).append(item)
        rows.append(
            {
                "session": session,
                "block": block,
                "started_at_utc": slot["started_at_utc"],
                "signals": _summarize_items(slot["signals"]),
                "signals_by_direction": {
                    direction: _summarize_items(items)
                    for direction, items in sorted(by_direction.items())
                },
                "signals_by_situation": [
                    {
                        "situation": situation,
                        "direction": direction,
                        **_summarize_items(items),
                    }
                    for (situation, direction), items in sorted(
                        by_situation.items(), key=lambda pair: -len(pair[1])
                    )
                ],
                "following": _summarize_items(slot["following"]),
                "against": _summarize_items(slot["against"]),
                "flow": _summarize_items(slot["flow"]),
                "flow_by_direction": {
                    direction: _summarize_items(
                        [item for item in slot["flow"] if item["direction"] == direction]
                    )
                    for direction in ("BUY", "SELL")
                    if any(item["direction"] == direction for item in slot["flow"])
                },
                "base_by_direction": {
                    direction: _summarize_items(
                        [item for item in slot["base"] if item["direction"] == direction]
                    )
                    for direction in ("BUY", "SELL")
                    if any(item["direction"] == direction for item in slot["base"])
                },
            }
        )
    return rows


# Calibração de cor informada pelo usuário: vela branca é de BAIXA neste gráfico.
COLOR_DIRECTION = {"green": "BUY", "red": "SELL", "white": "SELL"}

# Bloco de comparação: dentro de uma sessão longa, uma hora é o pedaço que pode
# se comportar como regime próprio. Sem isso, uma sessão de 5 horas vira "uma
# sessão" e o teste de "é a hora?" não tem como separar nada.
BLOCK_SECONDS = 3600

FLOW_WINDOW = 5

# Payout informado pelo usuário: ele opera entre 85% e 90%. Abaixo de 1/(1+p)
# a aposta perde dinheiro mesmo acertando mais da metade das vezes.
PAYOUT_MIN = 0.85
PAYOUT_MAX = 0.90


def _breakeven(payout: float) -> float:
    """Acerto mínimo para empatar com esse payout (empate conta como perda)."""
    return 1.0 / (1.0 + payout)


def _expected_value(rate: float, payout: float) -> float:
    """Lucro esperado por unidade apostada: acerta e recebe o payout, erra e perde 1."""
    return rate * (1.0 + payout) - 1.0


def _flow_directions(ladder: Mapping[str, Any], window: int) -> tuple[str, list[str | None]]:
    """Direção de cada uma das últimas velas: por cor quando existe, por fechamento
    quando o quadro é antigo e só guardou a escada de fechamentos."""
    colors = list(ladder.get("colors") or [])[:window]
    by_color = [COLOR_DIRECTION.get(str(color)) for color in colors]
    if len(by_color) >= window and all(direction for direction in by_color):
        return "cores", by_color
    closes = list(ladder.get("closes_px") or [])[:window]
    steps: list[str | None] = []
    for index in range(min(window - 1, len(closes) - 1)):
        newer, older = closes[index], closes[index + 1]
        if newer is None or older is None:
            steps.append(None)
        elif float(newer) < float(older):
            steps.append("BUY")
        elif float(newer) > float(older):
            steps.append("SELL")
        else:
            steps.append(None)
    return "fechamentos", steps


def _entry_candle(
    frame: Mapping[str, Any], bar_seconds: float
) -> tuple[Any, int] | None:
    """Qual vela o sinal está apostando.

    O mesmo candle aparece em vários quadros (o app reclassifica enquanto ele
    forma). Contar cada quadro como um sinal multiplica a amostra pelo número
    de quadros por vela e faz a mesma aposta votar várias vezes.
    """
    when = _parse_time(frame.get("occurred_at_utc"))
    age = (frame.get("features") or {}).get("age_bars")
    if when is None or not isinstance(age, int):
        return None
    window = max(1.0, float(bar_seconds))
    return (frame.get("session_id"), int(when.timestamp() // window) - age)


def _one_per_bar(
    timeline: Sequence[Mapping[str, Any]], bar_seconds: float
) -> list[Mapping[str, Any]]:
    """Uma aposta por vela.

    Quadros do mesmo minuto leem a mesma vela: contá-los todos infla o n e faz
    o mesmo minuto votar cinco vezes. Fica o quadro mais recente de cada vela.
    """
    window = max(1.0, float(bar_seconds))
    latest: dict[tuple[Any, int], Mapping[str, Any]] = {}
    for frame in timeline:
        when = _parse_time(frame.get("occurred_at_utc"))
        if when is None:
            continue
        key = (frame.get("session_id"), int(when.timestamp() // window))
        latest[key] = frame
    return list(latest.values())


def compute_flow_rule(
    frames: Sequence[Mapping[str, Any]],
    *,
    bar_seconds: float = 60.0,
    horizon_bars: int = 3,
    min_move_units: float = 0.5,
    window: int = FLOW_WINDOW,
) -> dict[str, Any]:
    """A aposta que o usuário propôs: entrar na direção das últimas velas da mesma
    cor, quando há pelo menos duas seguidas. Mede a regra, não a implementa."""
    timeline = sorted(
        (frame for frame in frames if frame.get("price_ladder")),
        key=lambda item: str(item.get("occurred_at_utc")),
    )
    # Modo único para o relatório: o que a maioria dos quadros permite ler. Quadros
    # antigos não têm cor gravada; misturar os dois modos na mesma tabela mentiria.
    mode_counts: dict[str, int] = {}
    for frame in timeline:
        found = _flow_directions(frame.get("price_ladder") or {}, window)[0]
        mode_counts[found] = mode_counts.get(found, 0) + 1
    mode = max(mode_counts, key=lambda key: mode_counts[key]) if mode_counts else "fechamentos"
    by_streak: dict[int, list[dict[str, Any]]] = {}
    for frame in _one_per_bar(timeline, bar_seconds):
        ladder = frame.get("price_ladder") or {}
        found_mode, directions = _flow_directions(ladder, window)
        if found_mode != mode or not directions or directions[0] is None:
            continue
        direction = directions[0]
        streak = 0
        for item in directions:
            if item != direction:
                break
            streak += 1
        measured = _measure(
            timeline, frame, direction, 0, bar_seconds, horizon_bars, min_move_units
        )
        if measured is None:
            continue
        by_streak.setdefault(streak, []).append({**measured, "direction": direction})
    def _settle(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        total = len(items)
        wins = sum(1 for item in items if float(item["move_units"]) > 0)
        ties = sum(1 for item in items if float(item["move_units"]) == 0)
        return {"total": total, "acerta": wins, "empata": ties, "erra": total - wins - ties}

    picked = [item for streak, items in by_streak.items() if streak >= 2 for item in items]
    settlement = {
        "todas": _settle(picked),
        "BUY": _settle([item for item in picked if item["direction"] == "BUY"]),
        "SELL": _settle([item for item in picked if item["direction"] == "SELL"]),
    }
    return {
        "mode": mode,
        "window": window,
        "settlement": settlement,
        "by_streak": {
            streak: _summarize_items(items) for streak, items in sorted(by_streak.items())
        },
        "by_streak_direction": {
            streak: {
                direction: _summarize_items(
                    [item for item in items if item["direction"] == direction]
                )
                for direction in ("BUY", "SELL")
                if any(item["direction"] == direction for item in items)
            }
            for streak, items in sorted(by_streak.items())
        },
    }


def format_flow_rule(flow: Mapping[str, Any]) -> str:
    mode = flow.get("mode")
    window = flow.get("window") or FLOW_WINDOW
    source = (
        "cores (verde=alta · vermelha/branca=baixa)"
        if mode == "cores"
        else "fechamentos (sem cor gravada nos quadros antigos)"
    )
    lines = [
        "",
        f"    REGRA DE FLUXO - últimas {window} velas, lidas por {source}",
        "    (entrar na direção das velas seguidas; nada muda no app, isto é medição)",
        "    (uma aposta por vela: quadros do mesmo minuto leem a mesma vela e contam uma vez)",
        "    velas seguidas    n   favorável   neutra   adversa   mediano",
    ]
    streaks = flow.get("by_streak") or {}
    if not streaks:
        lines.append("    Nenhum quadro pôde ser lido com essa janela.")
        return "\n".join(lines)
    for streak, bucket in streaks.items():
        total = bucket["total"] or 1
        lines.append(
            f"    {streak:>2} seguidas     {bucket['total']:>4}   "
            f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})   "
            f"{bucket['neutra']:>4}   {bucket['adversa']:>4}   "
            f"{bucket['median_move_units']:>7}"
        )
    for minimum in (2, 3):
        kept = [
            bucket
            for streak, bucket in streaks.items()
            if streak >= minimum
        ]
        if not kept:
            continue
        total = sum(bucket["total"] for bucket in kept)
        favorable = sum(bucket["favorável"] for bucket in kept)
        if not total:
            continue
        lines.append(
            f"    Regra de {minimum}+ velas seguidas: {favorable}/{total}"
            f" ({favorable / total:.0%}) favorável"
        )
    splits = flow.get("by_streak_direction") or {}
    if splits:
        lines.append("")
        lines.append("    Mesma regra separada por direção:")
        lines.append("    velas seguidas  direção    n   favorável")
        for streak, directions in splits.items():
            for direction, bucket in directions.items():
                total = bucket["total"] or 1
                lines.append(
                    f"    {streak:>2} seguidas     {direction:<7} {bucket['total']:>4}   "
                    f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})"
                )
    settlement = flow.get("settlement") or {}
    if settlement:
        lines.append("")
        lines.append(
            "    LIQUIDAÇÃO NA VELA DE EXPIRAÇÃO - fechou a favor, sem limiar de movimento"
        )
        lines.append(
            f"    (equilíbrio: {_breakeven(PAYOUT_MIN):.1%} com payout {PAYOUT_MIN:.0%}"
            f" · {_breakeven(PAYOUT_MAX):.1%} com {PAYOUT_MAX:.0%};"
            " empate conta como perda)"
        )
        lines.append(
            "    aposta 2+ velas    n   acerta   empata    erra   acerto   margem 95%"
            "   EV 85%   EV 90%"
        )
        for label in ("todas", "BUY", "SELL"):
            bucket = settlement.get(label) or {}
            total = bucket.get("total") or 0
            if not total:
                continue
            rate = bucket["acerta"] / total
            margin = 1.96 * math.sqrt(rate * (1 - rate) / total)
            low = rate - margin
            high = rate + margin
            lines.append(
                f"    {label:<14} {total:>5}   {bucket['acerta']:>6}   "
                f"{bucket['empata']:>7}   {bucket['erra']:>6}   "
                f"{rate:>6.0%}   +/-{margin * 100:>3.0f}pp"
                f"   {_expected_value(rate, PAYOUT_MIN):>+6.0%}"
                f"   {_expected_value(rate, PAYOUT_MAX):>+6.0%}"
            )
            if label == "todas":
                lines.append(
                    f"    {'':<14} com a margem desta rodada, o resultado a 85% vai de"
                    f" {_expected_value(low, PAYOUT_MIN):+.0%}"
                    f" a {_expected_value(high, PAYOUT_MIN):+.0%} por aposta"
                )
                if bucket["empata"] / total >= 0.10:
                    lines.append(
                        f"    {'':<14} {bucket['empata'] / total:.0%} de empates: o preço"
                        " não cruzou um pixel dentro da janela. Empate contado como"
                        " perda; leia este horizonte com cautela."
                    )
    return "\n".join(lines)


def format_session_comparison(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "",
        "    POR BLOCO DE 60 MIN - sinais e base na MESMA janela de mercado",
        "    (sessão longa é cortada em blocos; se o sinal bate a base aqui dentro,",
        "     o ganho não é o regime da hora)",
        "    (fluxo, base e sinais contados uma vez por vela)",
        "    início            sinais n/fav     seguir n/fav     fluxo2+ n/fav",
    ]
    if not rows:
        lines.append("    Nenhuma sessão com sinal acompanhado até o horizonte.")
        return "\n".join(lines)
    for row in rows:
        signals = row["signals"]
        following = row["following"]
        following = row["following"]
        flow = row.get("flow") or {"total": 0, FAVORABLE: 0}
        signals_total = signals["total"] or 1
        following_total = following["total"] or 1
        flow_total = flow["total"] or 1
        started = str(row.get("started_at_utc") or "")[:16].replace("T", " ")
        lines.append(
            f"    {started:<17} {signals['total']:>4}/{signals[FAVORABLE]:<3}"
            f" ({signals[FAVORABLE] / signals_total:>4.0%})  "
            f"{following['total']:>4}/{following[FAVORABLE]:<3}"
            f" ({following[FAVORABLE] / following_total:>4.0%})  "
            f"{flow['total']:>4}/{flow[FAVORABLE]:<3}"
            f" ({flow[FAVORABLE] / flow_total:>4.0%})"
        )
    lines.append("")
    lines.append(
        "    Sinais de cada sessão por situação e direção (para ver se o app brigou"
        " com o movimento):"
    )
    for row in rows:
        started = str(row.get("started_at_utc") or "")[:16].replace("T", " ")
        parts = []
        for entry in row.get("signals_by_situation") or []:
            total = entry["total"] or 1
            parts.append(
                f"{entry['direction']} {entry['situation'].replace(' anterior', '')}"
                f" {entry['total']}/{entry[FAVORABLE]} ({entry[FAVORABLE] / total:.0%})"
            )
        detail = " · ".join(parts) if parts else "(sem sinal)"
        lines.append(f"    {started:<17} {detail}")
        flow_split = row.get("flow_by_direction") or {}
        if flow_split:
            base_split = row.get("base_by_direction") or {}
            pieces = []
            for direction, bucket in flow_split.items():
                bucket_total = bucket["total"] or 1
                rate = bucket[FAVORABLE] / bucket_total
                base = base_split.get(direction) or {}
                base_total = base.get("total") or 0
                if not base_total:
                    pieces.append(
                        f"{direction} {bucket[FAVORABLE]}/{bucket['total']}"
                        f" ({rate:.0%}) sem base"
                    )
                    continue
                base_rate = base[FAVORABLE] / base_total
                pieces.append(
                    f"{direction} {bucket[FAVORABLE]}/{bucket['total']}"
                    f" ({rate:.0%}) vs base {base[FAVORABLE]}/{base_total}"
                    f" ({base_rate:.0%}) {rate - base_rate:+.0%}"
                )
            lines.append(
                "        fluxo 2+ x base cega (mesma sessão): " + " · ".join(pieces)
            )
            acertos = []
            for direction, bucket in flow_split.items():
                base = (row.get("base_by_direction") or {}).get(direction) or {}
                flow_total = bucket["total"] or 1
                base_total = base.get("total") or 0
                if not base_total:
                    continue
                acertos.append(
                    f"{direction} acerto {bucket.get('acerta', 0) / flow_total:.0%}"
                    f" vs base {base.get('acerta', 0) / base_total:.0%}"
                )
            if acertos:
                lines.append("        acerto na expiração: " + " · ".join(acertos))
    lines.append("")
    lines.extend(_flow_edge_verdict(rows))
    return "\n".join(lines)


# Régua combinada com o usuário ANTES do teste, para o veredito não ser
# escolhido depois de ver o número: a regra de fluxo só passa se bater a base
# cega da própria sessão em pelo menos 3 sessões, e nenhuma sessão grande pode
# ficar abaixo da base.
# Um bloco de 60 min tem no máximo 60 candles, e a regra de fluxo só aparece em
# ~47% deles: ~28 apostas por bloco é o teto. Exigir 50 por bloco seria exigir o
# impossível; 25 é o piso que um bloco cheio consegue entregar.
FLOW_EDGE_MIN_SAMPLE = 25
FLOW_EDGE_MIN_MARGIN = 0.10
FLOW_EDGE_MIN_SESSIONS = 3


FLOW_STRATIFIED_MIN = 15


def _flow_stratified_edge(
    rows: Sequence[Mapping[str, Any]]
) -> dict[str, float] | None:
    """Vantagem da regra DENTRO de cada bloco e direção.

    Somar os acertos e comparar com uma base agregada é o erro clássico: a regra
    aposta mais nos blocos em que a direção já pagava, e a média sobe sem que ela
    tenha escolhido nada. Aqui cada bloco contribui só com o desvio entre o que a
    regra acertou e o que a base do MESMO bloco previa, e a variância desses
    desvios dá o z.
    """
    deviation = 0.0
    variance = 0.0
    used = 0
    for row in rows:
        for direction in ("BUY", "SELL"):
            bucket = (row.get("flow_by_direction") or {}).get(direction)
            base = (row.get("base_by_direction") or {}).get(direction)
            if not bucket or not base:
                continue
            total = int(bucket.get("total") or 0)
            base_total = int(base.get("total") or 0)
            if total < FLOW_STRATIFIED_MIN or not base_total:
                continue
            rate = base.get("acerta", 0) / base_total
            deviation += bucket.get("acerta", 0) - rate * total
            variance += rate * (1 - rate) * total
            used += 1
    if not used or variance <= 0:
        return None
    return {
        "blocks": used,
        "deviation": deviation,
        "variance": variance,
        "z": deviation / math.sqrt(variance),
    }


def _flow_edge_verdict(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Veredito da regra de fluxo, controlando bloco e direção."""
    lines = [
        "    CONTROLE DA REGRA DE FLUXO - acerto sobre a base cega do MESMO bloco",
        f"    (uma aposta por vela; bloco = 60 min; só entra bloco/direção com n >="
        f" {FLOW_STRATIFIED_MIN})",
    ]
    for direction in ("BUY", "SELL"):
        deltas = []
        for row in rows:
            bucket = (row.get("flow_by_direction") or {}).get(direction)
            base = (row.get("base_by_direction") or {}).get(direction)
            if not bucket or not base:
                continue
            total = int(bucket.get("total") or 0)
            base_total = int(base.get("total") or 0)
            if total < FLOW_STRATIFIED_MIN or not base_total:
                continue
            delta = (
                bucket.get("acerta", 0) / total - base.get("acerta", 0) / base_total
            )
            deltas.append(f"{delta:+.0%} (n={total})")
        lines.append(
            f"    {direction}: " + (" · ".join(deltas) if deltas else "sem bloco elegível")
        )
    edge = _flow_stratified_edge(rows)
    if edge is None:
        lines.append(
            "    Regra de fluxo: amostra insuficiente para julgar - nenhum bloco"
            " com n suficiente em apostas independentes."
        )
        return lines
    lines.append(
        f"    Vantagem estratificada: {edge['deviation']:+.1f} acerto(s) acima do"
        f" esperado em {int(edge['blocks'])} bloco(s) · z = {edge['z']:.2f}"
    )
    if edge["z"] >= 1.96 and edge["deviation"] > 0:
        lines.append(
            "    Regra de fluxo: vantagem própria além da composição de blocos -"
            " candidata a veredito, sujeita a aprovação."
        )
    else:
        lines.append(
            "    Regra de fluxo: sem evidência de vantagem própria - o que aparece"
            " no agregado é compatível com composição de blocos. Não adotar."
        )
    return lines


def format_baseline(baseline: Mapping[str, Any]) -> str:
    lines = [
        "",
        "    LINHA DE BASE - entrar em todo quadro com escada, sem classificador",
        "    (o controle: sinal que acerta igual a esta linha, na mesma direção,",
        "    não escolheu nada; quem pagou foi a direção do período)",
        "    direção    n   favorável   neutra   adversa   mediano",
    ]
    for direction in ("BUY", "SELL"):
        bucket = baseline.get(direction) or {}
        total = bucket.get("total") or 0
        if not total:
            continue
        lines.append(
            f"    {direction:<7} {total:>4}   "
            f"{bucket[FAVORABLE]:>4} ({bucket[FAVORABLE] / total:>4.0%})   "
            f"{bucket[NEUTRAL]:>4}   {bucket[ADVERSE]:>4}   "
            f"{bucket['median_move_units']:>7}"
            f"   acerto {(bucket.get('acerta') or 0) / total:>4.0%}"
        )
    if not any((baseline.get(direction) or {}).get("total") for direction in ("BUY", "SELL")):
        lines.append("    Nenhum quadro pôde ser acompanhado até o horizonte.")
    lines.append(
        "    Quadros com escada: "
        f"{baseline.get('frames_with_ladder', 0)} · entradas contadas (1 por vela): "
        f"{baseline.get('bets', 0)} · entrada na vela mais recente"
    )
    bets = int(baseline.get("bets") or 0)
    if bets:
        margin = 1.96 * math.sqrt(0.25 / bets) * 100
        lines.append(
            f"    Amostra desta rodada: {bets} entradas independentes, "
            f"margem de +/-{margin:.0f}pp no pior caso."
        )
        lines.append(
            "    Para decidir 5pp perto de 55% são necessárias ~380 apostas;"
            " 10pp, ~95."
        )
        # Uma vela de 1 minuto por entrada: o relógio de captura é o mesmo número.
        lines.append(
            f"    Faltam {max(0, 95 - bets)} entradas (~minutos de gráfico)"
            f" para +/-10pp e {max(0, 380 - bets)} para +/-5pp."
        )
    lines.append(
        "    Uma entrada por vela: quadros vizinhos do mesmo candle não viram apostas."
    )
    situations = baseline.get("by_situation") or {}
    if situations:
        lines.append("")
        lines.append(
            "    Mesma linha de base, seguindo (ou contrariando) o movimento anterior:"
        )
        lines.append(
            "    situação                        n   favorável   neutra   adversa   mediano"
        )
        for situation, bucket in sorted(
            situations.items(), key=lambda pair: -pair[1]["total"]
        ):
            total = bucket["total"] or 1
            lines.append(
                f"    {situation:<30} {total:>4}   "
                f"{bucket[FAVORABLE]:>4} ({bucket[FAVORABLE] / total:>4.0%})   "
                f"{bucket[NEUTRAL]:>4}   {bucket[ADVERSE]:>4}   "
                f"{bucket['median_move_units']:>7}"
            )
        split = baseline.get("by_situation_direction") or {}
        if split:
            lines.append("")
            lines.append(
                "    Mesma linha de base, com a direção de cada aposta (sem isso a"
                " queda puxa a média):"
            )
            lines.append(
                "    situação                        direção    n   favorável   neutra   adversa   mediano"
            )
            for situation, directions in split.items():
                for direction, bucket in directions.items():
                    total = bucket["total"] or 1
                    lines.append(
                        f"    {situation:<30} {direction:<7} {total:>4}   "
                        f"{bucket[FAVORABLE]:>4} ({bucket[FAVORABLE] / total:>4.0%})   "
                        f"{bucket[NEUTRAL]:>4}   {bucket[ADVERSE]:>4}   "
                        f"{bucket['median_move_units']:>7}"
                    )
        regimes = baseline.get("by_regime") or {}
        if regimes:
            lines.append("")
            lines.append(
                "    REGIME LIDO - seguir o movimento dentro de cada regime (se o regime"
                " não separa, ele só reduz o funil):"
            )
            lines.append("    regime         seguir n/fav     contra n/fav")
            for regime, groups in sorted(
                regimes.items(), key=lambda pair: -pair[1]["seguir"]["total"]
            ):
                following = groups["seguir"]
                against = groups["contra"]
                follow_total = following["total"] or 1
                against_total = against["total"] or 1
                lines.append(
                    f"    {regime:<14} {following['total']:>4}/{following[FAVORABLE]:<3}"
                    f" ({following[FAVORABLE] / follow_total:>4.0%})   "
                    f"{against['total']:>4}/{against[FAVORABLE]:<3}"
                    f" ({against[FAVORABLE] / against_total:>4.0%})"
                )
        lines.append(
            "    Se seguir o movimento rende aqui o mesmo que nos sinais, a classe não"
        )
        lines.append("    escolheu o momento: o momento é o próprio movimento.")
    return "\n".join(lines)


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

    # Bloqueio é quadro sem sinal; C é sinal emitido com risco anotado. Somar os
    # dois fazia o funil parecer maior do que é e escondia o nome do bloqueio.
    reason_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for frame in frames:
        code = str(frame.get("code"))
        target = risk_counts if code == "C" else reason_counts
        # Motivos de A/B descrevem o que está bom; não entram em nenhuma das listas.
        if code in ("A", "B"):
            continue
        seen = set()
        for reason in frame.get("reasons") or []:
            if reason in seen:
                continue
            seen.add(reason)
            target[reason] = target.get(reason, 0) + 1
    top_reasons = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
    top_risk_reasons = sorted(risk_counts.items(), key=lambda item: (-item[1], item[0]))[:6]

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
        "top_risk_reasons": [
            {"reason": reason, "count": count} for reason, count in top_risk_reasons
        ],
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
            f"descartados: {outcomes['skipped']} · "
            f"repetidos no mesmo candle (contados uma vez): "
            f"{outcomes.get('repeated_frames', 0)}"
        )
        lines.append("")
        lines.append(
            "    classe   n     favorável   neutra   adversa   mediano   acerto"
        )
        for grade, bucket in outcomes["by_grade"].items():
            total = bucket["total"] or 1
            lines.append(
                f"    {grade:<7} {bucket['total']:>4}   "
                f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})   "
                f"{bucket['neutra']:>4}   {bucket['adversa']:>4}   "
                f"{bucket['median_move_units']:>7}"
                f"   {bucket.get('acerta', 0) / total:>5.0%}"
            )
        for direction, bucket in (outcomes.get("by_direction") or {}).items():
            total = bucket["total"] or 1
            lines.append(
                f"    {direction:<7} {bucket['total']:>4}   "
                f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})   "
                f"{bucket['neutra']:>4}   {bucket['adversa']:>4}   "
                f"{bucket['median_move_units']:>7}"
                f"   {bucket.get('acerta', 0) / total:>5.0%}"
            )
        by_grade_direction = outcomes.get("by_grade_direction") or {}
        if by_grade_direction:
            lines.append("")
            lines.append(
                "    Por classe e direção (controle do viés de mercado): uma classe que"
                " quase só vende"
            )
            lines.append(
                "    não pode ser comparada com uma que quase só compra na mesma amostra."
            )
            lines.append(
                "    classe  direção    n   favorável   neutra   adversa   mediano   acerto"
            )
            for grade, directions in by_grade_direction.items():
                for direction, bucket in directions.items():
                    total = bucket["total"] or 1
                    lines.append(
                        f"    {grade:<7} {direction:<7} {bucket['total']:>4}   "
                        f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})   "
                        f"{bucket['neutra']:>4}   {bucket['adversa']:>4}   "
                        f"{bucket['median_move_units']:>7}"
                        f"   {bucket.get('acerta', 0) / total:>5.0%}"
                    )
            lines.append("")
            lines.append("    Mistura de direção por classe (o que pode explicar a diferença):")
            for grade, directions in by_grade_direction.items():
                total = sum(bucket["total"] for bucket in directions.values()) or 1
                parts = " · ".join(
                    f"{direction} {bucket['total']}/{total} ({bucket['total'] / total:.0%})"
                    for direction, bucket in directions.items()
                )
                lines.append(f"      {grade}: {parts}")
            lines.append(
                "    Células com menos de 5 sinais não sustentam leitura; compare classes"
            )
            lines.append("    dentro da mesma direção, não entre direções.")

        alignment = outcomes.get("by_alignment") or {}
        if alignment:
            lines.append("")
            lines.append(
                "    SINAL SEGUE OU CONTRARIA O MOVIMENTO ANTERIOR (mesma janela,"
                " antes da entrada):"
            )
            lines.append(
                "    situação                        n   favorável   neutra   adversa   mediano"
            )
            for situation, bucket in alignment.items():
                total = bucket["total"] or 1
                lines.append(
                    f"    {situation:<30} {bucket['total']:>4}   "
                    f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})   "
                    f"{bucket['neutra']:>4}   {bucket['adversa']:>4}   "
                    f"{bucket['median_move_units']:>7}"
                )
            split = outcomes.get("by_alignment_direction") or {}
            if split:
                lines.append("")
                lines.append(
                    "    Mesmas situações separadas por direção (sem isso o"
                    " alinhamento só repete o viés):"
                )
                lines.append(
                    "    situação                        direção    n   favorável   neutra   adversa   mediano"
                )
                for situation, directions in split.items():
                    for direction, bucket in directions.items():
                        total = bucket["total"] or 1
                        lines.append(
                            f"    {situation:<30} {direction:<7} {bucket['total']:>4}   "
                            f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})   "
                            f"{bucket['neutra']:>4}   {bucket['adversa']:>4}   "
                            f"{bucket['median_move_units']:>7}"
                        )
            lines.append(
                "    Se quase todo sinal está a favor do que já andou, o app segue o"
                " movimento"
            )
            lines.append("    em vez de escolher ponto de virada.")

        context = outcomes.get("by_context") or {}
        if context:
            lines.append("")
            lines.append(
                "    SINAL A FAVOR OU CONTRA O CONTEXTO LIDO DO GRÁFICO"
                " (só quando o quadro tem contexto):"
            )
            lines.append(
                "    situação                        n   favorável   neutra   adversa   mediano"
            )
            for situation, bucket in context.items():
                total = bucket["total"] or 1
                lines.append(
                    f"    {situation:<30} {bucket['total']:>4}   "
                    f"{bucket['favorável']:>4} ({bucket['favorável'] / total:>4.0%})   "
                    f"{bucket['neutra']:>4}   {bucket['adversa']:>4}   "
                    f"{bucket['median_move_units']:>7}"
                )

        vetoes = outcomes.get("vetoes") or []
        if vetoes:
            lines.append("")
            lines.append(
                "    SIMULAÇÃO DE ABSTENÇÃO (nada muda no app; só a conta do que"
                " sobraria):"
            )
            for veto in vetoes:
                removed = veto["removed"]
                kept = veto["kept"]
                removed_total = removed["total"] or 1
                kept_total = kept["total"] or 1
                lines.append(
                    f"      vetar {veto['rule']}: descarta {removed['total']:>3}"
                    f" ({removed['favorável'] / removed_total:>4.0%} favorável) ·"
                    f" sobra {kept['total']:>3}"
                    f" ({kept['favorável'] / kept_total:>4.0%} favorável,"
                    f" mediana {kept['median_move_units']})"
                )
            lines.append(
                "    Vetar só melhora o retrato se o que sobra bater a base da mesma"
                " sessão;"
            )
            lines.append("    descartar sinal ruim não cria vantagem, só reduz ruído.")

        reasons = outcomes.get("by_reason") or {}
        if reasons:
            lines.append("")
            lines.append(
                "    Por motivo registrado (mínimo 3 sinais). Em A/B o motivo descreve "
                "o que está bom; em C, a regra que marcou risco:"
            )
            for reason, bucket in reasons.items():
                total = bucket["total"] or 1
                lines.append(
                    f"      {bucket['favorável']:>3}/{bucket['total']:<3} "
                    f"({bucket['favorável'] / total:>4.0%}) "
                    f"mediana {bucket['median_move_units']:>7}  {reason}"
                )
    lines += [
        "",
        "    'acerto' é fechamento a favor na vela de expiração: sem custo, sem",
        "    spread e sem payout. O equilíbrio com payout de 85% é 54.1% e com 90%",
        "    é 52.6%, contando empate como perda. 'favorável' mede deslocamento",
        "    relativo à faixa mediana e serve para comparar classes entre si.",
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
        f"Período: {summary['first_frame_at_utc']} -> {summary['last_frame_at_utc']}"
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

    if summary.get("top_risk_reasons"):
        lines += ["", "Motivos de risco nas classes com sinal (C):"]
        for entry in summary["top_risk_reasons"]:
            lines.append(f"    {entry['count']:>5}  {entry['reason']}")
        lines.append(
            "    Estes quadros viraram sinal, não bloqueio; o desfecho deles está"
        )
        lines.append("    em 'Por motivo registrado' abaixo.")

    if summary["top_reasons"]:
        lines += ["", "Motivos de bloqueio mais frequentes (quadros sem sinal):"]
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
        "    · 'acerto' (seção de desfecho) é fechamento a favor na vela de",
        "      expiração, sem custo e sem payout: não é resultado financeiro.",
        "    · Um quadro não é uma aposta: o mesmo candle aparece em vários quadros.",
        "      Todo n de desfecho conta uma vez por candle; os 5.000 quadros não são",
        "      5.000 entradas.",
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


def _make_stdout_printable() -> None:
    """Console e pipes do Windows usam cp1252 e quebram o relatório em qualquer
    caractere fora dessa pagina de codigo (aconteceu com a seta unicode ao
    usar Tee-Object)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _make_stdout_printable()
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
        nargs="+",
        default=[3],
        help="Quantas velas depois do sinal avaliar; aceita vários (padrão: 3).",
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
    outcomes_by_horizon = [
        compute_outcomes(
            frames,
            bar_seconds=args.bar_seconds,
            horizon_bars=horizon,
            min_move_units=args.min_move,
        )
        for horizon in args.horizon_bars
    ]
    baseline_by_horizon = [
        compute_baseline(
            frames,
            bar_seconds=args.bar_seconds,
            horizon_bars=horizon,
            min_move_units=args.min_move,
        )
        for horizon in args.horizon_bars
    ]
    sessions_by_horizon = [
        compute_session_comparison(
            frames,
            bar_seconds=args.bar_seconds,
            horizon_bars=horizon,
            min_move_units=args.min_move,
        )
        for horizon in args.horizon_bars
    ]
    flow_by_horizon = [
        compute_flow_rule(
            frames,
            bar_seconds=args.bar_seconds,
            horizon_bars=horizon,
            min_move_units=args.min_move,
        )
        for horizon in args.horizon_bars
    ]
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
                    "outcomes": outcomes_by_horizon,
                    "baseline": baseline_by_horizon,
                    "sessions": sessions_by_horizon,
                    "flow": flow_by_horizon,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report(summary, sweeps))
        for outcomes, baseline, sessions, flow in zip(
            outcomes_by_horizon, baseline_by_horizon, sessions_by_horizon, flow_by_horizon
        ):
            print(format_outcomes(outcomes))
            print(format_baseline(baseline))
            print(format_session_comparison(sessions))
            print(format_flow_rule(flow))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
