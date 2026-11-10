"""Quality gates for screen-capture frames and visual change independence."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
from math import isfinite


@dataclass(frozen=True, slots=True)
class FrameQuality:
    width: int
    height: int
    grayscale_variance: float
    age_seconds: float
    usable: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FrameFreshness:
    """Stateful comparison against prior capture frames.

    ``frame_id`` identifies the exact captured bytes. ``change_sequence`` advances
    only when a downsampled visual sample changes materially, so a repeated frame or
    cursor-level noise cannot be counted as a separate OCR observation.
    """

    frame_id: str
    change_sequence: int
    independent: bool
    frozen: bool
    unchanged_seconds: float
    changed_fraction: float
    repeated_frames: int


class FrameFreshnessMonitor:
    """Detect exact repeats and visually unchanged capture regions conservatively.

    A static chart can be genuine, so this is a fail-closed freshness gate rather
    than a claim that the market itself is frozen. After ``freeze_after_seconds``
    without a material pixel change the caller must block candidate decisions.
    """

    def __init__(
        self,
        *,
        freeze_after_seconds: float = 5.0,
        sample_size: tuple[int, int] = (64, 64),
        pixel_delta: int = 12,
        minimum_changed_fraction: float = 0.001,
    ) -> None:
        if not isfinite(freeze_after_seconds) or freeze_after_seconds <= 0:
            raise ValueError("freeze_after_seconds precisa ser positivo e finito.")
        if len(sample_size) != 2 or any(int(value) < 8 for value in sample_size):
            raise ValueError("sample_size precisa ter largura e altura de pelo menos 8 px.")
        if not 1 <= pixel_delta <= 255:
            raise ValueError("pixel_delta precisa ficar entre 1 e 255.")
        if not isfinite(minimum_changed_fraction) or not 0 <= minimum_changed_fraction <= 1:
            raise ValueError("minimum_changed_fraction precisa ficar entre 0 e 1.")
        self.freeze_after_seconds = float(freeze_after_seconds)
        self.sample_size = (int(sample_size[0]), int(sample_size[1]))
        self.pixel_delta = int(pixel_delta)
        self.minimum_changed_fraction = float(minimum_changed_fraction)
        self.reset()

    def reset(self) -> None:
        self._previous_sample: bytes | None = None
        self._previous_frame_id: str | None = None
        self._last_observed_at: float | None = None
        self._last_material_change_at: float | None = None
        self._change_sequence = -1
        self._repeated_frames = 0

    def observe(self, image, *, observed_at: float) -> FrameFreshness:
        """Observe one captured image using a monotonic timestamp."""
        if not isfinite(observed_at):
            raise ValueError("observed_at precisa ser finito.")
        if self._last_observed_at is not None and observed_at < self._last_observed_at:
            raise ValueError("observed_at não pode retroceder.")
        frame_id = blake2b(image.convert("RGB").tobytes(), digest_size=16).hexdigest()
        sample = image.convert("L").resize(self.sample_size).tobytes()
        if self._previous_sample is None:
            self._previous_sample = sample
            self._previous_frame_id = frame_id
            self._last_observed_at = observed_at
            self._last_material_change_at = observed_at
            self._change_sequence = 0
            self._repeated_frames = 0
            return FrameFreshness(frame_id, 0, True, False, 0.0, 1.0, 0)

        exact_repeat = frame_id == self._previous_frame_id
        if exact_repeat:
            self._repeated_frames += 1
        else:
            self._repeated_frames = 0
        changed = sum(
            abs(before - after) >= self.pixel_delta
            for before, after in zip(self._previous_sample, sample)
        )
        changed_fraction = changed / max(1, len(sample))
        independent = (
            not exact_repeat
            and changed_fraction >= self.minimum_changed_fraction
        )
        if independent:
            self._change_sequence += 1
            self._last_material_change_at = observed_at
        assert self._last_material_change_at is not None
        unchanged_seconds = max(0.0, observed_at - self._last_material_change_at)
        frozen = unchanged_seconds >= self.freeze_after_seconds
        self._previous_sample = sample
        self._previous_frame_id = frame_id
        self._last_observed_at = observed_at
        return FrameFreshness(
            frame_id=frame_id,
            change_sequence=self._change_sequence,
            independent=independent,
            frozen=frozen,
            unchanged_seconds=unchanged_seconds,
            changed_fraction=changed_fraction,
            repeated_frames=self._repeated_frames,
        )


def assess_frame(
    image,
    *,
    age_seconds: float = 0.0,
    minimum_width: int = 160,
    minimum_height: int = 120,
    minimum_variance: float = 2.0,
    maximum_age_seconds: float = 1.5,
) -> FrameQuality:
    """Reject tiny, nearly uniform, stale, or unmeasurable images.

    An unchanged image is not automatically marked unusable here; the stateful
    ``FrameFreshnessMonitor`` handles repeat/freeze decisions across captures.
    """
    width, height = map(int, image.size)
    age = float(age_seconds)
    reasons: list[str] = []
    if not isfinite(age) or age < 0:
        reasons.append("idade do quadro inválida")
        age = float("inf")
    if width < minimum_width or height < minimum_height:
        reasons.append(f"captura pequena ({width}×{height}; mínimo {minimum_width}×{minimum_height})")

    try:
        from PIL import Image, ImageStat

        sample = image.convert("L").resize(
            (min(64, width), min(64, height)), Image.Resampling.BILINEAR
        )
        variance = float(ImageStat.Stat(sample).var[0])
    except Exception:
        variance = 0.0
        reasons.append("não foi possível medir a variação visual")

    if not isfinite(variance) or variance < minimum_variance:
        reasons.append("quadro quase uniforme ou sem detalhe suficiente")
    if age > maximum_age_seconds:
        reasons.append(f"quadro desatualizado ({age:.2f} s)")

    return FrameQuality(
        width=width,
        height=height,
        grayscale_variance=variance,
        age_seconds=age,
        usable=not reasons,
        reasons=tuple(reasons),
    )
