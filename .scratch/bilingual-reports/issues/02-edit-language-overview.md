# TKT-2: 编辑语言 + 申请单双语概览

labels: `ready-for-agent`

## Parent

[docs/specs/bilingual-reports.md](../../../docs/specs/bilingual-reports.md)

## What to build

在「项目定位」收窄路径框并加入**编辑语言**总开关（中文 | 英文）。加载/重载申请单时把委托方、地址（含报告抬头优先）与样品字段的中英文写入项目状态；概览随编辑语言显示与编辑对应侧；两侧分别保存。编辑语言与导出弹窗的三档选择相互独立。切换编辑语言不改动 Leg 图试验名与候选池。

## Acceptance criteria

- [x] 「项目定位」同行可见中文|英文切换，路径输入明显变短，原有加载/选目录/重载按钮仍可用。
- [x] 解析申请单后项目状态同时持有中英文字段；不再丢弃解析出的英文。
- [x] 切到英文时概览显示英文侧（可空、可手改）；切回中文显示中文侧；保存再打开两侧内容仍在。
- [x] 无汉字的申请单字段值在英文侧按票 1 规则可用作英文。
- [x] 切换编辑语言不改变导出语言弹窗选项，也不改写 Leg/候选池名称。

## Blocked by

- [01-language-copy-helpers.md](01-language-copy-helpers.md)
