"""Captura segura de monitores e regiões usando MSS.

A camada não contém automação de mouse/teclado nem integração com corretora.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ScreenRegion:
    """Retângulo absoluto em pixels do desktop virtual."""

    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("A largura e a altura da região devem ser maiores que zero.")
        for name, value in (("left", self.left), ("top", self.top), ("width", self.width), ("height", self.height)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} deve ser um número inteiro de pixels.")

    def as_mss_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ScreenRegion":
        return cls(
            left=int(value["left"]),
            top=int(value["top"]),
            width=int(value["width"]),
            height=int(value["height"]),
        )


class ScreenCapture:
    """Abstrai MSS. Cada chamada cria e fecha seu próprio capturador."""

    @staticmethod
    def list_monitors() -> list[dict[str, int]]:
        try:
            import mss
        except ImportError as exc:  # pragma: no cover - depends on installation
            raise RuntimeError("Dependência MSS ausente. Instale com: pip install -r requirements.txt") from exc

        with mss.mss() as sct:
            # MSS monitor 0 representa todo o desktop virtual; os seguintes são displays individuais.
            return [dict(monitor) for monitor in sct.monitors[1:]]

    @staticmethod
    def capture(region: ScreenRegion):
        """Captura uma região e devolve uma imagem PIL em RGB."""
        try:
            import mss
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - depends on installation
            raise RuntimeError("Dependências ausentes. Instale com: pip install -r requirements.txt") from exc

        with mss.mss() as sct:
            shot = sct.grab(region.as_mss_dict())
            return Image.frombytes("RGB", shot.size, shot.rgb)
