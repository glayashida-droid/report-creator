# TKT-2: 申请单与基础数据解析模块 (Data Parsers Integration)

## 目标 (Objective)
集成已有的 `application_parser` 并编写针对本地 `标准库.xlsx` 和 `01-设备清单.xlsx` 的读取服务，让程序能够加载所有需要的基础映射数据。

## 需求 (Requirements)
*   **申请单解析**：确保能直接调用 `application_parser`，从例如 `A22606136861.xlsx` 提取数据，并存入 TKT-1 的项目中。
*   **标准库与设备库加载**：
    *   使用 `openpyxl` 编写工具函数读取 `database/标准库.xlsx` 和 `database/01-设备清单.xlsx`。
    *   将这些 Excel 的表头解析为内部模型列表，方便后续供下拉框调用（如获取所有标准号列表，根据标准号获取“标准描述”）。

## 阻塞依赖 (Blocked by)
*   [01-TKT-1-project-state.md](01-TKT-1-project-state.md)

## 测试/验收标准 (Acceptance Criteria)
*   [x] 运行脚本可以成功读取 `example/.../A22606136861.xlsx` 并打印出正确的公司名称和样品信息。
*   [x] 运行脚本能够读取并打印出标准库前5条记录的标准号和设备清单的设备名称，不报错。
