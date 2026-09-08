# TKT-3: 报告勾选 + 限值行展示快照

labels: `ready-for-agent`

## Parent

[docs/specs/data-table-limit-validation.md](../../../docs/specs/data-table-limit-validation.md)

## Demo path

预览始终能看到限值行 → 「报告中显示限值行」默认不勾 → 导出 Word 该表无限值行 → 勾选后再导出则含限值行 → 单格整表限值时预览（及勾选后的 Word）跨数据列居中展示，xlsx 未改合并 → 关闭明细重开，勾选恢复不勾。

## Objective

限值行预览常显；用会话态勾选控制 Word 是否输出；单限值跨列居中仅展示层，不落盘、不改 xlsx。

## Requirements

* 预览始终含限值行（若表中有）；勾选不影响预览显隐。
* 勾选默认 `false`，按表会话态保存（如按 `relative_path`），不写 `DataTableRef` / JSON；关明细或重开复位。
* 缝提供按 `include_limit_row` 裁剪/变换的展示快照；`false` 去掉限值行；`true` 保留。
* 单格整表限值：展示快照对限值行做跨数据列居中合并描述，不写回 xlsx。
* 限值行不计入 Word 分页重复表头；`word_engine` 消费展示快照 + 明细传入的勾选。
* 缝上可测：含/不含限值行的行集合、单限值合并描述。

## Blocked by

* [01-limit-driven-validate.md](01-limit-driven-validate.md)

## Acceptance Criteria

* [x] 预览始终显示限值行（有则显示）；勾选默认关且不落盘。
* [x] 不勾导出无限值行；勾选后本次导出有限值行。
* [x] 单限值时预览/勾选导出为跨列居中；磁盘 xlsx 合并未因此改写。
* [x] 展示快照相关模块测试合并后绿；Word 接线可人工验导出。
