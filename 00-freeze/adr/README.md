# ADR — 架构决策记录

EIS 的核心契约已冻结。任何修改（解冻请求）必须走以下流程：

```
变更提案 → ADR → 可执行工件 → 验证 → 合并
```

## ADR 必须有

| 章节 | 内容 |
|------|------|
| 变更原因 | 为什么必须改（问题、证据、影响面） |
| 影响范围 | 涉及哪些契约/扩展/案例/工具 |
| 兼容性分析 | 按 `06-evolution-contract/compatibility.rules.yaml` 判定的级别（MAJOR/MINOR/PATCH） |
| 迁移方案 | 脚本 + 数据迁移 + 双写/对账（如适用） |
| 回滚方案 | 回滚脚本与验证条件 |
| 可执行工件 | Schema/DDL/测试用例/工具变更的清单（路径） |
| 验收用例 | 对应 `acceptance.yaml` 的验收项 |

> **无工件的变更一律拒绝。**

## 命名与状态

- 文件名：`NNNN-<slug>.md`（四位序号，序号不复用）
- 状态：`Proposed` → `Accepted` / `Rejected` / `Superseded by NNNN`

## 现有记录

| 编号 | 标题 | 状态 |
|------|------|------|
| [0001](0001-eis-spec-v1.0-freeze.md) | EIS Spec v1.0 冻结 | Accepted |
| [0002](0002-pre-release-revisions.md) | 开源发布前定稿修订（Pre-release） | Accepted |
| [0003](0003-iam-extension-boundary-and-audit-scope.md) | IAM 首落地：扩展边界与审计范围 | Accepted |
| [0004](0004-authz-attributes-ownership.md) | 授权属性的属主与来源（拉取为准，推送为可选物化） | Accepted |
