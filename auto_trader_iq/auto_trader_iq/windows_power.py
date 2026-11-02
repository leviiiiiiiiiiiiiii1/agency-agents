"""Opt-in Windows execution-state controls to avoid idle display/system sleep."""

from __future__ import annotations

import ctypes
import sys


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def set_windows_keep_awake(enabled: bool) -> None:
    """Keep Windows awake/display-on for the calling thread, or release the request.

    This does not synthesize mouse input and does not prevent a user from manually
    locking the workstation. Call it from the long-lived Tk UI thread.
    """
    if sys.platform != "win32":
        raise RuntimeError("A prevenção de suspensão só está disponível no Windows.")

    kernel32 = ctypes.windll.kernel32
    set_execution_state = kernel32.SetThreadExecutionState
    set_execution_state.argtypes = [ctypes.c_uint]
    set_execution_state.restype = ctypes.c_uint
    flags = ES_CONTINUOUS
    if enabled:
        flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    if set_execution_state(flags) == 0:
        raise ctypes.WinError()
