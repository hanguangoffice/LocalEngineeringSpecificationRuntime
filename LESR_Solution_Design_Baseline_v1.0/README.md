# LESR 方案设计基线 v1.0

## 1. 定位

LESR（Local Engineering Specification Runtime，本地工程规范运行时）用于把用户自定义的工程规范转化为：

- 可寻址的工程语义对象；
- 可组合的 Profile 与规则；
- 可验证的关系和生命周期；
- AI 可精确调用的查询与上下文能力；
- 受控、可审计的变更；
- Git 支撑的本地权威状态；
- 可重建的查询和检索投影。

v1.0 是**方案设计基线**，表示主要语义和逻辑架构已经收敛，可以进入有限原型和技术选型验证。它仍然不是最终工程施工规格，也不冻结编程语言、数据库、序列化格式、MCP SDK、Web 框架或 UI 技术。

---

## 2. 已冻结的核心原则

1. Git 是必需基础设施。
2. 用户编写的规范决定规则、严格程度、流程和偏离政策。
3. LESR 不提供会覆盖用户规范的“宽松/严格模式”。
4. AI 可在一次限定授权后连续处理低风险 Draft。
5. AI 修改 Working Copy，不直接覆盖正式 Revision。
6. Markdown 用于阅读、导入、导出和发布视图，不承担主要语义事实源。
7. 采用 Composite Object、Governed Atomic Object、Addressable Fragment 和 Typed Field。
8. 采用封闭 Core Resource Class、可组合 Facet 和开放 Profile Kind。
9. Relation Assertion、Observation、Issue、Activity Record、Approval、Baseline 都具有独立语义。
10. Logical Object、Revision、Working Copy、Checkpoint 和 Git Commit 明确分离。
11. Internal UID 与 Human Key 分离，身份和历史编号不得复用。
12. 生命周期分为 Revision Maturity、Logical Object Disposition 和 Configuration Membership。
13. Approved、Effective 和 Baselined 是不同概念。
14. 普通长期关系默认绑定 Logical Object；Evidence、Approval、Baseline 等绑定准确 Revision。
15. Rule Definition、Evaluation Run、Observation 和 Enforcement Decision 分离。
16. Applicability 使用三值逻辑，未知不能静默等同不适用。
17. 规范模态、执行后果、权威、例外和偏离分离。
18. Profile 不得默认携带任意执行代码。
19. Review Package 是审批的不可变输入。
20. Git 提交树保存权威状态；查询数据库、全文索引和向量索引均可重建。
21. Git、Audit 和 Provenance 职责不同，三者均保留。
22. MCP 是可替换适配层，领域契约不依赖具体 MCP SDK 或某个客户端。

---

## 3. v1.0 新增的核心设计

### 规则表达

- `05B_RuleExpression元模型.md`
- `05C_Applicability表达式与三值逻辑.md`
- `05D_ConstraintAST类型单位路径与聚合.md`
- `05E_权威例外偏离与规则冲突解析.md`
- `05F_RuleCompiler解释映射与测试夹具.md`

### 配置解析

- `09D_EvaluationContext配置与EffectiveResolution.md`

### 评审批准

- `09E_ReviewPackage评审意见与批准模型.md`

### 权威状态和事务

- `10A_CanonicalState快照变更记录与Git权威.md`
- `10B_语义事务原子性Merge与Rebase.md`

### AI 与接口

- `07A_ContextContract完整性与渐进披露.md`
- `11A_MCP领域能力契约与版本策略.md`

### 原型与验收

- `17_方案设计基线总结与原型准入.md`
- `18_设计决策追踪矩阵.md`
- `19_最终方案验收清单.md`
- `术语表.md`
- `示例/`

---

## 4. 核心逻辑架构

