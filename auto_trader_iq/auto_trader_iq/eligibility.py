"""Elegibilidade estratégica com padrão fechado.

Este módulo não define estratégia. Ele apenas garante que nada seja considerado
elegível enquanto os critérios não forem declarados de forma explícita e completa.
Todos os campos de ``EligibilityCriteria`` são opcionais e, ausentes, bloqueiam a
elegibilidade em vez de assumir um valor razoável.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EligibilityCriteria:
    """Critérios declarados pelo operador. Ausente significa "não definido".

    Não existe valor padrão deliberado: qualquer campo em ``None`` mantém o
    candidato fora da elegibilidade e aparece no motivo da recusa.
    """

    min_confidence: float | None = None
    allowed_directions: tuple[str, ...] | None = None
    require_calibrated_palette: bool | None = None
    min_bars: int | None = None
    max_label_age_bars: int | None = None
    required_context_direction: str | None = None

    def missing_fields(self) -> list[str]:
        return [name for name, value in self.as_dict().items() if value is None]

    def as_dict(self) -> dict[str, object]:
        return {
            "min_confidence": self.min_confidence,
            "allowed_directions": self.allowed_directions,
            "require_calibrated_palette": self.require_calibrated_palette,
            "min_bars": self.min_bars,
            "max_label_age_bars": self.max_label_age_bars,
            "required_context_direction": self.required_context_direction,
        }


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    code: str
    eligible: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def display_text(self) -> str:
        if self.eligible:
            return "elegível para revisão humana"
        return "não elegível: " + "; ".join(self.reasons)


def evaluate_eligibility(
    criteria: EligibilityCriteria,
    observation: Mapping[str, object],
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
        )

    reasons: list[str] = []

    confidence = observation.get("confidence")
    if not isinstance(confidence, (int, float)):
        reasons.append("confiança do rótulo indisponível")
    elif confidence < float(criteria.min_confidence):
        reasons.append(
            f"confiança {confidence:.0f} abaixo do mínimo {float(criteria.min_confidence):.0f}"
        )

    direction = observation.get("direction")
    if direction not in tuple(criteria.allowed_directions or ()):
        reasons.append(f"direção {direction} não permitida pelos critérios")

    if criteria.require_calibrated_palette:
        if observation.get("palette_calibrated") is not True:
            reasons.append("paleta de velas não calibrada")

    bars = observation.get("bar_count")
    if not isinstance(bars, int) or bars < int(criteria.min_bars):
        reasons.append(f"velas detectadas abaixo do mínimo {criteria.min_bars}")

    label_age = observation.get("label_age_bars")
    if not isinstance(label_age, int):
        reasons.append("idade do rótulo em velas indisponível")
    elif label_age > int(criteria.max_label_age_bars):
        reasons.append(
            f"rótulo a {label_age} vela(s) da última, acima do limite "
            f"{criteria.max_label_age_bars}"
        )

    required = criteria.required_context_direction
    if required is not None and observation.get("context_direction") != required:
        reasons.append(
            f"contexto {observation.get('context_direction')} difere do exigido {required}"
        )

    if reasons:
        return EligibilityDecision("NOT_ELIGIBLE", False, tuple(reasons))
    return EligibilityDecision("ELIGIBLE_FOR_REVIEW", True, ())
