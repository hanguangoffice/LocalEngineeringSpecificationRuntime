# Local Engineering Specification Runtime（LESR）
## 本地工程规范运行时——Codex 实现规格

> 本文档用于直接交给 Codex 新会话，作为项目实现的主规格。  
> 实现过程中应优先保证：结构清晰、接口稳定、可测试、可扩展、数据可审计。  
> 不要把项目扩张成完整的企业级 ALM 平台，也不要优先开发复杂图形界面。

---

## 0. Codex 执行指令

你现在需要实现一个名为 **Local Engineering Specification Runtime，简称 LESR** 的本地工具。

LESR 的目标是把用户自定义的工程规范、流程规范、需求、设计、测试、代码规则和变更规则，转化为 AI 可以精确查询、受控修改和自动校验的本地工程系统。

请遵循以下原则：

1. 先阅读本文档全部内容，再生成实施计划。
2. 先完成 MVP，不得在核心能力完成前开发复杂前端。
3. 所有核心能力必须有自动化测试。
4. 所有数据修改必须可审计。
5. AI 不应直接依赖文件系统全文 grep 作为主要检索方式。
6. AI 不应直接覆盖正式规范文件，而应通过领域接口提出或执行受控变更。
7. 规范内容由用户提供，系统负责结构化、索引、关联、校验和暴露接口。
8. ASPICE、MISRA、项目规范等应以可插拔 Profile 形式接入。
9. 核心数据应可被 Git 管理、人工阅读和独立导出。
10. 若本文档存在实现细节冲突，以“数据安全、可追踪、MVP 简洁”为优先级。

---

# 1. 项目背景

传统工程规范通常以 Markdown、Word、Excel、PDF 或 ALM 工具条目存在。AI 在使用这些内容时，经常只能通过全文搜索、文件遍历或向量相似度读取零散片段，存在以下问题：

- AI 读取的是文本片段，而不是明确的工程对象；
- 需求、设计、测试和规则之间的关系难以可靠追踪；
- AI 无法区分草稿、已批准、已基线化和已废弃内容；
- 修改规范时缺少状态控制、影响分析和审计记录；
- 不同规范的结构不同，无法用单一需求表长期承载；
- 上下文容易过载，相关规范无法按当前任务精确组装；
- grep、全文读取和普通 RAG 难以表达规范优先级、约束关系和流程要求。

LESR 应作为一个本地工程规范运行时，为 AI 提供领域化接口。

---

# 2. 项目目标

LESR 必须实现以下核心目标。

## 2.1 结构化工程对象

将以下内容抽象为具有稳定 ID、类型、状态、版本、关系和元数据的对象：

- 需求；
- 架构；
- 详细设计；
- 接口定义；
- 编码规则；
- 测试规范；
- 测试结果；
- 静态分析发现；
- 偏离申请；
- 评审记录；
- 证据；
- 变更申请；
- 基线；
- 自定义工程规范。

## 2.2 精确查询

AI 应能通过稳定接口完成：

- 按 ID 查询；
- 按类型、模块、状态和标签筛选；
- 查询父子关系；
- 查询追踪链；
- 查询受某规则约束的对象；
- 查询某对象影响的设计、代码和测试；
- 查询当前生效版本；
- 查询历史版本；
- 查询缺失追踪关系；
- 查询冲突或未解决问题。

## 2.3 上下文组装

根据当前任务生成受控上下文包，减少无关内容，提高 AI 对关键规范的注意力。

示例任务：

- 修改某个 C 源文件；
- 新增软件需求；
- 执行需求变更影响分析；
- 审查接口设计；
- 检查 MISRA 偏离；
- 为某需求生成测试方案；
- 检查 ASPICE 风格追踪完整性。

## 2.4 受控写入

AI 应通过明确的领域工具完成写入，而不是任意修改正式文件。

写入必须支持：

- Schema 校验；
- 状态机校验；
- 关系合法性校验；
- 变更原因；
- 影响分析；
- 审计日志；
- 提案与批准分离；
- 基线保护；
- Git 友好存储。

## 2.5 多规范适配

系统必须支持不同规范 Profile，例如：

- ASPICE 风格流程与追踪；
- MISRA 风格代码规则、发现和偏离；
- 项目级编码规范；
- 接口规范；
- 软件架构规范；
- 测试规范；
- 家居物联网项目自定义规范；
- 未来的 AUTOSAR、CERT C、ISO 26262 风格配置。

---

# 3. 非目标

MVP 阶段不实现以下内容：

- 完整复刻 Codebeamer、DOORS 或 Polarion；
- 多租户云平台；
- 企业级组织权限系统；
- 复杂工作流设计器；
- 大型可视化图谱；
- 富文本在线协作编辑器；
- 实时多人协同；
- 完整 ASPICE 或 MISRA 标准内容；
- 商业标准文档的复制、分发或内置；
- 自动批准高风险变更；
- 无人工确认地修改已基线化对象。

