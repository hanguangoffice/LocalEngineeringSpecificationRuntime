# 04A 顶层语义类别与 Facet 能力模型

**决策成熟度：FOUNDATIONAL；具体枚举扩展 PROVISIONAL**

## 1. 为什么要同时保留类别与 Facet

Core Resource Class 固定资源的治理性质；Facet 固定能力；Kind 固定项目和 Profile 如何称呼并约束它。

---

## 2. Core Resource Class 不变量

### Governed Object

- 有 Logical ID；
- 有不可变 Revision；
- 可有 Workflow；
- 变化必须生成新 Revision；
- 可进入 Baseline；
- 可被正式 Relation 引用。

### Immutable Record

- 有 Record ID；
- 内容创建后不可修改；
- 可被撤回或替代，但原记录保留；
- 必须记录产生时间和 Agent；
- 通常固定引用输入 Revision。

### Change Workspace

- 固定 Base Configuration；
- 保存候选操作；
- 未 Apply 前不改变正式状态；
- 可以被 Scoped Delegation 修改；
- Apply 必须原子化。

### Configuration Snapshot

- 内容不可变；
- 所有逻辑引用必须可解析为准确 Revision；
- 包含 Effective Model；
- 可映射 Git Commit。

### Presentation Resource

- 内容可以重新生成；
- 必须说明查询或成员来源；
- 不因排版结构自动创建工程关系。

---

## 3. 核心 Facet

- Authored；
- Lifecycle；
- Normative；
- Applicability；
- Composition；
- Traceability；
- Verification Plan；
- Executable；
- Decision；
- Authorization；
- Issue；
- Record；
- Evidence；
- Observation；
- Confidentiality；
- External Binding。

---

## 4. Extension Facet

Profile 可以增加命名空间化 Facet，例如：

```text
automotive.can_signal
automotive.diagnostic_dtc
home_iot.device_capability
```

限制：

- 不能改变 Logical ID 语义；
- 不能让 Immutable Record 变可编辑；
- 不能绕过 Change Workspace；
- 不能自行授予批准能力；
- 不能覆盖核心 Provenance；
- 必须声明 Schema 和版本；
- 必须提供迁移和测试。

---

## 5. Kind 示例

### Software Requirement

```text
Core: Governed Object
Facets:
- Authored
- Lifecycle
- Normative
- Applicability
- Traceability
- Verification Target
```

### Coding Rule

```text
Core: Governed Object
Facets:
- Authored
- Lifecycle
- Normative
- Applicability
- Executable
- Deviation Policy
```

### CAN Signal

```text
Core: Governed Object
Facets:
- Authored
- Lifecycle
- Interface Definition
- Applicability
- Traceability
- External Binding
```

### Test Execution

```text
Core: Immutable Record
Facets:
- Record
- Evidence
- External Binding
```

### Static Analysis Observation

```text
Core: Immutable Record
Facets:
- Record
- Observation
- External Binding
```

### Static Analysis Issue

```text
Core: Governed Object
Facets:
- Lifecycle
- Issue
- Traceability
```

---

## 6. 能力发现

AI 查询 Kind 时，应获得计算后的能力：

```text
can_read
can_propose_revision
can_transition
can_be_baselined
can_be_deviated
can_accept_evidence
can_have_formal_trace
can_be_modified_under_delegation
```

能力由 Core Class、Facet、Profile、State 和 Delegation 共同决定。
