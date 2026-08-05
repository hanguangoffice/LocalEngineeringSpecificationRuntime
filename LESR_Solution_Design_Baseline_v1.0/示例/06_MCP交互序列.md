# 示例 06：AI 通过 MCP 参与修改

```text
AI → resolve(target file)
LESR → module/design/object candidates

AI → build_context(task, targets, baseline)
LESR → Context Manifest

AI → read mandatory revisions
LESR → exact content

User → authorize scoped delegation
LESR → Delegation Grant

AI → open workspace
AI → propose semantic operations
AI → validate workspace
AI → checkpoint
AI → build review package

User/Reviewer → approve package
AI or User → request apply
LESR → semantic transaction result + Git commit
```

AI 不获得通用文件写权限，也不能用自身批准替代用户审批。
