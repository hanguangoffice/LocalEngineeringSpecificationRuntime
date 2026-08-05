# 05C Applicability 表达式与三值逻辑

**决策成熟度：FOUNDATIONAL**

## 1. 三值结果

```text
APPLICABLE
NOT_APPLICABLE
INDETERMINATE
```

缺少安全等级、Variant、Profile 或对象映射时，结果为 INDETERMINATE，不能自动判为不适用。

---

## 2. 表达式节点

### 布尔组合

```text
ALL_OF
ANY_OF
NOT
```

### 比较

```text
EQUAL
NOT_EQUAL
LESS_THAN
LESS_OR_EQUAL
GREATER_THAN
GREATER_OR_EQUAL
IN
CONTAINS
MATCHES
STARTS_WITH
ENDS_WITH
```

### 存在性

```text
EXISTS
ABSENT
KNOWN
UNKNOWN
```

### 类型与能力

```text
RESOURCE_CLASS_IS
KIND_IS
HAS_FACET
IMPLEMENTS_CAPABILITY
```

### 关系

```text
HAS_RELATION
RELATED_TO
REACHABLE_BY_PATH
```

### 配置

```text
IN_BASELINE
VARIANT_MATCHES
PROFILE_ENABLED
WORKSPACE_IS
OPERATION_IS
TIME_WITHIN
ACTOR_HAS_CAPABILITY
```

---

## 3. 引用来源

表达式可引用：

- Target 字段；
- Facet 字段；
- Relation；
- Evaluation Context；
- Configuration；
- Workspace；
- Operation；
- Actor；
- Environment；
- Current Effective Model。

表达式不能直接访问文件系统、网络或任意数据库查询。

---

## 4. Unknown 传播

### ALL_OF

- 任一 FALSE → NOT_APPLICABLE；
- 全 TRUE → APPLICABLE；
- 无 FALSE 且存在 UNKNOWN → INDETERMINATE。

### ANY_OF

- 任一 TRUE → APPLICABLE；
- 全 FALSE → NOT_APPLICABLE；
- 无 TRUE 且存在 UNKNOWN → INDETERMINATE。

### NOT

- TRUE ↔ FALSE；
- UNKNOWN 保持 UNKNOWN。

---

## 5. Null、Absent、Unknown 分离

```text
ABSENT
    字段不存在

NULL
    字段明确为空

UNKNOWN
    当前不能获得值

VALUE
    存在确定值
```

三者不能互换。

---

## 6. Scope Selector 与 Applicability 分离

Target Selector 决定“检查谁”；Applicability 决定“规则是否对该候选生效”。

这样可以解释：

```text
候选对象被选择，因为 Kind=software_requirement
规则不适用，因为 Revision Maturity=draft
```

---

## 7. INDETERMINATE 的后果

Applicability 只返回语义结果。实际后果由 Enforcement Mapping 和项目规范决定。

例如：

```text
edit_draft        → ALLOW_WITH_OBSERVATION
approve_revision  → BLOCK_OPERATION
```

LESR 不自行设置项目严格程度。

---

## 8. 确定性

Applicability Expression 必须：

- 无副作用；
- 有限求值；
- 不访问未声明外部资源；
- 使用固定类型和单位；
- 输出解释树；
- 记录输入值与来源；
- 在相同 Evaluation Context 下得到相同结果。

---

## 9. 解释输出

```text
RULE-COM-014 applicability = INDETERMINATE

ALL_OF:
  kind_is(source_module)                = TRUE
  language_equal(C)                     = TRUE
  safety_level_in(ASIL_B, ASIL_C)       = UNKNOWN
    reason: target lacks safety_level
```

---

## 10. 当前决策

- Applicability 使用三值逻辑；
- Unknown 传播遵循确定规则；
- Null、Absent、Unknown 分离；
- Target Selector 与 Applicability 分离；
- 适用性不直接执行写操作；
- 每次判断必须产生解释树。
