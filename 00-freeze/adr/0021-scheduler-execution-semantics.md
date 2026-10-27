# ADR-0021：定时任务 / 日终批处理的执行语义（`extensions/scheduler/`）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #37（上游跟踪 #33）；ADR-0012 §4.2（归属裁决）；`extensions/scheduler/`、`tools/scheduler`、`tools/ci/scheduler-smoke.sql`、`docs/LANDING-IAM.md` §8 #12

## 1. 变更原因

`03-time-contract` 只定义**数据**的时间维度（`valid_from/valid_to/recorded_at/superseded_at`），
不定义**任务**的时间维度。日终结算、定时批处理在企业系统中普遍存在，但「同一计划时点只执行一次」
「同一互斥域同一时刻只有一个执行者」「租约过期后旧执行者不得再写」这些可观察语义没有契约位置，
每个实现自行发明，重复执行与并发冲突无规范可依。

事实核对：落地层已有分层口径（`docs/LANDING-IAM.md` §8 #12：长驻单例 → `LeaderElection`；
短临界区 → `Lock`；数据串行 → PG `SKIP LOCKED`；「锁只做内务，正确性不外包」），
但该口径没有升格为可验收契约。本 ADR 只把**执行语义**契约化，不把锁实现契约化。

## 2. 影响范围

- 扩展：新增 `extensions/scheduler/` 1.0.0（`kind: runtime`，无业务对象）
- 工具：新增 `tools/scheduler`（状态机参考 + PostgreSQL 语句模板）
- CI：PostgreSQL 任务执行 `scheduler.ddl` + `tools/ci/scheduler-smoke.sql`
- 文档：本 ADR、`extensions/README.md`、`docs/ROADMAP.md`、`CHANGELOG.md`
- 核心契约：**无改动**（不新增第七类契约、不改 01–06）

## 3. 兼容性分析

- 级别判定：**MINOR**（纯新增可选扩展）。

| 变更 | 判定 | 依据 |
|---|---|---|
| 新增 `extensions/scheduler/` 1.0.0 | MINOR | 新增可选扩展，不采用者不受影响 |
| 新增 `tools/scheduler` | 工具加法 | 不影响既有工具与契约 |
| 新增 `SCH-` 错误/规则前缀 | 无 | 使用扩展命名空间，不占用 `EIS-` |

- 破坏点：无。未加载该扩展的部署行为不变。

## 4. 决策

### 4.1 归属与形态

- 归属：**扩展契约**（跨域运行时能力），不新增核心契约类（ADR-0012 补充规则）；
- `kind: runtime`：无业务对象/命令/读取面，DDL 由扩展自带，`schema-compiler` 跳过编译；
- 本扩展不新增 CONFORMANCE 等级；不采用调度契约的部署不受影响。

### 4.2 作业定义（`scheduled_job`）

| 字段 | 语义 |
|---|---|
| `job_id` | 命名空间内的作业标识（主键），如 `finance.daily-close` |
| `schedule` | 计划表达式（cron 或日历文本），由部署方解析 |
| `schedule_format` | `cron` / `calendar`；只声明格式，不规定解析器实现 |
| `version` | 作业定义版本（每次定义变更 +1），与运行记录的 `attempt` 独立 |
| `enabled` | 停用后到点不执行，记录 `skipped` |

### 4.3 运行幂等（`job_run.run_key`）

- `run_key = job_id + scheduled_for`（字符串 `<job_id>@<scheduled_for ISO8601 UTC>`）；
- `run_key` UNIQUE **且** `(job_id, scheduled_for)` UNIQUE——同一计划时点至多一个 run；
- 重复触发（调度器重试、多实例同 tick）不产生第二份 run，只观察已有 run；
- 重跑必须**显式**改变计划时点或换用独立的运维命令，不得靠重复触发绕过去。

### 4.4 互斥作用域与租约

| 字段 | 语义 |
|---|---|
| `scope` | 互斥域（同 job 用 `job:<job_id>`，同分区用 `partition:<key>`） |
| `lease_id` / `lease_owner` / `lease_expires_at` | 当前执行者及其租约；`running` 必须持有租约 |
| `attempt` / `max_attempts` | 已开始的尝试次数与上限 |

