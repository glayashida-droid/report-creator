# TKT-6: 夜间同步（增量上传 · 校验 · 清本地 · 手动触发）

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

偏好里启用 22:30 夜间同步；白天拖入照片改 xlsx → 到点或点「立即备份」→ 公盘出现新文件 → 校验一致后本地原文件删除、目录仍在 → 照片栏该图变云标记；某文件失败则本地保留并显示失败摘要。

## Objective

落地辅测试缝 **Project sync**：增量上传、校验 purge、定时与手动（US-16、21–25、27；US-20 移动同步）。

## Requirements

* 新增 `src/io/project_sync.py`：`incremental_upload(local, remote, …)`、`purge_verified_uploads(…)`；大文件定义与 TKT-2 一致（图片、xlsx 等）。
* 校验：至少比 size；可选 mtime/hash。
* Purge：仅删除已确认上传成功的本地文件；保留目录与 `.thumbs`。
* `user_prefs`：`nightly_sync_enabled`、`nightly_sync_time`（`HH:MM`）；可选同步全部本地缓存项目 vs 仅当前项目。
* 主窗口：`QTimer` 到点 + 「立即备份到公盘」+ 非模态状态（上次同步时间/失败计数）；程序未运行则不执行（不装 launchd）。
* 上传含 `备用/` 内文件及正式相册变更；失败保留本地、可重试。
* 单测：upload 后 remote 有文件；verify 后 local 大文件删、目录在；失败不 purge。

## Blocked by

* TKT-1（JSON 与 source_path）
* TKT-2（镜像/purge 语义）
* TKT-3（上传后 UI 云标记依赖 merge）

## Acceptance criteria

- [x] 手动立即同步可将本地新照片/xlsx 推到公盘并在校验后清本地。
- [x] 定时任务在程序运行到设定时刻时触发同等逻辑。
- [x] 上传失败项本地仍在，界面可见失败摘要。
- [x] `project_sync` 单测绿。
