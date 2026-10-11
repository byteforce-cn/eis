# 审批域扩展（approval v1.0.0，骨架）

演示“主体分离”类不变量（与授权契约的 SoD 呼应）。当前为骨架：
对象与规则已定义，操作含提交（`submitRequest`）与决定（`decideRequest`）。

## 对象

| 对象 | 说明 |
|------|------|
| `ApprovalRequest` 审批申请 | 被审批操作 + 目标对象 + 申请人 + 状态 |
| `ApprovalDecision` 审批决定 | 决定人 + 结果（approve/reject）+ 意见 |

## 规则

- `rules/no-self-approval.yaml`：决定人 ≠ 申请人（错误码 APR-403-001，enforcement: prevent）

## 关联核心

- 授权：决定操作要求 `*.approve` 类权限，判定走 `04-authz-contract/resolution.api.yaml`
- SoD：与 `04-authz-contract/sod.rules.yaml` 的 SOD-001/SOD-002 同时生效
