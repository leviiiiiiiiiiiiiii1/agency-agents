"""Estratégia HMA + MACD para scalping M1 — independente das que já existem.

Este módulo não sabe nada de tela, OCR, clique ou ordem. Ele recebe uma série
de fechamentos de velas **já fechadas** e devolve sinais com motivo. Quem
executa (ou não) é o resto do projeto, e hoje o resto do projeto não executa
nada: cliques e ordens estão bloqueados.

Três decisões que valem registro antes do código:

1. HMA e MACD são calculados só com velas fechadas, e o sinal de uma vela i
   nunca lê nada depois de i. A entrada é na abertura de i+1, que é a vela
   seguinte à confirmação — o mesmo instante que o app usaria.
2. O eixo do gráfico é pixel: y menor é preço maior. Todo o módulo trabalha
   com a convenção "para cima = alta" e a inversão acontece uma vez, na
   entrada da série (`pixel_y=True`), não espalhada pelas regras.
3. Os filtros são medidos em unidades relativas (múltiplos da amplitude
   mediana da própria série), não em pixels absolutos: o mesmo número tem de
   valer para um gráfico com zoom diferente.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field, replace
from statistics import median
from typing import Any, Mapping, Sequence

BUY = "BUY"
SELL = "SELL"

BLOCK_LATERAL = "HMA lateralizada"
BLOCK_WEAK_HIST = "MACD sem força"
BLOCK_FLAT_HMA = "HMA praticamente horizontal"
BLOCK_VOLATILITY = "volatilidade excessiva"
BLOCK_LATE = "confirmação atrasada"
BLOCK_PAYOUT = "payout insuficiente"
BLOCK_HOUR = "fora do horário permitido"
BLOCK_ASSET = "ativo não permitido"
BLOCK_DUPLICATE = "sinal duplicado"


# --------------------------------------------------------------------------
# configuração


@dataclass(frozen=True)
class HmaMacdConfig:
    """Tudo que o painel precisa editar, com o padrão da especificação."""

    enabled: bool = False
    hma_period: int = 16
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    confirm_window: int = 1
    min_hist_strength: float = 0.25
    block_lateral: bool = True
    lateral_lookback: int = 10
    max_direction_changes: int = 3
    block_weak_hist: bool = True
    block_volatility: bool = True
    max_range_units: float = 2.5
    min_slope_units: float = 0.05
    expiry_bars: int = 1
    min_payout: float = 0.85
    allowed_hours: tuple[int, ...] = ()
    allowed_assets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.hma_period < 2:
            raise ValueError("hma_period precisa ser pelo menos 2.")
        if self.macd_fast < 1 or self.macd_slow <= self.macd_fast:
            raise ValueError("MACD exige lento maior que rápido.")
        if self.macd_signal < 1:
            raise ValueError("macd_signal precisa ser pelo menos 1.")
        if self.confirm_window < 0:
            raise ValueError("confirm_window não pode ser negativo.")
        if self.expiry_bars < 1:
            raise ValueError("expiry_bars precisa ser pelo menos 1.")
        if self.min_hist_strength < 0 or self.max_range_units <= 0:
            raise ValueError("limiares de filtro precisam ser positivos.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hma_period": self.hma_period,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "confirm_window": self.confirm_window,
            "min_hist_strength": self.min_hist_strength,
            "block_lateral": self.block_lateral,
            "lateral_lookback": self.lateral_lookback,
            "max_direction_changes": self.max_direction_changes,
            "block_weak_hist": self.block_weak_hist,
            "block_volatility": self.block_volatility,
            "max_range_units": self.max_range_units,
            "min_slope_units": self.min_slope_units,
            "expiry_bars": self.expiry_bars,
            "min_payout": self.min_payout,
            "allowed_hours": list(self.allowed_hours),
            "allowed_assets": list(self.allowed_assets),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HmaMacdConfig":
        """Lê a configuração salva sem quebrar o que não estava lá.

        Campo ausente fica no padrão; campo de tipo errado também. Perder a
        configuração inteira por causa de um campo novo é pior do que ignorar
        esse campo.
        """
        fields = cls.__dataclass_fields__
        values: dict[str, Any] = {}
        for name, spec in fields.items():
            if name not in data:
                continue
            raw = data[name]
            default = spec.default
            try:
                if isinstance(default, bool):
                    values[name] = bool(raw)
                elif isinstance(default, int):
                    values[name] = int(raw)
                elif isinstance(default, float):
                    values[name] = float(raw)
                elif isinstance(default, tuple):
                    wants_text = "str" in str(spec.type)
                    values[name] = tuple(
                        str(item) if wants_text else int(item) for item in raw or ()
                    )
                else:
                    values[name] = raw
            except (TypeError, ValueError):
                continue
        return cls(**values)

    def without_filters(self) -> "HmaMacdConfig":
        return replace(
            self,
            block_lateral=False,
            block_weak_hist=False,
            block_volatility=False,
            min_slope_units=0.0,
        )


SETTINGS_KEY = "hma_macd"


def load_config(settings: Mapping[str, Any]) -> HmaMacdConfig:
    """Configuração a partir do JSON de configurações do app (seção própria)."""
    section = settings.get(SETTINGS_KEY)
    if not isinstance(section, Mapping):
        return HmaMacdConfig()
    return HmaMacdConfig.from_dict(section)


def save_config(settings: Mapping[str, Any], config: HmaMacdConfig) -> dict[str, Any]:
    """Devolve o JSON de configurações com a seção desta estratégia trocada.

    As outras seções são copiadas intactas: esta estratégia não é dona do
    arquivo, só de uma chave dele.
    """
    payload = dict(settings)
    payload[SETTINGS_KEY] = config.as_dict()
    return payload


# --------------------------------------------------------------------------
# indicadores


def wma(values: Sequence[float | None], period: int) -> list[float | None]:
    """Média móvel ponderada linear, alinhada ao índice da entrada."""
    if period < 1:
        raise ValueError("period precisa ser pelo menos 1.")
    total = period * (period + 1) / 2
    out: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        if any(item is None for item in window):
            continue
        out[index] = sum(
            weight * float(item) for weight, item in enumerate(window, start=1)
        ) / total
    return out


def hma(values: Sequence[float | None], period: int = 16) -> list[float | None]:
    """Hull Moving Average: WMA(2*WMA(n/2) - WMA(n), sqrt(n))."""
    if period < 2:
        raise ValueError("period precisa ser pelo menos 2.")
    half = max(1, period // 2)
    root = max(1, int(math.sqrt(period)))
    fast = wma(values, half)
    slow = wma(values, period)
    raw = [
        None if (fast[i] is None or slow[i] is None) else 2 * fast[i] - slow[i]
        for i in range(len(values))
    ]
    return wma(raw, root)


def ema(values: Sequence[float | None], period: int) -> list[float | None]:
    """EMA semeada com a média simples das primeiras `period` leituras."""
    if period < 1:
        raise ValueError("period precisa ser pelo menos 1.")
    alpha = 2 / (period + 1)
    out: list[float | None] = [None] * len(values)
    seed: float | None = None
    count = 0
    total = 0.0
    for index, value in enumerate(values):
        if value is None:
            continue
        if seed is None:
            total += float(value)
            count += 1
            if count == period:
                seed = total / period
                out[index] = seed
            continue
        seed = alpha * float(value) + (1 - alpha) * seed
        out[index] = seed
    return out


def macd(
    values: Sequence[float | None],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD clássico: linha, sinal e histograma (linha - sinal)."""
    if slow <= fast:
        raise ValueError("slow precisa ser maior que fast.")
    fast_line = ema(values, fast)
    slow_line = ema(values, slow)
    line = [
        None if (fast_line[i] is None or slow_line[i] is None) else fast_line[i] - slow_line[i]
        for i in range(len(values))
    ]
    signal_line = ema(line, signal)
    histogram = [
        None if (line[i] is None or signal_line[i] is None) else line[i] - signal_line[i]
        for i in range(len(values))
    ]
    return line, signal_line, histogram


