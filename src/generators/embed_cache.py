"""In-memory cache of Word-embed JPEG bytes. Same encode settings as live export."""

from __future__ import annotations

import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from src.generators.word_engine import PHOTO_WIDTH_IN, WordGenerator

_CacheKey = Tuple[str, int, float]

_lock = threading.Lock()
_cache: Dict[_CacheKey, bytes] = {}


def reset_embed_cache() -> None:
    with _lock:
        _cache.clear()


def cache_size() -> int:
    with _lock:
        return len(_cache)


def _key(path: Path, width_in: float) -> Optional[_CacheKey]:
    try:
        resolved = path.resolve()
        st = resolved.stat()
    except OSError:
        return None
    return (str(resolved), int(st.st_mtime_ns), float(width_in))


def embed_stream_for(path: Path, width_in: float = PHOTO_WIDTH_IN) -> io.BytesIO:
    """Return embed JPEG bytes for path, reusing a prior encode when mtime matches."""
    key = _key(path, width_in)
    if key is not None:
        with _lock:
            hit = _cache.get(key)
        if hit is not None:
            return io.BytesIO(hit)
    stream = WordGenerator._encode_embed_stream(path, width_in)
    data = stream.getvalue()
    if key is not None:
        with _lock:
            _cache[key] = data
    return io.BytesIO(data)


def prefetch_embed_paths(
    paths: Sequence[Path],
    width_in: float = PHOTO_WIDTH_IN,
    *,
    cancelled: Optional[Callable[[], bool]] = None,
    max_workers: Optional[int] = None,
) -> int:
    """Encode unique paths in parallel. Returns how many were submitted."""
    unique: List[Path] = []
    seen = set()
    for raw in paths:
        if cancelled and cancelled():
            break
        path = Path(raw)
        try:
            marker = path.resolve()
        except OSError:
            marker = path
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(path)
    if not unique:
        return 0
    workers = max_workers or min(8, max(1, os.cpu_count() or 4))
    if workers == 1 or len(unique) == 1:
        for path in unique:
            if cancelled and cancelled():
                break
            try:
                embed_stream_for(path, width_in)
            except Exception:
                continue
        return len(unique)

    def _one(path: Path) -> None:
        if cancelled and cancelled():
            return
        embed_stream_for(path, width_in)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, path) for path in unique]
        for fut in futs:
            try:
                fut.result()
            except Exception:
                continue
    return len(unique)


def list_image_files(root: Path) -> List[Path]:
    from src.io.test_photos import is_image_file

    if not root.is_dir():
        return []
    out: List[Path] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    for child in children:
        try:
            if child.is_dir():
                out.extend(p for p in child.iterdir() if is_image_file(p))
            elif is_image_file(child):
                out.append(child)
        except OSError:
            continue
    return out
