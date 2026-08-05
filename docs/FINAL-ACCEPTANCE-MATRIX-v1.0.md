# LESR v1.0 最终验收追踪矩阵

本矩阵把新版基线 `19_最终方案验收清单.md` 映射到已冻结施工决策和实现验收。
“规格关闭”表示不再留给实现者选择；“实现证据”必须在长期切换 PR 中补齐。

| 组 | 规格关闭 | 实现证据 |
|---|---|---|
| A 定位 | Git 必需；Profile 决定严格度；Markdown/DB 不是事实源 | README、初始化和 canonical integrity E2E |
| B 对象 | UUIDv7、Logical/Revision、Fragment/Field 和 lineage 已冻结 | 不变量、promotion、split、consolidate 测试 |
| C 关系 | 独立 relation revision、四类 Binding、formal credit 判定已冻结 | 推断/提议关系不计正式追踪测试 |
| D 规则 | 封闭 AST、三值逻辑、单位/Path/Aggregate、冲突与 Fixture 已冻结 | 八类 fixture、类型/单位/冲突测试 |
| E 配置上下文 | 显式 Evaluation Context、解析优先级、Mandatory/Completeness 已冻结 | 五类任务零漏召回、零旧版混入测试 |
| F 变更审批 | Workspace、Checkpoint Ref、Review Package、Ed25519、CAS Apply 已冻结 | 篡改/撤销/Rebase/并发/原子性测试 |
| G 权威状态 | canonical ref/tree、Applied Change、Baseline、Projection 重建已冻结 | fault injection、reconciliation、rebuild 测试 |
| H 来源安全 | Actor/AI/Tool 分离、Delegation、签名、prompt 内容无授权能力 | AI 自批、注入、审计失败、路径逃逸测试 |
| I 原型准入 | P1～P5 已通过；P5 采用获批客户端替代；原型代码可删除 | 正式测试迁移后删除 `prototypes/` |

最终切换 PR 只有在本表“实现证据”全部提供、双平台 CI 通过并完成 Codex 实机探测后
才可由人工评审合并。P6 和 Claude Code deferred 状态必须保持显式。
