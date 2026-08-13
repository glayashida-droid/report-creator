# TKT-7: Word 报告生成引擎引擎 (Word Generator Engine)

## 目标 (Objective)
通过 `python-docx` 读取占位模板，将前端填写的项目状态（Project State）完整映射并渲染为 Word 报告。

## 需求 (Requirements)
*   准备一份基础的 Word 测试模板 `template.docx`，包含文本占位（如 `{{样品名称}}`）和空白的基础结果汇总表。
*   编写核心渲染逻辑：
    *   **基础替换**：遍历段落和表格，替换文本占位符。
    *   **多试验展开逻辑**：根据所选的导出模式（单试验 / 单 Leg / 全 Leg），按顺序将明细小节（8小节结构，包含从标准库带过来的评判要求、测试结果等）追加到文档末尾。
    *   **表格增行**：结果明细表根据用户填写的样品行（如 A01, A02）动态追加表格行并填入 Pass/Fail。
*   此层只关心生成，暂不插入图片。

## 阻塞依赖 (Blocked by)
*   [01-TKT-1-project-state.md](01-TKT-1-project-state.md)

## 测试/验收标准 (Acceptance Criteria)
*   [x] 写一个脱离 UI 的测试脚本，传入 Mock 好的 Project State。
*   [x] 能够成功导出 Word，且里面的占位符被正确替换。
*   [x] 明细部分能按要求的 8 小节正确生成文本段落。
