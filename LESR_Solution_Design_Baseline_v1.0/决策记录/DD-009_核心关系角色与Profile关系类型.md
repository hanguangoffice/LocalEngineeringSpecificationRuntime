# DD-009 核心关系角色与 Profile 关系类型

- 状态：ACCEPTED；角色清单细节 PROVISIONAL
- 决策：
  - LESR 提供封闭 Core Relation Role；
  - Profile 定义开放的 Relation Type，并映射到一个 Core Role；
  - Relation Assertion 保存具体关系事实。
- 理由：
  - 仅使用任意字符串无法跨 Profile 查询；
  - 仅使用少数通用谓词又不足以表达工程差异。
- 当前 Core Role：
  ORGANIZES、COMPOSES、REFINES、REALIZES、VERIFIES、CONSTRAINS、APPLIES_TO、DEPENDS_ON、IMPACTS、EVIDENCES、GOVERNS、AUTHORIZES、DERIVES_FROM、SUPERSEDES、CONFLICTS_WITH、REFERENCES。
- 正式追踪：
  由 Profile Relation Type 显式声明 trace credit。
- 反向：
  计算显示，不重复存储。
