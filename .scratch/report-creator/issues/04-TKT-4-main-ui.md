# TKT-4: 桌面主框架与基础绑定 (Main UI & Basic Binding)

## 目标 (Objective)
使用 PySide6 构建包含基本布局的桌面应用程序主窗口，打通 UI 与底层解析模块的第一步连接。

## 需求 (Requirements)
*   构建基于 PySide6 的 Main Window，应用 `qdarktheme` 样式（可选）。
*   **左侧/顶部**：包含“项目号输入框”、“解析申请单”按钮、“解析报价单”按钮。
*   **交互逻辑**：
    *   点击按钮时，调用 TKT-2 和 TKT-3 的逻辑。
    *   将获取到的客户/样品信息显示在一个只读文本框或信息面板中。
    *   将提取的“测试项目候选池”显示在界面的侧边栏列表中。

## 阻塞依赖 (Blocked by)
*   [02-TKT-2-data-parsers.md](02-TKT-2-data-parsers.md)
*   [03-TKT-3-pdf-parser.md](03-TKT-3-pdf-parser.md)

## 测试/验收标准 (Acceptance Criteria)
*   [x] 应用正常启动。
*   [x] 输入有效路径或点击解析后，界面能够正确显示提取出的公司信息和候选池列表。