def direction_of(hma_series: Sequence[float | None]) -> list[int]:
    """+1 subindo, -1 caindo, 0 sem leitura (ou parado)."""
    out = [0] * len(hma_series)
    for i in range(1, len(hma_series)):
        current, previous = hma_series[i], hma_series[i - 1]
        if current is None or previous is None:
            continue
        if current > previous:
            out[i] = 1
        elif current < previous:
            out[i] = -1
    return out


# --------------------------------------------------------------------------
# sinais


@dataclass(frozen=True)
class HmaMacdSignal:
    """Um sinal identificado, com o que o bloqueou (se algo bloqueou)."""

    signal_id: str
    direction: str
    turn_index: int          # vela em que a HMA virou
    confirm_index: int       # vela em que o histograma cruzou
    entry_index: int         # vela de entrada (abertura = fechamento da anterior)
    lag: int                 # confirmação tardia em velas
    price: float
    blocked: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.blocked

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.signal_id,
            "direction": self.direction,
            "turn_index": self.turn_index,
            "confirm_index": self.confirm_index,
            "entry_index": self.entry_index,
            "lag": self.lag,
            "price": self.price,
            "blocked": list(self.blocked),
        }


def _median_range(closes: Sequence[float], index: int, lookback: int = 20) -> float:
    moves = [
        abs(closes[i] - closes[i - 1])
        for i in range(max(1, index - lookback + 1), index + 1)
    ]
    moves = [move for move in moves if move > 0]
    return median(moves) if moves else 0.0


