# CHANGELOG

## v1.0 — 方案设计基线

### 新增并接受

- Revision Maturity 与 Logical Object Disposition 由不可变 Lifecycle Record 投影；

- Rule Definition、Evaluation Run、Observation、Enforcement Decision 分离；
- Canonical Rule AST；
- Applicability 三值逻辑；
- 类型、单位、Path、Relation Path 和 Aggregate 语义；
- Authority、Tailoring、Exception、Deviation 和冲突解析；
- Rule Compiler、Explanation Map 和 Test Fixtures；
- Evaluation Context 和 Effective Resolution；
- Review Package、Review Comment 和 Approval Attestation；
- Git Commit Tree 权威 Canonical State；
- Snapshot + Applied Change Record；
- Semantic Transaction、幂等、原子 Apply、Merge/Rebase；
- Context Contract 完整性；
- MCP 领域能力解耦；
- 原型准入门和最终验收清单。

### 方案阶段结论

主要语义和逻辑架构已经收敛。下一步进入可删除原型，不继续无限扩展概念。


## v0.6

### 已接受决策

- Internal UID 与 Human Key 分离。
- Human Key 支持 Alias；身份和历史编号不得复用。
- Logical Object 与不可变 Revision 分离。
- Fragment 只有准确 Revision 内地址。
- Working Copy 与正式 Revision 分离。
- Approved Revision 与多个并行 Draft Candidate 可以共存。
- AI 连续编辑发生在 Workspace Working Copy 中。
- Workspace Checkpoint 必须可由 Git 恢复。
- 连续细粒度编辑不要求每步 Git Commit。
- 普通长期关系默认使用 Logical Binding。
- Approval、Evidence、Baseline 和执行结果默认使用 Pinned Revision Binding。
- Lifecycle 分为 Revision Maturity、Logical Object Disposition 和 Configuration Membership。
- Approved、Effective、Baselined 分离。
- 禁止使用无解析上下文的 current。
- Git、Audit 与 Provenance 三者分工。
- AI 生成者、用户授权者、评审者和批准者分别记录。
- 默认不保存模型隐藏推理。

### 新增文档

- `04C_身份命名空间别名与血缘模型.md`
- `08A_WorkingCopyRevision与GitCheckpoint.md`
- `09B_生命周期有效版本与配置解析.md`
- `09C_来源证明责任与审计模型.md`
- DD-011 至 DD-016。

### 下一阶段

- Rule Expression；
- Configuration Resolution；
- Review 与 Approval；
- Canonical State 与语义事务。


## v0.5

### 已接受决策

- 引入封闭的 Core Relation Role，Profile 定义具体 Relation Type。
- Relation Type 必须声明语义角色、端点约束、绑定方式、追踪贡献和生命周期规则。
- Relation Assertion 的 source、predicate、target、binding 和 scope 为身份承载字段；改变这些字段时创建新 Assertion，并退役旧 Assertion。
- 反向名称由 Relation Type 计算，不存储重复反向边。
- 正式追踪贡献必须显式声明，Inferred/Proposed/Fragment Relation 默认不计入正式追踪。
- 引入六种核心 Normative Modality：OBLIGATION、PROHIBITION、PERMISSION、RECOMMENDATION、DISCOURAGEMENT、INFORMATIONAL。
- Modality、Enforcement、Deviation Policy 和 Criticality 分离。
- Enforcement 按具体操作或状态转换定义，不使用全局 severity 决定阻断。
- 显式 Permission 只有在具有例外或授权关系时才能覆盖 Prohibition。
- 未解决规范冲突产生 INDETERMINATE Effective Model，高风险正式操作暂停。

### 新增文档

- `05A_规范模态执行后果与冲突模型.md`
- `09A_关系角色谓词与追踪语义.md`
- DD-009、DD-010。

## v0.4

### 已接受决策

- Git 从推荐项提升为必需基础设施。
- 删除 LESR 自带的宽松、普通、严格等项目模式。
- 规范强度、门禁和偏离完全由用户编写的 Profile 与项目规范定义。
- 引入 Scoped Delegation Session，允许 AI 在一次授权后连续修改限定范围内的 Draft。
- Markdown 降级为导入、导出、阅读视图和报告格式，不承担主要语义事实源职责。
- 接受复合对象、受治理原子对象、内嵌元素和字段四层粒度模型。
- 接受 Fragment Promotion。
- 接受封闭核心资源类别 + Facet 组合 + Profile Kind。
- Finding 拆分为 Observation 和 Issue。
- Relation Assertion 成为独立、可版本化、可基线化的一等资源。
- 正式追踪默认指向对象；Fragment 只用于精确注释和证据定位，需正式治理时应提升。
- 普通父子关系不自动传播属性，传播只能由 Profile 显式定义。
- Baseline 冻结对象 Revision、Relation Assertion Revision、Profile/Tailoring 和 Effective Model。

### 被否决或修正

- 否决“Markdown 作为主要事实源”的默认倾向。
- 否决由 LESR 自己决定项目严格程度。
- 否决用继承树不断增加 Requirement、Rule、Evidence 等内核基类。
- 否决把 Finding 既当不可变扫描结果又当可编辑工作项。
- 修正“文件优先语义运行时”名称，改称 Git 支撑的本地工程语义运行时。

### 仍待原型

- Canonical Semantic State 的序列化格式；
- Snapshot + Change Record 的权威关系；
- Rule Backend；
- Relation Binding 的具体存储表示；
- MCP 工具颗粒度；
- Git Commit 与 Applied Change 是否强制一对一；
- Profile 扩展 Facet 的限制；
- UI 的最小验证范围。
