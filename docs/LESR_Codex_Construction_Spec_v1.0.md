# LESR v1.0 Codex 工程施工规格

**状态：FINAL IMPLEMENTATION SPECIFICATION**

**需求权威：`LESR_Solution_Design_Baseline_v1.0/`**

**领域契约：`1.0`**

**Canonical Schema：`1.0`**

## 1. 目标与边界

LESR v1.0 是由 Git 支撑的本地工程语义运行时。用户 Profile 决定项目规则和
严格度；LESR 内核负责稳定身份、不可变版本、关系断言、规则编译、配置解析、
上下文完整性、受控变更、评审批准、来源证明和 AI 能力边界。

v1.0 不实现旧 YAML/CLI/MCP 兼容层、生产数据迁移、UI、P6 外部格式互操作、
通用插件市场、中文专用分词、SHACL/Rego 执行后端或任意 Profile 代码执行。
Markdown 仅是导入源和展示视图，不是权威语义状态。

## 2. 冻结技术选择

| 领域 | v1.0 选择 |
|---|---|
| 运行时 | Python 3.12，Pydantic v2 frozen/extra-forbid 模型 |
| UID | RFC 9562 UUIDv7，小写连字符形式；UID 永不复用 |
| Canonical Encoding | UTF-8、LF、排序键、无无意义空白的 JSON |
| 数值 | JSON integer 可直接使用；非整数语义量必须用十进制字符串和单位 |
| 时间 | UTC RFC 3339，写入形式必须以 `Z` 结尾 |
| Rule | LESR 自有封闭类型 AST，Draft 2020-12 JSON Schema，Profile 不执行代码 |
| Projection | SQLite + FTS5，可删除重建；不得拥有正式事实 |
| Git | 命令行 plumbing、临时 index、`commit-tree`、CAS `update-ref` |
| CLI/MCP | Typer 能力式 CLI；领域端口与 MCP 1.x 薄适配器分离 |
| Approval | 本地 Ed25519；私钥不进入工程仓库，公钥和角色进入 Canonical State |
| Provenance | LESR Canonical JSON；未来只提供 PROV 映射 |

实现依赖新增 `cryptography` 和 `platformdirs`。发布 wheel 必须通过 package resource
携带与仓库 `schemas/v1` 完全相同的 Schema bytes；CI 比较二者 Hash，禁止维护两份
可独立变化的 Schema 源。

Canonical JSON 不允许 JSON `number` 承担非整数工程量。数量表示为
`{"decimal":"1.25","unit":"ms"}`；编译器在 Hash 前拒绝 NaN、Infinity、
浮点值、非 UTC 时间、重复集合成员和未声明扩展字段。Hash 使用
`sha256:<lowercase hex>`，覆盖完整 Canonical bytes，不覆盖文件路径。
读取器拒绝未知 major schema version；同 major 的未知字段因为 `extra-forbid` 被拒绝，
必须先通过显式、可审计的 Schema migration 形成新 Revision/Record。

## 3. 权威状态与 Git 映射

### 3.1 引用

- `refs/heads/lesr/canonical`：唯一正式 Canonical State。
- `refs/lesr/workspaces/{workspace_uid}`：活动 Working Copy。
- `refs/lesr/checkpoints/{workspace_uid}/{checkpoint_uid}`：可恢复里程碑。
- Git Tag 可指向包含 Baseline Manifest 的 commit，但不能替代 Manifest。

每次正式 Apply 生成一个 Applied Change Record 和一个 canonical commit。
Checkpoint 只推进 workspace/checkpoint ref，不进入 canonical history。

### 3.2 Canonical Tree

```text
canonical/
  objects/{entity_uid}.json
  revisions/{revision_uid}.json
  relations/{assertion_uid}/identity.json
  relations/{assertion_uid}/revisions/{relation_revision_uid}.json
  records/{record_type}/{record_uid}.json
  profiles/{profile_uid}/revisions/{profile_revision_uid}.json
  configurations/{configuration_uid}.json
  baselines/{baseline_uid}.json
  applied_changes/{transaction_uid}.json
  trust/actors/{actor_uid}.json
  provenance/{provenance_uid}.json
  audit_anchors/{anchor_uid}.json
```

