# 11A MCP 领域能力契约与版本策略

**决策成熟度：PROVISIONAL**

## 1. 原则

MCP 是 AI 适配器，不是 LESR 领域模型。领域能力先定义，再映射到 MCP Resources、Tools、Tasks 或 UI 扩展。

---

## 2. 能力组

### Resolve

- 解析 Human Key、Alias、UID、URI、文件或外部 ID。

### Inspect

- 获取 Logical Object、Revision、Facet、Relation、Provenance。

### Query

- Filter；
- Search；
- Traverse；
- Compare；
- Explain。

### Context

- Build Context Contract；
- Expand Manifest；
- Explain Selection；
- Check Completeness。

### Workspace

- Open；
- Checkpoint；
- Propose Operation；
- Validate；
- Build Review Package；
- Rebase；
- Abort。

### Governance

- Review；
- Approve；
- Revoke；
- Apply；
- Create Baseline；
- Compare Baseline。

### Compliance

- Compile Profile；
- Evaluate Rule；
- Run Validation；
- List Observation/Issue；
- Explain Conflict。

---

## 3. Resource 候选

适合映射为只读 Resource：

- Logical Object URI；
- Revision URI；
- Context Bundle；
- Review Package；
- Baseline Manifest；
- Effective Model Report；
- Validation Report。

---

## 4. Tool 候选

适合映射为 Tool：

- search；
- traverse；
- build_context；
- open_workspace；
- propose_operation；
- checkpoint；
- validate_workspace；
- build_review_package；
- approve_package；
- apply_transaction；
- create_baseline。

具体工具名和颗粒度必须通过客户端原型验证。

---

## 5. 长任务

全量校验、导入和大范围影响分析可映射到 MCP Tasks 或其他异步能力，但领域层只暴露：

```text
start
status
cancel
result
```

协议扩展可选，不能成为唯一实现路径。

---

## 6. Tool Schema

每个写工具必须包括：

- idempotency key；
- workspace；
- expected base；
- actor/delegation；
- dry-run；
- structured operation；
- risk class；
- response explanation。

不能暴露任意 SQL、任意文件写或通用 shell。

---

## 7. 错误契约

```text
code
category
message
affected_resources
rule_or_policy
retryable
suggested_capability
correlation_id
```

---

## 8. 版本策略

- 领域契约独立版本；
- MCP Adapter 独立版本；
- 支持能力协商；
- 不依赖某个客户端私有扩展；
- 稳定协议和候选协议分开测试；
- 新 MCP 功能只作为增强，不改变核心语义。

---

## 9. 当前标准环境说明

截至本设计基线形成时，MCP 已有 2025-11-25 发布规范，同时 2026-07-28 版本处于新一轮候选/发布演进阶段。LESR 不应把领域核心绑定到单一协议修订。

---

## 10. 当前决策

- MCP 与领域层解耦；
- Resources 用于稳定只读资源；
- Tools 用于有副作用能力；
- 长任务有协议无关状态机；
- 不暴露底层存储；
- Tool Schema 必须支持幂等和并发检查；
- 最终工具颗粒度由原型决定。
