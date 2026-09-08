# TKT-2: 导入样品编号保住限值行

labels: `ready-for-agent`

## Parent

[docs/specs/data-table-limit-validation.md](../../../docs/specs/data-table-limit-validation.md)

## Demo path

表中已有「限值」行 →「导入样品编号」→ 样品编号表头带在限值行之上合并写入，限值行 A 列仍为「限值」，样品 id 从限值行之下开始 → 刷新预览可见。无限值行的表导入行为与改前一致。

## Objective

导入样品编号时不破坏限值行标记与位置，使 TKT-1 的校验在导入后仍可用。

## Requirements

* 有限值行时：仅限值行之上的表头带并成「样品编号」；限值行紧挨其下，样品列保持「限值」；样品 id 从限值行之下写入。
* 无限值行时：行为与改前一致（US-16）。
* 复用 TKT-1 的限值行定位，不靠位置猜。
* 缝上模块测试：有限值行保住标记与写入起点；无限值行回归。

## Blocked by

* [01-limit-driven-validate.md](01-limit-driven-validate.md)

## Acceptance Criteria

* [x] 有限值行导入后，样品列限值标记仍在，id 不写进限值行或表头带。
* [x] 无限值行导入行为与改前测试/行为一致。
* [x] `import_sample_ids`（或同等）模块测试覆盖上述；合并后绿。
