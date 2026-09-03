"""Short-lived LAN HTTP inbox: phone browser uploads images into a photo folder."""

from __future__ import annotations

import html
import io
import re
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageOps

from src.io.qr_code import png_bytes as qr_png_bytes
from src.io.test_photos import IMAGE_EXTS, copy_into_album, is_image_file

MAX_REQUEST_BYTES = 80 * 1024 * 1024
COMPRESS_TARGET_BYTES = 500 * 1024
_BOUNDARY_RE = re.compile(r"boundary=([^;]+)", re.I)
_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)


def is_usable_lan_ipv4(ip: str) -> bool:
    parts = (ip or "").split(".")
    if len(parts) != 4:
        return False
    try:
        n = [int(p) for p in parts]
    except ValueError:
        return False
    if any(v < 0 or v > 255 for v in n):
        return False
    if n[0] in {0, 127} or n[0] >= 224:
        return False
    if n[0] == 169 and n[1] == 254:
        return False
    return True


def default_route_ipv4() -> Optional[str]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return None
    return ip if is_usable_lan_ipv4(ip) else None


def sniff_image_suffix(filename: str, data: bytes) -> Optional[str]:
    ext = Path(filename or "").suffix.lower()
    if ext in IMAGE_EXTS:
        return ext
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    return None


def _iter_multipart(content_type: str, body: bytes):
    match = _BOUNDARY_RE.search(content_type or "")
    if not match or not body:
        return
    boundary = match.group(1).strip().strip('"').encode("ascii", "ignore")
    if not boundary:
        return
    for raw in body.split(b"--" + boundary):
        chunk = raw.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        header_blob, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        filename = ""
        field = ""
        for line in header_blob.decode("utf-8", "replace").split("\r\n"):
            if not line.lower().startswith("content-disposition:"):
                continue
            name_m = re.search(r'name="([^"]*)"', line)
            file_m = re.search(r'filename="([^"]*)"', line)
            if name_m:
                field = name_m.group(1)
            if file_m:
                filename = Path(file_m.group(1).replace("\\", "/")).name
        yield field, filename, data


def parse_multipart(content_type: str, body: bytes) -> List[Tuple[str, bytes]]:
    parts: List[Tuple[str, bytes]] = []
    for field, filename, data in _iter_multipart(content_type, body):
        if field == "photos" or filename:
            parts.append((filename, data))
    return parts


def parse_form_fields(content_type: str, body: bytes) -> dict:
    fields = {}
    for field, filename, data in _iter_multipart(content_type, body):
        if field and not filename:
            fields[field] = data.decode("utf-8", "replace")
    return fields


def _flatten_rgb(img: Image.Image) -> Image.Image:
    if img.mode in {"RGBA", "LA"} or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert("RGB")


def _jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _best_jpeg_under(img: Image.Image, target: int) -> Optional[bytes]:
    lo, hi = 40, 92
    best: Optional[bytes] = None
    while lo <= hi:
        mid = (lo + hi) // 2
        blob = _jpeg_bytes(img, mid)
        if len(blob) <= target:
            best = blob
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def compress_image_to_target(
    data: bytes, target: int = COMPRESS_TARGET_BYTES
) -> Tuple[bytes, str]:
    """Keep original if already small; else JPEG near *target* without changing aspect ratio."""
    if len(data) <= target:
        return data, sniff_image_suffix("", data) or ".jpg"
    with Image.open(io.BytesIO(data)) as src:
        src = ImageOps.exif_transpose(src)
        src.load()
        work = _flatten_rgb(src)
    best = _jpeg_bytes(work, 40)
    for _ in range(16):
        fitted = _best_jpeg_under(work, target)
        if fitted is not None:
            return fitted, ".jpg"
        best = _jpeg_bytes(work, 40)
        width, height = work.size
        if min(width, height) <= 32:
            return best, ".jpg"
        scale = min(0.85, max(0.45, (target / max(len(best), 1)) ** 0.5 * 0.92))
        new_w = max(32, int(round(width * scale)))
        new_h = max(32, int(round(height * scale)))
        if (new_w, new_h) == (width, height):
            return best, ".jpg"
        work = work.resize((new_w, new_h), _RESAMPLE)
    return best, ".jpg"


