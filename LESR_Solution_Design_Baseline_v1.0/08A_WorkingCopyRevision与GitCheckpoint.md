# 08A Working Copy、Revision 与 Git Checkpoint

**决策成熟度：FOUNDATIONAL；Git Checkpoint 映射 PROVISIONAL**

## 1. 核心区分

```text
Working Copy
    Workspace 内可变候选

Checkpoint
    可恢复的中间快照

Revision
    正式、不可变的语义版本

Git Commit
    仓库持久化边界

Applied Change
    一次通过验证和审批的语义事务
```

五者不能混用。

---

## 2. Working Copy

Working Copy 必须绑定：

- Workspace；
- Base Revision；
- Effective Model；
- Delegation Grant；
- 当前 Draft 内容；
- 当前 Relation Proposal；
- 校验状态；
- Checkpoint 历史。

同一 Workspace 对同一 Logical Object 只允许一个活动 Working Copy。

不同 Workspace 可以基于同一 Approved Revision 创建并行候选。

---

## 3. 连续 AI 编辑

有效 Scoped Delegation 内，AI 可以连续：

1. 修改 Working Copy；
2. 添加或删除 Draft Fragment；
3. 创建 Proposed Relation；
4. 运行 Validator；
5. 根据 Observation 修复；
6. 形成 Checkpoint；
7. 生成 Review Package。

这些细粒度操作不要求每一步生成正式 Revision，也不要求每一步产生 Git Commit。

---

## 4. Checkpoint

Checkpoint 是恢复和审查单元，不是正式 Revision。

建议触发：

- 用户显式保存；
- AI 完成一个有意义的子任务；
- 达到时间或操作阈值；
- 运行重要验证之前；
- Workspace 暂停；
- 客户端退出；
- 提交评审之前。

Checkpoint 至少记录：

```yaml
checkpoint_id: ...
workspace_id: ...
base_revision: ...
working_state_hash: ...
operation_range: ...
created_by: ...
created_at: ...
validation_summary: ...
git_reference: ...
```

---

## 5. Git 持久化策略

已接受方案：

```text
B. Workspace Checkpoint 写入 Git
```

含义：

- 连续输入或每个字段修改无需提交；
- 可恢复 Checkpoint 必须进入 Git；
- 正式 Revision 必须进入 Git；
- Applied Change Record 必须进入 Git；
- Baseline 必须引用 Git Commit；
- Workspace 临时状态是否进入主分支不在此阶段冻结。

---

## 6. Checkpoint 与 Git 的映射候选

### 方案 A：每个 Checkpoint 一个 Commit

优点：简单、可恢复。  
缺点：可能产生大量提交。

### 方案 B：Workspace 专用引用或分支

优点：隔离候选，适合并行。  
缺点：Branch 管理和垃圾回收较复杂。

### 方案 C：Checkpoint Pack 写入对象目录，按策略 Commit

优点：控制 Commit 数量。  
缺点：恢复链更复杂。

当前只接受“Checkpoint 必须可由 Git 恢复”，具体映射仍为 `PROVISIONAL`。

---

## 7. Revision 形成时机

已接受：

- 连续编辑不产生正式 Revision；
- 提交评审时形成 Candidate Revision；
- 用户显式创建正式 Checkpoint 时可以形成 Revision；
- Apply Change 时形成最终不可变 Revision；
- 内容不变的批准不生成新的内容 Revision，只生成 Approval Attestation。

已接受：`in_review` 与 `approved` 可以指向同一 Revision UID。成熟度变化通过不可变 Lifecycle Record 表达；内容变化才创建新 Revision。

---

## 8. Submit Review

提交评审时：

1. 冻结 Working Copy 内容；
2. 生成不可变 Candidate Revision；
3. 固定 Relation Proposal；
4. 固定 Effective Model 哈希；
5. 运行要求的校验；
6. 生成 Review Package；
7. 关闭或只读化对应 Working Copy。

评审提出修改后，可以从 Candidate Revision 派生新的 Working Copy。

---

## 9. Apply Change

Apply 必须：

- 检查 Base Revision 未过期；
- 检查 Grant；
- 检查验证；
- 检查 Approval；
- 原子生成新 Revision 和 Relation Revision；
- 写入 Change Record；
- 写入 Provenance；
- 写入 Git；
- 更新查询投影；
- 保留失败恢复信息。

Apply 不得把 Working Copy 原地改成正式对象。

---

## 10. 并发与 Rebase

若 Base Revision 变化：

```text
Workspace Base: REQ@5
Repository Effective: REQ@6
```

系统暂停 Apply，并要求：

- Rebase；
- Merge；
- 放弃；
- 新建 Change。

AI 不能静默选择覆盖。

---

## 11. Workspace 生命周期

建议基础状态：

```text
open
active
paused
submitted
under_review
approved_to_apply
applied
aborted
archived
conflicted
```

这些是 Change Workspace 的核心操作状态；项目可扩展评审流程，但不得破坏原子性和历史完整性。

---

## 12. 当前已接受结论

- AI 编辑 Working Copy；
- Working Copy 可变；
- Revision 不可变；
- Checkpoint 用于恢复；
- Checkpoint 必须可由 Git 恢复；
- 连续编辑不要求逐步 Commit；
- 提交评审或 Apply 时形成正式 Revision；
- 同一 Workspace 对同一对象只存在一个活动 Working Copy；
- 并行 Workspace 允许；
- Base 变化时必须 Rebase 或冲突处理。

---

## 13. 尚未冻结

- Checkpoint 的 Git 映射；
- Workspace 是否必然对应 Branch；
- Candidate Revision 的存储目录；
- 自动 Checkpoint 阈值；
- Workspace Archive 保留期限；
- Applied Change 与 Commit 是否一对一。
