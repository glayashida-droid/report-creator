# TKT-3: 报价单解析引擎 (Quotation PDF Parser)

## 目标 (Objective)
通过 `pdfplumber` 解析 PDF 格式的报价单文件，提取其中的测试项目列表作为项目候选池。

## 需求 (Requirements)
*   编写解析逻辑，读取 `example/.../报价单.pdf` 格式文件。
*   通过正则或文本特征，过滤掉表头和无关文字，精准提取出测试项目名称（如“盐雾试验”、“温度循环”等）。
*   将提取出的测试项目放入 TKT-1 中定义的项目候选池（Candidate Pool）。

## 阻塞依赖 (Blocked by)
*   [01-TKT-1-project-state.md](01-TKT-1-project-state.md)

## 测试/验收标准 (Acceptance Criteria)
*   [x] 能够传入 `TO-26108862-02-04-05-06 报价单.pdf` 路径，提取出非空的字符串列表（测试项目）。
*   [x] 提取的项目列表中不能包含大量无关的表头废话。
