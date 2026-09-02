# TKT-5: 预览 · 下载到相册 · 原图查看（不落相册）

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

单击仅公盘的照片 → 中等清晰度预览，不在 `3.测试组/.../` 新增文件；双击或「查看原图」→ 系统预览/查看器打开，用临时或流式读公盘，不写相册；点「下载到本地」→ 原图写入正式相册路径，云标记消失。

## Objective

补齐云端照片的交互垂直切片（US-13、14、15），全部经 `project_assets.resolve_photo_path` / 专用 download API。

## Requirements

* `download_photo_to_album(relative_path)`：仅公盘有时从 remote 拷到 local 正式路径；已有本地则 no-op 或提示。
* 单击预览：用 `.thumbs` 或中等尺寸，禁止写入 `album_dir`。
* 双击/查看原图：本地有则本地开；仅公盘则读 remote 到 temp 或内存 viewer，不写相册。
* 照片项 UI：仅 `is_cloud_only` 时显示「下载到本地」。
* 单测：download 后 local 存在且 `is_cloud_only` 为假；preview 路径不创建相册下新文件（可用 mock 计数）。

## Blocked by

* TKT-3

## Acceptance criteria

- [x] 仅公盘图可预览且不污染正式相册目录。
- [x] 「下载到本地」后该图无云标记且路径在正式相册。
- [x] 原图查看不写入正式相册（temp 可接受）。
