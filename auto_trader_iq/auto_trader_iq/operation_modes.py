"""Explicit separation of observation, simulation, demo, and real execution modes.

This application currently has no trusted broker adapter that can verify an account,
order, balance, stake, payout, expiry, or settlement. REAL execution is unavailable
and stays unavailable. DEMO opens only through an explicit statement by the user,
made once per session, that the account on screen is a demo account - the app
still cannot check it, so the statement travels with every order it sends.
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
    DEMO_UNDER_USER_CONFIRMATION = "DEMO_UNDER_USER_CONFIRMATION"
    BLOCKED_NO_ACCOUNT_VERIFICATION = "BLOCKED_NO_ACCOUNT_VERIFICATION"
    BLOCKED_REAL_MODE = "BLOCKED_REAL_MODE"


def mode_decision(
    mode: OperationMode, *, demo_confirmed: bool = False
) -> ModeDecision:
    """Return the strongest execution permission supported by current integrations.

    ``demo_confirmed`` carries the user's per-session statement that the account on
    screen is DEMO. Without it DEMO stays blocked, exactly as before.
    """
    if mode is OperationMode.OBSERVATION:
        return ModeDecision.OBSERVE_ONLY
    if mode is OperationMode.SIMULATION:
        return ModeDecision.SIMULATION_ONLY
    if mode is OperationMode.DEMO:
        if demo_confirmed:
            return ModeDecision.DEMO_UNDER_USER_CONFIRMATION
        return ModeDecision.BLOCKED_NO_ACCOUNT_VERIFICATION
    return ModeDecision.BLOCKED_REAL_MODE


def actual_order_execution_allowed(
    mode: OperationMode, *, demo_confirmed: bool = False
) -> bool:
    """Fail closed: only DEMO, and only with the user's explicit statement.

    REAL never returns True here, whatever is passed in - the app cannot tell a
    demo account from a real one, and that is the one mistake it must not make.
    """
    if mode is not OperationMode.DEMO:
        return False
    return bool(demo_confirmed)