def _direction_changes(directions: Sequence[int], index: int, lookback: int) -> int:
    start = max(1, index - lookback + 1)
    changes = 0
    for i in range(start, index + 1):
        if directions[i] != 0 and directions[i - 1] != 0 and directions[i] != directions[i - 1]:
            changes += 1
    return changes


def generate_signals(
    closes: Sequence[float],
    config: HmaMacdConfig,
    *,
    payout: float | None = None,
    hours: Sequence[int] | None = None,
    asset: str | None = None,
) -> list[HmaMacdSignal]:
    """Sinais de HMA+MACD sobre uma série de velas fechadas.

    `closes` é a série já na convenção normal (valor maior = preço maior).
    `hours` é a hora local de cada vela, quando se quer aplicar a janela
    operacional.
    """
    if len(closes) < config.macd_slow + config.macd_signal:
        return []
    hma_series = hma(list(closes), config.hma_period)
    directions = direction_of(hma_series)
    _line, _signal, histogram = macd(
        list(closes), config.macd_fast, config.macd_slow, config.macd_signal
    )

    signals: list[HmaMacdSignal] = []
    last_direction: str | None = None
    for turn in range(1, len(closes)):
        if directions[turn] == 0 or directions[turn - 1] == 0:
            continue
        if directions[turn] == directions[turn - 1]:
            continue
        wanted = BUY if directions[turn] > 0 else SELL
        if wanted == last_direction:
            # Mesma direção do sinal anterior e nenhuma virada no meio: é o
            # mesmo evento, e evento repetido não é sinal novo.
            continue
        confirm = _find_confirmation(histogram, turn, config.confirm_window, wanted)
        if confirm is None:
            continue
        lag = confirm - turn
        blocked: list[str] = []
        if payout is not None and payout < config.min_payout:
            blocked.append(BLOCK_PAYOUT)
        if hours is not None and config.allowed_hours:
            if hours[confirm] not in config.allowed_hours:
                blocked.append(BLOCK_HOUR)
        if asset is not None and config.allowed_assets:
            if asset not in config.allowed_assets:
                blocked.append(BLOCK_ASSET)
        blocked.extend(_filter_reasons(closes, hma_series, directions, histogram, confirm, config))
        if lag > config.confirm_window:
            blocked.append(BLOCK_LATE)
        signals.append(
            HmaMacdSignal(
                signal_id=_signal_id(wanted, turn, confirm),
                direction=wanted,
                turn_index=turn,
                confirm_index=confirm,
                entry_index=confirm + 1,
                lag=lag,
                price=float(closes[confirm]),
                blocked=tuple(dict.fromkeys(blocked)),
            )
        )
        last_direction = wanted
    return signals


def confirmation_lags(
    closes: Sequence[float],
    config: HmaMacdConfig,
) -> dict[str, Any]:
    """Quanto tempo o MACD leva para confirmar cada virada da HMA.

    Existe porque a regra da especificação exige a confirmação na mesma vela
    ou na seguinte, e isso pode simplesmente não acontecer: a HMA vira no
    extremo do preço, e o histograma do MACD cruza o zero quando o impulso
    troca de sinal, que costuma ser depois. Medir a distância antes de adotar
    evita descobrir isso com dinheiro.
    """
    empty = {
        "turns": 0,
        "confirmed": 0,
        "lags": [],
        "median": None,
        "p10": None,
        "p90": None,
    }
    if len(closes) < config.macd_slow + config.macd_signal + 2:
        return empty
    directions = direction_of(hma(list(closes), config.hma_period))
    _line, _signal, histogram = macd(
        list(closes), config.macd_fast, config.macd_slow, config.macd_signal
    )
    up: list[int] = []
    down: list[int] = []
    for index in range(1, len(histogram)):
        current, previous = histogram[index], histogram[index - 1]
        if current is None or previous is None:
            continue
        if previous <= 0 < current:
            up.append(index)
        elif previous >= 0 > current:
            down.append(index)
    lags: list[int] = []
    turns = 0
    for turn in range(1, len(directions)):
        if not directions[turn] or not directions[turn - 1]:
            continue
        if directions[turn] == directions[turn - 1]:
            continue
        turns += 1
        wanted = up if directions[turn] > 0 else down
        found = _first_at_or_after(wanted, turn)
        if found is not None:
            lags.append(found - turn)
    if not lags:
        return {**empty, "turns": turns}
    ordered = sorted(lags)
    return {
        "turns": turns,
        "confirmed": len(lags),
        "lags": ordered,
        "median": median(ordered),
        "p10": ordered[max(0, int(len(ordered) * 0.1) - 1)],
        "p90": ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))],
    }


