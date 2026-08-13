# TKT-9: 全流程集成与导出触发 (Full Integration & Export UI)

## 目标 (Objective)
在 UI 层提供导出入口，连接底层的状态数据流和最终的报告生成引擎，完成真正的“一键出报告”。

## 需求 (Requirements)
*   在主界面提供“生成报告”菜单或按钮。
*   提供选项：“导出单项”、“导出当前 Leg”、“导出全部”。
*   点击后，收集界面内存里的最新 Project State，将其传递给 TKT-7 和 TKT-8 的生成引擎。
*   导出成功后，弹出对话框提示导出成功，并提供“打开报告”或“打开所在文件夹”的快捷按钮。

## 阻塞依赖 (Blocked by)
*   [06-TKT-6-test-detail-dialog.md](06-TKT-6-test-detail-dialog.md)
*   [08-TKT-8-photo-layout.md](08-TKT-8-photo-layout.md)

## 测试/验收标准 (Acceptance Criteria)
*   [x] 启动桌面端，加载示例项目，配置 2 个试验节点，填写假数据。
*   [x] 点击“导出全部”，程序能够运行结束无报错。
*   [x] 在输出目录下能找到最终的 Word 文件，内容包含首页信息、明细章节和抓取到的照片。
