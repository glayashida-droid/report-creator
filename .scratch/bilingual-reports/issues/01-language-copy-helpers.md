# TKT-1: 语言文案拼装（接缝 2）

labels: `ready-for-agent`

## Parent

[docs/specs/bilingual-reports.md](../../../docs/specs/bilingual-reports.md)

## What to build

落地语言侧文案拼装纯函数（接缝 2），供后续编辑态与 Word 导出共用：结论中英映射、中英文拼接（无英则只出中文）、申请单「无汉字可作英文」、照片文件夹中文名 → 三语说明（含自定义文件名覆盖规则的判定入口）。本票不接 UI、不改导出；用单测钉住对外行为即可验证。

## Acceptance criteria

- [x] 结论：中文合格/不合格/N/A ↔ 英文 Pass/Fail/N/A；中英文为 `合格 / Pass` 等形式（N/A 保持 N/A）。
- [x] 拼接：有中有英 → 对照串；仅中或仅英 → 单侧；英文模式缺英 → 空串且不回退中文。
- [x] 申请单值：不含汉字的纯英文/数字可作为英文侧；含汉字且无独立英文时英文侧为空。
- [x] 相册说明：试验前/试验中/试验后 → 中文原名、英文 Before test / Test setup / After test、中英文对照；自定义 stem 覆盖默认说明的规则可测；「数据」与未知夹名走文件名策略。
- [x] 模块测试在基线上为红、合并后为绿；无 GUI 依赖。

## Blocked by

- None (can start immediately)
