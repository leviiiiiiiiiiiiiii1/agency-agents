"""Leitura experimental de rótulos BUY/SELL por OCR.

Gera candidatos visuais para revisão humana. Não valida velas nem autoriza ordens.
"""

from __future__ import annotations

import re
import time
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
    color_required: bool = False


def _one_edit_apart(first: str, second: str) -> bool:
    """True for exactly one insertion, deletion, or substitution."""
    if first == second:
        return False
    if abs(len(first) - len(second)) > 1:
        return False
    left = right = differences = 0
    while left < len(first) and right < len(second):
        if first[left] == second[right]:
            left += 1
            right += 1
            continue
        differences += 1
        if differences > 1:
            return False
        if len(first) > len(second):
            left += 1
        elif len(second) > len(first):
            right += 1
        else:
            left += 1
            right += 1
    differences += (len(first) - left) + (len(second) - right)
    return differences == 1


def parse_ocr_rows(
    data: dict[str, Any],
    min_confidence: float = 70.0,
    *,
    require_color_below: float | None = None,
) -> list[SignalCandidate]:
    """Recognize exact labels and one-character OCR variants for color confirmation."""
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
        fuzzy = False
        if direction is None:
            possible_directions = {
                label_direction
                for label, label_direction in aliases.items()
                if _one_edit_apart(normalized, label)
            }
            if len(possible_directions) != 1:
                continue
            direction = next(iter(possible_directions))
            fuzzy = True
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
        color_required = fuzzy or (
            require_color_below is not None and confidence < require_color_below
        )
        candidates.append(
            SignalCandidate(direction, confidence, left, top, width, height, observed, color_required)
        )
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


def _colored_signal_mask(image):
    """Isolate saturated green/red signal text for an OCR fallback pass."""
    from PIL import Image

    rgb = image.convert("RGB")
    mask = bytearray(rgb.width * rgb.height)
    for index, (r, g, b) in enumerate(rgb.getdata()):
        if (
            (g >= 70 and g >= r * 1.25 and g >= b * 1.08)
            or (r >= 85 and r >= g * 1.30 and r >= b * 1.18)
        ):
            mask[index] = 255
    return Image.frombytes("L", rgb.size, bytes(mask))


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


