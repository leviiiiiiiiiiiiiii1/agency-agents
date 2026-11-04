"""Blank user-selected screen areas before OCR, preview, and snapshots."""

from __future__ import annotations

from PIL import Image, ImageDraw

from .capture import ScreenRegion


def mask_screen_regions(
    image: Image.Image,
    capture_region: ScreenRegion,
    excluded_regions: list[ScreenRegion] | tuple[ScreenRegion, ...],
) -> None:
    """Paint intersections black in-place using absolute desktop coordinates."""
    if not excluded_regions:
        return
    draw = ImageDraw.Draw(image)
    for excluded in excluded_regions:
        left = max(0, excluded.left - capture_region.left)
        top = max(0, excluded.top - capture_region.top)
        right = min(image.width, excluded.left + excluded.width - capture_region.left)
        bottom = min(image.height, excluded.top + excluded.height - capture_region.top)
        if left < right and top < bottom:
            draw.rectangle((left, top, right - 1, bottom - 1), fill=(0, 0, 0))
