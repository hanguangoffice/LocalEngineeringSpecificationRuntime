# 10 事实源、Git 与查询投影

**决策成熟度：FOUNDATIONAL；格式与投影技术 PROVISIONAL**

## 1. 权威模型

```text
Git Commit Tree
    权威结构化状态

Applied Change Record
    解释语义转换

Deterministic Snapshots
    提供当前资源读取

Query Projections
    可删除重建
```

具体定义见 `10A_CanonicalState快照变更记录与Git权威.md` 和 `10B_语义事务原子性Merge与Rebase.md`。

---

## 2. Git 中必须可恢复的语义

- Profile 和 Tailoring；
- Logical Object Descriptor；
- Object Revision；
- Relation Assertion Revision；
- Immutable Record；
- Workspace Checkpoint；
- Applied Change Record；
- Review Package/Approval Anchor；
- Configuration/Baseline Manifest；
- Provenance/Audit Anchor。

不要求一对象一文件，也不冻结具体目录。

---

## 3. Markdown 的位置

Markdown 可用于：

- Published Document；
- Review View；
- Human-readable Export；
- Long-form Explanation；
- Imported Source；
- 报告。

Markdown 不拥有独立正式语义。反向编辑必须转为 Reconciliation Workspace。

---

## 4. 确定性序列化要求

- Schema Version；
- Canonical Encoding；
- 稳定字段顺序；
- 稳定时间和数值表示；
- 稳定引用；
- 可重复 Hash；
- 扩展字段策略；
- 迁移记录。

具体格式由 P4 原型决定。

---

## 5. Query Projection

可使用：

- SQL；
- FTS；
- RDF；
- 属性图；
- Optional Vector；
- Cache。

Projection 必须记录：

- source_commit；
- projection_schema；
- completeness；
- errors；
- build tool version。

---

## 6. Git Checkpoint

连续编辑不要求逐步 Commit，但 Checkpoint 必须可由 Git 恢复。Branch、Ref、Commit 或 Pack 的映射由原型比较。

---

## 7. Git 不替代的语义

Git Commit 不等于：

- Object Revision；
- Lifecycle Transition；
- Approval；
- Baseline；
- Deviation；
- Context Bundle；
- Provenance；
- AI Delegation。

Git 保存这些资源的权威表示。

---

## 8. 外部手改

任何不经过 LESR Transaction 的 Git Diff 都被视为 Foreign Change，必须经过：

```text
Detect
→ Parse
→ Semantic Diff
→ Reconciliation Workspace
→ Validate
→ Review
→ Apply
```

不能静默成为正式状态。