---

# 4. 核心架构

LESR 推荐采用以下分层架构：

```text
┌──────────────────────────────────────────────┐
│ AI Client                                    │
│ Codex / Claude Code / Cursor / Other Agent   │
└──────────────────────┬───────────────────────┘
                       │ MCP
┌──────────────────────▼───────────────────────┐
│ LESR MCP Server                              │
│                                              │
│ Query Tools                                  │
│ Context Tools                                │
│ Change Tools                                 │
│ Validation Tools                             │
└──────────────┬────────────────┬──────────────┘
               │                │
┌──────────────▼───────┐  ┌─────▼──────────────┐
│ Domain Service       │  │ Retrieval Service  │
│                      │  │                    │
│ Artifact Service     │  │ Exact Lookup       │
│ Relation Service     │  │ SQLite FTS5        │
│ Workflow Service     │  │ Optional Vector    │
│ Change Service       │  │ Relation Expansion │
│ Baseline Service     │  │ Ranking            │
└──────────────┬───────┘  └─────┬──────────────┘
               │                │
┌──────────────▼────────────────▼──────────────┐
│ Local Storage                               │
│ SQLite Index + Git-managed YAML/Markdown    │
└─────────────────────────────────────────────┘
```

---

# 5. 技术栈

MVP 默认采用以下技术栈：

| 领域 | 技术 |
|---|---|
| 编程语言 | Python 3.12+ |
| 数据模型 | Pydantic v2 |
| 数据库 | SQLite |
| 全文检索 | SQLite FTS5 |
| 数据迁移 | Alembic 或轻量自定义迁移器 |
| CLI | Typer |
| MCP | 官方或主流 Python MCP SDK |
| 本地 API | FastAPI，可选但建议预留 |
| 配置格式 | YAML |
| Schema | JSON Schema |
| 测试 | pytest |
| 代码质量 | ruff、mypy |
| 包管理 | uv 或 Poetry，优先 uv |
| 版本管理 | Git |
| 日志 | Python logging + JSON 审计日志 |

MVP 不强制使用向量数据库。应先完成精确查询、全文检索和关系检索。

向量能力设计为可选插件：

- sqlite-vec；
- Qdrant Local；
- 其他实现 `EmbeddingProvider` 接口的后端。

---

# 6. 通用领域模型

系统内核只定义少量稳定概念。

## 6.1 Artifact

Artifact 表示任意工程对象。

基础字段：

```yaml
id: REQ-SW-0001
artifact_type: software_requirement
title: MQTT 断线重连
status: approved
version: 1
profile_ids:
  - aspice-lite
  - project-communication
tags:
  - mqtt
  - reconnect
  - availability
module: communication
owner: user
source_path: artifacts/requirements/software/REQ-SW-0001.yaml
content_hash: sha256-value
created_at: 2026-07-29T10:00:00Z
updated_at: 2026-07-29T10:00:00Z
```

Artifact 的规范正文和扩展属性：

```yaml
statement: >
  当 MQTT 连接意外断开时，系统应按照受控退避策略执行重连。

rationale: >
  防止频繁重连造成网络和服务端资源过载。

attributes:
  priority: high
  safety_level: QM
  verification_method: test
```

要求：

- `id` 全局唯一；
- `artifact_type` 由 Profile 定义；
- `status` 必须符合对应 Workflow；
- `attributes` 由 Profile Schema 校验；
- `source_path` 指向 Git 管理的源文件；
- 正式对象不可仅存在于 SQLite；
- SQLite 是索引和运行时数据库，YAML/Markdown 是可审阅事实源。

## 6.2 Relation

Relation 表示对象之间的有向关系。

```yaml
id: REL-000001
source_id: REQ-SW-0001
relation_type: derives_from
target_id: REQ-SYS-0004
status: active
rationale: >
  软件重连要求来源于系统离线恢复要求。
created_at: 2026-07-29T10:10:00Z
```

典型关系：

- `contains`
- `derives_from`
- `refines`
- `implements`
- `implemented_by`
- `verifies`
- `verified_by`
- `constrains`
- `constrained_by`
- `depends_on`
- `conflicts_with`
- `supersedes`
- `evidenced_by`
- `affects`
- `deviates_from`
- `generated_from`
- `applies_to`

关系是否合法由 Profile 定义。

## 6.3 Rule

Rule 是可执行或可解释的规范条目。

