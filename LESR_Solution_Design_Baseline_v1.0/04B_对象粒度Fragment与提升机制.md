# 04B 对象粒度、Fragment 与提升机制

**决策成熟度：FOUNDATIONAL；自动提升策略 PROVISIONAL**

## 1. 接受的层级

```text
Collection / View / Published Document
        │
Composite Governed Object
        │
Governed Atomic Object
        │
Addressable Fragment
        │
Typed Field
```

---

## 2. Governed Atomic Object 判定

强条件：

- 独立审批；
- 独立偏离；
- 不同适用范围；
- 独立生命周期；
- 稳定外部正式引用。

弱条件：

- 独立修改；
- 独立验证；
- 不同上游来源；
- 不同下游实现；
- 不同责任人；
- 不同变更频率。

---

## 3. Composite Object

- Organizing Composite：只分组；
- Normative Composite：父对象自身也是正式规范；
- Structural Composite：表示系统组成。

它们必须使用不同 Relation Type。

---

## 4. Addressable Fragment

Fragment：

- 有父 Revision；
- 有稳定局部 Key；
- 可以精确读取和注释；
- 与父对象共同版本化；
- 不具有独立 Workflow；
- 不默认进入 Baseline 成员清单；
- 不承担正式外部追踪。

示例：

```text
lesr://project/REQ-MQTT-002@3#acceptance/max_interval
```

---

## 5. Fragment Promotion

触发条件：

- 正式 Relation 需要指向它；
- 独立测试；
- 独立审批；
- 独立偏离；
- 不同 Applicability；
- 跨对象复用；
- 独立 Issue；
- 独立责任人。

流程：

```text
1. 打开 Change Workspace
2. 创建新 Logical ID
3. 转换 Fragment 内容
4. 建立 extracted_from
5. 更新父对象为引用或摘要
6. 迁移候选注释
7. 运行影响分析
8. Apply 后保留旧 Fragment 历史
```

---

## 6. 降级

Draft 且无正式外部 Relation 时可以重构。Approved/Baselined 对象不得删除 Logical ID，必须通过 superseded_by、merged_into 或归档保留历史。

---

## 7. 正式关系与 Fragment

正式工程关系默认只能指向 Governed Object 或准确 Revision。

精确注释、Evidence Location 和 Source Anchor 可以指向 Fragment。

若测试长期正式验证某 Fragment，应先提升。

---

## 8. 默认继承规则

任何 Composite Relation 默认不传播 State、Priority、Safety Level、Applicability、Approval、Deviation 和 Owner。

Profile 可定义派生传播，但必须：

- 不复制字段；
- 说明关系路径；
- 可解释；
- 发现冲突；
- 允许子对象显式覆盖时按规范裁决。
