# 采购系统（procurement v1.0.0）— 端到端试点

应用案例：自由组合扩展，不修改核心与扩展。

## 扩展组合（composition.yaml）

| 扩展 | 版本 | 提供 |
|------|------|------|
| `approval` | 1.0.0 | 申请/审批（禁止自审） |
| `inventory` | 1.0.0 | 收货入库（库存非负） |
| `accounting` | 1.0.0 | 应付/付款过账（借贷平衡）、关账（期间锁定） |

## 试点场景

- `scenarios/procure-to-pay.yaml`：申请 → 审批 → 收货 → 应付 → 付款 → 关账

## 验收

**现状**：场景已可执行——`python3 tools/e2e-runner --all` 一键运行（7 步 /
12 断言 / 6 条审计链，含自审负例 S1b）。

见 `acceptance.yaml` 的 `acceptance.pilot`：

1. 端到端场景跑通
2. 业务人员验证业务正确性（金额、数量、期间）
3. 合规人员验证审计完整性（`verify.tool` / `audit-verifier`）
4. 运维人员验证部署与回滚
