# 07A Context Contract、完整性与渐进披露

**决策成熟度：FOUNDATIONAL**

## 1. Context Contract

输入：

- Task Type；
- Task Description；
- Target Set；
- Evaluation Context；
- Token Budget；
- Sensitivity Boundary；
- Requested Completeness；
- Agent Capability。

输出：

- Invariants；
- Mandatory；
- Conditional；
- Supporting；
- Background；
- Negative Context；
- Active Deviations；
- Conflicts；
- Unknowns；
- Validation Obligations；
- Selection Trace；
- Omitted Candidates；
- Completeness Status。

---

## 2. Mandatory Read Set

只能由以下确定性来源建立：

- 直接关系；
- Applicability；
- Profile Context Policy；
- Effective Rules；
- Operation；
- Workspace；
- Configuration；
- Deviation；
- Security Policy。

向量相似度不得决定强制内容。

---

## 3. Completeness Status

```text
COMPLETE_UNDER_MODEL
INCOMPLETE_MISSING_RELATION
INCOMPLETE_UNKNOWN_SCOPE
INCOMPLETE_BUDGET
INCOMPLETE_INDEX
INDETERMINATE_CONFIGURATION
INDETERMINATE_PROFILE_CONFLICT
```

---

## 4. 渐进披露

### Manifest

ID、Revision、标题、状态、理由、摘要、关系路径。

### Focused Read

精确字段、Fragment 和关键正文。

### Deep Trace

版本历史、Evidence、完整关系、附件和 Provenance。

---

## 5. Token 预算

- Invariant 和 Mandatory 优先；
- 关键规范保留原文；
- Supporting 可摘要；
- Background 可裁剪；
- 冲突成对展示；
- 被裁剪对象列出；
- 预算不足时不得宣称完整。

---

## 6. Context Provenance

Context Bundle 是 Immutable Record，固定：

- Evaluation Context；
- Effective Model；
- Selected Revisions；
- Selection Algorithm Version；
- Summary Model；
- Completeness；
- Sensitivity Filtering；
- Token Estimate。

---

## 7. Agent 未遵循规则

LESR 无法直接控制模型内部行为，但可以：

- 要求 Agent 回报使用的 Rule ID；
- 检查输出变更对应的 Validation；
- 比较 Mandatory Set 与变更；
- 产生 Compliance Observation；
- 阻止不满足门禁的 Apply。

---

## 8. 当前决策

- Context 是可审计契约；
- Mandatory 不使用向量决定；
- 完整性显式；
- 渐进披露替代全文灌入；
- Context Bundle 进入 Provenance；
- 最终守门由确定性 Validation 和 Apply Policy 完成。
