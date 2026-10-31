"""Leitura experimental de rótulos BUY/SELL por OCR.

Gera candidatos visuais para revisão humana. Não valida velas nem autoriza ordens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SignalCandidate:
    direction: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    observed_text: str


def parse_ocr_rows(data: dict[str, Any], min_confidence: float = 70.0) -> list[SignalCandidate]:
    """Filtra BUY/SELL exatos, conservando caixas e a confiança dada pelo Tesseract."""
    if not 0 <= min_confidence <= 100:
        raise ValueError("A confiança mínima deve estar entre 0 e 100.")

    aliases = {
        "BUY": "BUY",
        "COMPRA": "BUY",
        "COMPRAR": "BUY",
        "SELL": "SELL",
        "VENDER": "SELL",
        "VENDA": "SELL",
    }
    candidates: list[SignalCandidate] = []
    row_count = len(data.get("text", []))
    for index in range(row_count):
        observed = str(data["text"][index]).strip()
        normalized = re.sub(r"[^A-Z]", "", observed.upper())
        direction = aliases.get(normalized)
        if direction is None:
            continue
        try:
            confidence = float(data["conf"][index])
            left = int(data["left"][index])
            top = int(data["top"][index])
            width = int(data["width"][index])
            height = int(data["height"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if confidence < min_confidence or width <= 0 or height <= 0:
            continue
        candidates.append(SignalCandidate(direction, confidence, left, top, width, height, observed))
    return candidates


class TesseractSignalDetector:
    """Detector configurável; requer o pacote pytesseract e o executável Tesseract OCR."""

    def __init__(self, min_confidence: float = 70.0, executable: str | None = None) -> None:
        if not 0 <= min_confidence <= 100:
            raise ValueError("A confiança mínima deve estar entre 0 e 100.")
        self.min_confidence = min_confidence
        self.executable = executable

    def check_ready(self) -> None:
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError("Falta pytesseract. Execute: python -m pip install -r requirements.txt") from exc

        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise RuntimeError(
                "Não encontrei o executável Tesseract OCR. Instale-o no Windows e, se necessário, "
                "defina TESSERACT_CMD com o caminho completo para tesseract.exe."
            ) from exc

    def detect(self, image) -> list[SignalCandidate]:
        """Executa uma leitura OCR sobre a captura. Coordenadas retornadas são da captura original."""
        try:
            import pytesseract
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise RuntimeError("Instale as dependências Python com: python -m pip install -r requirements.txt") from exc

        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        scale = 2
        prepared = ImageOps.autocontrast(image.convert("L"))
        prepared = prepared.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
        config = "--oem 3 --psm 11 -c tessedit_char_whitelist=BUYSELLCOMPRAVENDER"
        data = pytesseract.image_to_data(prepared, config=config, output_type=pytesseract.Output.DICT)
        candidates = parse_ocr_rows(data, self.min_confidence)
        return [
            SignalCandidate(c.direction, c.confidence, c.left // scale, c.top // scale,
                            max(1, c.width // scale), max(1, c.height // scale), c.observed_text)
            for c in candidates
        ]