```yaml
id: RULE-C-0012
artifact_type: coding_rule
title: 禁止未受控的隐式窄化转换
status: approved
profile_ids:
  - project-coding-standard

attributes:
  severity: error
  category: required
  language: c

check:
  kind: external
  provider: clang_tidy_adapter
  rule_key: custom-narrowing-conversion

deviation:
  allowed: true
  workflow: deviation-workflow
```

Rule 可以是：

- 纯信息规则；
- 声明式校验规则；
- Python 插件校验规则；
- 外部工具映射规则；
- 流程规则；
- 上下文加载规则。

## 6.4 Evidence

Evidence 表示评审、测试、静态分析、批准记录等证据。

```yaml
id: EVD-TEST-0007
artifact_type: test_evidence
title: MQTT 重连测试结果
status: accepted

attributes:
  test_case_id: TEST-COM-0031
  result: passed
  execution_time: 2026-07-29T09:30:00Z
  tool: pytest
  attachment: evidence/test-results/mqtt-reconnect.xml
```

## 6.5 Finding

Finding 表示检查发现。

```yaml
id: FIND-000042
artifact_type: finding
title: 软件需求缺失验证关系
status: open

attributes:
  severity: error
  validator_id: traceability.required_verified_by
  affected_artifact_id: REQ-SW-0008
  message: Approved 软件需求必须关联至少一个测试规范。
```

## 6.6 Change

Change 表示受控变更。

```yaml
id: CHG-000015
artifact_type: change_request
title: 增加 MQTT 最大退避时间
status: proposed

attributes:
  reason: 当前需求未限制最大退避时间
  author: ai-agent
  target_ids:
    - REQ-SW-0001
  impact_analysis_required: true
```

## 6.7 Baseline

Baseline 表示一组冻结版本。

```yaml
id: BL-0.1
artifact_type: baseline
title: Home Control MVP Baseline
status: released

attributes:
  created_by: user
  created_at: 2026-07-29T11:00:00Z
  members:
    - artifact_id: REQ-SW-0001
      version: 1
    - artifact_id: ARCH-COM-0002
      version: 3
```

---

# 7. Profile 机制

## 7.1 设计原则

不同规范不能被强行塞入同一种固定表结构。

系统应采用：

```text
通用内核
+ 规范 Profile
+ 项目裁剪
+ 校验插件
+ 上下文策略
```

目录结构：

```text
profiles/
├─ aspice-lite/
├─ misra-like/
├─ project-coding-standard/
├─ software-architecture/
├─ interface-specification/
├─ testing/
└─ home-iot-custom/
```

每个 Profile 至少包含：

```text
profile.yaml
schemas/
relations.yaml
workflows.yaml
validators/
context-policy.yaml
templates/
```

可选包含：

```text
mcp-tools.yaml
adapters/
migrations/
README.md
```

## 7.2 profile.yaml

示例：

```yaml
id: aspice-lite
name: ASPICE-like Engineering Profile
version: 0.1.0
description: >
  用于个人或小型工程项目的需求、设计、测试、追踪和变更管理。

dependencies: []

artifact_types:
  - stakeholder_requirement
  - system_requirement
  - software_requirement
  - software_architecture
  - software_detailed_design
  - test_specification
  - test_result
  - review_record
  - change_request

default_workflow: engineering-artifact-workflow
```

## 7.3 Schema

每种 Artifact Type 可以定义扩展字段。

示例：

```yaml
artifact_type: software_requirement

required:
  - statement
  - rationale
  - attributes.priority

properties:
  statement:
    type: string
    minLength: 10

  rationale:
    type: string

  attributes:
    type: object
    properties:
      priority:
        enum:
          - low
          - medium
          - high
      verification_method:
        enum:
          - analysis
          - inspection
          - test
          - demonstration
```

Schema 应转换或兼容 JSON Schema。

## 7.4 Relation Policy

示例：

```yaml
relations:
  - type: derives_from
    source_types:
      - software_requirement
    target_types:
      - system_requirement
    min_count:
      approved: 1

  - type: verified_by
    source_types:
      - software_requirement
    target_types:
      - test_specification
    min_count:
      approved: 1
```

## 7.5 Workflow

示例：

```yaml
id: engineering-artifact-workflow

states:
  - draft
  - in_review
  - approved
  - baselined
  - deprecated

transitions:
  - from: draft
    to: in_review
    required_checks:
      - schema_valid

  - from: in_review
    to: approved
    required_checks:
      - schema_valid
      - required_relations_valid
      - no_blocking_findings

  - from: approved
    to: baselined
    requires_human_confirmation: true

  - from: baselined
    to: deprecated
    requires_change_request: true
```

## 7.6 Context Policy

示例：