def _read_clock_from_bottom_right(image, pytesseract) -> tuple[PlatformClockReading | None, str, int]:
    """Lê HORA ATUAL apenas na faixa inferior direita, que costuma ser fonte pequena.

    Retorna (leitura, diagnóstico textual, quantidade de passadas). A faixa é cara em
    relação ao resto do quadro, por isso é isolada: quem chama decide quando pagar.
    """
    from PIL import Image, ImageOps

    crop_left = int(image.width * 0.70)
    crop_top = int(image.height * 0.93)
    clock_crop = image.crop((crop_left, crop_top, image.width, image.height)).convert("L")
    clock_scale = 4
    clock_crop = ImageOps.autocontrast(clock_crop).resize(
        (clock_crop.width * clock_scale, clock_crop.height * clock_scale),
        Image.Resampling.LANCZOS,
    )
    clock = None
    passes = 0
    diagnostics: list[str] = []
    for page_segmentation in (7, 6):
        # Não use whitelist na faixa do relógio: ela elimina os espaços,
        # cola HORA/ATUAL/data em uma única palavra e derruba a confiança.
        clock_config = f"--oem 3 --psm {page_segmentation}"
        passes += 1
        clock_data = pytesseract.image_to_data(
            clock_crop, config=clock_config, output_type=pytesseract.Output.DICT
        )
        diagnostics.append(f"psm{page_segmentation}:{_summarize_clock_ocr(clock_data)}")
        clock = parse_platform_clock_line(
            clock_data,
            origin_left=crop_left,
            origin_top=crop_top,
            scale=clock_scale,
        )
        if clock is not None:
            break
    return clock, " | ".join(diagnostics)[:360], passes


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
        # Phase timings for the most recent frame, so latency is measured instead of
        # guessed. Values describe work already performed; they never affect detection.
        self.last_ocr_timings: dict[str, Any] = {}
        self.last_clock_timings: dict[str, Any] = {}

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

    def detect_frame(
        self, image, *, read_clock: bool = True
    ) -> tuple[list[SignalCandidate], PlatformClockReading | None]:
        """Lê sinais e, opcionalmente, o relógio do rodapé.

        As coordenadas retornadas são relativas à captura original. O relógio só é
        aceito junto ao rótulo HORA ATUAL no canto inferior direito, nunca pelo PC.

        ``read_clock=False`` mantém a leitura de rótulos no caminho crítico e devolve
        apenas o relógio que a passada geral já conseguiu ler. A faixa do rodapé é
        cara e passa a ser lida por ``detect_clock`` em um executor próprio.
        """
        try:
            import pytesseract
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise RuntimeError("Instale as dependências Python com: python -m pip install -r requirements.txt") from exc

        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        self.last_clock_ocr_text = ""
        started_at = time.monotonic()
        timings: dict[str, Any] = {
            "full_pass_seconds": 0.0,
            "color_fallback_seconds": 0.0,
            "color_fallback_passes": 0,
            "clock_crop_seconds": 0.0,
            "clock_crop_passes": 0,
            "used_color_fallback": False,
            "upscale_factor": 1,
        }
        self.last_ocr_timings = timings
        pixel_count = image.width * image.height
        # Enlarging large captures quadruples Tesseract's input work without helping
        # labels that are already legible at native resolution. Small crops retain 2×.
        scale = 1 if pixel_count >= 1_000_000 else 2
        prepared = ImageOps.autocontrast(image.convert("L"))
        prepared = prepared.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
        whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:"
        config = f"--oem 3 --psm 11 -c tessedit_char_whitelist={whitelist}"
        full_pass_started_at = time.monotonic()
        data = pytesseract.image_to_data(prepared, config=config, output_type=pytesseract.Output.DICT)
        timings["full_pass_seconds"] = round(time.monotonic() - full_pass_started_at, 3)
        timings["upscale_factor"] = scale
        color_backed_minimum = max(40.0, self.min_confidence - 20.0)
        candidates = parse_ocr_rows(
            data,
            color_backed_minimum,
            require_color_below=self.min_confidence,
        )
        candidates = [
            SignalCandidate(
                c.direction,
                c.confidence,
                c.left // scale,
                c.top // scale,
                max(1, c.width // scale),
                max(1, c.height // scale),
                c.observed_text,
                c.color_required,
            )
            for c in candidates
        ]
        used_color_fallback = False
        if not candidates:
            color_mask = _colored_signal_mask(image)
            if color_mask.getbbox() is not None:
                color_scale = 2 if pixel_count >= 500_000 else 4
                enlarged_mask = color_mask.resize(
                    (image.width * color_scale, image.height * color_scale),
                    Image.Resampling.NEAREST,
                )
                fallback_started_at = time.monotonic()
                for page_segmentation in (11, 6):
                    color_config = (
                        f"--oem 3 --psm {page_segmentation} "
                        f"-c tessedit_char_whitelist={whitelist}"
                    )
                    timings["color_fallback_passes"] = (
                        int(timings["color_fallback_passes"]) + 1
                    )
                    color_data = pytesseract.image_to_data(
                        enlarged_mask,
                        config=color_config,
                        output_type=pytesseract.Output.DICT,
                    )
                    color_candidates = parse_ocr_rows(
                        color_data,
                        color_backed_minimum,
                        require_color_below=self.min_confidence,
                    )
                    if color_candidates:
                        candidates = [
                            SignalCandidate(
                                c.direction,
                                c.confidence,
                                c.left // color_scale,
                                c.top // color_scale,
                                max(1, c.width // color_scale),
                                max(1, c.height // color_scale),
                                c.observed_text,
                                c.color_required,
                            )
                            for c in color_candidates
                        ]
                        used_color_fallback = True
                        break
                timings["color_fallback_seconds"] = round(
                    time.monotonic() - fallback_started_at, 3
                )
                timings["used_color_fallback"] = used_color_fallback
        self.last_candidate_count = len(candidates)
        self.last_color_rejected_count = 0
        color_checked: list[SignalCandidate] = []
        for candidate in candidates:
            color_direction = _signal_color_direction(image, candidate)
            if (
                (color_direction is not None and color_direction != candidate.direction)
                or ((used_color_fallback or candidate.color_required) and color_direction is None)
            ):
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
        elif not read_clock:
            timings["clock_crop_passes"] = 0
        else:
            clock_started_at = time.monotonic()
            clock, clock_text, passes = _read_clock_from_bottom_right(image, pytesseract)
            self.last_clock_ocr_text = clock_text
            timings["clock_crop_passes"] = passes
            timings["clock_crop_seconds"] = round(time.monotonic() - clock_started_at, 3)
        timings["total_seconds"] = round(time.monotonic() - started_at, 3)
        return candidates, clock

    def detect_clock(self, image) -> PlatformClockReading | None:
        """Lê somente a faixa do relógio, para rodar fora do caminho crítico.

        Não altera candidatos nem contadores da leitura de rótulos: o estado do
        relógio é atualizado pelo chamador, que decide se a leitura ainda vale.
        """
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError(
                "Instale as dependências Python com: python -m pip install -r requirements.txt"
            ) from exc

        if self.executable:
            pytesseract.pytesseract.tesseract_cmd = self.executable
        started_at = time.monotonic()
        clock, clock_text, passes = _read_clock_from_bottom_right(image, pytesseract)
        self.last_clock_ocr_text = clock_text
        self.last_clock_timings = {
            "clock_crop_passes": passes,
            "total_seconds": round(time.monotonic() - started_at, 3),
        }
        return clock

    def detect(self, image) -> list[SignalCandidate]:
        """Compatibilidade: retorna apenas os candidatos de sinal."""
        candidates, _timer = self.detect_frame(image)
        return candidates
