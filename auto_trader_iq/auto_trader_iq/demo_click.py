"""Guarded Windows mouse primitives for the user's explicitly selected DEMO test."""

from __future__ import annotations

import ctypes
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
        raise PermissionError("Cliques automáticos não estão explicitamente habilitados nesta sessão.")
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


def windows_window_signature_at_point(x: int, y: int) -> dict[str, object] | None:
    """Return a persisted identity/geometry signature for the root window at a point."""
    if sys.platform != "win32":
        raise RuntimeError("A identificação da janela sob o cursor só funciona no Windows.")
    from ctypes import wintypes

    handle = windows_window_at_point(x, y)
    if handle is None:
        return None
    user32 = ctypes.windll.user32
    hwnd = wintypes.HWND(handle)
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    )
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    class_name = ctypes.create_unicode_buffer(256)
    rect = wintypes.RECT()
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRect.restype = wintypes.BOOL
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    user32.GetClassNameW(hwnd, class_name, len(class_name))
    return {
        "process_id": int(process_id.value),
        "class_name": class_name.value,
        "rect": [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)],
    }


def windows_mouse_move(x: int, y: int) -> None:
    """Move the Windows cursor without pressing any mouse button."""
    if sys.platform != "win32":
        raise RuntimeError("Movimentos do mouse só podem ser usados no Windows.")
    user32 = ctypes.windll.user32
    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.SetCursorPos.restype = ctypes.c_bool
    if not user32.SetCursorPos(int(x), int(y)):
        raise ctypes.WinError()


def windows_last_input_idle_seconds() -> float:
    """Return seconds since the last input in the Windows session."""
    if sys.platform != "win32":
        raise RuntimeError("A leitura de inatividade só funciona no Windows.")
    from ctypes import wintypes

    class LastInputInfo(ctypes.Structure):
        _fields_ = (("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD))

    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(LastInputInfo)
    user32 = ctypes.windll.user32
    user32.GetLastInputInfo.argtypes = (ctypes.POINTER(LastInputInfo),)
    user32.GetLastInputInfo.restype = wintypes.BOOL
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError()
    kernel32 = ctypes.windll.kernel32
    kernel32.GetTickCount.restype = wintypes.DWORD
    now = int(kernel32.GetTickCount())
    elapsed_ms = (now - int(info.dwTime)) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


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