def _page(album: str, message: str = "", ok_count: int = 0) -> bytes:
    title = html.escape(album or "照片")
    notice = ""
    if ok_count:
        notice = f'<p class="ok">已上传 {ok_count} 张，可继续选择。</p>'
    if message:
        notice += f'<p class="err">{html.escape(message)}</p>'
    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>上传到 {title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
       margin: 0; padding: 24px 16px; background: #0D1117; color: #E6EDF3; }}
h1 {{ font-size: 22px; color: #00FFFF; }}
p {{ color: #8B949E; line-height: 1.5; }}
.ok {{ color: #3ee0a0; }}
.err {{ color: #FF6B6B; }}
.opt {{
  display: flex; align-items: center; gap: 12px;
  font-size: 17px; padding: 14px 16px; margin: 8px 0;
  border-radius: 12px; background: #12181F; border: 1px solid #1F2A37; color: #E6EDF3;
}}
.opt input {{ width: 22px; height: 22px; margin: 0; accent-color: #00FFFF; }}
.pick {{
  display: block; width: 100%; box-sizing: border-box; position: relative;
  font-size: 18px; font-weight: 700; padding: 20px 16px; margin: 16px 0;
  border-radius: 12px; background: #1A2330; color: #00FFFF;
  border: 1px solid rgba(0, 255, 255, 0.35); text-align: center;
}}
.pick input {{
  position: absolute; inset: 0; opacity: 0; width: 100%; height: 100%;
  cursor: pointer; font-size: 24px;
}}
.filehint {{ margin: 0 0 8px 0; }}
button {{
  display: block; width: 100%; box-sizing: border-box;
  font-size: 18px; padding: 16px; margin: 16px 0; border-radius: 12px;
  background: #00FFFF; color: #0D1117; border: 0; font-weight: 700;
}}
</style>
</head>
<body>
<h1>上传到「{title}」</h1>
<p>从相册选择 jpg / png，上传后按文件夹名自动编号。</p>
{notice}
<form method="post" enctype="multipart/form-data">
<label class="opt"><input type="radio" name="compress" value="1" checked> 压缩上传（约 500KB，保持比例）</label>
<label class="opt"><input type="radio" name="compress" value="0"> 原图上传</label>
<label class="pick">选择照片
<input type="file" name="photos" accept="image/jpeg,image/png,.jpg,.jpeg,.png" multiple required>
</label>
<p class="filehint" id="filehint">未选择文件</p>
<button type="submit">上传</button>
</form>
<script>
document.querySelector('input[name=photos]').addEventListener('change', function () {{
  var n = this.files.length;
  document.getElementById('filehint').textContent = n ? ('已选 ' + n + ' 张') : '未选择文件';
}});
</script>
</body>
</html>
"""
    return body.encode("utf-8")


class PhotoInbox:
    def __init__(
        self,
        dest: Path,
        prefix: str,
        *,
        advertise_host: Optional[str] = None,
        port: int = 0,
    ):
        self.dest = Path(dest)
        self.prefix = prefix
        self.token = secrets.token_urlsafe(16)
        self._advertise = advertise_host
        self._port_request = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._saved: List[Path] = []
        self._drained = 0
        self.host = ""
        self.port = 0
        self.url = ""

    @classmethod
    def start(
        cls,
        dest: Path,
        prefix: str,
        *,
        advertise_host: Optional[str] = None,
        port: int = 0,
    ) -> "PhotoInbox":
        inbox = cls(dest, prefix, advertise_host=advertise_host, port=port)
        inbox._serve()
        return inbox

    def __enter__(self) -> "PhotoInbox":
        if self._httpd is None:
            self._serve()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def drain_new(self) -> List[Path]:
        with self._lock:
            new = self._saved[self._drained :]
            self._drained = len(self._saved)
            return list(new)

    @staticmethod
    def qr_png_bytes(text: str) -> bytes:
        return qr_png_bytes(text)

    def _serve(self) -> None:
        self.dest.mkdir(parents=True, exist_ok=True)
        handler = _make_handler(self)

        class _Server(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        httpd = _Server(("0.0.0.0", self._port_request), handler)
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        host = (self._advertise or "").strip() or default_route_ipv4() or "127.0.0.1"
        self.host = host
        self.url = f"http://{host}:{self.port}/u/{self.token}"
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def save_uploads(
        self,
        files: Sequence[Tuple[str, bytes]],
        compress: bool = True,
    ) -> Tuple[List[Path], str]:
        skipped: List[str] = []
        staged: List[Path] = []
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for index, (filename, data) in enumerate(files):
                if not data:
                    skipped.append(filename or "空文件")
                    continue
                suffix = sniff_image_suffix(filename, data)
                if suffix is None:
                    skipped.append(filename or "非图片")
                    continue
                if compress:
                    try:
                        data, suffix = compress_image_to_target(data)
                    except Exception:
                        skipped.append(filename or "压缩失败")
                        continue
                path = tmp_dir / f"up_{index}{suffix}"
                path.write_bytes(data)
                try:
                    with Image.open(path) as img:
                        img.verify()
                except Exception:
                    skipped.append(filename or path.name)
                    continue
                if not is_image_file(path):
                    skipped.append(filename or path.name)
                    continue
                staged.append(path)
            written: List[Path] = []
            if staged:
                with self._lock:
                    written = copy_into_album(self.dest, staged, self.prefix)
                    self._saved.extend(written)
        note = ""
        if skipped:
            shown = "、".join(skipped[:6])
            note = f"已跳过：{shown}"
        return written, note


def _make_handler(inbox: PhotoInbox):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, format, *args):
            return

        def _token_ok(self) -> bool:
            path = urlparse(self.path).path
            parts = path.rstrip("/").split("/")
            return len(parts) == 3 and parts[1] == "u" and parts[2] == inbox.token

        def _send(self, code: int, body: bytes, content_type="text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._token_ok():
                self._send(403, _page(inbox.prefix, "无效链接，请重新扫描电脑上的二维码。"))
                return
            query = parse_qs(urlparse(self.path).query)
            ok = 0
            if query.get("ok"):
                try:
                    ok = int(query["ok"][0])
                except ValueError:
                    ok = 0
            self._send(200, _page(inbox.prefix, ok_count=ok))

        def do_POST(self):
            if not self._token_ok():
                self._send(403, _page(inbox.prefix, "无效链接，请重新扫描电脑上的二维码。"))
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._send(413, _page(inbox.prefix, "文件太大或为空。"))
                return
            body = self.rfile.read(length)
            ctype = self.headers.get("Content-Type") or ""
            files = parse_multipart(ctype, body)
            compress = parse_form_fields(ctype, body).get("compress", "1") != "0"
            written, note = inbox.save_uploads(files, compress=compress)
            if not written and not note:
                note = "没有可导入的 jpg / jpeg / png。"
            if written:
                loc = f"/u/{inbox.token}?ok={len(written)}"
                self.send_response(303)
                self.send_header("Location", loc)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send(200, _page(inbox.prefix, note))

    return Handler
