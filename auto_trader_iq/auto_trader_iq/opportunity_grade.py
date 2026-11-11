"""Classificação do momento da oportunidade a partir do que a tela permite medir.

O indicador que gera as etiquetas usa RSI, MACD e distância às médias. Nada disso é
legível por pixel hoje. Este módulo classifica a oportunidade apenas com medidas
verificáveis — idade do rótulo em velas, corpo, pavios, posição dentro da faixa
recente e regime de contexto — e declara explicitamente o que ficou sem medir.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import median
from typing import Any, Mapping, Sequence

GRADE_IMMEDIATE = "A"
GRADE_GOOD = "B"
GRADE_RISKY = "C"
GRADE_NO_TRADE = "NO_TRADE"

# Medidas que a captura de tela não fornece hoje. Ficam explícitas para que a
# classificação nunca sugira que foram consideradas.
UNMEASURED = ("rsi20", "macd_histograma", "distancia_ema20")

# Versão 1 gravava ``fresh_age_bars=0``, valor que a tela nunca produz (a vela em
# formação fica sempre à direita da seta). Versão 2 corrige para 1.
GRADE_CRITERIA_VERSION = 2

# Marca como a geometria foi medida. ``setup_candle_v1`` mede a vela anterior à
# seta; registros sem esta marca usaram a própria vela da seta e não são
# comparáveis com os novos.
GRADE_METHOD = "setup_candle_v1"


@dataclass(frozen=True, slots=True)
class GradeCriteria:
    """Limiares da classificação. Ausente significa "não definido"."""

    fresh_age_bars: int | None = None
    max_age_bars: int | None = None
    min_body_vs_median: float | None = None
    max_body_vs_median_a: float | None = None
    max_body_vs_median_b: float | None = None
    min_distance_to_level: float | None = None
    block_lateral_regime: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "fresh_age_bars": self.fresh_age_bars,
            "max_age_bars": self.max_age_bars,
            "min_body_vs_median": self.min_body_vs_median,
            "max_body_vs_median_a": self.max_body_vs_median_a,
            "max_body_vs_median_b": self.max_body_vs_median_b,
            "min_distance_to_level": self.min_distance_to_level,
            "block_lateral_regime": self.block_lateral_regime,
        }

    def missing_fields(self) -> list[str]:
        return [name for name, value in self.as_dict().items() if value is None]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GradeCriteria":
        unknown = set(data) - set(cls().as_dict())
        if unknown:
            raise ValueError(f"Limiares desconhecidos: {', '.join(sorted(unknown))}")
        return cls(**{name: data.get(name) for name in cls().as_dict()})


# A seta é desenhada na última vela fechada, e o gráfico mantém a vela em formação à
# direita dela: idade 0 não ocorre na prática. Medido em 12 quadros com sinal — todos
# com idade 1. Por isso "fresco" significa idade <= 1, aprovado pelo usuário.
DEFAULT_CRITERIA = GradeCriteria(
    fresh_age_bars=1,
    max_age_bars=2,
    min_body_vs_median=0.4,
    max_body_vs_median_a=1.5,
    max_body_vs_median_b=2.0,
    min_distance_to_level=0.15,
    block_lateral_regime=True,
)


def migrate_criteria(
    criteria: GradeCriteria, version: int | None
) -> tuple[GradeCriteria, bool]:
    """Aplica correções de padrão antigo. Devolve ``(criteria, mudou)``.

    Só mexe no valor que era padrão da versão anterior; um valor diferente foi
    escolha explícita e é preservado.
    """
    if version is not None and version >= GRADE_CRITERIA_VERSION:
        return criteria, False
    if criteria.fresh_age_bars == 0:
        return replace(criteria, fresh_age_bars=DEFAULT_CRITERIA.fresh_age_bars), True
    return criteria, False


def validate_grade_criteria(criteria: GradeCriteria) -> list[str]:
    problems: list[str] = []
    if criteria.fresh_age_bars is not None and criteria.max_age_bars is not None:
        if criteria.fresh_age_bars > criteria.max_age_bars:
            problems.append("fresh_age_bars não pode exceder max_age_bars.")
    for name in ("fresh_age_bars", "max_age_bars"):
        value = getattr(criteria, name)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            problems.append(f"{name} precisa ser inteiro.")
        elif value is not None and value < 0:
            problems.append(f"{name} não pode ser negativo.")
    for name in (
        "min_body_vs_median",
        "max_body_vs_median_a",
        "max_body_vs_median_b",
        "min_distance_to_level",
    ):
        value = getattr(criteria, name)
        if value is not None and not isinstance(value, (int, float)):
            problems.append(f"{name} precisa ser numérico.")
        elif value is not None and value < 0:
            problems.append(f"{name} não pode ser negativo.")
    if (
        criteria.max_body_vs_median_a is not None
        and criteria.max_body_vs_median_b is not None
        and criteria.max_body_vs_median_a > criteria.max_body_vs_median_b
    ):
        problems.append("max_body_vs_median_a não pode exceder max_body_vs_median_b.")
    if criteria.block_lateral_regime is not None and not isinstance(
        criteria.block_lateral_regime, bool
    ):
        problems.append("block_lateral_regime precisa ser booleano.")
    return problems


@dataclass(frozen=True, slots=True)
class SignalFeatures:
    direction: str
    age_bars: int | None
    body: float | None
    candle_range: float | None
    upper_wick: float | None
    lower_wick: float | None
    body_vs_median: float | None
    close_from_extreme: float | None
    distance_to_level: float | None
    context_regime: str | None
    context_direction: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "age_bars": self.age_bars,
            "body": self.body,
            "candle_range": self.candle_range,
            "upper_wick": self.upper_wick,
            "lower_wick": self.lower_wick,
            "body_vs_median": (
                round(self.body_vs_median, 3) if self.body_vs_median is not None else None
            ),
            "close_from_extreme": (
                round(self.close_from_extreme, 3)
                if self.close_from_extreme is not None
                else None
            ),
            "distance_to_level": (
                round(self.distance_to_level, 3)
                if self.distance_to_level is not None
                else None
            ),
            "context_regime": self.context_regime,
            "context_direction": self.context_direction,
        }


@dataclass(frozen=True, slots=True)
class Grade:
    code: str
    reasons: tuple[str, ...]
    unmeasured: tuple[str, ...] = UNMEASURED

    @property
    def display_text(self) -> str:
        if self.code == GRADE_NO_TRADE:
            return "NÃO OPERAR: " + "; ".join(self.reasons)
        label = {
            GRADE_IMMEDIATE: "entrada imediata",
            GRADE_GOOD: "boa oportunidade",
            GRADE_RISKY: "entrada arriscada",
        }[self.code]
        detail = f" ({'; '.join(self.reasons)})" if self.reasons else ""
        return f"classe {self.code} — {label}{detail}"


def build_features(
    candidate: Any,
    bars: Sequence[Any],
    candles: Sequence[Any],
    *,
    direction: str,
    age_bars: int | None,
    context_regime: str | None,
    context_direction: str | None,
    reference_window: int = 20,
    body_window: int = 10,
    setup_offset: int = 1,
) -> SignalFeatures | None:
    """Reúne as medidas de um candidato; ``None`` se a vela não for identificável.

    A geometria só existe para velas com cor calibrada, então ``candles`` pode ser
    menor que ``bars``. O casamento é por proximidade dentro da mesma tolerância
    usada pela idade do rótulo, e a mediana usa as velas à esquerda desta — nunca
    índices de ``bars`` aplicados a ``candles``.
    """
    if not bars or not candles:
        return None
    text_center = candidate.left + candidate.width / 2
    index = min(range(len(bars)), key=lambda i: abs(bars[i].center_x - text_center))
    gaps = [bars[i + 1].center_x - bars[i].center_x for i in range(len(bars) - 1)]
    normal_gaps = [gap for gap in gaps if gap >= 8]
    tolerance = max(18.0, (median(normal_gaps) if normal_gaps else 24.0) * 0.65)
    # O indicador avalia a vela fechada e desenha a seta na vela seguinte, que é a
    # vela de entrada. Medir o corpo/fechamento da própria seta descreveria o que já
    # aconteceu depois do sinal. O setup é a vela anterior à seta.
    setup_index = index - setup_offset
    if setup_index < 0:
        return None
    setup_bar_x = float(bars[setup_index].center_x)
    candle = min(candles, key=lambda item: abs(item.center_x - setup_bar_x))
    if abs(candle.center_x - setup_bar_x) > tolerance:
        return None
    entry_candle = min(candles, key=lambda item: abs(item.center_x - bars[index].center_x))
    if abs(entry_candle.center_x - bars[index].center_x) > tolerance:
        entry_candle = candle

    body = max(0.0, float(candle.body_bottom - candle.body_top))
    candle_range = max(1.0, float(candle.low - candle.high))
    at_or_before = [
        item for item in candles if float(item.center_x) <= float(candle.center_x) + 1e-6
    ]
    bodies = [
        max(0.0, float(item.body_bottom - item.body_top))
        for item in at_or_before[-body_window:]
    ]
    typical_body = median(bodies) if bodies else 0.0
    body_vs_median = (body / typical_body) if typical_body > 0 else None

    # 0 = fechou colado no extremo favorável (movimento já percorrido).
    if direction == "BUY":
        close_from_extreme = (float(candle.close_y) - float(candle.high)) / candle_range
    else:
        close_from_extreme = (float(candle.low) - float(candle.close_y)) / candle_range

    window = candles[-reference_window:]
    zone_top = min(float(item.high) for item in window)
    zone_bottom = max(float(item.low) for item in window)
    zone_range = max(1.0, zone_bottom - zone_top)
    # A distância ao nível contrário usa o preço de entrada (fechamento da vela da
    # seta), não o fechamento do setup: é onde o preço está quando se decide entrar.
    close_y = float(entry_candle.close_y)
    if direction == "BUY":
        distance_to_level = (close_y - zone_top) / zone_range
    else:
        distance_to_level = (zone_bottom - close_y) / zone_range

    return SignalFeatures(
        direction=direction,
        age_bars=age_bars,
        body=body,
        candle_range=candle_range,
        upper_wick=float(candle.upper_wick),
        lower_wick=float(candle.lower_wick),
        body_vs_median=body_vs_median,
        close_from_extreme=close_from_extreme,
        distance_to_level=distance_to_level,
        context_regime=context_regime,
        context_direction=context_direction,
    )


def grade_opportunity(
    features: SignalFeatures | None,
    criteria: GradeCriteria,
) -> Grade:
    """Classifica o momento. Sem medidas suficientes, não classifica como bom."""
    missing = criteria.missing_fields()
    if missing:
        return Grade("CRITERIA_UNDEFINED", (f"limiares não definidos: {', '.join(missing)}",))
    if features is None:
        return Grade(GRADE_NO_TRADE, ("vela do rótulo não identificada",))

    if criteria.block_lateral_regime and features.context_regime == "lateral":
        return Grade(GRADE_NO_TRADE, ("mercado lateralizado",))
    if features.age_bars is None:
        return Grade(GRADE_NO_TRADE, ("idade do rótulo indisponível",))
    if features.age_bars > criteria.max_age_bars:
        return Grade(
            GRADE_NO_TRADE,
            (f"rótulo a {features.age_bars} vela(s), acima do limite {criteria.max_age_bars}",),
        )

    severe: list[str] = []
    minor: list[str] = []
    strong: list[str] = []

    if features.age_bars > criteria.fresh_age_bars:
        minor.append(f"rótulo com {features.age_bars} vela(s) de idade")
    elif features.age_bars == 0:
        strong.append("rótulo na vela atual")
    else:
        strong.append(f"rótulo na vela fechada mais recente ({features.age_bars} de idade)")

    ratio = features.body_vs_median
    if ratio is None:
        minor.append("corpo típico indisponível")
    elif ratio < criteria.min_body_vs_median:
        minor.append(f"corpo {ratio:.2f}× a mediana (fraco)")
    elif ratio > criteria.max_body_vs_median_b:
        severe.append(f"corpo {ratio:.2f}× a mediana (esticado)")
    elif ratio <= criteria.max_body_vs_median_a:
        strong.append(f"corpo {ratio:.2f}× a mediana")
    else:
        # Faixa intermediária: vela maior que o ideal, ainda não esticada.
        minor.append(f"corpo {ratio:.2f}× a mediana (acima do ideal)")

    distance = features.distance_to_level
    if distance is None:
        minor.append("posição na faixa indisponível")
    elif distance < criteria.min_distance_to_level:
        severe.append(f"preço a {distance:.0%} da faixa até o nível contrário")
    else:
        strong.append(f"folga de {distance:.0%} até o nível contrário")

    close_pos = features.close_from_extreme
    if close_pos is not None and close_pos <= 0.2:
        severe.append("fechou colado no extremo do próprio candle")

    if (
        features.context_direction is not None
        and features.context_direction != features.direction
    ):
        severe.append(
            f"sinal {features.direction} contra contexto {features.context_direction}"
        )

    if severe:
        return Grade(GRADE_RISKY, tuple(severe + minor))
    if minor:
        return Grade(GRADE_GOOD, tuple(minor))
    return Grade(GRADE_IMMEDIATE, tuple(strong))
