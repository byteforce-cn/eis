# 审批域扩展（approval v1.0.1）

演示“主体分离”类不变量（与授权契约的 SoD 呼应），并提供两种流转模式：

- **简单模式**：`approval.request.submit` → `approval.request.decide`（v1.0.0 冻结语义，保持不变）；
- **区块模式**（加法演进，MINOR）：一张单据按属主分区块确认，支持条件参与、
  打回后全部重确认、发起方撤回与 system 自动回写。

## 对象

| 对象 | 说明 |
|------|------|
| `ApprovalRequest` | 被审批操作 + 目标对象 + 申请人 + 状态（pending/approved/rejected/withdrawn；区块模式携带 `section_ids`） |
| `ApprovalDecision` | 简单模式决定：决定人 + 结果（approve/reject）+ 意见 |
| `ApprovalSection` | 区块模式节点：`key/title/owner/state/confirmer/decided_at/comment`；`applicable=false` → `not_applicable`（不阻塞） |

## 命令

| 命令 | 说明 | 权限 |
|------|------|------|
| `approval.request.submit` | 提交（可选 `sections` 进入区块模式） | `approval.request.submit` |
| `approval.request.decide` | 简单模式决定（区块模式调用会被拒绝：APR-409-002） | `approval.request.decide` |
| `approval.section.confirm` | 区块确认（全部就绪 → 单据完成） | `approval.section.confirm.<owner>` |
| `approval.section.reject` | 区块打回（单据 rejected，重提需全部重确认） | `approval.section.confirm.<owner>` |
| `approval.section.complete` | system 属主自动回写确认（建号/权限分配等区块） | `approval.section.complete` |
| `approval.request.resubmit` | 发起方重提（清空全部 confirmed/rejected 区块） | `approval.request.resubmit` |
| `approval.request.withdraw` | 发起方撤回（仅无人确认前） | `approval.request.withdraw` |

错误码：`APR-403-001` 自审、`APR-403-002` 区块属主不匹配、`APR-403-003` 非发起方、
`APR-409-002` 模式不匹配、`APR-409-003` 状态不允许、`APR-409-004` 仅已驳回可重提、
`APR-409-005` 已有确认不可撤回、`APR-409-006` 区块 key 重复。

## 不变量与规则

- `rules/no-self-approval.yaml`：决定人 ≠ 申请人；
- `rules/block-readiness.yaml`：全部区块就绪（confirmed / not_applicable）⟺ 单据完成；
- `rules/resubmit-reset.yaml`：重提后不得存在已确认区块；
- `rules/withdraw-timing.yaml`：无人确认前可撤回，有人确认后拒绝。

## 关联核心

- 授权：决定操作要求 `*.approve` 类权限，判定走 `04-authz-contract/resolution.api.yaml`；
  区块属主权限为动态标识 `approval.section.confirm.<owner>`，由处理器经内核
  `DEFERRED_AUTHZ` + `api.check_permission` 判定；
- SoD：与 `04-authz-contract/sod.rules.yaml` 的 SOD-001/SOD-002 同时生效。

## 可执行用例

```bash
python3 tools/e2e-runner extensions/approval/tests/approval.test.yaml
```

覆盖：简单模式既有用例、区块正常流转、条件不适用、打回→重提→全部重确认、
有人确认后撤回被拒、无人确认可撤回、属主不匹配被拒、模式不匹配被拒，以及
`ApprovalRequest` 加法演进的 MINOR 兼容性判定（`tests/compat/`）。
