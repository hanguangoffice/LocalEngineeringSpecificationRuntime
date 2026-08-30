# LESR 架构状态

LESR 是面向人和 AI 代理的本地单仓库工程控制平面。Git commit tree 是 Canonical
State；SQLite/FTS5、Mission、Task 和 Agent Run 数据是可重建或可恢复的本地运行状态。
领域服务处理正式写入，CLI、MCP 与 Web 适配同一组能力和决策策略。

## 从目标到工程结果

```text
自然语言目标 / 自定义规范
          ↓
上游模板 + Profile → 工程地图
          ↓
Mission Mandate → Work Package 依赖图 → 专业 Agent Run
          ↓
Context / Working Copy / Validation / Impact / Test / Rebase
          ↓
AUTO_EXECUTE / BATCH_FOR_MILESTONE / HUMAN_DECISION_NOW / BLOCK
          ↓
语义事务 → Git Canonical State → 可重建查询视图
```

Mission 协调运行过程，不改变工程事实的权威模型。代理可以在 Mandate 范围内编辑和验证；
Candidate 只有经过适用的治理策略与 Git 原子事务后才进入 Canonical State。任务进度和
代理内部交接不会污染工程提交历史。

## 规范与工程结构

零规范接入位于权威写入之前。它读取许可明确、版本固定的上游模板，保留用户原话并生成
可编辑工程内容；导入自定义规范时也走同一入口。Profile 决定 Kind、Relation、Rule、
Workflow 和工程展示映射。展示映射只组织视图，不创造合规事实。

因此工程地图可以为 ASPICE-like Profile 展示 SYS/SWE/SUP，也可以为通用软件、API、
数据科学或嵌入式工程展示完全不同的区域。每个区域都能继续进入层级、关系、追踪覆盖、
变化、验证和证据视图，而不是只有一组静态按钮。

## 决策与授权

后端从语义差异、生命周期、Profile、Mission Mandate、影响和外部效果派生决策结果。
调用方不能用自报风险级别制造审批。`AUTO_EXECUTE` 直接继续；
`BATCH_FOR_MILESTONE` 汇总同一阶段的材料；`HUMAN_DECISION_NOW` 只暂停依赖当前决定的
工作；`BLOCK` 返回代理修正方案。

Delegation Grant 规定代理可自动执行的范围，不是人类 Approval。普通编辑、校验、测试、
修复和无冲突合并属于运行过程。Ed25519 只用于 Profile 指定的正式人类责任边界。

## 权威与完整性

Git OID 和 CAS 引用推进负责存储内容身份、历史和并发写入；Ed25519 负责把正式人类决定
绑定到准确评审主题。Git 不加密仓库外私钥，也不提供业务批准签名。完整边界与已精简的
重复摘要见 `integrity-boundaries.md`。

## 历史与当前契约

0.5 的操作队列工作区和浅关系校验已经由 1.0 语义内核取代。2.0 产品线在该内核之上
引入 Mission、代理执行和工程地图，改变默认交互方式，不另建第二套权威模型。完整交互
契约见 `AGENTIC-PRODUCT-CONTRACT.md`，版本关系见 `versioning.md`。

以下状态词仍需严格区分：

- **Architecture Validated**：实验支持某项设计决定。
- **Feature Implemented**：生产代码和定向测试已经存在。
- **Integrated**：所有权威边界使用同一实现。
- **Release Gate Passed**：指定版本的 Gate 报告及其要求均已通过。

早期 P1～P5 原型报告只作为架构证据。历史 Gate 的 PASS 也只属于报告注明的版本，不能
直接转换为当前工作版本的发布结论。
