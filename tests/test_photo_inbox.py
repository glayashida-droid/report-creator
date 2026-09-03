"""Phone-scan photo inbox: LAN HTTP upload into a numbered album."""

from __future__ import annotations

import io
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from src.io.photo_inbox import (
    COMPRESS_TARGET_BYTES,
    PhotoInbox,
    compress_image_to_target,
    is_usable_lan_ipv4,
    parse_form_fields,
    parse_multipart,
    sniff_image_suffix,
)


def _png_bytes(color="red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_bytes(color="blue") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "JPEG")
    return buf.getvalue()


def _noisy_jpeg(width=1600, height=1000, quality=95) -> bytes:
    buf = io.BytesIO()
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(
        buf, "JPEG", quality=quality
    )
    return buf.getvalue()


def _multipart(
    files: list[tuple[str, bytes]],
    field="photos",
    fields: dict | None = None,
) -> tuple[bytes, str]:
    boundary = "----ReachInboxTestBoundary"
    chunks: list[bytes] = []
    for key, value in (fields or {}).items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        chunks.append(str(value).encode())
        chunks.append(b"\r\n")
    for name, data in files:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{field}"; filename="{name}"\r\n'.encode()
        )
        chunks.append(b"Content-Type: application/octet-stream\r\n\r\n")
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _post(url: str, files: list[tuple[str, bytes]], fields: dict | None = None):
    body, ctype = _multipart(files, fields=fields)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", ctype)
    req.add_header("Content-Length", str(len(body)))
    return urllib.request.urlopen(req, timeout=5)


def test_is_usable_lan_ipv4():
    assert is_usable_lan_ipv4("192.168.1.8")
    assert is_usable_lan_ipv4("10.0.0.2")
    assert is_usable_lan_ipv4("172.16.5.1")
    assert not is_usable_lan_ipv4("127.0.0.1")
    assert not is_usable_lan_ipv4("0.0.0.0")
    assert not is_usable_lan_ipv4("169.254.1.1")
    assert not is_usable_lan_ipv4("224.0.0.1")
    assert not is_usable_lan_ipv4("not-an-ip")


def test_sniff_image_suffix():
    assert sniff_image_suffix("shot.PNG", _png_bytes()) == ".png"
    assert sniff_image_suffix("x.JPEG", _jpeg_bytes()) == ".jpeg"
    assert sniff_image_suffix("image", _png_bytes()) == ".png"
    assert sniff_image_suffix("image", _jpeg_bytes()) == ".jpg"
    assert sniff_image_suffix("note.txt", b"hello") is None


def test_parse_multipart_keeps_binary():
    png = _png_bytes()
    body, ctype = _multipart([("a.png", png), ("b.jpg", b"\xff\xd8\xff")])
    parts = parse_multipart(ctype, body)
    assert [name for name, _ in parts] == ["a.png", "b.jpg"]
    assert parts[0][1] == png


def test_inbox_upload_numbers_by_folder_prefix():
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "试验前"
        album.mkdir()
        Image.new("RGB", (8, 8), "black").save(album / "试验前-001.png")
        with PhotoInbox.start(album, "试验前", advertise_host="127.0.0.1") as inbox:
            assert inbox.url.startswith("http://127.0.0.1:")
            assert inbox.token in inbox.url
            page = urllib.request.urlopen(inbox.url, timeout=5).read().decode("utf-8")
            assert "试验前" in page
            assert 'accept="image/jpeg,image/png,.jpg,.jpeg,.png"' in page
            assert 'name="compress"' in page
            assert "压缩上传" in page
            assert "原图上传" in page
            assert "选择照片" in page
            _post(inbox.url, [("phone.png", _png_bytes()), ("two.jpg", _jpeg_bytes())])
            new = inbox.drain_new()
            assert [p.name for p in new] == ["试验前-002.png", "试验前-003.jpg"]
            assert (album / "试验前-002.png").is_file()
            assert (album / "试验前-003.jpg").is_file()
        try:
            urllib.request.urlopen(inbox.url, timeout=1)
            raise AssertionError("server should be stopped")
        except (urllib.error.URLError, ConnectionError, OSError):
            pass


def test_inbox_rejects_wrong_token_and_non_images():
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "数据"
        album.mkdir()
        with PhotoInbox.start(album, "数据", advertise_host="127.0.0.1") as inbox:
            bad = inbox.url.rsplit("/", 1)[0] + "/not-the-token"
            try:
                urllib.request.urlopen(bad, timeout=5)
                raise AssertionError("wrong token should 403")
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
            _post(inbox.url, [("notes.txt", b"not an image")])
            assert inbox.drain_new() == []
            assert list(album.iterdir()) == []


def test_inbox_qr_png_is_square():
    png = PhotoInbox.qr_png_bytes("http://192.168.1.8:8765/u/abc")
    with Image.open(io.BytesIO(png)) as img:
        assert img.size[0] == img.size[1]
        assert img.size[0] >= 120


def test_qr_matrix_has_finder_patterns():
    from src.io.qr_code import make_matrix

    grid = make_matrix("http://192.168.1.8:8765/u/token")
    n = len(grid)
    finder = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ]
    for y in range(7):
        assert grid[y][:7] == finder[y]
        assert grid[y][n - 7 :] == finder[y]
        assert grid[n - 7 + y][:7] == finder[y]


def test_parse_form_fields_reads_compress():
    body, ctype = _multipart([("a.png", _png_bytes())], fields={"compress": "0"})
    assert parse_form_fields(ctype, body)["compress"] == "0"
    files = parse_multipart(ctype, body)
    assert files[0][0] == "a.png"


def test_compress_image_to_target_keeps_aspect_and_size_band():
    src = _noisy_jpeg(1800, 1200)
    assert len(src) > COMPRESS_TARGET_BYTES
    out, suffix = compress_image_to_target(src)
    assert suffix == ".jpg"
    assert 300 * 1024 <= len(out) <= 620 * 1024
    with Image.open(io.BytesIO(src)) as a, Image.open(io.BytesIO(out)) as b:
        assert abs(a.size[0] / a.size[1] - b.size[0] / b.size[1]) < 0.02


def test_compress_skips_already_small():
    tiny = _png_bytes()
    out, suffix = compress_image_to_target(tiny)
    assert out == tiny
    assert suffix == ".png"


def test_inbox_compress_default_and_original_opt_out():
    noisy = _noisy_jpeg(1800, 1200)
    assert len(noisy) > COMPRESS_TARGET_BYTES
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "试验前"
        album.mkdir()
        with PhotoInbox.start(album, "试验前", advertise_host="127.0.0.1") as inbox:
            _post(inbox.url, [("big.jpg", noisy)], fields={"compress": "1"})
            compact = inbox.drain_new()
            assert compact[0].suffix == ".jpg"
            assert compact[0].stat().st_size <= 620 * 1024
            _post(inbox.url, [("big.jpg", noisy)], fields={"compress": "0"})
            original = inbox.drain_new()
            assert original[0].stat().st_size == len(noisy)
            assert original[0].name == "试验前-002.jpg"


