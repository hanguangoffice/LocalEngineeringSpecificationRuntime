# 05B Rule Expression 元模型

**决策成熟度：FOUNDATIONAL**

## 1. 四类资源必须分离

### Rule Definition

用户批准的规范定义，属于 Governed Object。

### Evaluation Run

某次执行规则求值的 Activity Record。

### Observation

不可变检查结果。

### Enforcement Decision

结合 Observation、Operation、Authority、Exception、Deviation 和配置得到的操作决策。

---

## 2. Rule Revision 的组成

```text
Identity
Authoritative Statement
Interpretation Note
Target Selector
Applicability Expression
Normative Modality
Constraint AST
Evaluation Specification
Enforcement Mapping
Authority Declaration
Exception Policy
Deviation Policy
Explanation Map
Test Fixtures
Provenance
```

这些内容共同版本化。若只修改机器表达而不修改原文，仍然产生新 Rule Revision。

---

## 3. Authoritative Statement

保存用户认可的原始规范文本。它必须：

- 可由人阅读；
- 具有语言标识；
- 保留来源引用；
- 与机器表达一同评审；
- 不被编译器自动重写。

机器 AST 是对原文的执行解释，不宣称自动替代原文。

---

## 4. Target Selector

规则目标可以是：

- Governed Object；
- Immutable Record；
- Relation Assertion；
- Change Workspace；
- Configuration Snapshot；
- Activity；
- Operation；
- Presentation/Export；
- 外部映射对象。

Target Selector 返回候选 Target Set，不直接判断适用性。

---

## 5. Normative Modality

核心集合：

```text
OBLIGATION
PROHIBITION
PERMISSION
RECOMMENDATION
DISCOURAGEMENT
INFORMATIONAL
```

模态表示规范含义，不直接表示是否阻断操作。

---

## 6. Evaluation Specification

```text
DECLARATIVE
REGISTERED_VALIDATOR
EXTERNAL_TOOL
HUMAN_ATTESTATION
AI_SEMANTIC
COMPOSITE
```

AI_SEMANTIC 默认只能产生 Advisory Observation。用户若赋予更高门禁作用，必须明确模型能力、上下文、置信门槛和人工复核条件。

---

## 7. Enforcement Mapping

按 Operation 映射：

```text
ALLOW
ALLOW_WITH_OBSERVATION
REQUIRE_ACKNOWLEDGEMENT
REQUIRE_REVIEW
REQUIRE_DEVIATION
BLOCK_OPERATION
```

示例：

```text
edit_draft            → ALLOW_WITH_OBSERVATION
submit_review         → REQUIRE_REVIEW
approve_revision      → BLOCK_OPERATION
create_baseline       → BLOCK_OPERATION
```

---

## 8. Rule Evaluation Outcome

封闭集合：

```text
PASS
FAIL
NOT_APPLICABLE
INDETERMINATE
SUPPRESSED_BY_DEVIATION
EVALUATOR_ERROR
NOT_EVALUATED
```

任何未知、缺失或执行器异常都不得折叠为 PASS。

---

## 9. Rule AST 顶层结构

概念结构：

```text
RuleAST {
  target
  applicability
  modality
  constraint
  evaluation
  enforcement
  authority
  exception_policy
  deviation_policy
}
```

Rule AST 不允许任意代码节点。扩展执行通过注册 Validator 引用。

---

## 10. Rule Revision 有效性

Rule Revision 只有在以下条件满足时才能进入 Approved：

- 原文存在；
- AST 通过 Schema 和类型检查；
- 所有符号可解析；
- Authority 明确；
- Enforcement 对关键操作无缺口，或 Profile 有明确默认；
- Test Fixtures 通过；
- 无未解决编译冲突；
- 必要 Reviewer 完成评审。

---

## 11. 当前决策

- 原文与 AST 共同治理；
- Rule AST 是封闭、可版本化、可解释结构；
- 模态与执行后果分离；
- Evaluation 与 Enforcement 分离；
- Profile 不携带任意执行代码；
- 规则执行必须能追溯到准确 Rule Revision 和 Effective Model。
