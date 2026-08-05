# 10A Canonical State、快照、变更记录与 Git 权威

**决策成熟度：FOUNDATIONAL；序列化格式 PROVISIONAL**

## 1. 权威状态

已接受模型：

```text
Git Commit Tree
  ├─ Deterministic Semantic Snapshots
  ├─ Immutable Records
  ├─ Applied Change Records
  ├─ Profiles / Tailoring
  ├─ Configuration / Baseline Manifests
  └─ Provenance / Audit Anchors
```

Git Commit Tree 是某一时刻的权威仓库状态。

---

## 2. Snapshot 与 Change Record

### Semantic Snapshot

方便读取当前资源状态。

### Applied Change Record

解释从 Base Tree 到 Result Tree 的语义操作。

两者必须一致。若不一致：

- 仓库标记损坏；
- 高风险操作停止；
- 通过验证工具和 Git 历史恢复；
- 不以查询数据库为准。

---

## 3. 为什么不采用数据库唯一事实源

- Git 是必需；
- 用户要求本地、可恢复和可迁移；
- Query DB 可删除重建；
- Baseline 需要固定仓库状态；
- 外部工具和 AI 不应绕过 Git 权威。

数据库仍用于高效查询，但不拥有独立正式事实。

---

## 4. 为什么不采用 Markdown 事实源

Markdown 不适合稳定表达：

- UID；
- Revision；
- Relation Assertion；
- Profile Schema；
- Enforcement；
- Baseline；
- Semantic Transaction；
- Approval Scope。

Markdown 可由 Canonical State 渲染，也可通过受控导入转为 Change Proposal。

---

## 5. Deterministic Serialization

具体格式未冻结，但必须满足：

- 字段顺序确定；
- 编码确定；
- 时间格式确定；
- 无随机空白；
- 引用格式确定；
- Hash 可重复；
- Schema Version 显式；
- Unknown Extension 保留或明确拒绝。

---

## 6. 外部手工修改

Git 中结构化文件被外部编辑后，LESR 不直接视为正式 Change。

流程：

```text
Detect Foreign Diff
→ Parse
→ Compare Semantic State
→ Create Import/Reconciliation Workspace
→ Validate
→ Review
→ Apply
```

无法解析的改动隔离并报告。

---

## 7. Query Projection

可包含：

- SQL；
- FTS；
- Graph；
- Optional Vector；
- Cache；
- File Mapping。

Projection 记录：

- source_commit；
- projection_schema；
- index completeness；
- build report。

---

## 8. Baseline

Baseline Manifest 固定：

- Git Commit；
- Resource Revision；
- Relation Revision；
- Effective Model；
- Configuration；
- Deviation；
- 外部引用；
- 可选 Evidence Set。

Git Tag 可以指向 Baseline Commit，但 Tag 不替代 Manifest。

---

## 9. Workspace State

Workspace Checkpoint 也必须进入 Git 可恢复域，但不一定进入发布分支。具体使用 Branch、Ref 或 Pack 由原型决定。

---

## 10. 当前决策

- Git Commit Tree 是权威状态；
- Snapshot 与 Applied Change Record 同时保存；
- Query Projection 可重建；
- 外部手改通过 Reconciliation Workspace；
- Markdown 仅是 View/Import；
- Baseline Manifest 固定语义配置并引用 Git。
