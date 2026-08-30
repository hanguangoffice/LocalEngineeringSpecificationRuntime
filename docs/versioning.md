# 版本叙述

LESR 同时出现三类版本，它们表达不同对象：

- **Runtime 版本**：Python 包和本地产品的版本。当前源码声明为 `2.0.0`。
- **Canonical Format / Schema 版本**：仓库中工程事实的持久格式。当前仍为 `1.0`，Runtime 升级不自动改写工程事实。
- **历史 Gate 与发布标签**：`docs/gates/`、RC 复核矩阵和 `runtime-v1.0.0` 记录当时版本的验收证据，不代表后续产品线已经完成同等发布验证。

`LESR_Codex_Construction_Spec_v1.0.md` 是 1.0 语义运行时的历史施工规格；`AGENTIC-PRODUCT-CONTRACT.md` 定义 2.0 产品线的交互契约。前者保留语义内核和 Git 权威边界的来历，后者把日常使用改为 Mission 与代理驱动。

源码中的 `2.0.0` 是当前工作版本标识。是否具备发布条件，以对应版本的测试结果、构建产物和发布记录为准，不能从版本字符串或历史 Gate 推断。
