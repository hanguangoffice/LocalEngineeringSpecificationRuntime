# 零规范接入：上游来源与复刻边界

## 结论

LESR 的零规范接入不让模型凭经验发明文档骨架。运行时只从固定的上游快照读取模板结构，用户原话作为独立内容映射；两者不会混写成一个无法追溯来源的“AI 模板”。

模板组合只负责选择适当的公开骨架：

| LESR 方案 | 原样采用的独立上游结构 |
|---|---|
| 通用软件产品与功能 | GitHub Spec Kit |
| 小工具、脚本与快速原型 | GitHub Spec Kit Lean |
| 平台、运行时与插件系统 | Spec Kit + arc42 + MADR |
| REST API 与服务集成 | Spec Kit + Swagger OpenAPI 3.1 + arc42 + MADR |
| 事件驱动、消息与 IoT 集成 | Spec Kit + AsyncAPI 3.1 + arc42 + MADR |
| 数据科学与机器学习 | Spec Kit + Cookiecutter Data Science + TensorFlow Model Card + MADR |
| 本地 AI、GPU 与模型应用 | Spec Kit + arc42 + Cookiecutter Data Science + TensorFlow Model Card + MADR |
| 嵌入式、实时与安全关键系统 | Spec Kit + arc42 + NASA FRET + MADR |
| 安全敏感与威胁建模 | Spec Kit + arc42 + OWASP Threat Model Library + MADR |

这些方案不再只是给同两套模板换场景名称。每个领域模板都对应本地保存的上游原文件，并由场景选择器实际加入该方案。通用需求模板仍负责用户场景和验收；领域模板分别负责 API、消息、数据、模型、实时需求、威胁模型或架构决策，不相互冒充。

## 固定来源

### GitHub Spec Kit

- Repository: <https://github.com/github/spec-kit>
- Commit: `59dc772b47b5d765ee8a920c3ccfd6dbac5bd1ec`
- License: MIT
- 本地保存：标准 Specification、Plan、Tasks 模板及 Lean 的 README 和 Specify 命令。

### arc42 中文模板

- Repository: <https://github.com/arc42/arc42-template>
- Commit: `8dff0d9b1f9640684df8c3bbcdc2ee45f989ca0f`
- License: CC BY-SA 4.0
- 本地保存：中文入口和第 1～12 章原始 AsciiDoc。
- LESR 没有删除、翻译或重写上游文件。由 arc42 模板衍生的模板内容遵守 CC BY-SA；用户填写的工程内容仍归用户自行决定授权，符合上游许可证说明。

### 领域专用模板