```yaml
task_types:
  coding:
    mandatory:
      - direct_requirements
      - approved_design
      - interface_contracts
      - coding_rules
      - active_deviations
      - linked_tests

    optional:
      - related_decisions
      - historical_changes
      - similar_findings

    exclude:
      - deprecated
      - rejected

  requirement_change:
    mandatory:
      - parent_requirements
      - child_requirements
      - implementing_designs
      - linked_tests
      - active_baseline
      - change_policy
```

---

# 8. 项目级裁剪

项目配置目录：

```text
projects/
└─ home-control/
   ├─ project.yaml
   ├─ enabled-profiles.yaml
   ├─ tailoring.yaml
   ├─ terminology.yaml
   ├─ context-policy.yaml
   ├─ precedence.yaml
   └─ exceptions.yaml
```

示例：

```yaml
project:
  id: home-control
  name: Home Control Local Engineering Project
  version: 0.1.0

enabled_profiles:
  - aspice-lite
  - misra-like
  - software-architecture
  - interface-specification
  - home-iot-custom
```

裁剪示例：

```yaml
profiles:
  aspice-lite:
    disabled_artifact_types:
      - supplier_agreement
      - acquisition_process

  misra-like:
    enforcement:
      mandatory: error
      required: warning
      advisory: info
```

优先级示例：

```yaml
precedence:
  - approved_deviation
  - project_rule
  - safety_rule
  - industry_profile_rule
  - default_rule
```

---

# 9. 数据存储

## 9.1 Git 管理的事实源

推荐目录：

```text
repository/
├─ lesr.yaml
├─ profiles/
├─ projects/
├─ artifacts/
│  ├─ requirements/
│  ├─ architecture/
│  ├─ design/
│  ├─ interfaces/
│  ├─ rules/
│  ├─ tests/
│  ├─ evidence/
│  ├─ findings/
│  ├─ changes/
│  └─ baselines/
├─ relations/
├─ attachments/
├─ audit/
└─ .lesr/
   └─ index.db
```

要求：

- `.lesr/index.db` 可以重建；
- 正式工程数据不应只存在于数据库；
- 审计日志可以采用 JSONL；
- 文件名建议包含 Artifact ID；
- 每个 Artifact 单独存储，避免巨型文件；
- 正文较长时可采用 YAML front matter + Markdown body。

## 9.2 SQLite 表

MVP 至少包含：

```text
artifacts
artifact_versions
relations
profiles
workflows
changes
baselines
baseline_members
findings
audit_events
file_index
```

建议字段：

### artifacts

```text
id
artifact_type
title
status
current_version
module
owner
profile_ids_json
tags_json
source_path
content_text
attributes_json
content_hash
created_at
updated_at
```

### artifact_versions

```text
artifact_id
version
snapshot_json
content_hash
created_at
created_by
change_id
```

### relations

```text
id
source_id
relation_type
target_id
status
rationale
created_at
updated_at
```

### findings

```text
id
validator_id
artifact_id
severity
status
message
details_json
created_at
resolved_at
```

### audit_events

```text
id
timestamp
actor
operation
target_type
target_id
before_hash
after_hash
request_json
result_json
```

## 9.3 索引策略

至少建立以下索引：

- Artifact ID 唯一索引；
- artifact_type；
- status；
- module；
- source_path；
- relation source_id；
- relation target_id；
- relation_type；
- finding artifact_id；
- finding status；
- FTS5 title + content + tags。

---

# 10. 检索设计

检索优先级：

1. 精确 ID；
2. 结构化过滤；
3. 关系扩展；
4. FTS5；
5. 可选语义检索；
6. 排序与解释。

搜索结果必须返回命中原因。

示例：

```json
{
  "artifact_id": "REQ-SYS-0023",
  "score": 0.94,
  "reasons": [
    "title_keyword_match",
    "module_exact_match",
    "direct_relation_to_target_file",
    "approved_status_boost"
  ]
}
```

禁止只返回不透明的向量分数。

---

# 11. AI 上下文组装

## 11.1 输入

```json
{
  "task_type": "coding",
  "task": "修改 MQTT 断线重连逻辑",
  "target_files": [
    "src/communication/mqtt_client.c"
  ],
  "target_artifact_ids": [
    "DES-COM-0018"
  ],
  "token_budget": 12000
}
```

## 11.2 输出

```json
{
  "summary": "当前任务受 3 条强制规范、2 条接口约束和 1 条已批准偏离影响。",
  "must_read": [],
  "should_read": [],
  "reference": [],
  "conflicts": [],
  "missing_information": [],
  "selection_trace": []
}
```

每个上下文项包含：

```json
{
  "artifact_id": "RULE-COM-0004",
  "priority": "mandatory",
  "reason": "该规则直接约束 communication 模块",
  "content_excerpt": "……",
  "relation_path": [
    "src/communication/mqtt_client.c",
    "implements",
    "DES-COM-0018",
    "constrained_by",
    "RULE-COM-0004"
  ]
}
```

