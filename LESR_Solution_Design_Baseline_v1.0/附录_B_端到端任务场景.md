# 附录 B：端到端任务场景

## 1. 一次授权连续完成 Draft

用户授权 communication 范围后，AI 连续创建和修改 Draft、提出 Relation、运行校验并修复。出现超范围 Interface 变更时暂停。最终提交 Review Package，用户批准后 Apply。

## 2. Finding 处置

工具产生 Observation，项目规则可创建 Issue。修复、Deviation 或误报处置后重新运行工具，产生新 Observation。旧 Observation 保留。

## 3. Fragment Promotion

Requirement Fragment 因 Variant 独立适用而提升为 Governed Object，建立 extracted_from，更新父对象并迁移正式 Relation。旧 Baseline 保持可解析。

## 4. Baseline

冻结 Object Revision、Relation Assertion Revision、Effective Profile、Tailoring、Deviation、Git Commit 和 Integrity Hash。Markdown 文档可从 Baseline 重建。
