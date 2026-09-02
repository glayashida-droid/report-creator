# TKT-2: 结构镜像（跳过大文件 · 保留目录骨架）

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

从公盘路径载入含大量照片的项目 → 本地出现完整目录树与申请单等轻量文件，但 `3.测试组/` 下不拉回 jpg/png 原图与已存在的大 xlsx；夜间 purge 后空目录仍保留，新照片可直接拖入本地相册路径。

## Objective

扩展镜像策略，使本地 `data/{项目号}/` 成为可长期保留的**目录骨架**工作区，而非全量副本（US-07、08；US-03 之镜像部分）。

## Requirements

* 扩展 `incremental_copy`（或 sibling API）：默认跳过 `IMAGE_EXTS` 原图、超过尺寸阈值的文件；仍跳过 junk、`~$`、从公盘覆盖本地 `project_state.json`（JSON 走 TKT-1）。
* 轻量文件（如 `1.接样组/` 下申请单 xlsx）仍增量复制。
* 从路径加载项目时调用新策略；`MirrorWorker` 行为与 UI 状态（镜像中/就绪）一致。
* purge 本地大文件时（TKT-6）只删文件、不 `rmdir` 相册/试验目录。
* 单测：大图片不同步到 dest；目录存在；轻量 xlsx 仍复制。

## Blocked by

* None (can start immediately; parallel with TKT-1)

## Acceptance criteria

- [x] 从公盘载入含照片的项目后，本地无照片原图但有对应空相册目录（或仅公盘侧有图、本地无文件）。
- [x] 申请单等轻量文件仍出现在本地镜像路径。
- [x] 扩展后的 mirror/copy 单测绿。
