# 示例 03：CAN Signal 接口规则

## 原文

每个 CAN Signal 必须定义数据长度、Factor、Offset、Unit、物理范围、无效值和超时行为。

## 结构解释

字段类约束：

```text
required(length)
required(factor)
required(offset)
required(unit)
required(physical_min)
required(physical_max)
required(invalid_value)
required(timeout_behavior_relation)
```

一致性约束：

```text
physical_min <= physical_max
raw_range + factor + offset 能覆盖物理范围
invalid_value 不得落入正常有效编码，除非显式声明
timeout_behavior_relation target kind = interface_behavior
```
