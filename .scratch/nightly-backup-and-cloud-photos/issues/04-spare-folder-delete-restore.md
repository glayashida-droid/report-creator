# TKT-4: 备用文件夹（删除 · 还原 · 排除导出）

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

在照片栏删除某张图 → 文件移入该试验 `3.测试组/{Leg}-{试验}/备用/` → 列表与相册计数不再显示；从备用拖回 `试验前` 等正式相册 → 重新出现；`list_albums` 不把 `备用` 当普通相册。

## Objective

删除不走 JSON 软删，走磁盘移动到 **备用**；与合并视图、导出排除一致（US-17、18、19；US-20 移动语义留给 TKT-6 上传）。

## Requirements

* 常量：`SPARE_ALBUM_NAME = "备用"`，位于试验目录下（与 `数据表附件/` 同级）。
* 删除照片 API：`move_photo_to_spare(relative_path)` 或等价；创建 `备用/` 若不存在。
* `project_assets` 合并枚举排除 `备用/` 内路径；`list_albums` 不列出 `备用`。
* 「全部重命名」等批量操作不作用于 `备用/` 内文件。
* UI：删除走 move；可选简易「备用」查看/拖出还原（或访达打开备用夹即可，文档写清）。
* 单测：删除后正式列表不含；移回后含；导出 resolver 不含备用。

## Blocked by

* TKT-3

## Acceptance criteria

- [x] 删除照片后文件在试验目录 `备用/` 下，正式相册列表不可见。
- [x] 拖回正式相册后重新出现在合并列表。
- [x] `list_albums` / 合并导出列表均不含 `备用` 相册。