def _first_at_or_after(values: Sequence[int], start: int) -> int | None:
    for value in values:
        if value >= start:
            return value
    return None


def _find_confirmation(
    histogram: Sequence[float | None],
    turn: int,
    window: int,
    direction: str,
) -> int | None:
    """Primeira vela, de `turn` a `turn+window`, com o histograma cruzando zero."""
    limit = min(len(histogram) - 1, turn + window)
    for index in range(turn, limit + 1):
        current, previous = histogram[index], histogram[index - 1] if index else None
        if current is None or previous is None:
            continue
        if direction == BUY and previous <= 0 < current:
            return index
        if direction == SELL and previous >= 0 > current:
            return index
    return None


def _filter_reasons(
    closes: Sequence[float],
    hma_series: Sequence[float | None],
    directions: Sequence[int],
    histogram: Sequence[float | None],
    index: int,
    config: HmaMacdConfig,
) -> list[str]:
    reasons: list[str] = []
    scale = _median_range(closes, index)
    if config.block_lateral:
        changes = _direction_changes(directions, index, config.lateral_lookback)
        if changes > config.max_direction_changes:
            reasons.append(BLOCK_LATERAL)
    if config.block_weak_hist and histogram[index] is not None:
        recent = [abs(value) for value in histogram[max(0, index - 20) : index] if value]
        reference = median(recent) if recent else 0.0
        strength = abs(float(histogram[index]))
        # Comparado com o próprio histórico do histograma, não com pixels: o
        # mesmo limiar vale para qualquer zoom.
        if reference > 0 and strength < config.min_hist_strength * reference:
            reasons.append(BLOCK_WEAK_HIST)
    if config.min_slope_units and scale > 0:
        current, previous = hma_series[index], hma_series[index - 1]
        if current is not None and previous is not None:
            if abs(current - previous) / scale < config.min_slope_units:
                reasons.append(BLOCK_FLAT_HMA)
    if config.block_volatility and scale > 0 and index:
        if abs(closes[index] - closes[index - 1]) / scale > config.max_range_units:
            reasons.append(BLOCK_VOLATILITY)
    return reasons


def _signal_id(direction: str, turn: int, confirm: int) -> str:
    raw = f"{direction}:{turn}:{confirm}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# --------------------------------------------------------------------------
# resultado e estatística


@dataclass
class StrategyStats:
    total: int = 0
    executed: int = 0
    blocked: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    net: float = 0.0
    by_reason: dict[str, int] = field(default_factory=dict)
    by_direction: dict[str, dict[str, float]] = field(default_factory=dict)
    by_hour: dict[int, dict[str, float]] = field(default_factory=dict)
    by_expiry: dict[int, dict[str, float]] = field(default_factory=dict)
    by_asset: dict[str, dict[str, float]] = field(default_factory=dict)
    peak: float = 0.0
    max_drawdown: float = 0.0

    @property
    def accuracy(self) -> float | None:
        decided = self.wins + self.losses + self.draws
        return self.wins / decided if decided else None


def _bucket(store: dict[Any, dict[str, float]], key: Any) -> dict[str, float]:
    return store.setdefault(key, {"n": 0, "wins": 0, "net": 0.0})


