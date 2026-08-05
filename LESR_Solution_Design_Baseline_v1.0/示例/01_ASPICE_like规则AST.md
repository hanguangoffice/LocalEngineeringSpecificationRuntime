# 示例 01：ASPICE-like 追踪规则

## 原文

Approved 软件需求必须至少有一个上游系统需求，并至少有一个能够计入正式追踪的验证关系。

## 结构解释

```text
Target:
  Kind = software_requirement

Applicability:
  revision_maturity = approved

Modality:
  OBLIGATION

Constraint:
  ALL_OF
    relation_count(REFINES, target=system_requirement, min=1)
    relation_count(VERIFIES, formal_trace_credit=true, min=1)

Evaluation:
  DECLARATIVE

Enforcement:
  edit_draft       ALLOW_WITH_OBSERVATION
  approve_revision BLOCK_OPERATION
  create_baseline  BLOCK_OPERATION
```

## Fixture

- Approved、上下游齐全 → PASS；
- Draft、无关系 → NOT_APPLICABLE；
- Approved、缺上游 → FAIL；
- Maturity 未知 → INDETERMINATE；
- 只有 Proposed Relation → FAIL；
- 存在有效 Deviation 且规则允许 → SUPPRESSED_BY_DEVIATION。
