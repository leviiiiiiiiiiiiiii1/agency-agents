"""Leitura experimental de rótulos BUY/SELL por OCR.

Gera candidatos visuais para revisão humana. Não valida velas nem autoriza ordens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .candle_timer import PlatformClockReading, parse_platform_clock, parse_platform_clock_line


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


def _signal_color_direction(image, candidate: SignalCandidate) -> str | None:
    """Classify a colored label by its dominant green (BUY) or red (SELL) pixels.

    Neutral/unknown labels return None so OCR remains usable with uncolored themes.
    A color that contradicts the recognized word rejects the candidate rather than
    silently changing its direction.
    """
    left = max(0, candidate.left - 2)
    top = max(0, candidate.top - 2)
    right = min(image.width, candidate.left + candidate.width + 2)
    bottom = min(image.height, candidate.top + candidate.height + 2)
    if right <= left or bottom <= top:
        return None
    red = green = 0
    for r, g, b in image.crop((left, top, right, bottom)).convert("RGB").getdata():
        if g >= 70 and g >= r * 1.25 and g >= b * 1.08:
            green += 1
        elif r >= 85 and r >= g * 1.30 and r >= b * 1.18:
            red += 1
    dominant = max(red, green)
    if dominant < 4 or dominant < min(red, green) * 1.35:
        return None
    return "SELL" if red > green else "BUY"


def _summarize_clock_ocr(data: dict[str, Any], limit: int = 180) -> str:
    """Short local diagnostic of tokens from the bottom-right clock-only crop."""
    snippets: list[str] = []
    texts = data.get("text", [])
    confidences = data.get("conf", [])
    for index, raw in enumerate(texts):
        token = str(raw).strip()
        if not token:
            continue
        try:
            confidence = float(confidences[index])
            snippets.append(f"{token}[{confidence:.0f}]")
        except (IndexError, TypeError, ValueError):
            snippets.append(token)
    return " ".join(snippets)[:limit]


class TesseractSignalDetector:
    """Detector configurável; requer o pacote pytesseract e o executável Tesseract OCR."""

    def __init__(self, min_confidence: float = 70.0, executable: str | None = None) -> None:
        if not 0 <= min_confidence <= 100:
            raise ValueError("A confiança mínima deve estar entre 0 e 100.")
        self.min_confidence = min_confidence
        self.executable = executable
        self.last_clock_ocr_text = ""
        self.last_candidate_count = 0
        self.last_color_rejected_count = 0

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

    def detect_frame(self, image) -> tuple[list[SignalCandidate], PlatformClockReading | None]:
        """Lê sinais e relógio; usa OCR focado no rodapé se a leitura geral falhar.

        As coordenadas retornadas são relativas à captura original. O relógio só é
        aceito junto ao rótulo HORA ATUAL no canto inferior direito, nunca pelo PC.
        """
        try:
            import pytesseract
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise RuntimeError("Instale as dependências Python com: python -m pip install -r requirements.txt") from exc

        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        self.last_clock_ocr_text = ""
        scale = 2
        prepared = ImageOps.autocontrast(image.convert("L"))
        prepared = prepared.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
        whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:"
        config = f"--oem 3 --psm 11 -c tessedit_char_whitelist={whitelist}"
        data = pytesseract.image_to_data(prepared, config=config, output_type=pytesseract.Output.DICT)
        candidates = parse_ocr_rows(data, self.min_confidence)
        candidates = [
            SignalCandidate(c.direction, c.confidence, c.left // scale, c.top // scale,
                            max(1, c.width // scale), max(1, c.height // scale), c.observed_text)
            for c in candidates
        ]
        self.last_candidate_count = len(candidates)
        self.last_color_rejected_count = 0
        color_checked: list[SignalCandidate] = []
        for candidate in candidates:
            color_direction = _signal_color_direction(image, candidate)
            if color_direction is not None and color_direction != candidate.direction:
                self.last_color_rejected_count += 1
            else:
                color_checked.append(candidate)
        candidates = color_checked
        clock = parse_platform_clock(data, prepared.width, prepared.height)
        if clock is not None:
            clock = PlatformClockReading(
                clock.hour, clock.minute, clock.second, clock.confidence,
                clock.left // scale, clock.top // scale, clock.text,
            )
            self.last_clock_ocr_text = f"full:{clock.text}"
        else:
            # HORA ATUAL costuma estar em fonte pequena no rodapé. Leia apenas
            # essa faixa ampliada; tente um segundo layout se o primeiro não bastar.
            crop_left = int(image.width * 0.70)
            crop_top = int(image.height * 0.93)
            clock_crop = image.crop((crop_left, crop_top, image.width, image.height)).convert("L")
            clock_scale = 4
            clock_crop = ImageOps.autocontrast(clock_crop).resize(
                (clock_crop.width * clock_scale, clock_crop.height * clock_scale),
                Image.Resampling.LANCZOS,
            )
            clock = None
            diagnostics: list[str] = []
            for page_segmentation in (7, 6):
                # Não use whitelist na faixa do relógio: ela elimina os espaços,
                # cola HORA/ATUAL/data em uma única palavra e derruba a confiança.
                clock_config = f"--oem 3 --psm {page_segmentation}"
                clock_data = pytesseract.image_to_data(
                    clock_crop, config=clock_config, output_type=pytesseract.Output.DICT
                )
                diagnostic = _summarize_clock_ocr(clock_data)
                diagnostics.append(f"psm{page_segmentation}:{diagnostic}")
                clock = parse_platform_clock_line(
                    clock_data,
                    origin_left=crop_left,
                    origin_top=crop_top,
                    scale=clock_scale,
                )
                if clock is not None:
                    break
            self.last_clock_ocr_text = " | ".join(diagnostics)[:360]
        return candidates, clock

    def detect(self, image) -> list[SignalCandidate]:
        """Compatibilidade: retorna apenas os candidatos de sinal."""
        candidates, _timer = self.detect_frame(image)
        return candidates
