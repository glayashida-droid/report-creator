# TKT-4: 删卡片 / 删 Leg 强关联确认

labels: `ready-for-agent`

## Parent

[docs/specs/leg-scoped-test-dirs.md](../../../docs/specs/leg-scoped-test-dirs.md)

## What to build

已挂钩试验删除前确认：删卡片时说明将删除试验目录（含照片与数据表附件）；「是」删卡片+目录，「否」整次取消。未挂钩删卡片不弹盘确认。删整条 Leg 若有已挂钩节点，一次确认并列出将删目录名；全未挂钩则直接删 Leg 结构。提供删除试验目录的 IO。同步修正根 SPEC 与数据表规格中过时的「纯试验名路径 / 删卡不删目录」表述。

## Acceptance criteria

- [ ] 已挂钩删卡：确认「是」→ 卡片与对应试验目录皆无；「否」→ 两者都在。
- [ ] 未挂钩删卡：无目录确认框，卡片直接移除。
- [ ] 删 Leg 有挂钩：一次列出目录名；「是」删 Leg、卡片与所列目录；「否」全保留。
- [ ] 删 Leg 无挂钩：不弹盘确认，直接删 Leg 结构。
- [ ] `delete` 试验目录 IO：存在则移除，不存在 no-op；主缝测试为绿。
- [ ] 根 SPEC / 相关规格中与 ADR-0002 冲突的旧表述已改掉。

## Blocked by

- [01-path-formula-hook](01-path-formula-hook.md)
