# LESR Runtime 1.2.0

Local Engineering Specification Runtime (LESR) is a local, single-user semantic
runtime for governed engineering specifications. Git commit trees are the authority;
SQLite/FTS5 is a disposable projection. The requirements authority is
`LESR_Solution_Design_Baseline_v1.0/`, while
`docs/LESR_Codex_Construction_Spec_v1.0.md` freezes the implementation contract.

This is the stable local runtime. Architecture validation, feature implementation,
integration, and release qualification are reported separately in `docs/gates/`. The
recovery point for the previous runtime is `runtime-0.5.0a2`.

## Runtime model

The 1.0 runtime separates Logical Objects, immutable Revisions and Records,
versioned Relation Assertions, exact Profile/Workflow/Relation Type revisions,
configuration-bound Graph Snapshots, typed rules, Working Copies, reviewed Candidate
Revisions, signed approvals, atomic semantic transactions, and Baselines.

There is no implicit `current`: evaluation requires an exact Configuration, Effective
Model, Canonical Commit, and Evaluation Time. External endpoints are never resolved
over the network during evaluation. Candidate Apply recomputes governance and rule
validation at the Git transaction boundary before an expected-old-value ref update.

## Development and release gates

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

CI runs on Python 3.12 for Windows and Ubuntu. It verifies the 81-entry baseline
Manifest, all construction schemas, deterministic serialization, the fixed small
performance dataset, HTTP/Playwright UI flow, and isolated wheel/sdist installation.
The medium and large performance protocols are fixed in `docs/performance/README.md`.

## 普通用户：从网页开始

在 LESR 工程中运行（空工程也可以）：

```powershell
lesr web PROJECT
```

如果是在源码工程内使用，则运行：

```powershell
.venv\Scripts\python.exe -m lesr.cli.main web PROJECT
```

终端会显示一个本机地址。复制到浏览器打开后，进入“从需求开始”：可以直接粘贴自然语言需求，也可以导入自己的 Markdown 或 PDF 规范文件。LESR 会从固定上游版本中选择适合当前方向的模板组合：通用需求使用 GitHub Spec Kit，架构、API、消息、数据科学、模型说明、嵌入式实时需求、安全威胁模型和架构决策分别采用 arc42、OpenAPI、AsyncAPI、Cookiecutter Data Science、TensorFlow Model Card、NASA FRET、OWASP Threat Model Library 与 MADR。运行策略、本机身份和初始配置在后台完成；只有会改变产品范围或预期结果、且无法从已有内容判断的选择才会交给用户。

已有规范的日常工作只需要：

1. 用 Human Key 或关键词查找工程内容；
2. 按名称选择工程配置和本机身份；
3. 填写 Human Key、内容和变更理由，检查影响与问题；
4. 批准人阅读变更范围、批准理由和校验结论后签名；
5. 将已批准变更写入工程，必要时再发布基线。

Commit、UID、Hash、Delegation UID 和原始协议返回不会出现在普通流程中。
只有审计或故障排查时才需要打开左侧的“审计详情”。页面使用更大的正文字号，
GSAP 动效只表达页面切换、流程推进、状态改变和确认反馈；系统偏好减少动态效果时，
所有状态仍会直接显示。

模板来源、精确提交、许可证和 `grill-me` 行为选取记录见
[`docs/zero-spec-intake-sources.md`](docs/zero-spec-intake-sources.md)。

## Advanced product entry points

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

`lesr init` creates the format-1.0 repository Manifest. The explicit bootstrap-plan /
bootstrap-root proof-of-possession flow installs the first human trust root and exact
Profile/Rule governance; configuration-plan / configuration-init then creates the first
Configuration. Successor Configurations are planned and human-approved explicitly;
Deviation, Exception, and Rule-conflict approvals are independently recorded before an
exact successor Configuration selects them. A missing 1.0 Manifest is rejected rather
than treated as a legacy repository. Workspace candidates and review evidence live on
recoverable Workspace refs before Apply, so separate CLI invocations can complete one
workflow. Private-key signing is never available through MCP. The MCP adapter
advertises only tools it actually exposes; admin maintenance remains CLI/local UI only.

The local Web adapter binds to `127.0.0.1`, has no CDN or runtime Node build, and uses a one-time launch
token, idle locking, Host/Origin/CSRF checks, and a short-lived signer broker. Windows
keys use DPAPI; Linux prefers Secret Service; the fallback is an scrypt/AES-GCM
encrypted PKCS#8 file and never plaintext. Its HTTP capability layer and engineering
console complete Context, Workspace Open/Edit/Submit/Rebase/Merge, conflict governance,
human signing, atomic Apply, and Baseline Prepare/Apply. The real Playwright product test
executes the full Edit -> Review -> Sign -> Apply -> Baseline path against Git and SQLite.
The packaged UI vendors GSAP Core 3.15.0 locally. Timelines visualize panel focus,
Workspace/Candidate progression, operation decisions, human governance and atomic Apply;
`prefers-reduced-motion` removes motion without hiding state or capability.

## Compatibility and deferred scope

This is a breaking upgrade. It does not migrate the 0.5 Canonical State, Workspace,
YAML, CLI, or MCP contracts. ReqIF, SARIF, Excel, Codebeamer, OSLC, OCR,
Chinese-specific tokenization, a general plugin sandbox, SHACL/Rego execution,
multi-repository operation, and multi-user service deployment remain deferred.

Local rights-cleared Markdown/PDF import produces reviewable Workspace candidates with
provenance. Restricted source documents and extracted standards text are not committed.
