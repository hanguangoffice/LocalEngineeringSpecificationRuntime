# LESR v1.0 最终验收追踪矩阵

本矩阵把新版基线 `19_最终方案验收清单.md` 映射到已冻结施工决策和实现验收。
“规格关闭”表示不再留给实现者选择；以下证据已迁入长期实现测试。远端双平台 CI
和 Codex 实机探测在本 PR 推送后记录，合并仍由人工评审决定。

| 组 | 规格关闭 | 长期实现证据 | 状态 |
|---|---|---|---|
| A 定位 | Git 必需；Profile 决定严格度；Markdown/DB 不是事实源 | `test_v1_e2e.py`、`test_v1_markdown.py` | 本地通过 |
| B 对象 | UUIDv7、Logical/Revision、Fragment/Field 和 lineage 已冻结 | `test_v1_semantic.py`、基线 shape 合成数据集 | 本地通过 |
| C 关系 | 独立 relation revision、四类 Binding、formal credit 判定已冻结 | relation binding/formal trace/提议关系测试 | 本地通过 |
| D 规则 | 封闭 AST、三值逻辑、单位/Path/Aggregate、冲突与 Fixture 已冻结 | `test_v1_rules.py` 八类 fixture 与受限投影测试 | 本地通过 |
| E 配置上下文 | 显式 Evaluation Context、解析优先级、Mandatory/Completeness 已冻结 | `test_v1_context.py` 五类任务、预算和 stale exclusion | 本地通过 |
| F 变更审批 | Workspace、Checkpoint Ref、Review Package、Ed25519、CAS Apply 已冻结 | Review Package 操作绑定、篡改/撤销/过期/Base 冲突测试 | 本地通过 |
| G 权威状态 | canonical ref/tree、Applied Change、Baseline、Projection 重建已冻结 | `test_v1_git.py` fault injection、幂等、reconciliation、rebuild | 本地通过 |
| H 来源安全 | Actor/AI/Tool 分离、Delegation、签名、prompt 内容无授权能力 | AI 自批、Prompt Injection 替换、路径逃逸、Schema 验证测试 | 本地通过 |
| I 原型准入 | P1～P5 已通过；P5 采用获批客户端替代；原型代码可删除 | 正式测试已迁移；`prototypes/` 实现已删除，报告保留 | 本地通过 |

最终切换 PR 只有在本表“长期实现证据”全部提供、双平台 CI 通过并完成 Codex 实机探测后
才可由人工评审合并。P6 和 Claude Code deferred 状态必须保持显式。
