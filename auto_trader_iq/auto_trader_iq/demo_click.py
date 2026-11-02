"""Guarded Windows mouse primitives for the user's explicitly selected DEMO test."""

from __future__ import annotations

import ctypes
import math
import sys
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


def demo_entry_deadline_open(
    armed_at: float | None,
    now: float,
    max_delay_seconds: float = 15.0,
) -> bool:
    """Return whether an automatic DEMO entry is still within its arm deadline."""
    if armed_at is None or not math.isfinite(armed_at) or not math.isfinite(now):
        return False
    if not math.isfinite(max_delay_seconds) or max_delay_seconds < 0:
        return False
    elapsed = now - armed_at
    return 0 <= elapsed <= max_delay_seconds


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
    screen-region and calibrated frontmost-window checks before invoking this function.
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


def windows_mouse_position() -> tuple[int, int]:
    """Read the current cursor coordinates through the Windows API (no click)."""
    if sys.platform != "win32":
        raise RuntimeError("A calibração do mouse só pode ser usada no Windows.")

    class Point(ctypes.Structure):
        _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))

    point = Point()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError()
    return int(point.x), int(point.y)


def windows_window_at_point(x: int, y: int) -> int | None:
    """Get the root window currently visible at a physical screen point."""
    if sys.platform != "win32":
        raise RuntimeError("A identificação da janela sob o cursor só funciona no Windows.")
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    window = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not window:
        return None
    root_window = user32.GetAncestor(window, 2)  # GA_ROOT
    return int(root_window or window)


def windows_mouse_click(x: int, y: int) -> None:
    """Move the cursor and send exactly one left click using the Windows API."""
    if sys.platform != "win32":
        raise RuntimeError("Cliques da corretora só podem ser usados no Windows.")
    user32 = ctypes.windll.user32
    if not user32.SetCursorPos(int(x), int(y)):
        raise ctypes.WinError()
    down = 0x0002  # MOUSEEVENTF_LEFTDOWN
    up = 0x0004    # MOUSEEVENTF_LEFTUP
    user32.mouse_event(down, 0, 0, 0, 0)
    user32.mouse_event(up, 0, 0, 0, 0)
