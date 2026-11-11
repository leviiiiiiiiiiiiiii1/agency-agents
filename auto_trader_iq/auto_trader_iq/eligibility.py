"""Elegibilidade estratégica declarada e auditável.

Este módulo não define estratégia: exige que os critérios sejam declarados de forma
explícita e completa. Campo ausente (``None``) bloqueia a elegibilidade em vez de
assumir um valor razoável. A configuração é validada antes de ser usada, e o hash
dos critérios acompanha cada decisão para que mudar parâmetros não reescreva o
histórico já registrado.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

BUY = "BUY"
SELL = "SELL"
DIRECTIONS = (BUY, SELL)

# Piso do classificador de contexto: abaixo disso ele nunca sai de "waiting".
MIN_CONTEXT_BARS = 6
# O filtro de associação aceita no máximo a última vela e a anterior.
MAX_STRUCTURAL_LABEL_AGE = 1

PROFILE_NAMES = ("conservadora", "equilibrada", "seletiva")


@dataclass(frozen=True, slots=True)
class EligibilityCriteria:
    """Critérios declarados pelo operador. Ausente significa "não definido"."""

    min_confidence: float | None = None
    allowed_directions: tuple[str, ...] | None = None
    require_calibrated_palette: bool | None = None
    min_bars: int | None = None
    max_label_age_bars: int | None = None
    # Contexto é tratado por dois booleanos: exigir direção é diferente de exigir
    # alinhamento, e o classificador devolve None em lateral/pavios/misto.
    require_directional_context: bool | None = None
    require_context_alignment: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_confidence": self.min_confidence,
            "allowed_directions": list(self.allowed_directions)
            if self.allowed_directions is not None
            else None,
            "require_calibrated_palette": self.require_calibrated_palette,
            "min_bars": self.min_bars,
            "max_label_age_bars": self.max_label_age_bars,
            "require_directional_context": self.require_directional_context,
            "require_context_alignment": self.require_context_alignment,
        }

    def missing_fields(self) -> list[str]:
        return [name for name, value in self.as_dict().items() if value is None]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EligibilityCriteria":
        unknown = set(data) - set(cls().as_dict())
        if unknown:
            raise ValueError(f"Critérios desconhecidos: {', '.join(sorted(unknown))}")
        directions = data.get("allowed_directions")
        if directions is not None:
            if isinstance(directions, str) or not isinstance(directions, (list, tuple)):
                raise ValueError("allowed_directions precisa ser uma lista de direções.")
            directions = tuple(directions)
        return cls(
            min_confidence=data.get("min_confidence"),
            allowed_directions=directions,
            require_calibrated_palette=data.get("require_calibrated_palette"),
            min_bars=data.get("min_bars"),
            max_label_age_bars=data.get("max_label_age_bars"),
            require_directional_context=data.get("require_directional_context"),
            require_context_alignment=data.get("require_context_alignment"),
        )

    def criteria_hash(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    code: str
    eligible: bool
    reasons: tuple[str, ...] = ()
    criteria_hash: str | None = None

    @property
    def display_text(self) -> str:
        if self.eligible:
            return "elegível para revisão humana"
        return "não elegível: " + "; ".join(self.reasons)


def validate_criteria(
    criteria: EligibilityCriteria,
    *,
    ocr_floor: float,
) -> list[str]:
    """Valida faixas e contradições. Retorna a lista de problemas encontrados.

    ``ocr_floor`` é a confiança mínima que o detector já aplica antes de qualquer
    decisão. Um limite de elegibilidade abaixo dela não filtra nada e é tratado como
    erro de configuração, não como escolha conservadora.
    """
    problems: list[str] = []

    if criteria.min_confidence is not None:
        if not isinstance(criteria.min_confidence, (int, float)):
            problems.append("min_confidence precisa ser numérico.")
        elif not 0 <= float(criteria.min_confidence) <= 100:
            problems.append("min_confidence precisa estar entre 0 e 100.")
        elif float(criteria.min_confidence) < float(ocr_floor):
            problems.append(
                f"min_confidence {float(criteria.min_confidence):.0f} está abaixo do piso "
                f"do OCR ({float(ocr_floor):.0f}) e não filtraria nada."
            )

    if criteria.allowed_directions is not None:
        if not criteria.allowed_directions:
            problems.append("allowed_directions não pode ficar vazio.")
        invalid = set(criteria.allowed_directions) - set(DIRECTIONS)
        if invalid:
            problems.append(
                f"allowed_directions inválidas: {', '.join(sorted(invalid))}."
            )

    if criteria.min_bars is not None:
        if not isinstance(criteria.min_bars, int) or isinstance(criteria.min_bars, bool):
            problems.append("min_bars precisa ser inteiro.")
        elif criteria.min_bars < MIN_CONTEXT_BARS:
            problems.append(
                f"min_bars abaixo de {MIN_CONTEXT_BARS} torna o contexto sempre 'waiting'."
            )

    if criteria.max_label_age_bars is not None:
        if not isinstance(criteria.max_label_age_bars, int) or isinstance(
            criteria.max_label_age_bars, bool
        ):
            problems.append("max_label_age_bars precisa ser inteiro.")
        elif not 0 <= criteria.max_label_age_bars <= MAX_STRUCTURAL_LABEL_AGE:
            problems.append(
                "max_label_age_bars acima de "
                f"{MAX_STRUCTURAL_LABEL_AGE} contradiz o filtro de associação."
            )

    for name, value in (
        ("require_calibrated_palette", criteria.require_calibrated_palette),
        ("require_directional_context", criteria.require_directional_context),
        ("require_context_alignment", criteria.require_context_alignment),
    ):
        if value is not None and not isinstance(value, bool):
            problems.append(f"{name} precisa ser booleano.")

    if (
        criteria.require_context_alignment is True
        and criteria.require_directional_context is False
    ):
        problems.append(
            "require_context_alignment exige require_directional_context verdadeiro."
        )
    if (
        criteria.require_directional_context is True
        and criteria.require_calibrated_palette is False
    ):
        problems.append(
            "exigir direção de contexto com paleta não calibrada é contraditório: "
            "sem calibração não existe direção."
        )
    return problems


CONSERVATIVE_CRITERIA = EligibilityCriteria(
    min_confidence=88.0,
    allowed_directions=(BUY, SELL),
    require_calibrated_palette=True,
    min_bars=10,
    max_label_age_bars=1,
    require_directional_context=True,
    require_context_alignment=True,
)

BALANCED_CRITERIA = EligibilityCriteria(
    min_confidence=80.0,
    allowed_directions=(BUY, SELL),
    require_calibrated_palette=True,
    min_bars=8,
    max_label_age_bars=1,
    require_directional_context=True,
    require_context_alignment=False,
)

SELECTIVE_CRITERIA = EligibilityCriteria(
    min_confidence=92.0,
    allowed_directions=(BUY, SELL),
    require_calibrated_palette=True,
    min_bars=12,
    max_label_age_bars=1,
    require_directional_context=True,
    require_context_alignment=True,
)

PROFILES: dict[str, EligibilityCriteria] = {
    "conservadora": CONSERVATIVE_CRITERIA,
    "equilibrada": BALANCED_CRITERIA,
    "seletiva": SELECTIVE_CRITERIA,
}


def evaluate_eligibility(
    criteria: EligibilityCriteria,
    observation: Mapping[str, Any],
) -> EligibilityDecision:
    """Avalia um candidato já associado a uma vela recente.

    A ordem é deliberada: primeiro verifica se os critérios existem, porque um
    candidato nunca deve ser aprovado por ausência de configuração.
    """
    missing = criteria.missing_fields()
    if missing:
        return EligibilityDecision(
            code="CRITERIA_UNDEFINED",
            eligible=False,
            reasons=(f"critérios não definidos: {', '.join(missing)}",),
            criteria_hash=criteria.criteria_hash(),
        )

    reasons: list[str] = []

    confidence = observation.get("confidence")
    if not isinstance(confidence, (int, float)):
        reasons.append("confiança do rótulo indisponível")
    elif float(confidence) < float(criteria.min_confidence):
        reasons.append(
            f"confiança {float(confidence):.0f} abaixo do mínimo "
            f"{float(criteria.min_confidence):.0f}"
        )

    direction = observation.get("direction")
    if direction not in tuple(criteria.allowed_directions or ()):
        reasons.append(f"direção {direction} não permitida pelos critérios")

    if criteria.require_calibrated_palette:
        if observation.get("palette_calibrated") is not True:
            reasons.append("paleta de velas não calibrada")

    bars = observation.get("bar_count")
    if not isinstance(bars, int) or isinstance(bars, bool):
        reasons.append("quantidade de velas indisponível")
    elif bars < int(criteria.min_bars):
        reasons.append(f"velas detectadas ({bars}) abaixo do mínimo {criteria.min_bars}")

    label_age = observation.get("label_age_bars")
    if not isinstance(label_age, int) or isinstance(label_age, bool):
        reasons.append("idade do rótulo em velas indisponível")
    elif label_age > int(criteria.max_label_age_bars):
        reasons.append(
            f"rótulo a {label_age} vela(s) da última, acima do limite "
            f"{criteria.max_label_age_bars}"
        )

    context_direction = observation.get("context_direction")
    if criteria.require_directional_context and context_direction is None:
        reasons.append("contexto visual sem direção (lateral, pavios ou misto)")
    if (
        criteria.require_context_alignment
        and context_direction is not None
        and context_direction != direction
    ):
        reasons.append(
            f"contexto {context_direction} não confirma a direção do sinal {direction}"
        )

    if reasons:
        return EligibilityDecision(
            code="NOT_ELIGIBLE",
            eligible=False,
            reasons=tuple(reasons),
            criteria_hash=criteria.criteria_hash(),
        )
    return EligibilityDecision(
        code="ELIGIBLE_FOR_REVIEW",
        eligible=True,
        reasons=(),
        criteria_hash=criteria.criteria_hash(),
    )