- 同一 `scope` 同一时刻至多一个 `running`（部分唯一索引兜底）；
- 租约过期：同一 run 可被**抢占**（复用同一行、`attempt+1`、换新 `lease_id`）；同 scope 的
  陈旧 `running` 行先回收为 `failed`（`lease_expired`），再允许新 run；
- **旧持有者的写入以 `lease_id` 比对拒绝**（finish/heartbeat 必须携带认领时的 `lease_id`），
  正确性不依赖锁本身；
- `attempt > max_attempts` 后不再认领。

### 4.5 执行记录与终态

- 状态机：`running → succeeded | failed`；`skipped` 由停用/互斥域被占/计划时点已处理产生；
- `succeeded` / `skipped` 为终态；`failed` 在 `attempt < max_attempts` 时可由下一次认领重试；
- 每次状态迁移写 EIS 审计条目（actor = 调度服务主体，`valid_time` = 迁移时刻），
  审计链由宿主按 `05-audit-contract` 维护；
- `last_error` 只记录机器可读原因 + 摘要，不承载业务数据。

### 4.6 不与核心时间契约混用

- `scheduled_for` 是**计划时点**，不是业务有效时间；不得写入业务对象的 `valid_from`；
- 运行记录是运行时状态，不进入 `01-data-contract` 的对象多版本模型（本扩展 `kind: runtime`）。

### 4.7 明确不做

| 不做项 | 理由 |
|---|---|
| 分布式锁算法、选主、共识 | 部署拓扑相关，属实现与运维（ADR-0012 第三层） |
| cron/日历解析器实现与时区规则 | 实现自由；契约只要求 `scheduled_for` 为 UTC 计划时点 |
| 调度器部署形态（嵌入 / 独立服务 / K8s CronJob） | 部署方职责 |
| `SKIP LOCKED` 等具体 SQL 写法 | 仅作参考实现与模板，不是契约条款 |
| 任务 DAG / 依赖编排 | 属 `coord` workflow（`docs/ORCHESTRATION-BOUNDARY.md`） |
| 把执行记录当业务审计 | 业务审计仍由领域命令写入；调度迁移只写自身审计条目 |

## 5. 迁移方案

- 部署：执行 `extensions/scheduler/scheduler.ddl` 建表；接入调度器（可用 `tools/scheduler --print-sql` 为模板）；
- 作业：先写 `scheduled_job`，再按计划时点调用认领；`job_id` 建议带业务命名空间；
- 数据：新表，无核心表回填。

## 6. 回滚方案

- 停用调度器后 `DROP TABLE job_run, scheduled_job`；核心契约与既有表不受影响；
- 回滚 = revert 本 ADR + 扩展目录 + CI 步骤。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 扩展清单 | `extensions/scheduler/manifest.yaml` | `kind: runtime`；规则引用 |
| 表结构 | `extensions/scheduler/scheduler.ddl` | job/run、run_key 唯一、状态机、租约、scope 互斥 |
| 规则 | `extensions/scheduler/rules/scheduling.rules.yaml` | SCH-001..012 + 不做项 |
| 说明 | `extensions/scheduler/README.md` | 认领/抢占/终态/审计/监控 |
| 参考实现 | `tools/scheduler` | 状态机 + PG 语句模板；`--self-test` / `--print-sql` |
| 用例 | `extensions/scheduler/tests/scheduler.test.yaml` | static（DDL/规则）+ cli（自测/模板） |
| CI 冒烟 | `tools/ci/scheduler-smoke.sql`、`.github/workflows/ci.yml` | run_key 唯一 / 状态机 / 租约 / scope 互斥 |

## 8. 验收用例

- `python3 tools/scheduler --self-test`：重复计划时点、过期租约抢占、旧 lease_id 写入拒绝、
  重试上限、停用/互斥跳过、终态不可再迁；
- `python3 tools/scheduler --print-sql`：含 `FOR UPDATE SKIP LOCKED` 与 `job_run`；
- `python3 tools/e2e-runner extensions/scheduler/tests/scheduler.test.yaml`：全部通过；
- `python3 tools/e2e-runner --all`：全绿（计数随新增用例更新）；
- CI PostgreSQL：`scheduler.ddl` + `scheduler-smoke.sql` 全过。
