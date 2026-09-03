# TKT-9: 集成验收 · 文档 · ADR 补丁

labels: `ready-for-agent`

## Parent

[docs/specs/nightly-backup-and-cloud-photos.md](../../../../docs/specs/nightly-backup-and-cloud-photos.md)

## Demo path

走通规格 Further notes 示例：第一日 1–5 上传清本地 → 第二日见 1–5 云图 → 下载 4 → 拷入 6–10 → 列表 1–3,5 云 + 4,6–10 本地 → 夜间上传 4,6–10 并清本地 → 导出 Word 含全部正式相册图；第二人从公盘加载见 JSON 排期与云图。

## Objective

端到端 smoke、文案与 ADR 一致；`update.txt` 与连接状态摘要（公盘 JSON / 上次同步）。

## Requirements

* 新增或扩展集成测试 / 手工 test plan 文档覆盖 US-30–32（JSON 即时、照片滞后可接受）。
* 更新 `docs/adr/0001-photos-live-on-disk.md` 或短 ADR-0003：合并视图 + 备用 + 公盘备份，照片清单仍不进 JSON。
* `update.txt` 用户可见变更摘要。
* 主界面可选：上次同步时间、公盘 JSON 状态（与现有连接状态并列）。
* 确认 `CONTEXT.md` 词汇与 spec 一致（若 TKT-1–8 未改全则本票补齐）。

## Blocked by

* TKT-1
* TKT-2
* TKT-3
* TKT-4
* TKT-5
* TKT-6
* TKT-7
* TKT-8

## Acceptance criteria

- [x] 规格 Further notes 示例场景可手工或自动走通。
- [x] 全 suite 绿（或本 feature 相关测试绿）。
- [x] ADR / update.txt 已更新；无 UI 层散落双根 photo 逻辑。
