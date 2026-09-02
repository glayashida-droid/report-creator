# TKT-7: Word 导出读合并视图

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

项目本地无原图、公盘有试验照片 → 导出 Word 仍嵌入这些图；含 `备用/` 内已删图不出现；嵌入时读公盘原图用临时文件，不写正式相册。

## Objective

`WordGenerator` / `photo_scraper` 经 **Project assets** 取图路径，与明细列表一致（US-28、29）。

## Requirements

* `_insert_photos` / `iter_export_photos` 改调 merge resolver，禁止直接 `list_photos(local_root)`。
* 仅公盘图：读 remote 到 temp 再 embed；temp 生命周期限于导出过程。
* 顺序仍尊重 `photo_album_order` 与 `list_albums` 规则（不含备用）。
* 单测：fixture 本地空、remote 有图 → 导出路径解析含 remote；备用图不出现。

## Blocked by

* TKT-3
* TKT-4（备用排除）

## Acceptance criteria

- [x] 仅公盘有的照片能出现在导出 Word 中。
- [x] `备用/` 内照片不出现在导出中。
- [x] 导出不在正式相册目录留下原图副本。
