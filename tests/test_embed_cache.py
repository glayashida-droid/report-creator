from pathlib import Path

from PIL import Image

from src.generators.embed_cache import (
    cache_size,
    embed_stream_for,
    prefetch_embed_paths,
    reset_embed_cache,
)
from src.generators.elp_prep import list_elp_pattern_photos, warm_elp_pattern_cache
from src.generators.word_engine import PHOTO_WIDTH_IN, WordGenerator


def _png(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color=(12, 34, 56)).save(path, "PNG")
    return path


def test_embed_stream_cache_reuses_bytes(tmp_path: Path):
    reset_embed_cache()
    path = _png(tmp_path / "a.png")
    first = embed_stream_for(path, PHOTO_WIDTH_IN).getvalue()
    assert cache_size() == 1
    second = embed_stream_for(path, PHOTO_WIDTH_IN).getvalue()
    assert first == second
    assert cache_size() == 1
    encoded = WordGenerator._encode_embed_stream(path, PHOTO_WIDTH_IN).getvalue()
    assert encoded == first


def test_prefetch_embed_paths_encodes_unique_files(tmp_path: Path):
    reset_embed_cache()
    paths = [_png(tmp_path / f"{i}.png") for i in range(3)]
    assert prefetch_embed_paths(paths, max_workers=2) == 3
    assert cache_size() == 3
    assert prefetch_embed_paths(paths + paths, max_workers=2) == 3
    assert cache_size() == 3


def test_warm_elp_pattern_cache_reads_nested_folders(tmp_path: Path):
    reset_embed_cache()
    folder = tmp_path / "启动脉冲"
    _png(folder / "校准.png")
    _png(tmp_path / "root.png")
    listed = list_elp_pattern_photos(tmp_path)
    assert len(listed) == 2
    assert warm_elp_pattern_cache(tmp_path) == 2
    assert cache_size() == 2
