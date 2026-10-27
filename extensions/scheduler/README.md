# 定时任务执行语义扩展（Scheduler）

> **归属**：跨域运行时扩展（ADR-0012 §4.2 → `extensions/scheduler/`），不修改核心六类契约。
> **裁决**：ADR-0021；规则：`rules/scheduling.rules.yaml`（SCH-001..012）。
> **参考实现**：`tools/scheduler`（状态机语义 + PostgreSQL 语句模板）。

## 1. 定位

`03-time-contract` 定义**数据**的时间维度；本扩展定义**任务**的时间维度：

- 同一计划时点（`job_id + scheduled_for`）至多执行一次；
- 同一互斥域（`scope`）同一时刻至多一个执行者；
- 租约过期可被抢占，旧持有者的写入必须被拒绝；
- 执行终态可观测、可审计。

它是**可选扩展**：不使用调度契约的系统不受影响；本扩展不新增 CONFORMANCE 等级。

本扩展**不**规定锁算法、选主、cron 解析器与调度器部署形态——这些属于实现与运维
（ADR-0012 第三层）。正确性由 `run_key` 唯一约束与 `lease_id` 比对保证，**锁只做内务，
正确性不外包**。

## 2. 结构

```
extensions/scheduler/
├── manifest.yaml                 # kind: runtime；无业务对象/命令
├── scheduler.ddl                 # scheduled_job + job_run（PostgreSQL 16）
├── rules/scheduling.rules.yaml   # SCH-001..012（MUST + 不做项）
├── README.md
└── tests/scheduler.test.yaml     # static + cli 可执行用例
```

## 3. 作业定义（`scheduled_job`）

| 字段 | 语义 |
|------|------|
| `job_id` | 命名空间内的作业标识（主键），如 `finance.daily-close` |
| `schedule` / `schedule_format` | 计划表达式与格式（`cron` / `calendar`）；解析器由部署方提供 |
| `version` | 作业定义版本（定义变更 +1），与运行 `attempt` 独立 |
| `enabled` | 停用后到点不执行，写 `skipped`（`job_disabled`） |

## 4. 运行记录（`job_run`）

| 字段 | 语义 |
|------|------|
| `run_key` | `job_id@scheduled_for`（UTC），**外部幂等键**，UNIQUE |
| `(job_id, scheduled_for)` | 计划时点唯一（DB 兜底），同一时点至多一个 run |
| `scope` | 互斥域：`job:<job_id>` 或 `partition:<key>`；同 scope 至多一个 `running` |
| `status` | `running → succeeded | failed`；`skipped` 由停用/互斥域被占/显式跳过产生 |
| `attempt` / `max_attempts` | 已开始尝试次数与上限；达到上限后不再认领 |
| `lease_id` / `lease_owner` / `lease_expires_at` | 租约三元组；`running` 必须持有 |
| `finished_at` / `last_error` | 终态时间与机器可读原因（`scope_held` / `job_disabled` / `lease_expired`） |

## 5. 认领、抢占与完成

1. **回收**：同 scope 内租约已过期但仍为 `running` 的陈旧 run 先置为 `failed`
   （`last_error = lease_expired`），再允许新 run 认领该 scope；
2. **认领**：按 `run_key` 查找；不存在则插入 `running`（`attempt = 1`）；
3. **重复触发**：同 `run_key` 且租约未过期 → 只观察，不插入第二份；
4. **抢占**：同 `run_key` 且租约过期 → 复用同一行，`attempt+1`、换新 `lease_id`；
5. **完成**：`finish` 必须携带认领时的 `lease_id`；不匹配（已被抢占）→ 拒绝；
6. **重试**：`failed` 且 `attempt < max_attempts` 可被下一次认领重试；否则不再认领；
7. **终态**：`succeeded` / `skipped` 不可再 `finish` 或认领。

`tools/scheduler --print-sql` 输出上述状态的 PostgreSQL 语句模板（含 `FOR UPDATE SKIP LOCKED`）；
`--self-test` 用确定性内存存储验证全部语义。

## 6. 审计与监控

- 每次状态迁移（`running → succeeded|failed|skipped`）写一条 EIS 审计条目
  （`05-audit-contract` 哈希链；actor = 调度服务主体）；本扩展不另建审计链；
- 指标至少包含：`running` 数、租约过期 `running` 数、`failed` 数、`skipped` 数、
  最老未完成 run 年龄；按 `job_id` 与 `scope` 分段，不得只报单一成功率。

## 7. 非目标

| 非目标 | 理由 |
|---|---|
| 分布式锁算法 / 选主 / 共识 | 部署拓扑相关，属实现与运维 |
| cron / 日历解析器实现 | 实现自由；契约只要求 `scheduled_for` 为 UTC |
| 调度器部署形态 | 部署方职责 |
| 任务 DAG / 跨作业依赖 | 属 `coord` workflow（`docs/ORCHESTRATION-BOUNDARY.md`） |
| 把运行记录当业务审计 | 业务审计仍由领域命令写入 |
