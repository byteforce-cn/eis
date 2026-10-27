# 可靠投递扩展（Outbox/Inbox）

> **归属**：跨域运行时扩展（ADR-0012 §4.2 → `extensions/outbox/`），不修改核心六类契约。
> **裁决**：ADR-0018；规则：`rules/delivery.rules.yaml`（OBX-001..012）。
> **参考实现**：`tools/relay`（状态机语义 + PostgreSQL 语句模板）。

## 1. 定位

核心契约定义了事件「如何产生」，本扩展定义事件「如何可靠离开领域、到达消息中间件，以及消费方如何幂等」。
它是**可选扩展**：不使用 Outbox 的系统不受影响；本扩展不新增 CONFORMANCE 等级。

## 2. 结构

```
extensions/outbox/
├── manifest.yaml             # 扩展清单（无业务对象/命令）
├── outbox.ddl                # outbox_message + inbox_message（PostgreSQL 16）
├── rules/delivery.rules.yaml # OBX-001..012（MUST/SHOULD + 不做项）
├── README.md
└── tests/outbox.test.yaml    # static + cli 可执行用例
```

## 3. 生产段：Outbox

| 字段 | 语义 |
|------|------|
| `aggregate_type` / `aggregate_id` | 聚合类型与聚合根 ID（**分片键 = `aggregate_id`**） |
| `seq` | 聚合内单调递增序号（从 1 开始）；`(aggregate_id, seq)` 唯一 |
| `event_id` | 全局唯一（事件只入 Outbox 一次） |
| `payload` | 事件正文（jsonb）；不是读模型投影 |
| `status` | `pending → processing → sent`；失败可回 `pending`，不可重试/超限 → `dead` |
| `attempts` / `next_attempt_at` | 投递尝试次数与下次到期时间（指数退避） |
| `lease_owner` / `lease_expires_at` | 认领租约；`processing` 必须持有租约，过期可回收 |

捕获纪律（OBX-001/003/004）：

- Outbox 行必须与业务数据在**同一本地事务**提交；跨库禁止双写（用 CDC 或流程编排）；
- `seq` 由属主域在该事务内分配（读当前聚合最大 seq + 1）；`(aggregate_id, seq)` 唯一是最后防线；
- 分片键只能是聚合根 ID；同一聚合 `seq` 未 `sent` 时，后续 `seq` 不得被认领。

## 4. Relay 语义

1. **认领**：按 `next_attempt_at` 取到期行，`FOR UPDATE SKIP LOCKED`；每聚合只认领最小未 `sent` 的 `seq`（顺序屏障）；分片内串行、分片间并行；
2. **投递**：broker 确认（publisher confirm / `acks=all`）成功后才标记 `sent`（确认后置）；
3. **失败**：可重试 → `pending` + 指数退避（有上限）；不可重试（schema/序列化/明确拒绝）或超限 → `dead`；
4. **租约回收**：`processing` 超时回到 `pending`；旧持有者的确认/失败因租约归属不符被拒绝；
5. **死信**：`dead` 可观测、可显式重放；重放保留 `event_id` 与 `(aggregate_id, seq)`，不自动无限重放；
6. **清理**：`sent` 行定期清理或按分区 drop；**outbox 不是事件历史**，回放走事件存储或 broker retention。

`tools/relay --print-sql` 输出上述状态的 PostgreSQL 语句模板；`--self-test` 用确定性内存存储验证语义。

## 5. 消费段：Inbox（最小语义）

| 状态 | 语义 |
|------|------|
| `processing` | 已认领，持有租约（或处于退避等待，租约为空 + `next_attempt_at` 未来） |
| `done` | 处理完成；同一 `(consumer_group, event_id)` 的重复投递直接忽略 |
| `dead` | 不可重试或超限；需显式重放 |

- 唯一键 `(consumer_group, event_id)`；不同消费者组独立处理同一事件；
- 消费方先 Inbox 去重，再执行业务副作用；`done` 与业务副作用应在同一本地事务提交（或按幂等键收敛）。

## 6. 监控（必须分段）

| 指标 | 说明 |
|------|------|
| `outbox_pending` / `outbox_oldest_pending_age_seconds` | 生产段积压与最老年龄 |
| `outbox_failure_rate` / `outbox_dead` | 投递失败率与死信数 |
| `consumer_group_lag` | 消费段滞后（按 consumer group），**不得**与 outbox lag 合并 |

## 7. 明确不做

- 分片数、线程模型、relay 部署形态（嵌入进程 / sidecar / 共享服务）；
- 消息中间件选型（Kafka / RabbitMQ / 其他）与客户端配置；
- exactly-once 投递（只承诺 at-least-once）；
- 从 outbox 表做历史回放；
- 跨库双写（用 CDC 或流程编排）。

## 8. 验收

```bash
python3 tools/e2e-runner extensions/outbox/tests/outbox.test.yaml
python3 tools/relay --self-test
python3 tools/relay --print-sql          # PostgreSQL 语句模板（FOR UPDATE SKIP LOCKED）
```

CI 的 PostgreSQL 冒烟任务执行 `extensions/outbox/outbox.ddl` 与 `tools/ci/outbox-smoke.sql`
（唯一约束 / 状态机 / 租约字段 / Inbox 幂等）。
