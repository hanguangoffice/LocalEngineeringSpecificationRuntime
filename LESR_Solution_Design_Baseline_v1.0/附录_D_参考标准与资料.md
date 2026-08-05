# 附录 D：参考标准与资料

## 1. MCP

- Stable specification: 2025-11-25  
  https://modelcontextprotocol.io/specification/2025-11-25
- 2026-07-28 release candidate / evolving revision  
  https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/
- Tools  
  https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- Roadmap  
  https://modelcontextprotocol.io/development/roadmap

LESR 结论：领域能力与 MCP SDK/修订解耦；新协议能力只作为增强。

## 2. JSON Schema

- Draft 2020-12  
  https://json-schema.org/draft/2020-12
- Specification index  
  https://json-schema.org/specification

用途：结构 Schema、接口 Schema、Profile 元数据。它不单独承担关系、流程和 Authority 规则。

## 3. SHACL

- SHACL Recommendation  
  https://www.w3.org/TR/shacl/
- SHACL 1.2 Core  
  https://www.w3.org/TR/shacl12-core/
- SHACL 1.2 Rules  
  https://www.w3.org/TR/shacl12-rules/
- SHACL 1.2 Profiling  
  https://www.w3.org/TR/shacl12-profiling/

用途：作为 RDF 图约束和规则后端候选。是否进入实现由 P2 原型决定。

## 4. OSLC

- OSLC Requirements Management 2.1  
  https://www.oasis-open.org/standard/oslc-requirements-management-version-2-1-oasis-standard/
- OSLC RM Part 1  
  https://docs.oasis-open.org/oslc-domains/oslc-rm/v2.1/cs01/part1-requirements-management-spec/oslc-rm-v2.1-cs01-part1-requirements-management-spec.html
- OSLC RM Vocabulary  
  https://docs.oasis-open.org/oslc-domains/oslc-rm/v2.1/cs01/part2-requirements-management-vocab/oslc-rm-v2.1-cs01-part2-requirements-management-vocab.html
- OSLC Quality Management 2.1  
  https://www.oasis-open.org/standard/oslc-qm-2-1/
- OSLC Architecture Management 2.1  
  https://docs.oasis-open.org/oslc-domains/oslc-am/v2.1/cs01/part1-architecture-management-spec/oslc-am-v2.1-cs01-part1-architecture-management-spec.html

用途：资源身份、生命周期链接和互操作边界；不要求早期实现完整服务端。

## 5. ReqIF

- OMG ReqIF  
  https://www.omg.org/reqif/

用途：传统需求工具交换边界。

## 6. SARIF

- OASIS SARIF 2.1.0  
  https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html

用途：外部静态分析 Observation 导入。

## 7. Provenance

- W3C PROV-O  
  https://www.w3.org/TR/prov-o/

用途：Entity–Activity–Agent 来源证明思想。

## 8. Git 与 SQLite

- Git Documentation  
  https://git-scm.com/docs
- SQLite FTS5  
  https://sqlite.org/fts5.html

用途：Git 权威状态和本地全文查询候选。

## 9. 使用原则

- 锁定正式版本；
- 草案和候选版只用于原型观察；
- 不复制商业标准全文；
- 内部模型不等同任何单一标准；
- 标准升级必须进入 Change 和影响分析。
