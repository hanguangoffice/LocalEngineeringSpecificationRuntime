# 09E Review Package、评审意见与批准模型

**决策成熟度：FOUNDATIONAL**

## 1. Review Package

审批对象不是模糊的 Change ID，而是不可变 Review Package。

Package 固定：

- Workspace；
- Base Revision Set；
- Candidate Revision Set；
- Relation Changes；
- Disposition Changes；
- Semantic Diff；
- Impact Analysis；
- Validation Runs；
- Observations/Issues；
- Open Findings；
- Effective Model Hash；
- Evaluation Context；
- Required Review Roles；
- Package Hash。

---

## 2. Review Comment

Review Comment 是 Immutable Record，绑定：

- Review Package；
- Revision/Relation/Fragment Anchor；
- Reviewer；
- Category；
- Severity；
- Comment；
- Disposition；
- Resolution Evidence。

Comment 内容不修改；通过 Reply、Resolution 或 Superseding Record 处理。

---

## 3. Approval 类型

至少区分：

- Content Approval；
- Technical Approval；
- Process Approval；
- Risk/Deviation Approval；
- Baseline Approval；
- Release Approval。

一个通用 `approved=true` 不足以表达责任。

---

## 4. Approval Attestation

固定：

- Subject Package Hash；
- Approved Scope；
- Approval Type；
- Actor/Role；
- Effective Model Hash；
- Conditions；
- Expiration；
- Timestamp；
- Signature/Confirmation Reference；
- Provenance。

---

## 5. Partial Approval

默认不允许随意部分批准。只有 Package 明确分区且满足以下条件时才允许：

- 分区具有独立 Revision Set；
- 无跨分区 Blocking Dependency；
- 影响分析证明可独立应用；
- Profile 允许；
- Approval Scope 精确列出。

---

## 6. Conditional Approval

允许，但条件必须：

- 结构化；
- 可验证；
- 有期限；
- 有责任人；
- 在 Apply 前满足，或 Profile 明确允许后置义务。

未满足条件不能静默视为批准。

---

## 7. Re-review Trigger

以下变化使旧评审失效或触发增量重评：

- Candidate 内容哈希变化；
- Relation Change 变化；
- Base Revision 变化；
- Impact Scope 变化；
- Effective Model 变化；
- Blocking Finding 变化；
- Deviation 变化；
- Configuration 变化；
- Required Reviewer Policy 变化。

纯展示变化不触发重评。

---

## 8. Reviewer Independence

Profile 可以要求：

- 作者与 Reviewer 分离；
- AI 不计入 Human Reviewer；
- 偏离由不同角色批准；
- 高风险变更需要双人批准；
- Reviewer 不能批准自己提出的 Deviation。

LESR 内核至少禁止 AI 正式批准自身生成的 Revision。

---

## 9. Approval 撤销

Approval Record 不修改。通过 Revocation Record：

- 指明原 Approval；
- 原因；
- Actor；
- 时间；
- 影响；
- 后续状态。

已使用该 Approval 创建的 Baseline 不删除，但标记风险并产生 Impact。

---

## 10. Apply 前门禁

```text
Package Hash 匹配
Required Approval 完整
Condition 完成
Base 未过期
Effective Model 匹配
Blocking Finding 已解决或合法偏离
Configuration Closure 完整
Semantic Transaction 可构建
```

---

## 11. 当前决策

- Review Package 是不可变审批输入；
- 评审意见是独立 Record；
- Approval 类型和 Scope 明确；
- Partial Approval 默认禁止；
- Conditional Approval 必须结构化；
- 语义变化触发重评；
- Approval 固定准确内容和规则环境。
