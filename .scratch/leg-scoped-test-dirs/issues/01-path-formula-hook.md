# TKT-1: 路径公式贯通（挂钩建夹 + 导出读盘）

labels: `ready-for-agent`

## Parent

[docs/specs/leg-scoped-test-dirs.md](../../../docs/specs/leg-scoped-test-dirs.md)

## What to build

试验目录改为 `{leg_name}-{试验名}`（例：`Leg 1-温湿度试验`）。明细里首次建照片夹或添加数据表时按新公式挂钩落盘；卡片与报告检测项目仍只显示试验名。相册列表与 Word 贴图只认新路径。无可用试验名时仍不可挂钩。英文卡片名不进入目录名。

## Acceptance criteria

- [ ] 给定 Leg 与可用中文试验名，试验目录 / 照片夹 / 数据表附件路径均为 `3.测试组/{leg_name}-{试验名}/…`。
- [ ] 仅建卡不起夹时，磁盘上不出现该试验目录（懒挂钩）。
- [ ] 明细模版四夹、自定义照片夹、添加数据表均写到新公式路径；跨 Leg 同名试验各有独立目录。
- [ ] 导出/列出相册只读新路径，不读纯试验名旧路径。
- [ ] 试验名不可用时不能挂钩；主缝（试验目录 IO）相关测试基线红、合并后绿。

## Blocked by

- None (can start immediately)