| 来源 | 固定版本 | 许可证 | LESR 用途 |
|---|---|---|---|
| [MADR](https://github.com/adr/madr) | `4.0.0` / `2475fe1973f66a12aaf58a91d8fa7b42c0f5ea3d` | CC0-1.0 OR MIT | 架构决策记录 |
| [Swagger Petstore](https://github.com/swagger-api/swagger-petstore) | `swagger-petstore-v31-1.0.10` / `a1019e6f46909dc9e37c15ffe04541d388d0f03d` | Apache-2.0 | OpenAPI 3.1 设计优先契约实例 |
| [AsyncAPI Specification](https://github.com/asyncapi/spec) | `v3.1.0` / `b3fac5bb522771428ea57b16129b273cd3ea0180` | Apache-2.0 | 异步消息契约 |
| [Cookiecutter Data Science](https://github.com/drivendataorg/cookiecutter-data-science) | `v2.3.0` / `0f6b163cdbe3918a2c65ab57ad9fefda93976d9e` | MIT | 数据科学工程结构 |
| [TensorFlow Model Card Toolkit](https://github.com/tensorflow/model-card-toolkit) | `v2.0.0` / `05474c8ccf259a9b229d33b98edfc2cbf28e1a8e` | Apache-2.0 | 模型用途、限制、数据和评估说明；上游已归档，因此固定在最后稳定版 |
| [OWASP Threat Model Library](https://github.com/OWASP/www-project-threat-model-library) | `v1.0.2` / `a3d9c0c5a8dbcbf50e7ce5ddedeb299418fa9b27` | MIT | 威胁模型 Schema 与完整实例 |
| [NASA FRET](https://github.com/NASA-SW-VnV/fret) | `v3.1.0` / `58db455be35182a015e607232d9f4e3c86731932` | Apache-2.0 | 状态、实时、边界、诊断等结构化需求 |

LESR 不执行这些上游模板中的 Jinja、JavaScript 或其他代码；它们作为只读规范结构使用。OpenAPI 和 OWASP 条目包含官方完整实例，是供系统提取字段结构与覆盖项的参考，不会把示例业务内容当成用户需求。

每个文件的字节数和 SHA-256 记录在 `src/lesr/intake/catalog.json`。这里使用校验值的具体原因是证明外部仓库在指定提交时的文件被逐字节纳入；LESR 自己的 Git 历史无法证明另一个仓库的历史内容。校验边界仅限第三方快照同步，不用于普通需求对象。

## `grill-me` 比对

实际下载并比对了两个公开实现：

1. `stevegsax/grill-me`，commit `a383d37b36d221f1d635ac7567d04ca5a565facb`。仓库没有许可证，因此不分发其文字或代码。
2. `matt-riley/agent-skills`，commit `b4cbef10b4f7e84210d1e4f9d696d25ac74699be`。`grill-me` 和 `reverse-prompt` 为 GPL-3.0，因此不把其原文或代码复制进 LESR 运行时。

选取并独立实现的行为如下：

| LESR 行为 | 上游原文位置 | 验证方式 |
|---|---|---|
| 能从代码、文档或工程目录确定的事实先调查，不询问用户 | `stevegsax/SKILL.md` “Do your homework first”；`interrogation-patterns.md` “When to explore instead of ask” | 已给工程路径时标记为已覆盖；未给时采用 greenfield 默认，不生成事实问题 |
| 只把产品决策交给用户 | `matt-riley/SKILL.md` Workflow 1；`interrogation-patterns.md` “one branch at a time” | 运行策略、授权细节和许可证调查不生成 intake 问题；`next_question` 只保留给会改变产品范围的选择 |
| 每个产品问题提供推荐答案 | `matt-riley/SKILL.md` Workflow 1 和 Guardrails | 存在产品范围问题时 `next_question.recommended_answer` 必填 |
| 后台处理运行边界 | `interrogation-patterns.md` “Resolve foundational concepts before dependent decisions” | 安装、下载、删除和系统修改采用运行时策略，不在建立草案前阻断用户 |
| 检查未声明假设、故障方式和依赖风险 | `stevegsax/SKILL.md` “Specific things to probe for” | 风险仍进入 Gap 记录和后续验证，但不转化为用户授权问答 |
| 请求足够完整时停止提问 | `interrogation-patterns.md` “When to stop” | 无阻断/未决项时 `next_question` 为 `null` |

没有采用：纯访谈而不执行、要求用户先命名 session、每次维护 `.grill.md` 文件、默认创建 CONTEXT/ADR、把所有不完整字段都变成问题。这些行为与 LESR“系统先完成可调查工作、普通用户只处理实质决定”的产品目标不一致。

## 运行时保证

- `IntakeCatalog.verify_vendored_sources()` 在分析前验证全部可分发上游文件。
- `IntakeService` 只复制用户原句到 Requirement Item，不以模型生成句子替换原文。
- Starter Document 从选中方案的主模板读取后仅替换主模板定义的占位符，并在末尾增加清晰标记的 `LESR Intake Mapping` 与所选领域模板清单。
- 场景选择结果必须准确列出实际采用的上游模板名称和用途；不得只返回一个 LESR 自创的场景名。
- arc42 的 12 个主章节标题直接从固定的 AsciiDoc 文件解析，不在 Python 中手写第二份章节清单。
- 对空仓库的“建立工程草案”自动建立本机身份、最小 Profile、Configuration 和可编辑 Workspace；运行边界由后端处理，不进入日常界面。

验证命令：

```powershell
uv run pytest tests/test_zero_spec_intake.py
uv run ruff check src tests
uv run mypy src
```
