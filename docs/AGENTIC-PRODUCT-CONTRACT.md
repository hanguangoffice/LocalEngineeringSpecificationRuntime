# LESR 代理化产品契约

状态：1.2 产品线的目标交互契约。它规定产品应如何工作，不单独构成实现完成或发布通过的证明。

## 产品目的

LESR 是人和 AI 代理共同使用的本地工程控制平面。它不把内部语义操作直接变成普通用户
流程，也不把单用户 ALM 的全部维护工作转交给一个人。

用户用自然语言目标或自定义规范启动 **Mission**。LESR 随后：

1. 从固定上游模板和当前 Profile 建立适用的工程结构；
2. 将 Mission 拆成需求、架构、实现、验证、证据与集成等 Work Package；
3. 为专业代理提供准确 Context，并协调可恢复 Working Copy、校验、影响分析和测试；
4. 在 Mission Mandate 范围内自动继续；
5. 只有策略要求人类决定时才生成一份可读的 Decision Request。

## 产品分层

```text
用户工作面
  工程地图 / Mission / 工程内容 / 待决定 / 版本

代理执行面
  Mission / Work Package 依赖图 / Agent Run / 集成 / 重试 / 交接

确定性控制面
  Configuration / Context / Workspace / Rule / Impact / Governance / Git 事务

持久化
  Git Canonical State 与 Workspace refs / 可重建 SQLite 运行视图
```

产品界面不要求用户组装 Workspace、UID、Hash、Git Ref、Delegation 或 Context Contract。
这些信息只在审计诊断中查看。

## Mission 与 Work Package 边界

- Mission 是代表一个用户目标的本地运行状态。
- Mission Mandate 记录工程、配置、允许范围、操作类型、限额、停止条件和有效期。
- Work Package 形成无环依赖图；一个工作包受阻时，不影响无依赖关系的其他工作继续。
- 协调代理负责拆分和集成；需求、架构、实现、验证等专业代理负责各自工作包；独立检查
  可以作为同一里程碑的另一个工作包，而不是每一步人工复核。
- Agent Run 保存执行、证据和交接状态。它属于运行状态，不作为工程事实写入 Canonical Git。
- Candidate 通过 Workspace ref 恢复；完成的工程变化只经过既有 Git 事务进入 Canonical State。

## 决策策略

调用方不选择风险等级。LESR 从实际语义差异、生命周期、Profile、Mission Mandate、影响
和外部效果派生四种结果：

- `AUTO_EXECUTE`：自动继续；
- `BATCH_FOR_MILESTONE`：保留到当前里程碑，与同阶段内容一起呈现；
- `HUMAN_DECISION_NOW`：生成 Decision Request，只暂停依赖该决定的工作；
- `BLOCK`：当前方案不符合模型或 Mandate，返回代理修正，不把它包装成用户审批。

计划、Context 收集、Working Copy 编辑、校验、测试、修复、Checkpoint、代理检查和无冲突
Rebase 自动进行。人工决定只用于材料工程取舍（目标或验收变化、结果不同的关键方案、
关键证据不足）以及正式责任（Profile 指定的人类角色、Profile/信任/权限变化、Deviation、
Exception、正式 Baseline 或 Release）。

An in-scope delegated Apply is recorded as delegated execution. It is never represented
as an AI-issued human Approval.

## Decision Request

Decision Request 是持久记录，每次只有一个主要操作。普通页面显示：

- 决定类型和工程区域；
- Mission 目标以及现在需要决定的原因；
- 可读的前后变化；
- 受影响的需求、设计、测试、证据和交付物；
- 校验结果与仍存在的不确定性；
- 集成代理的推荐和会产生不同结果的备选；
- 接受或拒绝之后会发生什么。

技术标识和分离签名属于审计详情，不承担解释任务。

## 工程展示

展示映射是 Profile/模板拥有的非权威 Revision。它把 Kind、Facet 和 Relation Type 组织为
工程区域、树、文档、矩阵、关系图、追踪覆盖和版本视图，不创造对象、关系或合规事实。

Web 产品从选中的映射生成导航。ASPICE-like Profile 可以显示 SYS/SWE/SUP；通用软件
Profile 可以显示目标、需求、架构、实现、验证和发布；其他领域使用自己的工程区域。
区域必须能够进入真实内容、层级、关系和覆盖情况，Web 适配器不能硬编码某一种分类。

## 完整性与签名边界

- Git Commit/Tree OID 与 expected-old-value ref 更新保护已存内容和并发写入。
- 稳定 UID 标识领域资源。
- Review Package 和跨能力汇合的评审证据保留摘要，用于绑定工作区评审与 Apply 边界。
- 资源内部不再为每个记录重复建立摘要链。
- Git 不保护仓库外私钥，也不表示工程角色的业务批准；需要正式人类批准时使用 Ed25519。
- 人类签名是否需要由当前 Profile 决定。私钥保存在仓库外，由操作系统或加密回退方案保护。

完整边界、保留原因和已删除字段见 `integrity-boundaries.md`。

## 兼容关系

本契约改变 1.2 产品线的默认交互方式。既有 1.0 Canonical 资源继续作为工程事实；Mission、
Agent Run 和展示数据属于上层运行与视图。旧的逐步 Web 操作流程和调用方自报风险级别不再
作为产品承诺。实现与发布状态必须另由当前版本的代码、测试和发布记录确认。