结构化文件的外部修改只能进入 Reconciliation Workspace。无法解析的路径被隔离；
高风险操作在 reconciliation、projection stale、audit failure 或 canonical integrity
failure 状态下停止。

### 3.3 原子 Apply

Apply 必须校验 Expected Base、Expected Revisions、Effective Model Hash、Delegation、
Review Package Hash、完整人类批准、阻塞 Finding、Configuration Closure 和幂等键。
所有操作在临时 Git index 构建候选 tree，校验 Snapshot 与 Applied Change 一致后
创建 commit，最后用带 expected-old-value 的 `update-ref` 推进 canonical ref。
Ref 推进是唯一权威切换点。投影失败只设置 stale；重复请求返回原 commit；同一
幂等键对应不同事务必须冲突。

## 4. 领域模型与不变量

- Logical Object、Revision、Relation Assertion/Revision、Immutable Record、Profile、
  Configuration、Baseline 和 Applied Change 使用 `schemas/v1` 中的精确契约。
- Revision 和 Record 永不原地修改；Maturity、Disposition、Membership 由有序的
  Immutable Record 投影。冲突或未知事件返回 `INDETERMINATE`。
- Human Key 可变化；Alias 具有有效期且同一 Evaluation Context 中不得活动歧义。
- Relation 是独立、可版本化资源。Logical、Pinned、Fragment、External Binding
  必须显式。Proposed/Inferred/Fragment Relation 不自动获得 Formal Trace Credit。
- Fragment Promotion、Split、Consolidate 必须生成新对象、准确 Relation Revision
  和 lineage records；旧 UID/Revision 继续可解析。

## 5. Rule、Configuration 与 Context

Rule Definition 同时固定原文、Source Hash、Canonical AST、Authority、Modality、
Enforcement 和八类 Fixtures。编译依次执行 Schema、符号、类型、单位、冲突、
Explanation Map 和 Fixture 检查。Applicability 使用三值逻辑；Unknown 不得变成
PASS 或 NOT_APPLICABLE。Permission 不自动覆盖 Prohibition；Exception、Tailoring、
Deviation 和外部 suppression 保持不同资源与结果。

所有 Effective Resolution 都接收显式 Evaluation Context。解析优先级为准确 Pin、
Workspace Candidate、Configuration Membership、Variant/Time、允许的低风险最新批准；
高风险操作禁止 latest fallback。缺失、冲突或歧义返回 `INDETERMINATE`。

Context Contract 固定 Invariant、Mandatory、Conditional、Supporting、Negative、
Deviation、Conflict、Unknown、Selection Trace、Omitted Candidates 和 Completeness。
Mandatory Read Set 只能由关系、规则、配置、操作和安全策略决定；FTS/向量结果只能
进入 Supporting。Token 不足时保留全部 Mandatory，并返回 `INCOMPLETE_BUDGET`。

## 6. Workspace、Review 与 Ed25519 Approval

Workspace 写入统一使用 Write Envelope：Workspace、Expected Base、Idempotency Key、
Actor、Delegation、Dry Run、Risk Class、Structured Operation。AI 只能在有效 Delegation
内编辑 Working Copy、运行校验、Checkpoint 和生成 Review Package。

Review Package 固定 Base/Candidate Revision、Relation/Disposition Change、Semantic
Diff、Impact、Validation、Finding、Effective Model、Evaluation Context、Required Roles
和 Package Hash。任何语义字段变化或 Rebase 都生成新 Package Hash，并使旧批准失效。

