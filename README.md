# LESR Runtime 2.0.0

Local Engineering Specification Runtime（LESR）是面向单个本地 Git 工程的 **AI
工程控制平面**。用户给出目标、已有规范和验收要求；LESR 把它们组织成可查看的工程
结构，为专业代理准备上下文、分配工作包、验证结果并管理正式发布边界。它不是要求用户
逐项维护对象和逐步点击批准的本地 ALM 复刻。

Git commit tree 保存正式工程状态，SQLite/FTS5 只是可重建的查询视图。需求权威仍是
`LESR_Solution_Design_Baseline_v1.0/`。当前 Python 包版本为 `2.0.0`，Canonical
Format 仍为 `1.0`；历史 1.0 Gate 是当时的验证记录，不自动证明当前工作版本已经发布。
版本含义见 [`docs/versioning.md`](docs/versioning.md)。

## 产品工作方式

一次工作从 Mission 开始。LESR 根据自然语言需求或导入的自定义规范选择固定版本的
上游模板，结合项目 Profile 建立工程地图，再把目标拆成有依赖关系的工作包。需求、
架构、实现、验证、证据和交付物由不同代理处理，控制平面负责上下文、工作区、校验、
影响分析、合并与恢复。

工程地图的栏目由 Profile 和模板决定：ASPICE-like 工程可以显示 SYS、SWE、SUP；
通用软件工程可以显示目标、需求、架构、实现、验证和发布；API、数据科学、嵌入式等
方向使用各自的名称。栏目下面展示真实工程内容、关系、覆盖情况和当前变化，不把内部
UID、Hash 或 Git 引用当作导航。

后台决策路由分为四种结果：自动继续、汇总到里程碑、立即请求人工决定、阻止当前方案。
普通编辑、上下文收集、校验、测试、修复、检查点和无冲突合并不会逐步请求批准。人工
只处理会改变材料工程取舍或验收结果的分歧，以及 Profile 明确指定的正式基线、发布、
偏离和例外责任。

完整产品契约见
[`docs/AGENTIC-PRODUCT-CONTRACT.md`](docs/AGENTIC-PRODUCT-CONTRACT.md)，工程状态
与签名边界见 [`docs/integrity-boundaries.md`](docs/integrity-boundaries.md)。

## 开发验证入口

```powershell
py -m uv sync --all-extras
py -m uv run python scripts/verify_baseline_manifest.py
py -m uv run python scripts/verify_construction_schemas.py
py -m uv run pytest
py -m uv run ruff check .
py -m uv run mypy src
py -m uv build --wheel --sdist --out-dir release-dist
py -m uv run python scripts/verify_distribution.py release-dist
```

这些命令是当前仓库的验证入口。某个版本是否已通过，以该次实际执行结果和发布记录为准。
中型和大型性能协议见 `docs/performance/README.md`。

## 普通用户：从网页开始

在 LESR 工程中运行（空工程也可以）：

```powershell
lesr web PROJECT
```

如果是在源码工程内使用，则运行：

```powershell
.venv\Scripts\python.exe -m lesr.cli.main web PROJECT
```

终端会显示一个本机地址。打开后可以直接描述目标，也可以导入自己的 Markdown 或 PDF
规范。LESR 从固定上游版本中组合 GitHub Spec Kit、arc42、OpenAPI、AsyncAPI、
Cookiecutter Data Science、TensorFlow Model Card、NASA FRET、OWASP Threat Model
Library 和 MADR 等结构，再建立可浏览的工程地图。

进入已有工程后，用户主要看到当前 Mission、工程地图、代理工作进展、待处理的材料
取舍和版本结果。系统用可读的内容名称和工程区域解释变化；内部标识集中在审计详情。
具体操作见 [`docs/USER-GUIDE.md`](docs/USER-GUIDE.md)。

模板来源、精确提交、许可证和 `grill-me` 行为选取记录见
[`docs/zero-spec-intake-sources.md`](docs/zero-spec-intake-sources.md)。

## 工程维护与适配器入口

