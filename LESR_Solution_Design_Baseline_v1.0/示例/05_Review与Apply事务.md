# 示例 05：Review 与 Apply 事务

```text
Workspace CHG-021
  Base: REQ@5, DESIGN@3
  Candidate: REQ@6, DESIGN@4
  Relation: REQ@6 implemented_by DESIGN@4
```

## Review Package

固定：

- Candidate Hash；
- Relation Change；
- Impact；
- Validation；
- Effective Model；
- Reviewer Roles。

## Approval

Content Approval + Technical Approval 均绑定 Package Hash。

## Apply

事务：

1. 校验 Base；
2. 校验 Approval；
3. 创建两个 Revision；
4. 创建 Relation Assertion Revision；
5. 创建 Applied Change Record；
6. 构建新 Git Tree；
7. 推进 Canonical Ref；
8. 重建 Projection。

任何一步在 Ref 推进前失败，不产生正式半状态。