Ed25519 私钥通过 `platformdirs` 写入当前用户配置目录，文件权限采用平台允许的最严
模式，永不写入工程、日志、MCP 响应或 Context。Canonical trust record 保存公钥、
Actor UID、角色、有效期和撤销记录。签名消息为以下 UTF-8 bytes：

```text
LESR-APPROVAL-V1\n
package_hash\n
effective_model_hash\n
scope_hash\n
approval_type\n
expires_at_or_empty
```

Apply 同时验证签名、Actor/Role、Scope、有效期、撤销和 Reviewer Independence。
AI Principal 永远不能形成正式 Approval。MCP v1.0 不暴露 key generation 或 signing；
人类只通过交互式 CLI `approval keygen` 和 `approval sign` 完成签名。

## 7. Projection、CLI 与 MCP

`.lesr/projection.sqlite3` 被 Git 忽略。Projection metadata 至少记录 source commit、
projection schema version、completeness 和 build report；source commit 不匹配时查询
返回 stale 并建议 rebuild。精确 UID/Revision 查询和关系遍历优先，FTS 只作 Supporting。

CLI 固定命令组：`resolve`、`inspect`、`query`、`context`、`workspace`、
`review-package`、`approval`、`apply`、`baseline`、`projection`、`reconcile`、`mcp`。
不存在无上下文 `current`，也不存在直接 Artifact Patch。

领域能力分为 Resolve、Inspect、Query、Context、Workspace、Governance、Compliance。
MCP 提供 capability negotiation、Resources、分页和协议无关 `start/status/cancel/result`
长任务；不得暴露任意文件、SQL、Shell 或 Approval 私钥操作。领域代码不得导入 MCP SDK。

错误响应固定为：`code/category/message/affected_resources/rule_or_policy/retryable/`
`suggested_capability/correlation_id`。错误码发布后保持稳定。

## 8. 仓库结构与施工顺序

长期代码按 domain、application、ports、adapters、cli/mcp 分层。领域层只依赖标准库和
领域模型；Git、SQLite、Ed25519、Markdown、CLI、MCP 都通过端口接入。

施工顺序固定为：Canonical models/serialization → Rule compiler → Resolution/Context
→ Git transaction/workspace → Review/Approval → Projection → Application capabilities
→ CLI/MCP → examples/cleanup。每一步迁移对应原型不变量测试；全部迁移后删除旧 YAML
实现和 `prototypes/` 代码，保留 Gate 报告与合成数据的正式测试版本。

## 9. 交付门

- Windows/Ubuntu、Python 3.12：Manifest、Schema、pytest、Ruff、strict mypy 全通过。
- P1～P5 的全部不变量进入正式测试，不再依赖 prototype package。
- 五类 Context 场景 Mandatory 零漏召回、旧 Revision 零混入。
- Git fault injection、幂等、并发、重建、外部修改 reconciliation 全通过。
- Ed25519 篡改、撤销、过期、Rebase、AI 自批、Prompt Injection 测试全通过。
- CLI 和 MCP 完成 Resolve → Context → Workspace → Review → Human Sign → Apply →
  Baseline；Codex 实机重新完成只读和受控写能力探测。
- 示例使用新 Canonical State，包版本为 `1.0.0`，旧恢复标签继续有效。

## 10. 延期项

Claude Code 在其模型会话恢复后补测。P6、UI、中文专用分词、通用插件沙箱、
SHACL/Rego 执行和旧格式迁移只能作为 v1.0 之后的独立需求进入，不得阻塞或暗中扩大
本次施工范围。

## 11. 实现期勘误

`applied-change.schema.json` 不包含 `result_commit`。Applied Change 与结果 tree 同处一个
commit；让其内容包含该 commit 的对象 ID 会产生不可解的加密哈希自引用。权威结果 commit
由 `refs/heads/lesr/canonical` 的 CAS 推进和 Git parent 链确定，Applied Change 继续固定
Base、Transaction、Review Package、Effective Model、Operations、Approvals、Provenance 与
Audit Anchor。该勘误不降低任何追踪或恢复能力。
