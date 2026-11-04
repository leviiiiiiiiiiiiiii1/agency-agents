"""Blank user-selected screen areas before OCR, preview, snapshots, or recording."""

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


def point_inside_region(x: int, y: int, region: ScreenRegion) -> bool:
    return region.left <= x < region.left + region.width and region.top <= y < region.top + region.height


def point_is_masked(x: int, y: int, excluded_regions: list[ScreenRegion]) -> bool:
    return any(point_inside_region(x, y, region) for region in excluded_regions)


def point_is_masked_with_margin(
    x: int,
    y: int,
    excluded_regions: list[ScreenRegion],
    *,
    margin_x: int = 50,
    margin_y: int = 50,
) -> bool:
    """Require a calibrated button point and a surrounding OCR-safety margin to be masked."""
    return any(
        region.left <= x - margin_x
        and x + margin_x < region.left + region.width
        and region.top <= y - margin_y
        and y + margin_y < region.top + region.height
        for region in excluded_regions
    )
