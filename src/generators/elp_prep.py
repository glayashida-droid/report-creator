"""Background prep for ELP export: plan OCR + pattern-photo embed cache."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from src.generators.embed_cache import list_image_files, prefetch_embed_paths
from src.parsers.elp_plan import ElpPlan, parse_elp_plan


def parse_elp_plan_for_export(plan_pdf: Optional[Path]) -> ElpPlan:
    return parse_elp_plan(plan_pdf, ocr_cover=True)


def list_elp_pattern_photos(pattern_dir: Optional[Path]) -> List[Path]:
    if pattern_dir is None:
        return []
    return list_image_files(Path(pattern_dir))


def warm_elp_pattern_cache(
    pattern_dir: Optional[Path],
    *,
    cancelled: Optional[Callable[[], bool]] = None,
) -> int:
    """Encode ELP calibration photos into the embed cache. Returns file count."""
    photos = list_elp_pattern_photos(pattern_dir)
    if cancelled and cancelled():
        return 0
    return prefetch_embed_paths(photos, cancelled=cancelled)