```text
用户 / AI / CLI / 未来 UI / 外部工具
                 │
                 ▼
        Interaction Adapters
     MCP / CLI / REST / Import / Export
                 │
                 ▼
       Application Orchestrator
                 │
 ┌───────────────┼─────────────────┐
 ▼               ▼                 ▼
Semantic     Effective Model    Context Planner
Registry     & Policy Resolver
 │               │                 │
 └───────────────┼─────────────────┘
                 ▼
 Change Workspace / Review / Validation
                 │
                 ▼
       Semantic Transaction Engine
                 │
                 ▼
       Git-backed Canonical State
                 │
                 ▼
       Rebuildable Projections
 SQL / FTS / Graph / Optional Vector / Cache
```

---

## 5. 当前规则模型

```text
Authoritative Statement
+ Target Selector
+ Applicability Expression
+ Normative Modality
+ Constraint AST
+ Evaluation Method
+ Enforcement Mapping
+ Authority
+ Exception / Deviation Policy
+ Explanation Map
+ Test Fixtures
```

自然语言是用户认可的规范文本；Canonical Rule AST 是执行解释。两者共同属于 Rule Revision，任何修改均需版本化。

---

## 6. 当前配置模型

高风险操作必须提供或解析出明确的 Evaluation Context：

```text
Repository
Project
Configuration / Baseline
Variant
Time
Workspace Overlay
Operation
Actor / Delegation
Target Set
Environment
Effective Profile Set
```

若无法唯一解析 Effective Revision、Effective Rule 或有效偏离，结果为 `INDETERMINATE`，系统不得自行猜测。

---

## 7. 当前评审模型

审批绑定不可变 Review Package，Package 至少固定：

- Base Revision Set；
- Candidate Revision Set；
- Relation Changes；
- Semantic Diff；
- Impact Analysis；
- Validation Results；
- Open Findings；
- Effective Model Hash；
- Context/Configuration；
- Required Reviewers；
- Package Hash。

任何影响语义的改变都会使旧审批失效或触发重新评审。

---

## 8. 当前权威状态模型

已接受：

```text
Git Commit Tree
    保存权威结构化快照、不可变记录、Profile、配置和变更记录

Applied Change Record
    解释从旧树到新树发生的语义转换

Query Projection
    从 Git 权威状态重建，不具备独立权威
```

这不是纯 Markdown 文件系统，也不是数据库唯一事实源。

---

## 9. 建议阅读顺序

1. `17_方案设计基线总结与原型准入.md`
2. `02_设计原则与系统边界.md`
3. `04_核心语义模型.md`
4. `04A_顶层语义类别与Facet能力模型.md`
5. `04B_对象粒度Fragment与提升机制.md`
6. `04C_身份命名空间别名与血缘模型.md`
7. `05B_RuleExpression元模型.md`
8. `05C_Applicability表达式与三值逻辑.md`
9. `05D_ConstraintAST类型单位路径与聚合.md`
10. `05E_权威例外偏离与规则冲突解析.md`
11. `05F_RuleCompiler解释映射与测试夹具.md`
12. `07A_ContextContract完整性与渐进披露.md`
13. `08A_WorkingCopyRevision与GitCheckpoint.md`
14. `09D_EvaluationContext配置与EffectiveResolution.md`
15. `09E_ReviewPackage评审意见与批准模型.md`
16. `10A_CanonicalState快照变更记录与Git权威.md`
18. `10B_语义事务原子性Merge与Rebase.md`
19. `11A_MCP领域能力契约与版本策略.md`
20. `14_原型实验计划.md`
21. `19_最终方案验收清单.md`

---

## 10. 尚未冻结的实现选择

以下内容必须通过原型后再写最终施工规格：

- 编程语言和运行时；
- UID 具体格式；
- Canonical State 的 JSON/YAML/JSON-LD 表示；
- Git Workspace Checkpoint 的 Commit/Branch/Ref 方案；
- Rule AST 的具体序列化；
- SQL、RDF 或属性图的投影选择；
- JSON Schema、SHACL、Rego 或自定义验证器的实际组合；
- MCP 稳定版/候选版 SDK 选择；
- Web UI 和桌面 UI；
- 插件沙箱；
- 打包和升级机制。
