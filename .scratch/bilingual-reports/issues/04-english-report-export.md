# TKT-4: 英文报告导出（含照片说明）

labels: `ready-for-agent`

## Parent

[docs/specs/bilingual-reports.md](../../../docs/specs/bilingual-reports.md)

## What to build

接通导出「英文」：选用英文模板，用项目状态中已确认的英文侧生成封面、样品信息表、样品清单、结果汇总、试验明细（小标题、环境条件标签、设备表、条件/评判/结果、结论）与检测照片说明。缺英文处留空，绝不回退中文。检测项目英文取自标准库 `test item`（多标准拼装顺序与中文侧一致精神）。照片文件夹名仍为中文；模版三夹默认说明为 Before test / Test setup / After test；若图片文件被自定义命名则说明用该 stem；「数据」与自定义夹仍以文件名为主。法律文案以模板为准。中文导出不回归；导出范围与未完成拦截逻辑不变。

## Acceptance criteria

- [x] 导出选「英文」不再提示模板未就绪；使用英文模板；报告编号无 `C`/`E` 字母后缀（与现有规则一致）。
- [x] 封面、样品信息标签与日期、清单/汇总表头、明细（1）～（8）与「检测照片」为英文表述；结论为 Pass/Fail/N/A。
- [x] 某字段无英文时该处为空，文档中不出现对应中文回退。
- [x] 汇总/明细检测项目英文来自 `test item`；缺则该侧空。
- [x] 试验前/中/后照片说明为 Before test / Test setup / After test（或自定义 stem）；文件夹名未改成英文。
- [x] 同范围中文导出仍可用；未完成试验仍拦截导出。
- [x] Word 引擎级测试覆盖英文关键串与缺英不回退（可无 UI）。

## Blocked by

- [01-language-copy-helpers.md](01-language-copy-helpers.md)
- [03-detail-bilingual-standards.md](03-detail-bilingual-standards.md)
