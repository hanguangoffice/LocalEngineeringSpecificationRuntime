# 示例 02：MISRA-like 外部工具规则

## 原文

适用 C 模块不得存在规则 C-NARROW-01 的未解决违反；允许偏离，但必须完成技术理由、风险分析和批准。

## 结构解释

```text
Target:
  Kind = source_module

Applicability:
  language = C
  generated_code != true

Modality:
  PROHIBITION

Constraint:
  no_open_external_observation(rule_mapping=C-NARROW-01)

Evaluation:
  EXTERNAL_TOOL

Deviation:
  allowed
  requires rationale, risk, compensating_control, approver

Enforcement:
  edit_draft       ALLOW_WITH_OBSERVATION
  submit_review    REQUIRE_DEVIATION
  approve_revision BLOCK_OPERATION
```

External Tool suppression 只作为 Observation 属性，不等同批准 Deviation。
