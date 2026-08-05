# 05F Rule Compiler、解释映射与测试夹具

**决策成熟度：FOUNDATIONAL；编译器实现 PROVISIONAL**

## 1. 编译流水线

```text
Rule Source
→ Parse
→ Schema Validation
→ Symbol Resolution
→ Type Checking
→ Unit Checking
→ Applicability Normalization
→ Constraint Normalization
→ Authority Resolution
→ Conflict Analysis
→ Fixture Execution
→ Canonical Rule AST
→ Effective Model
```

---

## 2. Rule Source

Rule Source 可以来自：

- 本地 UI；
- 领域 API；
- AI 提案；
- Profile 包；
- 结构化导入；
- 受控自然语言辅助转换。

所有来源最终进入相同编译流程。

---

## 3. 自然语言辅助转换

AI 可以提出 AST 草案，但不能自动将其视为批准解释。

转换结果必须提供：

- 原文；
- AST；
- Interpretation Note；
- 未表达部分；
- 推断部分；
- 歧义；
- 示例；
- 需要用户决定的问题。

---

## 4. Explanation Map

将 AST 节点映射回原文片段或解释说明：

```text
AST node C-14
  来源：原文“至少一个验证用例”
  解释：relation_count minimum=1
```

这样评审者可以发现机器解释偏差。

---

## 5. Test Fixtures

每条可执行规则至少建议包含：

- positive；
- negative；
- not_applicable；
- indeterminate；
- exception；
- deviation；
- conflict；
- migration。

Fixture 固定：

- Input Resources；
- Evaluation Context；
- Expected Applicability；
- Expected Constraint Result；
- Expected Enforcement。

---

## 6. 编译诊断

```text
ERROR
    无法生成有效 AST

WARNING
    可编译，但存在未覆盖文本或弱解释

INFO
    规范说明或优化建议
```

典型错误：

- 未知 Kind；
- Path 不存在；
- 类型不兼容；
- 单位维度错误；
- 无界 Relation Path；
- Authority 循环；
- Enforcement 缺失；
- Fixture 失败；
- Exception 指向不存在规则。

---

## 7. Effective Model

Effective Model 是编译产物，包含：

- Profile 版本；
- Tailoring；
- Rule AST；
- Relation Type；
- Workflow；
- Unit Registry；
- Function Registry；
- Deviation；
- Authority Graph；
- Hash；
- Compilation Report。

它可缓存、可重建、可比较，不是用户直接编辑的事实源。

---

## 8. 版本兼容

Rule AST Schema、Profile Schema 和 Effective Model Schema 各自版本化。升级必须：

- 提供迁移器；
- 重跑 Fixture；
- 比较语义变化；
- 产生 Change；
- 重新批准必要规则。

---

## 9. 当前决策

- Rule Compiler 是独立逻辑组件；
- AI 只能生成待评审的 AST 草案；
- Explanation Map 必须存在；
- Fixture 是 Rule Revision 的一部分；
- Effective Model 带内容哈希和编译报告；
- 编译器版本进入 Provenance。
