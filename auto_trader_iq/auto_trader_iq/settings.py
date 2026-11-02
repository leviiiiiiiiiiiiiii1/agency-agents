"""Helpers for persistent application settings and Tesseract discovery."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any


def load_settings(path: Path) -> dict[str, Any]:
    """Load a JSON object of user settings from disk."""
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("O arquivo de configuração precisa conter um objeto JSON.")
    return result


def save_settings(path: Path, settings: Mapping[str, Any]) -> None:
    """Atomically write settings so an interruption cannot truncate the config."""
    target = Path(path)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(dict(settings), indent=2), encoding="utf-8")
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def find_tesseract_executable(
    environ: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
) -> str:
    """Return an explicit override, a PATH result, or a standard Windows install path."""
    env = os.environ if environ is None else environ
    configured = str(env.get("TESSERACT_CMD", "")).strip().strip('"')
    if configured:
        return configured

    path_result = shutil.which("tesseract", path=env.get("PATH"))
    if path_result:
        return path_result

    if (sys.platform if platform is None else platform) != "win32":
        return ""

    program_files = [
        env.get("ProgramFiles", r"C:\Program Files"),
        env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    seen: set[str] = set()
    for base in program_files:
        candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
        normalized = os.path.normcase(str(candidate))
        if normalized not in seen:
            seen.add(normalized)
            if candidate.is_file():
                return str(candidate)
    return ""
