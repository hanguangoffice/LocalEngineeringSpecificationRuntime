# LESR 的完整性与签名边界

这份说明面向维护者和审计人员。普通工作页面只展示工程名称、工程区域、内容变化、影响和决定理由；下面的技术标识集中在审计详情中。

## Git 负责什么

Canonical State 保存为 Git tree。Git Commit/Tree OID 能证明读取到的文件集合正是某次提交的内容；带 expected-old-value 的引用更新用于发现并发推进，避免两个写入者同时覆盖工程状态。工作区引用和提交历史还提供恢复与差异查看。

Git 的内容寻址没有代替两件事：

- 它不保护仓库外的 Ed25519 私钥，也不提供私钥加密。Windows DPAPI、Linux Secret Service 或加密 PKCS#8 文件负责本机私钥保存。
- 它不表达“哪一位具有某工程角色的人批准了哪个变更范围”。Git 提交身份不是 LESR 的业务批准签名。

## Ed25519 负责什么

当当前 Profile 把某个边界明确分配给人类时，Ed25519 签名把批准人、角色、Review Package、Effective Model、批准范围、条件和有效期绑定为一个正式批准。私钥留在用户侧，Canonical State 只保存公钥、信任角色、撤销记录和签名结果。

签名不是普通编辑、校验、测试或代理协作的前置步骤。Mission Mandate 已覆盖的执行由代理继续完成；正式发布、基线、偏离/例外或 Profile 指定的人类责任才进入签名流程。

## 仍保留的内容摘要

以下摘要跨越了 Git 之外或不同时间点之间的交接，因此保留：

- `ReviewPackage.package_hash`：批准发生在工作区候选进入 Canonical State 之前。摘要把签名固定到同一组候选、差异、模型与评审材料；候选重建或 Rebase 后自然形成新的批准主题。
- Review Package 中的证据摘要：Semantic Diff、Graph Snapshot、Context Bundle、Impact Report、Validation 和 Finding 可能由不同能力生成并在评审时汇合。摘要用于确认评审看到的材料与 Apply 边界重新读取的材料相同。
- 外部模板和导入源摘要：本地 Git 不能证明另一个仓库指定版本的文件内容，也不能证明导入前的外部文件。该摘要只用于外部快照和来源交接。
- Ed25519 签名消息中的 scope digest：它是签名编码的一部分，不作为独立持久字段；验证时从实际 scope 重新计算。

## 已删除的重复摘要

下列字段没有独立的跨边界使用者，内容本身已随 Git tree 保存，并可通过明确 UID 引用，因此已删除：

- `AuditAnchor.previous_anchor_hash`、`event_hashes` 与 `anchor_hash` 组成的第二条审计链；
- `ReviewPackage.subject_hash`；
- `SignedApproval.scope_hash` 持久字段；
- `WorkspaceCheckpoint.checkpoint_hash`；
- `ReviewComment.comment_hash`；
- `CommentResolution.resolution_hash`；
- `ConditionSatisfaction.satisfaction_hash` 与仅保存摘要的 `condition_hash`；
- `ApprovalRevocation.revocation_hash`；
- Signer IPC 请求体中重复传输的 challenge 字段。

审计记录现在按事务 UID 保存参与者、操作类型、批准引用和时间，顺序与内容完整性由包含
它的 Git commit 和 parent 历史承担。评论处理引用 `comment_uid`，条件满足记录保存原始
条件结构，撤销记录引用批准 UID。Signer 仍使用进程间连接的随机认证密钥、独立短生命
周期进程和超时；删掉的是请求体内对同一随机值的再次回显。

Runtime 2 仍可读取 Runtime 1.x 已写入的上述辅助字段，并在读取时校验旧摘要；新记录不再
输出这些字段。旧评论摘要引用、条件摘要引用和旧审批签名继续按原有语义解析，因此升级
Runtime 不要求重写 Canonical Git 历史。

## 判断原则

新增摘要或签名之前，需要先指出它跨越的真实边界、要阻止的具体失败，以及 Git 历史、事务、主键、类型和普通测试为什么不足。若信息只在同一 Git tree 内重复出现，优先使用资源 UID、Git 差异和明确引用。
