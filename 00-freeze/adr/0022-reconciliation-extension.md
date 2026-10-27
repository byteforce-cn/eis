# ADR-0022：业务对账域扩展（`extensions/reconciliation/`）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #36（上游跟踪 #33）；ADR-0012 §4.2（归属裁决）；ADR-0021（scheduler 共用 run 元结构）；`extensions/reconciliation/`、`tools/ci/reconciliation-smoke.sql`

## 1. 变更原因

核心仓库对 `reconciliation` 无直接命中；`docs/CONFORMANCE.md` L4 的「迁移 + 回滚 + 对账」指
**结构迁移对账**（`06-evolution-contract/`），不是业务数据核对。日终对账、流水对账、差错队列是
财务与库存场景的最后一道正确性防线，但当前没有契约位置：差异分类、容忍度与差错处理状态机
每个实现自行发明，跨系统核不上。

这不是核心契约缺失，而是**领域能力缺失**：`01`–`06` 是元结构，对账是用这些元结构表达的
业务过程。塞进核心会让核心绑定「订单 / 支付 / 库存 / 总账」等具体域，与 README 的
「案例自由」原则冲突。

## 2. 影响范围

- 扩展：新增 `extensions/reconciliation/` 1.0.0（领域扩展）
- 对象：`Run`（运行）、`Difference`（差异）
- 命令：`reconciliation.run.start` / `reconciliation.run.finish` / `reconciliation.difference.resolve`
- 读取面：`reconciliation.report.read`（只读投影）
- 迁移：`migrations/V301__reconciliation_initial.sql`（`run_key` 当前行唯一索引）
- CI：PostgreSQL 任务执行 V301 + `tools/ci/reconciliation-smoke.sql`
- 文档：本 ADR、`extensions/README.md`、`docs/ROADMAP.md`、`CHANGELOG.md`
- 核心契约：**无改动**

## 3. 兼容性分析

- 级别判定：**MINOR**（纯新增可选扩展）。

| 变更 | 判定 | 依据 |
|---|---|---|
| 新增 `extensions/reconciliation/` 1.0.0 | MINOR | 新增可选扩展，不采用者不受影响 |
| 新增 `REC-` 规则/错误码前缀 | 无 | 扩展命名空间，不占用 `EIS-` |
| 新增 V301 迁移 | 迁移加法 | 只建索引，不改核心表 |

- 破坏点：无。

## 4. 决策

### 4.1 归属与形态

- **独立** `extensions/reconciliation/`，不并入 `accounting`：库存 / 支付 / 总账都要复用，
  并入会让 `accounting` 变成通用域（issue #36 的两种落点中选独立）；
- 不新增核心契约类；对账不是 CONFORMANCE 等级。

### 4.2 运行（`Run`）

| 决策点 | 规定 |
|---|---|
| 身份 | `run_key = domain:period:sequence`；同一 `run_key` 只允许一个当前对象（命令校验 + V301 部分唯一索引兜底） |
| 幂等 | 同一 `run_key` 重复发起 → `REC-409-001`，不产生第二份运行 |
| 重跑 | 同一 `(domain, period)` 重跑必须显式换 `sequence`（REC-002），不得靠重复提交绕过 |
| 状态机 | `running → succeeded \| failed`；`skipped` 用于显式跳过；终态不可再 `finish`（`REC-409-002`） |
| 容忍度 | `tolerance_amount`（2 位小数）/ `tolerance_quantity`（4 位小数）；绝对差 ≤ 容忍度才可判 `matched` |
| 期间 | `period = YYYY-MM`；期间锁定复用 `accounting.period.close`，不另建期间对象（REC-006） |

### 4.3 差异（`Difference`）

- 受控分类：`matched` / `amount_mismatch` / `missing_source` / `missing_target` /
  `resolved` / `written_off`；新建差异只能用前四类（`REC-400-001`）；