def backtest(
    closes: Sequence[float],
    config: HmaMacdConfig,
    *,
    payout: float = 0.86,
    expiry_bars: int | None = None,
    stake: float = 1.0,
    hours: Sequence[int] | None = None,
    asset: str | None = None,
    entry_delay: int = 0,
) -> StrategyStats:
    """Aplica a estratégia e liquida cada sinal aprovado na vela de expiração.

    Empate (fechamento idêntico) conta como perda, como a corretora liquida.
    Nenhum sinal aprovado é descartado por falta de dado: se a vela de
    expiração não existe na série, o sinal não é contado.
    """
    horizon = expiry_bars if expiry_bars is not None else config.expiry_bars
    signals = generate_signals(closes, config, payout=payout, hours=hours, asset=asset)
    stats = StrategyStats()
    equity = 0.0
    for signal in signals:
        stats.total += 1
        if not signal.allowed:
            stats.blocked += 1
            for reason in signal.blocked:
                stats.by_reason[reason] = stats.by_reason.get(reason, 0) + 1
            continue
        # Entrada na abertura da vela seguinte: o último fechamento conhecido é
        # o da vela da confirmação. Expiração de 1 vela sai no fechamento
        # seguinte, que é exatamente uma vela de exposição.
        entry_index = signal.confirm_index + entry_delay
        exit_index = entry_index + horizon
        if exit_index >= len(closes):
            stats.total -= 1
            continue
        entry = closes[entry_index]
        moved = closes[exit_index] - entry
        won = moved > 0 if signal.direction == BUY else moved < 0
        draw = moved == 0
        stats.executed += 1
        if draw:
            stats.draws += 1
            profit = -stake
        elif won:
            stats.wins += 1
            profit = stake * payout
        else:
            stats.losses += 1
            profit = -stake
        stats.net += profit
        equity += profit
        stats.peak = max(stats.peak, equity)
        stats.max_drawdown = min(stats.max_drawdown, equity - stats.peak)
        for table, key in (
            (stats.by_direction, signal.direction),
            (stats.by_hour, hours[signal.confirm_index] if hours else 0),
            (stats.by_expiry, horizon),
            (stats.by_asset, asset or "sem ativo"),
        ):
            bucket = _bucket(table, key)
            bucket["n"] += 1
            bucket["wins"] += 1 if won else 0
            bucket["net"] += profit
    return stats


# --------------------------------------------------------------------------
# séries a partir do que o app grava


@dataclass(frozen=True)
class MarketSeries:
    """Fechamentos de uma sequência contínua de velas, já na convenção normal."""

    label: str
    closes: tuple[float, ...]
    hours: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.closes)


def series_from_ladder(
    frames: Sequence[Mapping[str, Any]],
    *,
    bar_seconds: float = 60.0,
    max_gap_bars: int = 5,
    pixel_y: bool = True,
) -> list[MarketSeries]:
    """Reconstrói a série M1 a partir das escadas de preço gravadas nos quadros.

    Cada quadro traz os fechamentos por idade (índice 0 = vela atual). O
    índice absoluto da vela é o minuto do quadro menos a idade, então quadros
    diferentes do mesmo minuto preenchem a mesma vela. Sessões diferentes não
    são emendadas: região, zoom ou paleta podem ter mudado, e uma série
    emendada mediria um gráfico que nunca existiu.
    """
    from datetime import datetime, timezone

    by_session: dict[str, dict[int, float]] = {}
    for frame in frames:
        ladder = frame.get("price_ladder") or {}
        closes = ladder.get("closes_px") or []
        stamp = frame.get("occurred_at_utc")
        if not isinstance(stamp, str) or not closes:
            continue
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        base = int(when.timestamp() // max(1.0, bar_seconds))
        session = str(frame.get("session_id") or "")
        bucket = by_session.setdefault(session, {})
        for age, value in enumerate(closes):
            if value is None:
                continue
            index = base - age
            previous = bucket.get(index)
            # O quadro mais recente manda: ele leu a vela já formada.
            if previous is None or base >= previous[0]:
                bucket[index] = (base, float(value))  # type: ignore[assignment]

    series: list[MarketSeries] = []
    for session, bucket in by_session.items():
        indices = sorted(bucket)
        if not indices:
            continue
        run: list[int] = [indices[0]]
        for index in indices[1:]:
            if index - run[-1] > max_gap_bars:
                series.append(_build(session, run, bucket, bar_seconds, pixel_y))
                run = [index]
            else:
                run.append(index)
        series.append(_build(session, run, bucket, bar_seconds, pixel_y))
    return [item for item in series if len(item.closes) >= 2]


def _build(
    session: str,
    indices: Sequence[int],
    bucket: Mapping[int, Any],
    bar_seconds: float,
    pixel_y: bool,
) -> MarketSeries:
    from datetime import datetime, timezone

    closes: list[float] = []
    hours: list[int] = []
    for index in indices:
        value = bucket[index][1]
        closes.append(-float(value) if pixel_y else float(value))
        moment = datetime.fromtimestamp(index * max(1.0, bar_seconds), tz=timezone.utc)
        hours.append(moment.astimezone().hour)
    label = (
        f"{session[:8]} · {datetime.fromtimestamp(indices[0] * bar_seconds, tz=timezone.utc):%d/%m %H:%M}"
        f" a {datetime.fromtimestamp(indices[-1] * bar_seconds, tz=timezone.utc):%d/%m %H:%M}"
    )
    return MarketSeries(label=label, closes=tuple(closes), hours=tuple(hours))
