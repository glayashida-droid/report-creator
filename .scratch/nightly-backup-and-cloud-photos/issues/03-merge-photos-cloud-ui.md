# TKT-3: 合并视图 + 云标记（照片列表）

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

打开已上传并清本地的项目 → 试验照片栏显示公盘已有图的缩略图且带云标记；拖入新图到正式相册 → 无云标记；同路径本地与公盘都有时显示本地版（无云）。

## Objective

落地主测试缝 **Project assets**：合并枚举与读路径；照片面板改经此缝，不再只扫单一 `project_root`（US-09、10、11、12；US-33 缓存可先做最小读公盘缩略图）。

## Requirements

* 新增 `src/io/project_assets.py`（或等价）：给定 `local_root`、`remote_root`：
  * `list_merged_photos(leg, test, album)` → 条目含 `relative_path`、`read_path`、`is_cloud_only`；
  * `resolve_photo_path(relative_path)` → 本地优先，否则公盘；
  * 默认排除试验目录下 `备用/`（删除语义在 TKT-4 接好）。
* `test_photos_panel` / 明细照片抽屉：列表与计数走 merge API；云标记仅当 `is_cloud_only`。
* 新拖入仍写本地 `album_dir`；刷新列表后无云。
* 公盘图缩略图：优先 `.thumbs` 缓存（可建目录）；无缓存时从公盘读原图生成并缓存（首版可同步生成）。
* 模块单测：仅公盘 / 仅本地 / 同路径本地优先 / 排除备用（占位接口亦可，TKT-4 补全删除）。

## Blocked by

* TKT-1（需要可靠 `source_path` + 打开流程）

## Acceptance criteria

- [x] 仅公盘有的照片出现在列表且带云标记；仅本地有的无云；同路径以本地为准。
- [x] 新拖入照片立即可见且无云标记。
- [x] `project_assets` 合并列表单测绿；照片面板无散落 `if local else remote`。
