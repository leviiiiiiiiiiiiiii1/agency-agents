"""Guarded mouse-click primitives for the user's explicitly selected DEMO test."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ClickTarget:
    x: int
    y: int

    def __post_init__(self) -> None:
        if isinstance(self.x, bool) or isinstance(self.y, bool):
            raise ValueError("As coordenadas do botão precisam ser inteiros não negativos.")
        if not isinstance(self.x, int) or not isinstance(self.y, int) or self.x < 0 or self.y < 0:
            raise ValueError("As coordenadas do botão precisam ser inteiros não negativos.")


def click_demo_direction(
    direction: str,
    *,
    buy_target: ClickTarget | None,
    sell_target: ClickTarget | None,
    enabled: bool,
    demo_confirmed: bool,
    clicker: Callable[[int, int], None],
) -> ClickTarget:
    """Click the calibrated direction button only after session-level opt-in.

    The caller must still enforce signal, timeframe, platform-clock window,
    screen-region and app-window checks before invoking this function.
    """
    if not enabled or not demo_confirmed:
        raise PermissionError("Cliques DEMO não estão explicitamente habilitados nesta sessão.")
    if direction == "BUY":
        target = buy_target
    elif direction == "SELL":
        target = sell_target
    else:
        raise ValueError("Direção desconhecida; somente BUY/SELL são aceitos.")
    if target is None:
        raise ValueError("O botão desta direção ainda não foi calibrado.")
    clicker(target.x, target.y)
    return target


def windows_mouse_click(x: int, y: int) -> None:
    """Send a single left mouse click using PyAutoGUI on the Windows host."""
    import sys

    if sys.platform != "win32":
        raise RuntimeError("Cliques da corretora só podem ser usados no Windows.")
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "PyAutoGUI não está instalado. No Windows, instale as dependências atualizadas."
        ) from exc
    pyautogui.click(x=x, y=y, clicks=1, interval=0.1)
