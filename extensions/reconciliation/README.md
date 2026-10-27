# 业务对账域扩展（Reconciliation）

> **归属**：领域扩展（ADR-0012 §4.2 → 独立 `extensions/reconciliation/`，不并入 `accounting`）。
> **裁决**：ADR-0022；规则：`rules/reconciliation.rules.yaml`（REC-001..010）。

## 1. 定位

对账是财务 / 库存 / 支付场景的最后一道正确性防线。它不是核心契约缺口，而是**领域能力**：
用六类元结构（对象 / 命令 / 时间 / 授权 / 审计 / 演进）表达「运行 → 差异 → 处理 → 只读报告」。

独立成扩展而不是并入 `accounting`：库存、支付、审批都要求对账，`accounting` 不应变成通用域。

## 2. 结构

```
extensions/reconciliation/
├── manifest.yaml                  # 对象 / 命令 / 规则 / 权限 / 不变量
├── objects/
│   ├── reconciliation-run.schema.json      # Run（run_key、状态、容忍度、计数）
│   └── difference-record.schema.json       # Difference（受控分类、处理方式）
├── operations/
│   ├── run.openapi.yaml           # reconciliation.run.start
│   ├── run-finish.openapi.yaml    # reconciliation.run.finish
│   ├── difference-resolve.openapi.yaml    # reconciliation.difference.resolve
│   └── report.openapi.yaml        # GET 只读报告（as_of / recorded_as_of）
├── rules/reconciliation.rules.yaml
├── migrations/V301__reconciliation_initial.sql (+ rollback)
├── README.md
└── tests/reconciliation.test.yaml
```

## 3. 运行（`Run`）

| 字段 | 语义 |
|------|------|
| `domain` / `period` / `sequence` | 对账域 / 期间（YYYY-MM）/ 显式运行序号 |
| `run_key` | `domain:period:sequence`；同一 `run_key` 只允许一个**当前**对象（迁移的部分唯一索引兜底） |
| `status` | `running → succeeded \| failed`；`skipped` 用于显式跳过 |
| `tolerance_amount` / `tolerance_quantity` | 绝对差 ≤ 容忍度才可判 `matched`（金额 2 位、数量 4 位小数） |
| `source_count` / `target_count` / `difference_count` | 来源 / 目标 / 差异记录计数 |

纪律：

- 同一 `run_key` 重复发起 → `REC-409-001`，**不产生第二份运行**；
- 同一 `(domain, period)` 重跑必须显式换 `sequence`（REC-002），并在运维侧记录原因；
- 期间边界复用 `03-time-contract` 与 `accounting.period.close` 的既有语义，不另建期间对象。

## 4. 差异（`Difference`）

| 字段 | 语义 |
|------|------|
| `run_id` | 所属运行 |
| `category` | 受控枚举：`matched` / `amount_mismatch` / `missing_source` / `missing_target` / `resolved` / `written_off` |
| `source_ref` / `target_ref` | 来源 / 目标业务引用（缺失侧为 null） |
| `amount_delta` / `quantity_delta` | 来源 - 目标；受控十进制字符串 |
| `resolution_code` | `adjust` / `write_off` / `manual_match` / `accept`；未处理为 null |
| `resolved_by` / `resolved_at` | 处理人与处理时间 |

- 新建差异只能使用前四类；`resolved` / `written_off` 只能由处理命令产生；
- 分类禁止自由文本（`REC-400-001`）；
- 处理只能走 `reconciliation.difference.resolve`，并写审计事件 `reconciliation.difference.resolved`
  （REC-004）；不得直接改差异记录；
- `write_off` → 终态 `written_off`，其余处理方式 → `resolved`；已处理 / `matched` 再次处理 → `REC-409-003`。

## 5. 命令与读取面

| 命令 | 说明 | 冲突 |
|------|------|------|
| `reconciliation.run.start` | 发起运行并落差异 | `REC-409-001`（run_key 已存在）、`REC-400-001`（分类/数值非法） |
| `reconciliation.run.finish` | `running → succeeded \| failed` | `REC-409-002`（已终态）、`REC-400-002`（failed 缺原因） |
| `reconciliation.difference.resolve` | 调整 / 核销 / 人工匹配 / 接受 | `REC-409-003`（不可处理） |

读取面 `reconciliation.report.read`：`GET /reconciliation/runs/{runId}/report`，
报告是运行与差异的**只读投影**（REC-005），支持 `as_of` / `recorded_as_of`；
未授权 fail-closed 403（reason_code 由 authz `/check` 给出 `NO_PERMISSION`）。

## 6. 与调度扩展的关系

对账本质上是「带 `run_key` 的批处理」。运行幂等与执行记录与
`extensions/scheduler/`（ADR-0021）共用同一元结构：调度器负责**何时跑**，本扩展负责**跑什么、
差异如何分类与处理**；两者不互相依赖，组合由部署方决定。

## 7. 非目标

| 非目标 | 理由 |
|---|---|
| 对账匹配算法 / 规则引擎 | 实现自由，契约只规定共享语义 |
| 外部系统连接器（API / 文件 / CDC） | 集成拓扑属部署方职责 |
| 差错队列的调度、分派与处理界面 | 属实现与运维 |
| 对账报告呈现格式与导出模板 | 读模型消费者决定 |
| 独立对账服务/作业的部署形态 | 部署方职责 |