## 11.3 上下文分区

固定分区：

- `MUST_READ`
- `SHOULD_READ`
- `REFERENCE`
- `CONFLICTS`
- `MISSING_INFORMATION`
- `ACTIVE_DEVIATIONS`
- `VALIDATION_REQUIREMENTS`

## 11.4 Token Budget

上下文组装器必须：

- 优先保留强制规范；
- 优先保留直接关系；
- 优先保留 approved 和 baselined 内容；
- 对长内容生成受控摘要；
- 保留 Artifact ID 和原始路径；
- 不得用摘要替代必须逐字遵循的关键规则；
- 输出被省略内容的列表；
- 输出选择原因。

---

# 12. MCP 工具定义

MCP Server 应优先暴露领域工具，不暴露任意 SQL。

## 12.1 查询工具

### `get_artifact`

输入：

```json
{
  "id": "REQ-SW-0001",
  "include_relations": true,
  "include_history": false
}
```

### `list_artifacts`

输入：

```json
{
  "artifact_types": ["software_requirement"],
  "statuses": ["approved"],
  "modules": ["communication"],
  "tags": ["mqtt"],
  "limit": 50
}
```

### `search_artifacts`

输入：

```json
{
  "query": "断网后保持本地控制",
  "artifact_types": [],
  "statuses": ["approved", "baselined"],
  "modules": [],
  "limit": 20
}
```

### `get_related_artifacts`

输入：

```json
{
  "id": "REQ-SW-0001",
  "relation_types": ["derives_from", "verified_by", "implemented_by"],
  "direction": "both",
  "depth": 2
}
```

### `get_traceability_chain`

输入：

```json
{
  "id": "REQ-SW-0001",
  "direction": "both",
  "max_depth": 5
}
```

### `get_effective_rules`

输入：

```json
{
  "artifact_id": "DES-COM-0018",
  "task_type": "coding"
}
```

## 12.2 上下文工具

### `build_task_context`

输入：

```json
{
  "task_type": "coding",
  "task": "修改 MQTT 重连策略",
  "target_files": ["src/communication/mqtt_client.c"],
  "target_artifact_ids": ["DES-COM-0018"],
  "token_budget": 12000
}
```

### `explain_context_selection`

输入：

```json
{
  "context_request_id": "CTX-000012"
}
```

## 12.3 变更工具

### `create_change_request`

### `propose_artifact`

### `propose_artifact_update`

### `propose_relation`

### `withdraw_change`

### `apply_change`

`apply_change` 默认要求人工确认。

输入应包含：

```json
{
  "change_id": "CHG-000015",
  "confirmed_by": "user"
}
```

## 12.4 校验工具

### `validate_artifact`

### `validate_change`

### `check_traceability`

### `check_profile_compliance`

### `check_impact`

### `list_open_findings`

### `resolve_finding`

## 12.5 基线工具

### `create_baseline`

### `get_baseline`

### `compare_baselines`

### `list_baseline_members`

创建基线必须要求人工确认。

---

# 13. CLI

CLI 命令建议：

```text
lesr init
lesr index
lesr validate
lesr serve-mcp
lesr serve-api
lesr artifact get
lesr artifact list
lesr artifact create
lesr relation add
lesr search
lesr context build
lesr change create
lesr change validate
lesr change apply
lesr baseline create
lesr baseline compare
lesr profile list
lesr profile validate
lesr doctor
```

示例：

```bash
lesr init --project home-control
lesr index
lesr validate --all
lesr serve-mcp
```

`lesr doctor` 应检查：

- Python 环境；
- SQLite FTS5；
- 配置完整性；
- Profile 依赖；
- Schema；
- 文件路径；
- 数据库是否需要重建；
- 重复 ID；
- 无效引用；
- MCP 服务可用性。

---

# 14. 写入与变更规则

## 14.1 普通草稿对象

允许直接创建，但仍需：

- Schema 校验；
- ID 唯一性校验；
- 审计记录；
- 版本记录。

## 14.2 Approved 对象

修改时必须：

- 创建 Change Request；
- 记录原因；
- 运行影响分析；
- 生成差异；
- 重新校验关系；
- 人工确认后应用。

## 14.3 Baselined 对象

修改时必须：

- 创建 Change Request；
- 标识受影响 Baseline；
- 生成新版本；
- 不覆盖旧版本；
- 人工批准；
- 生成审计事件。

## 14.4 AI 权限

MVP 中，AI 默认允许：

- 查询；
- 搜索；
- 组装上下文；
- 创建草稿；
- 提出变更；
- 提出关系；
- 运行校验；
- 生成影响分析。

AI 默认不允许：

