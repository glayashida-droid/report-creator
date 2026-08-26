# TKT-3: 明细双语（标准 / 设备 / 关键参数）

labels: `ready-for-agent`

## Parent

[docs/specs/bilingual-reports.md](../../../docs/specs/bilingual-reports.md)

## What to build

试验明细随**编辑语言**展示与编辑双语内容：选中标准时中文列与英文列（`condition` / `Evaluation requirement` / `result`，以及 `test item` 供后续导出）一并灌入并持久化；设备选择同时记下中文名与库中 `Equipment` 英文名；关键参数确认用同一组值分别替换中、英文条件原文，取消则两侧回库原文。英文编辑态结论显示为 Pass/Fail/N/A（底层枚举不变）。完成勾仍不要求英文侧非空。Leg 卡片名、试验目录、照片文件夹名保持中文。

## Acceptance criteria

- [x] 勾选标准后，英文条件/评判/结果描述可从库载入；切换编辑语言明细显示对应侧；用户修改写入项目状态。
- [x] 关键参数确认后中英文条件均被同一组确认值替换；取消确认两侧回到各自原文。
- [x] 已选设备持久化英文名；英文编辑态列表/已选显示英文名（缺则空）。
- [x] 英文编辑态样品结论展示 Pass/Fail/N/A，存盘仍为原枚举。
- [x] 仅缺英文时仍可打完成勾并导出中文范围；试验目录与照片夹名不随编辑语言改名。

## Blocked by

- [02-edit-language-overview.md](02-edit-language-overview.md)
