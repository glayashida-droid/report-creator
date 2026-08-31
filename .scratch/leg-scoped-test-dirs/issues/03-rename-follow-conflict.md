# TKT-3: 改名跟目录 + 冲突回滚

labels: `ready-for-agent`

## Parent

[docs/specs/leg-scoped-test-dirs.md](../../../docs/specs/leg-scoped-test-dirs.md)

## What to build

已挂钩卡片改中文名（Leg 图手工改名，或明细保存时标准「试验名称」覆盖）时，试验目录从 `{leg_name}-A` 改名为 `{leg_name}-B`，数据表索引相对路径前缀一并更新。目标目录已存在则提示「同名试验项目已存在，请重新命名」，改名失败并回滚卡片名，目录不动。未挂钩时改名只改卡片、不建盘不挪盘。

## Acceptance criteria

- [ ] 已挂钩：手工把中文名 A→B，磁盘目录与数据表相对路径前缀同步为 `{leg_name}-B`。
- [ ] 已挂钩：明细选标准保存后中文名被覆盖为 B 时，同样跟目录改名。
- [ ] 目标 `{leg_name}-B` 已存在 → 固定提示文案、卡片名回滚、源目录仍在。
- [ ] 未挂钩改名不创建、不移动试验目录。
- [ ] 主缝 rename 成功/冲突测试为绿。

## Blocked by

- [01-path-formula-hook](01-path-formula-hook.md)
