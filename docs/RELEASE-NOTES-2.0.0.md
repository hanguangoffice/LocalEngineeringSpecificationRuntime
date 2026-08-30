# LESR Runtime 2.0.0

Runtime 2.0 将默认产品路径从逐项操作工作区改为 Mission 驱动的本地 AI 工程控制平面。
Canonical Format 继续使用 1.0；升级 Runtime 不会改写既有工程事实。

## 主要变化

- 自然语言目标和用户自带 Markdown/PDF 规范进入同一个需求入口。
- 固定上游模板与当前 Profile 生成工程地图和真实工程区域。
- 接受需求后自动建立 Mission、Mandate、Work Package 依赖图和可编辑工作区。
- 专业代理通过统一任务契约领取、校验、汇报和交接工作。
- 决策路由使用工作区校验、影响和任务范围派生 AUTO、BATCH、HUMAN 或 BLOCK；调用方不能自报风险等级。
- 普通编辑、上下文整理、校验、修复和无冲突工作不再逐步请求人工批准。
- 人工界面集中呈现工程取舍、影响、建议和备选；UID、Commit、Hash 与 Delegation 保留在审计详情。
- 工程地图、任务和决策成为一级工作面；低层工作区、评审和维护能力保留为辅助工具。
- 删除资源内部重复的辅助摘要链，保留 Git CAS、正式人类签名以及跨边界评审和来源摘要。

## 兼容性

- Python 包和默认 Web/MCP 交互升级为 2.0.0。
- Canonical Format、Schema Catalog 和既有 Git 权威状态保持 1.0。
- Runtime 1.x 已保存的辅助摘要字段保持只读兼容；Runtime 2 读取并校验，但新记录不再写入。
- 1.0/1.2 的细粒度 CLI 能力仍可用于维护和适配器开发，但不再代表普通用户流程。
- Mission、Agent Run 和 Decision Request 位于本地运行数据库，不写入 Canonical Git。

## 使用入口

```powershell
.venv\Scripts\python.exe -m lesr.cli.main web PROJECT
```

终端显示一次性本机地址。打开后可直接描述目标或导入已有规范。
