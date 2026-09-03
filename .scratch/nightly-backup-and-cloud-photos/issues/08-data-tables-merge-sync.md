# TKT-8: 数据表合并 + 夜间上传

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

本地无 xlsx、公盘 `数据表附件/` 有 → 明细列表仍显示索引项，预览/打开读公盘路径；白天新建表在本地 → 夜间同步上传后本地 xlsx 清掉，索引仍在 JSON（TKT-1 已即时上公盘）。

## Objective

数据表附件走与照片相同的合并与同步规则（US-26、27）；本期打开仅公盘表时可直接外开公盘路径（不必先做「下载到本地」按钮，除非实现简单）。

## Requirements

* `project_assets` 扩展：`resolve_data_table_path(relative_path)` 本地优先 → 公盘。
* 明细数据表：刷新预览、外开 Excel 用 resolve 路径。
* 夜间同步（TKT-6）已覆盖 `数据表附件/*.xlsx` 上传与 purge；本票接好 IO 与 UI。
* 单测：仅 remote 有 xlsx 时 resolve 指向 remote；本地有则 local。

## Blocked by

* TKT-3（assets 模块）
* TKT-6（上传 purge）

## Acceptance criteria

- [x] 仅公盘有的数据表附件可在明细中预览或外开。
- [x] 本地新建/修改的表经夜间同步上公盘并清本地后，仍可通过索引 + 公盘路径访问。
- [x] resolve 单测绿。