- 金额 / 数量差异为受控十进制字符串（金额 2 位、数量 4 位，REC-010）；
- 处理方式：`adjust` / `write_off` / `manual_match` / `accept`；
  `write_off` → `written_off`，其余 → `resolved`；
- **处理只能走命令** `reconciliation.difference.resolve`，写审计事件
  `reconciliation.difference.resolved`；禁止直接改差异记录（REC-004）；
- 已处理 / `matched` 再次处理 → `REC-409-003`。

### 4.4 报告

- 报告是运行与差异的**只读投影**，不落独立报告表、不参与写路径（REC-005）；
- 读取面 `reconciliation.report.read`，支持 `as_of` / `recorded_as_of`（02 查询契约）；
- 未授权 fail-closed 403，reason_code 由 authz `/check` 给出 `NO_PERMISSION`。

### 4.5 与调度扩展共用元结构

对账本质上是「带 `run_key` 的批处理」。#37 的 `extensions/scheduler/`（ADR-0021）负责
**何时跑**（计划时点幂等、互斥、租约），本扩展负责**跑什么、差异如何分类与处理**；
两者不互相依赖，组合由部署方决定，避免长出两套 run 模型。

### 4.6 明确不做

| 不做项 | 理由 |
|---|---|
| 对账匹配算法 / 规则引擎 | 实现自由；契约只规定共享语义 |
| 外部系统连接器（API / 文件 / CDC） | 集成拓扑属部署方职责（`docs/INTEGRATION-BOUNDARY.md`） |
| 差错队列调度、分派与人工处理界面 | 实现与运维 |
| 报告呈现格式与导出模板 | 读模型消费者决定 |
| 独立对账服务/作业的部署形态 | 部署方职责 |
| 把 `run_key` 唯一性写成核心契约 | 属领域规则，用对象 + 唯一索引表达 |

## 5. 迁移方案

- 部署：`tools/schema-compiler compile --all` 生成 `reconciliation_run` / `reconciliation_difference`，
  执行 `migrations/V301__reconciliation_initial.sql` 建 `run_key` 当前行唯一索引；
- 数据：新表，无核心表回填；历史 run 不迁入；
- 使用方：按 `run_key` 发起运行，差异随运行落库，处理差异走命令。

## 6. 回滚方案

- 回滚 V301（`V301__reconciliation_initial.rollback.sql`）→ 删除本扩展表；
- 回滚 = revert 本 ADR + 扩展目录 + CI 步骤；核心契约不受影响。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 扩展清单 | `extensions/reconciliation/manifest.yaml` | 对象 / 命令 / 权限 / 不变量 |
| 对象 | `extensions/reconciliation/objects/*.schema.json` | Run / Difference（含 `id`/`version`/双时间轴） |
| 命令契约 | `extensions/reconciliation/operations/*.openapi.yaml` | 3 命令 + 只读报告 |
| 处理器 | `extensions/reconciliation/handlers.py` | run_key 幂等、状态机、差异处理 |
| 规则 | `extensions/reconciliation/rules/reconciliation.rules.yaml` | REC-001..010 + 不做项 |
| 迁移 | `extensions/reconciliation/migrations/V301__*` | `run_key` 当前行唯一索引 + 回滚 |
| 用例 | `extensions/reconciliation/tests/reconciliation.test.yaml` | 8 个 scenario（幂等/分类/处理/终态/授权/时点） |
| CI 冒烟 | `tools/ci/reconciliation-smoke.sql`、`.github/workflows/ci.yml` | run_key 唯一 / 分类受控 |

## 8. 验收用例

- `python3 tools/e2e-runner extensions/reconciliation/tests/reconciliation.test.yaml` → 8/8；
- `python3 tools/e2e-runner --all` → 全绿（计数随新增用例更新）；
- `python3 tools/contract-checker` → 通过；
- `python3 tools/schema-compiler check` → 编译 2 表且含 T-R009 排他约束；
- CI PostgreSQL：V301 + `reconciliation-smoke.sql` 全过。