- 自动批准；
- 自动建立正式基线；
- 删除历史版本；
- 静默解决冲突；
- 静默忽略强制校验；
- 直接覆盖已批准或已基线对象。

---

# 15. 校验框架

校验器接口：

```python
class Validator(Protocol):
    id: str

    def validate(
        self,
        artifact: Artifact,
        repository: Repository,
        context: ValidationContext,
    ) -> list[Finding]:
        ...
```

支持三类校验器。

## 15.1 声明式校验

适合：

- 必填字段；
- 枚举；
- 长度；
- 状态；
- 必须关系；
- 禁止关系；
- 数量约束；
- Profile 适用范围。

## 15.2 Python 插件校验

适合：

- 跨对象一致性；
- 复杂追踪；
- 版本兼容性；
- 变更影响；
- 自定义工程逻辑。

## 15.3 外部工具适配器

适合：

- clang-tidy；
- cppcheck；
- PC-lint；
- Polyspace；
- Coverity；
- pytest；
- CMake；
- CANoe；
- Excel Dataset 检查器。

所有外部结果统一转换为：

- Finding；
- Evidence；
- Relation；
- Audit Event。

---

# 16. 规范适配示例

## 16.1 ASPICE-like Profile

关注：

- 工作产品；
- 状态；
- 双向追踪；
- 需求到设计；
- 设计到测试；
- 变更影响；
- 评审证据；
- 基线。

示例校验：

- Approved 软件需求必须有上游来源；
- Approved 软件需求必须有关联设计；
- Approved 软件需求必须有关联测试规范；
- 需求变更必须分析下游对象；
- 测试结果必须对应特定需求版本；
- 基线成员不可被静默覆盖。

## 16.2 MISRA-like Profile

关注：

- 规则等级；
- 适用语言；
- 静态分析发现；
- 偏离申请；
- 偏离理由；
- 风险分析；
- 批准状态；
- 代码位置。

注意：

- 不得在仓库中内置或复制受版权保护的 MISRA 标准全文；
- Profile 只提供数据结构、接口和示例占位规则；
- 用户自行提供其合法持有的规则摘要、规则 ID 和项目解释；
- 系统可以关联外部标准引用，但不负责分发标准内容。

## 16.3 自定义项目 Profile

适合：

- 家居物联网架构规范；
- RK3566 中控约束；
- ESP32/STM32 节点规范；
- MQTT Topic 规则；
- 离线可用性；
- 模块边界；
- 日志规则；
- 故障降级；
- 配置管理；
- 测试要求。

---

# 17. API 设计原则

即使 MVP 主要使用 MCP，也应将领域逻辑与 MCP 传输层分离。

推荐模块：

```text
lesr/
├─ domain/
├─ services/
├─ repositories/
├─ profiles/
├─ validators/
├─ retrieval/
├─ context/
├─ changes/
├─ baselines/
├─ audit/
├─ cli/
├─ mcp/
└─ api/
```

MCP 工具只调用 Service，不直接操作数据库。

禁止：

- MCP Handler 中写 SQL；
- CLI 中复制业务逻辑；
- Validator 直接修改 Artifact；
- 数据库模型泄漏到外部接口；
- 写操作绕过审计服务。

---

# 18. 推荐仓库结构

```text
lesr/
├─ pyproject.toml
├─ README.md
├─ LICENSE
├─ CHANGELOG.md
├─ docs/
│  ├─ architecture.md
│  ├─ profile-authoring.md
│  ├─ mcp-tools.md
│  └─ examples.md
├─ src/
│  └─ lesr/
│     ├─ __init__.py
│     ├─ config.py
│     ├─ domain/
│     ├─ services/
│     ├─ repositories/
│     ├─ storage/
│     ├─ profiles/
│     ├─ workflows/
│     ├─ validators/
│     ├─ retrieval/
│     ├─ context/
│     ├─ changes/
│     ├─ baselines/
│     ├─ audit/
│     ├─ cli/
│     ├─ mcp/
│     └─ api/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ fixtures/
│  └─ e2e/
├─ examples/
│  └─ home-control/
├─ built_in_profiles/
│  ├─ core/
│  ├─ aspice-lite/
│  └─ misra-like/
└─ scripts/
```

---

# 19. MVP 范围

MVP 必须完成以下内容。

## 19.1 必须实现

- 项目初始化；
- YAML Artifact；
- Relation；
- Profile 加载；
- JSON Schema 校验；
- Workflow 状态检查；
- SQLite 索引；
- FTS5 搜索；
- 关系查询；
- 追踪链；
- 基础上下文组装；
- 变更提案；
- 审计日志；
- Artifact 历史版本；
- 基线冻结；
- CLI；
- MCP Server；
- 单元测试；
- 集成测试；
- 示例项目；
- 基础文档。

