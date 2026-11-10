"""Explicit separation of observation, simulation, demo, and real execution modes.

This application currently has no trusted broker adapter that can verify an account,
order, balance, stake, payout, expiry, or settlement. Consequently DEMO and REAL
execution are deliberately unavailable; a UI toggle is not proof of account type.
"""

from __future__ import annotations

from enum import StrEnum


class OperationMode(StrEnum):
    OBSERVATION = "OBSERVATION"
    SIMULATION = "SIMULATION"
    DEMO = "DEMO"
    REAL = "REAL"


class ModeDecision(StrEnum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    SIMULATION_ONLY = "SIMULATION_ONLY"
    BLOCKED_NO_ACCOUNT_VERIFICATION = "BLOCKED_NO_ACCOUNT_VERIFICATION"
    BLOCKED_REAL_MODE = "BLOCKED_REAL_MODE"


def mode_decision(mode: OperationMode) -> ModeDecision:
    """Return the strongest execution permission supported by current integrations."""
    if mode is OperationMode.OBSERVATION:
        return ModeDecision.OBSERVE_ONLY
    if mode is OperationMode.SIMULATION:
        return ModeDecision.SIMULATION_ONLY
    if mode is OperationMode.DEMO:
        return ModeDecision.BLOCKED_NO_ACCOUNT_VERIFICATION
    return ModeDecision.BLOCKED_REAL_MODE


def actual_order_execution_allowed(mode: OperationMode) -> bool:
    """Fail closed: no current mode is authorized to send a platform click/order."""
    return False
