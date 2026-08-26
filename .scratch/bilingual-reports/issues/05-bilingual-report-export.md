# TKT-5: 中英文报告导出（含照片说明）

labels: `ready-for-agent`

## Parent

[docs/specs/bilingual-reports.md](../../../docs/specs/bilingual-reports.md)

## What to build

接通导出「中英文」：选用中英文模板，按对照规则拼装首页（委托单位/地址中文 + Customer/Address 英文）、样品信息表标签与说明句、清单/汇总表头、检测项目 `中文 / 英文`、结论 `合格 / Pass` 等、明细小标题与正文块、设备名称对照。无英文则只出中文（不造空斜杠）。报告编号 `…E`。照片说明为对照形式（试验前 Before test 等），自定义文件名同样覆盖默认说明；文件夹名保持中文。法律文案以模板为准。依赖票 4 已打通的导出与照片说明路径，本票扩展为对照输出。

## Acceptance criteria

- [x] 导出选「中英文」使用中英文模板；报告编号带 `E` 后缀。
- [x] 封面中文行与 Customer/Address 英文行均按状态填写；缺英时英文行空、中文行仍在。
- [x] 样品信息/清单/汇总/明细表头与小标题为中英对照；检测项目与结论按拼接规则；无英则仅中文。
- [x] 明细条件/评判/结果使用状态中已保存的中英文（先中后英或对照，与 raw 精神一致）；数据表不翻译。
- [x] 照片说明为中英对照默认语，或自定义 stem；相册文件夹名仍为中文。
- [x] Word 引擎级测试覆盖中英文关键串与「无英只出中文」。

## Blocked by

- [04-english-report-export.md](04-english-report-export.md)