## 19.2 可延后

- 向量检索；
- Web UI；
- 图数据库；
- 复杂权限；
- 多用户；
- 外部静态分析工具；
- 自动 Git commit；
- 图形追踪矩阵；
- VS Code 插件。

---

# 20. 实施阶段

## Phase 0：工程骨架

交付：

- Python 项目；
- uv 配置；
- ruff；
- mypy；
- pytest；
- CI；
- 基础包结构；
- README。

## Phase 1：领域模型与文件存储

交付：

- Artifact；
- Relation；
- Finding；
- Change；
- Baseline；
- YAML 读写；
- ID 校验；
- 哈希；
- 版本快照。

## Phase 2：Profile 与校验

交付：

- Profile Loader；
- Schema；
- Relation Policy；
- Workflow；
- 声明式校验器；
- Findings。

## Phase 3：SQLite 索引与查询

交付：

- 数据库迁移；
- 索引构建；
- 增量更新；
- FTS5；
- 结构化筛选；
- 关系查询；
- 追踪链。

## Phase 4：变更与基线

交付：

- Change Request；
- Patch；
- Diff；
- 影响分析基础版；
- 人工确认；
- Baseline；
- Audit。

## Phase 5：上下文组装

交付：

- task_type；
- Context Policy；
- mandatory/optional/reference；
- token budget；
- selection trace；
- conflict 输出。

## Phase 6：MCP

交付：

- 查询工具；
- 上下文工具；
- 变更工具；
- 校验工具；
- 基线工具；
- MCP 示例配置。

## Phase 7：示例 Profile 和项目

交付：

- aspice-lite；
- misra-like；
- home-control；
- 示例 Artifact；
- 示例关系；
- 示例变更；
- 示例基线；
- 演示脚本。

---

# 21. 验收标准

## 21.1 初始化

执行：

```bash
lesr init --project demo
```

结果：

- 创建完整目录；
- 创建默认配置；
- 创建 core Profile；
- 创建 SQLite 数据库；
- 可重复执行且不破坏已有数据。

## 21.2 索引

执行：

```bash
lesr index
```

结果：

- 所有 Artifact 被索引；
- 重复 ID 被报告；
- 无效 Schema 被报告；
- 无效 Relation 被报告；
- 数据库可删除后重建。

## 21.3 精确查询

执行：

```bash
lesr artifact get REQ-SW-0001
```

结果：

- 返回 Artifact；
- 返回状态和版本；
- 返回关联关系；
- 返回源文件路径；
- 返回 Profile。

## 21.4 搜索

执行：

```bash
lesr search "MQTT 断线重连"
```

结果：

- 返回相关 Artifact；
- 返回命中原因；
- 支持状态和类型过滤；
- Approved 结果可获得适当优先级。

## 21.5 追踪检查

执行：

```bash
lesr validate --scope module:communication
```

结果：

- 缺失上游需求被发现；
- 缺失测试关系被发现；
- 无效引用被发现；
- Findings 可查询。

## 21.6 上下文组装

输入编码任务后，系统应返回：

- 强制规范；
- 直接需求；
- 设计；
- 接口；
- 适用规则；
- 活跃偏离；
- 测试；
- 冲突；
- 选择原因；
- 被省略内容。

## 21.7 受控变更

对 approved 对象调用直接更新时：

- 系统拒绝；
- 建议创建 Change Request。

创建并确认 Change Request 后：

- 新版本生成；
- 旧版本保留；
- 审计事件生成；
- 相关索引更新；
- 受影响 Baseline 被报告。

## 21.8 MCP

AI 客户端可以通过 MCP：

- 查询 Artifact；
- 搜索；
- 获取追踪链；
- 构建上下文；
- 提出变更；
- 运行校验；
- 查询 Findings。

---

# 22. 测试要求

至少覆盖：

## 单元测试

- ID 生成与校验；
- Artifact Schema；
- Relation Policy；
- Workflow；
- Profile Loader；
- Context Ranking；
- Token Budget；
- Audit；
- Patch；
- Baseline。

## 集成测试

- YAML → SQLite；
- SQLite → Query；
- Change → Apply → Version；
- Baseline → Change Impact；
- Profile → Validation；
- MCP → Service。

## 端到端测试

场景一：

```text
创建系统需求
→ 创建软件需求
→ 建立 derives_from
→ 创建测试规范
→ 建立 verified_by
→ 校验通过
```

场景二：

```text
Approved 需求直接修改
→ 被拒绝
→ 创建 Change Request
→ 生成影响分析
→ 人工确认
→ 新版本生成
→ 审计完整
```

场景三：

```text
修改 C 文件任务
→ build_task_context
→ 返回设计、接口、编码规则、偏离和测试
```

---

