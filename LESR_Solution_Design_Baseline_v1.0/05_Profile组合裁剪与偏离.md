# 05 Profile 组合、裁剪与偏离

**决策成熟度：FOUNDATIONAL；Profile 包格式 PROVISIONAL**

## 1. Profile 的职责

Profile 定义 Vocabulary、Kind、Facet 组合、Field Schema、Relation Type、Workflow、Rule、Applicability、Context Policy、Deviation Policy 和 Presentation Mapping。

Profile 不负责替项目选择“严格模式”。用户在 Profile 和项目规范中直接写出 Normative Effect。

---

## 2. Profile 层次

```text
Foundation
Domain
Industry-like
Organization
Project
Scope Configuration
Approved Deviation
```

下层可以扩展和收紧上层。放宽上层规则必须符合上层 Deviation Policy。

---

## 3. Kind 编译

1. 确定 Core Resource Class；
2. 合并必需 Facet；
3. 检查 Facet 兼容性；
4. 合并 Field Schema；
5. 合并 Relation Policy；
6. 合并 Workflow；
7. 解析 Rule；
8. 解析 Applicability；
9. 生成能力描述；
10. 生成来源轨迹。

若同一 Kind 被定义成不同 Core Class，属于不可自动解析冲突。

---

## 4. 组合操作

- extend；
- refine；
- replace；
- tailor；
- deviate。

加载顺序不能决定语义。

---

## 5. Normative Effect

用户规范至少定义：

```text
modality
enforcement
deviation_allowed
required_approval
applicability
evidence_required
```

冲突时必须返回规则、来源、作用域、强度、偏离可能性和所需裁决。

---

## 6. Effective Model

必须包含 Profile/版本、Tailoring、Scope、Active Deviation、Kind 能力、Effective Rule、Propagation Rule、冲突、编译哈希和来源轨迹。

Baseline 必须冻结该结果或足以确定性重建它的全部输入。

## 7. 规范语义

Modality、Enforcement、Deviation Policy、Criticality 和 Conflict 的详细模型见 `05A_规范模态执行后果与冲突模型.md`。

## 12. v1.0 Rule Expression 约束

Profile 必须通过 `05B`～`05F` 定义的 Rule Source 编译流程进入 Effective Model。Profile 不得通过加载顺序覆盖冲突，也不得默认携带任意可执行代码。

## 13. Effective Model 的配置依赖

Effective Model 必须在 Evaluation Context 中解析，记录 Profile、Tailoring、Authority、Exception、Deviation、Unit Registry、Function Registry 和编译器版本。
