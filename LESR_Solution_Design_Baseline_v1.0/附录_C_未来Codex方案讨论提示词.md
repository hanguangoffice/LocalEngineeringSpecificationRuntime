# 附录 C：未来 Codex 原型评审提示词

```text
你参与 LESR Solution Design Baseline v1.0 的原型评审。

当前已经结束开放式方案扩展，进入可删除原型阶段。不要直接生成完整生产工程，不要提前冻结数据库、语言、UI、MCP SDK 或最终文件格式。

必须先阅读：
- README.md
- 17_方案设计基线总结与原型准入.md
- 04A_顶层语义类别与Facet能力模型.md
- 04B_对象粒度Fragment与提升机制.md
- 04C_身份命名空间别名与血缘模型.md
- 05B_RuleExpression元模型.md
- 05C_Applicability表达式与三值逻辑.md
- 05D_ConstraintAST类型单位路径与聚合.md
- 05E_权威例外偏离与规则冲突解析.md
- 05F_RuleCompiler解释映射与测试夹具.md
- 09D_EvaluationContext配置与EffectiveResolution.md
- 09E_ReviewPackage评审意见与批准模型.md
- 09F_生命周期事件与状态投影.md
- 10A_CanonicalState快照变更记录与Git权威.md
- 10B_语义事务原子性Merge与Rebase.md
- 14_原型实验计划.md
- 19_最终方案验收清单.md

任务：
1. 选择一个原型 P1～P5；
2. 明确该原型要验证的假设；
3. 只实现最小实验；
4. 提供对照方案和测量指标；
5. 标记所有可删除代码；
6. 不改变已接受领域语义；
7. 若发现语义矛盾，先形成设计缺陷报告，不自行重写基线；
8. 输出实验结果、失败模式和推荐决策。

禁止：
- 直接开发完整 UI；
- 创建万能 Artifact 表；
- 让 AI 直接写 Approved 状态；
- 用 Git Commit 代替 Revision；
- 使用模糊 current；
- 让查询数据库成为唯一事实源；
- 把原型技术自动升级为最终技术。
```
