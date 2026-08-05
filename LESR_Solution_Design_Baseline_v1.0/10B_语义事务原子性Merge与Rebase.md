# 10B 语义事务、原子性、Merge 与 Rebase

**决策成熟度：FOUNDATIONAL**

## 1. Semantic Transaction

一次 Apply 是一个语义事务，包含：

```text
Transaction Identity
Base Commit
Expected Revision Set
Effective Model Hash
Operations
Preconditions
Validation Evidence
Approval Set
Resulting Resource Set
Postconditions
Provenance
Idempotency Key
```

---

## 2. 核心操作

封闭操作族：

- CREATE_LOGICAL_OBJECT；
- CREATE_REVISION；
- SET_DISPOSITION；
- ASSERT_RELATION；
- RETIRE_RELATION；
- CREATE_RECORD；
- RETRACT_RECORD；
- CREATE_DEVIATION；
- REVOKE_DEVIATION；
- UPDATE_PROFILE_BINDING；
- CREATE_CONFIGURATION；
- CREATE_BASELINE；
- PROMOTE_FRAGMENT；
- SPLIT_OBJECT；
- CONSOLIDATE_OBJECT。

Profile 可定义高层命令，但必须展开为核心操作。

---

## 3. Apply 流水线

```text
1. Verify Workspace and Delegation
2. Verify Base Commit and Expected Revisions
3. Verify Review Package Hash
4. Verify Approval and Conditions
5. Compile Transaction Plan
6. Evaluate Preconditions
7. Build New Semantic Tree in Staging
8. Validate Post-State
9. Persist Git Objects and Commit
10. Atomically Advance Canonical Ref
11. Rebuild/Increment Projection
12. Emit Audit and Provenance
```

若 Projection 更新失败，Canonical Git State 仍有效，Projection 标记过期并重建。

---

## 4. 原子性

同一 Transaction 中：

- 所有资源和关系一起生效；
- 任一 Preconditions 或 Postconditions 失败则不推进 Canonical Ref；
- 不出现半个 Baseline、半个 Relation 或只写部分 Revision；
- Git 提交成功但 Ref 未推进时可安全回收；
- Ref 推进后可从 Git 完整恢复。

---

## 5. Idempotency

重复提交同一 `idempotency_key + transaction_hash`：

- 返回相同结果；
- 不重复创建 Revision；
- 不重复生成 Audit；
- 不重复推进 Ref。

相同 Key 但不同 Hash 返回冲突。

---

## 6. Semantic Diff

Diff 以领域操作表示：

```text
Field Changed
Fragment Added/Removed
Relation Asserted/Retired
Disposition Changed
Rule Meaning Changed
Profile Binding Changed
Configuration Membership Changed
```

文本 Diff 作为辅助 View。

---

## 7. Semantic Merge

三方输入：

```text
Base
Ours
Theirs
```

可自动合并：

- 不同对象；
- 同一对象不同独立字段；
- 不冲突的 Relation；
- 纯展示变化。

必须人工处理：

- 同一规范字段不同修改；
- Fragment 删除与修改；
- Kind/Facet 不兼容；
- Human Key 冲突；
- Relation 端点冲突；
- Rule AST 语义冲突；
- Profile/Authority 变化；
- 同一 Deviation 不同状态。

---

## 8. Rebase

Workspace Rebase：

1. 固定旧 Base；
2. 解析新 Effective Base；
3. 重放语义操作；
4. 重新运行 Rule Compiler、Impact 和 Validation；
5. 生成新 Review Package；
6. 旧 Approval 失效。

AI 可提出 Rebase，但冲突解决需在授权范围内；高风险冲突要求用户介入。

---

## 9. Git Merge

普通 Git Merge 不能直接成为正式语义合并。Git 合并结果需要 LESR 校验并形成 Reconciliation Transaction。

---

## 10. Recovery

需支持：

- Staging 清理；
- 未推进 Commit 回收；
- Canonical Ref 校验；
- Projection 重建；
- Checkpoint 恢复；
- Audit 补偿记录；
- 外部 Git 操作检测。

---

## 11. 当前决策

- Apply 是原子语义事务；
- 核心操作族封闭；
- Git Ref 推进是权威切换点；
- Projection 失败不回滚 Git 权威；
- Merge/Rebase 以语义操作执行；
- 普通 Git Merge 需重新验证；
- Rebase 后旧审批失效。
