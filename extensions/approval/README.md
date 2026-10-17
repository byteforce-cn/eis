# 审批域扩展（approval v1.1.0）

演示“主体分离”类不变量（与授权契约的 SoD 呼应），并提供两种流转模式：

- **简单模式**：`approval.request.submit` → `approval.request.decide`（v1.0.0 冻结语义，保持不变）；
- **区块模式**（加法演进，MINOR）：一张单据按属主分区块确认，支持条件参与、
  打回后全部重确认、发起方撤回与 system 自动回写。

## 对象

| 对象 | 说明 |
|------|------|
| `ApprovalRequest` | 被审批操作 + 目标对象 + 申请人 + 状态（pending/approved/rejected/withdrawn；区块模式携带 `section_ids`） |
| `ApprovalDecision` | 简单模式决定：决定人 + 结果（approve/reject）+ 意见 |
| `ApprovalSection` | 区块模式节点：`key/title/owner/step_order/state/confirmer/decided_at/comment`；`step_order` 声明处理顺序（0 起递增，确认/回写须前序就绪：APR-409-007）；`applicable=false` → `not_applicable`（不阻塞） |

## 命令

| 命令 | 说明 | 权限 |
|------|------|------|
| `approval.request.submit` | 提交（可选 `sections` 进入区块模式） | `approval.request.submit` |
| `approval.request.decide` | 简单模式决定（区块模式调用会被拒绝：APR-409-002） | `approval.request.decide` |
| `approval.section.confirm` | 区块确认（须前序就绪，APR-409-007；全部就绪 → 单据完成） | `approval.section.confirm.<owner>` |
| `approval.section.reject` | 区块打回（单据 rejected，重提需全部重确认；不受顺序门限制） | `approval.section.confirm.<owner>` |
| `approval.section.complete` | system 属主自动回写确认（须前序就绪，APR-409-007） | `approval.section.complete` |
| `approval.request.resubmit` | 发起方重提（清空全部 confirmed/rejected 区块） | `approval.request.resubmit` |
| `approval.request.withdraw` | 发起方撤回（仅无人确认前） | `approval.request.withdraw` |

错误码：`APR-403-001` 自审、`APR-403-002` 区块属主不匹配、`APR-403-003` 非发起方、
`APR-409-002` 模式不匹配、`APR-409-003` 状态不允许、`APR-409-004` 仅已驳回可重提、
`APR-409-005` 已有确认不可撤回、`APR-409-006` 区块 key 重复、`APR-409-007` 前序区块未就绪。

## 读取面权限（issue #8）

`manifest.yaml` 的 `permissions` 是唯一权限来源（6 命令 + 1 读取）。`approval.request.read`
（`kind: read`）覆盖消费方（`ims-approval`，经 BFF 同源 `/api/approval`）的四个读端点：

| 读操作 | 用途 |
|--------|------|
| `GET /requests?operation=&status=&targetId=&requester=&todoFor=me` | 审批中心列表（`todoFor=me` 按调用者持有的 `approval.section.confirm.<owner>` 过滤待办） |
| `GET /requests/{id}` | 单据详情（单据头 + 区块数组 + `flowPhase/flowState` + 服务端判定的 `canConfirm/canReject`） |
| `GET /requests/{id}/decisions` | `decide` 路径决策列表 |
| `GET /requests/by-target/{type}/{id}` | 按业务对象反查单据与 system 区块 ID（HR 供给成功后回写 system 区块的对账入口，调用方为 `ims-hr` 服务身份） |

- 读权限**不是命令**：不参与命令级 `/check`，由消费方读面授权门按声明标识执行；
- **fail-closed**：未授权返回 403；**读面 403 无契约码**（`APR-403-*` 仅覆盖命令面），
  reason_code 由 authz `/check` 给出 `NO_PERMISSION`——「已声明未授予」与「未声明引用」不再含糊；
- 动态属主命令权限以 `approval.section.confirm.*` 声明（确认与打回复用同一属主权限）；
- 消费方（`ims-approval` / `ims-iam`）按声明标识接入 `approval.request.read`，不得自造权限标识；
  判定用例见 `tests/fixtures-authz.yaml` 与 `approval.test.yaml` 的 `kind: authz` 用例。

## 不变量与规则

- `rules/no-self-approval.yaml`：决定人 ≠ 申请人；
- `rules/block-readiness.yaml`：全部区块就绪（confirmed / not_applicable）⟺ 单据完成；
- `rules/section-order.yaml`：按 `step_order` 顺序处理（`section_ids` 数组顺序一致），确认/回写须前序就绪（APR-409-007）；`not_applicable` 不阻塞；重提保留 `step_order`；历史数据空值按 `section_ids` 位置回退；
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

覆盖：简单模式既有用例、区块正常流转、条件不适用、区块顺序（乱序拒绝 / 不适用前序 / 重提后重走）、打回→重提→全部重确认、
有人确认后撤回被拒、无人确认可撤回、属主不匹配被拒、模式不匹配被拒，以及
`ApprovalRequest`/`ApprovalSection` 加法演进的 MINOR 兼容性判定与迁移生成（`tests/compat/`）。
