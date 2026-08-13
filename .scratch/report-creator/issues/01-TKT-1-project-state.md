# TKT-1: 项目脚手架与本地状态存储 (Project Scaffolding & Local State)

## 目标 (Objective)
搭建项目基础环境，并实现核心的数据模型（Project State）和本地 JSON 的保存/加载机制。这是所有后续工作的基础。

## 需求 (Requirements)
*   初始化虚拟环境，编写 `requirements.txt`。
*   定义项目的状态模型（Pydantic 或 Data Class），包含：
    *   全局信息：项目号、申请公司、样品接收日期、检测起止日期等。
    *   候选池：从报价单提取的可用试验列表。
    *   Leg 结构：列表或字典，记录有多少个 Leg。
    *   试验节点：每个 Leg 下包含哪些按顺序的试验节点。
    *   试验明细数据：选中的标准、设备、样品编号 (A01 等)、测试结论 (Pass/Fail)。
*   提供一个基础管理器类，支持将上述状态结构序列化为本地 `project_state.json` 文件并能够重新反序列化加载。

## 阻塞依赖 (Blocked by)
*   None

## 测试/验收标准 (Acceptance Criteria)
*   [x] 能够在纯 Python 环境（无 UI）下，实例化状态对象，添加模拟数据，成功导出为 JSON。
*   [x] 能够从 JSON 成功读取数据，还原为正确的状态对象。