```powershell
lesr init PROJECT
lesr bootstrap-plan PROJECT TRUST.json DELEGATION.json --governance-operation RULE.json --governance-operation PROFILE.json
lesr bootstrap-root PROJECT TRUST.json DELEGATION.json APPROVAL.json KEY --governance-operation RULE.json --governance-operation PROFILE.json
lesr configuration-plan PROJECT CONFIGURATION.json
lesr configuration-init PROJECT CONFIGURATION.json APPROVAL.json ACTOR_UID DELEGATION_UID KEY
lesr configuration-create-plan PROJECT CONFIGURATION.json --supporting-approval GOVERNANCE_APPROVAL.json
lesr governance-approval-record PROJECT GOVERNANCE_APPROVAL.json ACTOR_UID DELEGATION_UID KEY
lesr configuration-create PROJECT CONFIGURATION.json APPROVAL.json ACTOR_UID DELEGATION_UID KEY --supporting-approval GOVERNANCE_APPROVAL.json
lesr capabilities
lesr intake analyze REQUEST.txt --project-name PROJECT_NAME
lesr intake verify-sources
lesr resolve PROJECT IDENTIFIER
lesr inspect PROJECT UID
lesr query PROJECT --kind software_requirement --text reconnect
lesr context build PROJECT TASK CONFIGURATION_UID ACTOR_UID EVALUATION_TIME --target UID
lesr workspace open PROJECT CONFIGURATION_UID DELEGATION_UID ACTOR_UID IDEMPOTENCY_KEY
lesr workspace propose PROJECT WORKSPACE_UID BASE ACTOR_UID DELEGATION_UID KEY operation.json
lesr review-package PROJECT WORKSPACE_UID BASE CONFIGURATION_UID ACTOR_UID DELEGATION_UID KEY EVALUATION_TIME
lesr approval keygen ACTOR_UID "Reviewer" --role technical
lesr approval sign TRUST.json PACKAGE.json technical
lesr apply PROJECT WORKSPACE_UID BASE ACTOR_UID DELEGATION_UID KEY PACKAGE_UID APPROVAL.json EVALUATION_TIME
lesr baseline prepare PROJECT WORKSPACE_UID BASE CONFIGURATION_UID ACTOR_UID DELEGATION_UID KEY EVALUATION_TIME
lesr baseline apply PROJECT WORKSPACE_UID BASE PACKAGE_UID ACTOR_UID DELEGATION_UID KEY EVALUATION_TIME APPROVAL.json
lesr projection rebuild PROJECT
lesr mcp serve PROJECT
lesr web PROJECT
```

这些命令暴露控制平面的细粒度能力，供维护、适配器开发和审计复现使用，不是普通用户要
手工走完的流程。Mission 协调器和代理运行器组合这些能力；本机引导、配置解析、上下文、
工作区和恢复由后台处理。偏离、例外、规则冲突以及正式发布责任仍按 Profile 进入治理。
候选和评审材料在 Apply 前保存在可恢复的 Workspace ref 中。MCP 不提供私钥签名；迁移、
恢复和清理等管理能力留在本机 CLI 或维护界面。

本地 Web 适配器监听 `127.0.0.1`，使用一次性启动入口、会话锁定和短生命周期签名进程。
Windows 私钥由 DPAPI 保护；Linux 优先使用 Secret Service；回退方案使用加密 PKCS#8。
Web、CLI 与 MCP 复用同一领域能力。仓库包含 HTTP、浏览器和 Git/SQLite 事务路径的测试；
当前工作版本的实际结论以对应测试运行和发布记录为准。

## Compatibility and deferred scope

Canonical Format 1.0 不迁移 0.5 Canonical State、Workspace、YAML、CLI 或 MCP 契约。
Runtime 2.0 的 Mission 与工程地图改变默认交互方式，但不要求把运行中的代理任务写入
Canonical Git。ReqIF、SARIF、Excel、Codebeamer、OSLC、OCR、中文专用分词、通用插件
沙箱、SHACL/Rego、多仓库和多用户服务仍在当前范围之外。

Local rights-cleared Markdown/PDF import produces reviewable Workspace candidates with
provenance. Restricted source documents and extracted standards text are not committed.