# 23. 错误处理

错误必须使用稳定错误码。

示例：

```text
LESR-ARTIFACT-NOT-FOUND
LESR-DUPLICATE-ID
LESR-SCHEMA-INVALID
LESR-RELATION-INVALID
LESR-WORKFLOW-TRANSITION-DENIED
LESR-BASELINE-PROTECTED
LESR-CHANGE-REQUIRED
LESR-PROFILE-LOAD-FAILED
LESR-CONTEXT-BUDGET-EXCEEDED
LESR-HUMAN-CONFIRMATION-REQUIRED
```

错误响应应包含：

```json
{
  "code": "LESR-CHANGE-REQUIRED",
  "message": "Approved Artifact 不允许直接修改。",
  "details": {
    "artifact_id": "REQ-SW-0001",
    "status": "approved"
  },
  "suggested_action": {
    "tool": "create_change_request"
  }
}
```

---

# 24. 安全与可靠性

MVP 至少做到：

- 不执行 Profile 中的任意未信任代码；
- Python Validator 插件需要显式启用；
- 文件路径必须限制在项目根目录；
- 防止路径穿越；
- 写入采用临时文件 + 原子替换；
- 写入前备份或生成版本快照；
- MCP 写工具默认保守；
- 高风险动作要求人工确认；
- 审计日志不可由普通写接口删除；
- 敏感配置不写入仓库；
- 外部命令适配器默认禁用 shell；
- 对外部命令使用参数列表，不拼接命令字符串。

---

# 25. 性能目标

面向个人和小型项目，MVP 目标：

- 10,000 个 Artifact 以内；
- 100,000 条 Relation 以内；
- 精确 ID 查询低于 100 ms；
- 普通结构化搜索低于 500 ms；
- FTS 搜索低于 1 s；
- 深度 3 的关系查询低于 1 s；
- 全量索引可以接受数秒至数十秒；
- 增量索引优先。

不为百万级数据提前优化。

---

# 26. 可观测性

日志分类：

- application log；
- audit log；
- validation log；
- MCP request log。

每次上下文构建应生成：

- request_id；
- 任务类型；
- 输入目标；
- 选中的 Artifact；
- 选择原因；
- 排除原因；
- token 估算；
- 执行耗时。

---

# 27. 后续扩展方向

核心稳定后，可以考虑：

- sqlite-vec；
- Qdrant Local；
- 本地图形界面；
- 追踪矩阵；
- 图谱浏览；
- VS Code 扩展；
- Git hook；
- 自动静态分析导入；
- CANoe 测试结果适配；
- Excel Dataset 适配；
- Codebeamer 导出导入；
- OSLC 风格 REST 资源；
- 项目模板市场；
- 规范差异比较；
- AI 自动提出关联；
- 人工审查队列。

---

# 28. Codex 首次执行输出要求

在开始编码前，请先输出：

1. 对需求的理解；
2. MVP 边界；
3. 关键架构决策；
4. 目录结构；
5. 数据模型；
6. Phase 0～Phase 3 的具体任务；
7. 风险清单；
8. 需要保持兼容的接口；
9. 第一批自动化测试；
10. 准备创建的文件列表。

随后直接开始实现 Phase 0 和 Phase 1。

不要等待用户再次确认，除非遇到以下情况：

- 工作目录中已有同名项目且可能被覆盖；
- 当前环境缺少必要写权限；
- 发现本文档内部存在无法同时满足的硬冲突；
- 必须接触用户未授权的外部系统。

---

# 29. 第一版完成定义

第一版可被认为完成，必须同时满足：

- 能初始化项目；
- 能保存和索引 Artifact；
- 能定义和加载 Profile；
- 能执行 Schema、Relation 和 Workflow 校验；
- 能进行结构化搜索和 FTS 搜索；
- 能查询追踪关系；
- 能生成任务上下文；
- 能提出和应用受控变更；
- 能建立和比较 Baseline；
- 能通过 MCP 被 Codex 类 AI 调用；
- 有完整自动化测试；
- 有一个可运行的 home-control 示例项目；
- SQLite 可以删除并从源文件重建；
- Approved 和 Baselined 对象不会被静默覆盖；
- 每个写操作都有审计记录。

---

# 30. 最终原则

LESR 的核心价值不在于生成规范，而在于把用户已有规范转化为：

- 可寻址对象；
- 可查询关系；
- 可执行规则；
- 可控流程；
- 可审计变更；
- 可解释上下文；
- AI 可调用接口。

实现时应始终优先保证：

```text
稳定 ID
> 结构化关系
> 受控写入
> 校验
> 上下文选择
> 语义检索
> 图形界面
```

不要让 UI、向量数据库或复杂工作流抢占核心数据模型和接口设计的优先级。
