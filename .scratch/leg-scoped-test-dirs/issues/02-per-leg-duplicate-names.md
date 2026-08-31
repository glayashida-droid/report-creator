# TKT-2: 同 Leg 重名校验

labels: `ready-for-agent`

## Parent

[docs/specs/leg-scoped-test-dirs.md](../../../docs/specs/leg-scoped-test-dirs.md)

## What to build

同名试验校验改为「仅同一条 Leg 内」中文试验名不可重复；跨 Leg 允许同名。保存项目时同 Leg 重名则拦截提示；同一 Leg 内名不唯一时不能挂钩建照片夹或添加数据表。

## Acceptance criteria

- [ ] 同一 Leg 内两张卡片中文名相同 → 判为重名；跨 Leg 同名 → 不判重。
- [ ] 存在同 Leg 重名时保存项目失败并提示，不写盘。
- [ ] 同 Leg 名不唯一时，新建照片夹 / 添加数据表被提示中止。
- [ ] 跨 Leg 同名时可保存，且（在 TKT-1 已就绪时）可分别挂钩到各自目录。
- [ ] 辅缝（项目状态同名校验）测试覆盖上述行为。

## Blocked by

- None (can start immediately)
