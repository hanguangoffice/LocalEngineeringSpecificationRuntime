# 05D Constraint AST、类型、单位、路径与聚合

**决策成熟度：FOUNDATIONAL；函数与单位后端 PROVISIONAL**

## 1. 核心类型系统

建议最小类型：

```text
Boolean
Integer
Decimal
String
Enum
Date
DateTime
Duration
Quantity
URI
InternalUID
HumanKey
RevisionRef
FragmentRef
Path
List<T>
Set<T>
Map<K,V>
Record
```

不允许隐式把 String 当作 Number、Duration 或 Quantity。

---

## 2. Quantity

工程值必须支持：

```text
numeric value
unit
dimension
precision
tolerance
```

比较前执行受控单位转换。不同维度不可比较。

例如：

```text
120 s == 120000 ms
120 s != 120 mm
```

单位注册表属于 Effective Model 的一部分并进入版本哈希。

---

## 3. Path

Path 是对结构化语义字段的稳定引用，不是 JSON 文件路径。

示例：

```text
facet.interface.signal.unit
facet.lifecycle.maturity
fragment.acceptance_criteria[id=AC-02].expected
```

Profile 编译时 Path 必须解析到类型。

---

## 4. Constraint 节点族

### Field Constraint

- required；
- forbidden；
- type；
- enum；
- pattern；
- cardinality。

### Value Constraint

- compare；
- range；
- tolerance；
- set membership；
- uniqueness。

### Relation Constraint

- predicate；
- endpoint kind；
- binding；
- state；
- minimum/maximum；
- formal trace credit。

### Graph Path Constraint

- path expression；
- minimum/maximum depth；
- cycle policy；
- endpoint condition；
- binding rule。

### Lifecycle Constraint

- allowed transition；
- required approval；
- immutable after state；
- disposition rule。

### Process Constraint

- required Activity；
- order；
- actor separation；
- required Evidence；
- completion condition。

### Temporal Constraint

- before/after；
- freshness；
- interval overlap；
- expiration；
- revalidation trigger。

### Aggregate Constraint

- count；
- ratio；
- all/any/none；
- group by；
- threshold；
- completeness。

### External Result Constraint

- external rule mapping；
- accepted tool/version；
- result state；
- evidence freshness。

### Human/AI Attestation Constraint

- required role；
- checklist；
- model capability；
- confidence；
- human confirmation。

---

## 5. Quantifier

支持：

```text
EXISTS
FOR_ALL
NONE
COUNT
RATIO
```

所有量词必须有明确有限集合，不允许无界查询。

---

## 6. Relation Path

概念节点：

```text
STEP(predicate, direction, binding)
SEQUENCE
ALTERNATIVE
OPTIONAL
REPEAT(min,max)
FILTER
```

`REPEAT` 必须设置最大深度，防止无限遍历。

---

## 7. Aggregate 规则

聚合规则结果必须说明：

- Scope；
- Denominator；
- Excluded Items；
- Unknown Items；
- Threshold；
- Result。

未知对象不能静默从分母中消失，除非用户规则明确规定。

---

## 8. Constraint Evaluation

Constraint 返回：

```text
SATISFIED
VIOLATED
INDETERMINATE
EVALUATOR_ERROR
```

再映射为 Rule Evaluation Outcome。

---

## 9. 注册函数

允许有限、纯函数注册，例如：

```text
normalize_signal_name
compare_semantic_version
is_generated_code
```

注册函数必须：

- 有类型签名；
- 无副作用；
- 版本化；
- 显式启用；
- 可测试；
- 可超时；
- 不能拥有任意文件或网络权限。

---

## 10. 当前决策

- Rule AST 有静态类型；
- 单位是核心语义；
- Path 与序列化格式解耦；
- Relation Path 有界；
- Aggregate 明确处理 Unknown；
- 复杂能力通过注册纯函数或 Validator，不在 Profile 中嵌入代码。
