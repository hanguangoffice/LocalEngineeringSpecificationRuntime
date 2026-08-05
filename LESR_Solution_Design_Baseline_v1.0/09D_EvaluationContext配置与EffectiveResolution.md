# 09D Evaluation Context、配置与 Effective Resolution

**决策成熟度：FOUNDATIONAL**

## 1. Evaluation Context

任何高风险求值必须有明确上下文：

```text
Repository
Project
Configuration / Baseline
Variant
Time
Workspace Overlay
Operation
Actor
Delegation
Target Set
Environment
Effective Model
```

---

## 2. Configuration Snapshot

配置快照至少冻结：

- Object Revision；
- Relation Assertion Revision；
- Profile Revision；
- Tailoring Revision；
- Effective Model Hash；
- Active Deviation Revision；
- Unit/Function Registry；
- External Reference Version；
- 可选 Toolchain Configuration；
- Git Commit。

---

## 3. 配置层

```text
Base Configuration
→ Variant Overlay
→ Environment Overlay
→ Workspace Overlay
→ Explicit Request Override
```

每层只能使用 Profile 允许的覆盖操作。

Workspace Overlay 只影响当前候选，不会改变已发布 Baseline。

---

## 4. Effective Revision 解析

顺序：

1. 显式 Pinned Revision；
2. Workspace Candidate；
3. Explicit Configuration Membership；
4. Variant/Time Selector；
5. Profile 允许的 Latest Approved Fallback；
6. 无唯一结果时 INDETERMINATE。

高风险 Apply、Approval 和 Baseline 默认不允许使用隐式 Latest Approved Fallback。

---

## 5. Effective Rule 解析

```text
Enabled Profiles
+ Profile Versions
+ Tailoring
+ Configuration Scope
+ Rule Applicability
+ Authority
+ Exception
+ Deviation
= Effective Rule Set
```

结果必须记录被排除规则及原因。

---

## 6. Partial Configuration

Partial Configuration 可以用于探索和 Draft，但必须标记：

```text
COMPLETE
PARTIAL
INDETERMINATE
INCONSISTENT
```

进入 Approval、Apply 或 Baseline 时，项目规范要求的闭包必须完整。

---

## 7. 配置闭包

闭包可包括：

- Required Relations；
- Referenced Parameters；
- Interface Dependencies；
- Applicable Profiles；
- Active Deviations；
- Evidence；
- Toolchain；
- External Baseline。

闭包规则由 Profile 定义。

---

## 8. 时间语义

支持：

- valid_from；
- valid_until；
- evaluation_time；
- as_of；
- evidence_freshness；
- deviation_expiration。

时间比较必须使用明确时区和不可歧义时间格式。

---

## 9. Variant

Variant 是配置维度，不应只作为标签。Profile 定义：

- 维度；
- 允许值；
- 互斥关系；
- 默认值；
- 派生条件；
- 覆盖权限。

---

## 10. 解析输出

```text
effective_context_id
selected_revisions
selected_relations
effective_rules
active_deviations
excluded_items
unknowns
conflicts
closure_status
explanation_trace
```

---

## 11. 当前决策

- 高风险求值必须有 Evaluation Context；
- Baseline/Configuration 明确冻结规则与对象；
- Workspace 是覆盖层；
- 高风险操作不使用隐式 current；
- Partial Configuration 不能伪装完整；
- Effective Resolution 必须可解释和可复现。
