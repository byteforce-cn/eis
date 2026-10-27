# ADR-0018：可靠投递扩展（`extensions/outbox/`：Outbox + Inbox）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #31（含 #34 Inbox）；ADR-0012 §4.2（归属裁决）；`extensions/README.md`、`extensions/outbox/`、`tools/relay`、`tools/schema-compiler`、`tools/contract-checker`、`.github/workflows/ci.yml`、`docs/KNOWN-LIMITATIONS.md`

## 1. 变更原因

六类核心契约定义了事件「如何产生」，但没有定义事件「如何可靠离开领域、到达消息中间件」。
每个采用者都要重新推导 at-least-once、聚合内有序、重复、死信、租约回收与清理；常见错误
（多 relay 无分片并行、先标记后投递、毒消息无限重试）会造成真实的数据不一致。

ADR-0012 已裁决：落点 `extensions/outbox/`（跨域运行时扩展），**不新增第七类核心契约**，
并要求 `tools/relay` 同批交付（否则租约回收/毒消息不可验收）；#34 的 Inbox 语义并入本项。

## 2. 影响范围

- 扩展：新增 `extensions/outbox/`（manifest / `outbox.ddl` / `rules/delivery.rules.yaml` / README / 用例）
- 扩展机制：manifest 增可选 `extension.kind: domain|runtime`（运行时扩展无业务对象；
  `schema-compiler` 跳过其 DDL 编译，`contract-checker` 校验枚举）
- 工具：新增 `tools/relay`（状态机参考实现 + PostgreSQL 语句模板）；`schema-compiler` 跳过 runtime 扩展
- CI：PostgreSQL 任务执行 `outbox.ddl` + `tools/ci/outbox-smoke.sql`
- 文档：本 ADR、`extensions/README.md`、`docs/KNOWN-LIMITATIONS.md` §5、`CHANGELOG.md`
- 核心契约：**无改动**（不新增契约类、不改 01–06）

## 3. 兼容性分析

- 级别判定：**MINOR**（纯新增）。

| 变更 | 判定 | 依据 |
|---|---|---|
| 新增 `extensions/outbox/` 1.0.0 | MINOR | 新增可选扩展，不采用者不受影响 |
| `extension.kind` 可选字段（默认 `domain`） | MINOR | 可选字段新增；既有扩展行为不变 |
| 新增 `tools/relay` | 工具加法 | 不影响既有工具与契约 |
| 新增 `EIS-` 错误码 | 无 | 扩展使用自有前缀 `OBX-`；不占用核心命名空间 |

- 破坏点：无。未声明 `kind: runtime` 的扩展仍按业务扩展编译 DDL。

## 4. 决策

### 4.1 归属与形态

- 归属：**扩展契约**（跨域运行时能力），不新增第七类核心契约（ADR-0012 补充规则）；
- `extensions/outbox/` 自包含：表结构、规则、参考 relay、用例都在扩展内；
- 不提供业务对象/命令/读取面，因此 `manifest.kind = runtime`（无 DDL 由 `schema-compiler` 生成）；
- 本扩展不新增 CONFORMANCE 等级；不采用 Outbox 的部署不受影响。

### 4.2 生产段（Outbox）

| 决策点 | 规定 |
|---|---|
| 原子捕获 | Outbox 行与业务数据同一本地事务提交；跨库**禁止双写**（用 CDC 或流程编排）。修正提案措辞：「跨库时不得使用 Outbox」过强——CDC 本身也是 outbox 形态 |
| 投递语义 | at-least-once；不承诺 exactly-once；消费方幂等 |
| 分片 | 分片键 = `aggregate_id`（聚合根 ID），不得是 outbox 行 ID / event_id；**分片内串行、分片间并行**（修正提案「同一分片同一时刻只能一个实例」为分片内约束） |
| 聚合内顺序 | `seq` 聚合内单调递增且唯一（`(aggregate_id, seq)` UNIQUE）；前一 `seq` 未 `sent` 时，后续 `seq` 不得被认领/投递（顺序屏障）；跨聚合不承诺顺序 |
| 确认后置 | broker 确认成功后才标记 `sent`；禁止先标记后投递 |
| 状态机 | `pending → processing → sent`；失败回 `pending` / 超限或不可重试 → `dead`；`processing` 持有租约（`lease_owner` + `lease_expires_at`），过期可回收 |
| 失败 | 可重试：指数退避（有上限）；不可重试（schema/序列化/明确拒绝）：直接 `dead`；禁止无限重试 |
| 死信 | `dead` 可观测、可**显式**重放；不自动无限重放 |
| 清理/回放 | `sent` 定期清理或分区 drop；outbox 是**投递真相源**，不是事件历史；回放走事件存储 / broker retention（修正提案的表述冲突） |
| 监控 | pending 数、最老 pending 年龄、失败率、死信数；outbox lag 与 consumer group lag **分段**监控 |

### 4.3 消费段（Inbox，并入 #34）

- 唯一键 `(consumer_group, event_id)`；同一消费者组对同一事件只处理一次；
- 状态：`processing`（持有租约，或退避等待）/ `done`（重复投递忽略）/ `dead`（需显式重放）；
- 不同 `consumer_group` 独立处理同一事件；死信可重放，重放不改变事件身份。

### 4.4 参考实现（`tools/relay`）

- 范围：状态机语义参考 + PostgreSQL 语句模板（`--print-sql`，claim 使用 `FOR UPDATE SKIP LOCKED`）；
- 不绑定 broker 客户端、中间件选型与部署形态；不替代生产 relay；
- `--self-test` 用确定性内存存储验证：分片并行/顺序屏障、确认后置、退避、死信重放、租约回收、Inbox 幂等；
- CI PostgreSQL 冒烟执行 `outbox.ddl` + `tools/ci/outbox-smoke.sql`（唯一约束、状态机、租约、Inbox）。

### 4.5 明确不做

| 不做项 | 理由 |
|---|---|
| `contracts/07-delivery-contract` | 等于改核心，与「六类契约冻结」矛盾（ADR-0012） |
| 分片数/线程模型/relay 部署形态 | 实现自由，因部署拓扑而异 |
| 消息中间件选型与客户端配置 | 部署方职责 |
| exactly-once | 需要分布式事务/幂等 sink，超出 at-least-once 契约 |
| outbox 作为历史回放源 | 回放语义属事件存储/broker retention |
| CDC/ESB 的选型与配置 | 集成拓扑属部署方职责 |
| 用 outbox 表承载跨库业务事务 | 双写不可原子；用 CDC 或流程编排 |

## 5. 迁移方案

- 部署：执行 `extensions/outbox/outbox.ddl` 建表；接入 relay（可用 `tools/relay --print-sql` 为模板）；
- 业务域：在写事务内追加 Outbox 行并分配 `seq`；事件仍按既有事件契约产生；
- 消费方：按 `(consumer_group, event_id)` 建 Inbox 幂等；
- 数据：新表，无核心表回填；`sent` 行按保留策略清理。

## 6. 回滚方案

- 停用 relay 后 `DROP TABLE inbox_message, outbox_message`；核心契约与既有表不受影响；
- 回滚 = revert 本 ADR + 扩展目录 + CI 步骤；`kind` 字段可保留（默认 `domain`）。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 扩展清单 | `extensions/outbox/manifest.yaml` | `kind: runtime`；规则引用 |
| 表结构 | `extensions/outbox/outbox.ddl` | outbox_message + inbox_message、唯一/状态/租约约束、分片索引 |
| 规则 | `extensions/outbox/rules/delivery.rules.yaml` | OBX-001..012 + `not_in_contract` + 验收映射 |
| 说明 | `extensions/outbox/README.md` | 捕获/顺序/relay/Inbox/监控/非目标 |
| 参考 relay | `tools/relay` | 状态机 + PG 语句模板；`--self-test` / `--print-sql` |
| 用例 | `extensions/outbox/tests/outbox.test.yaml` | static（DDL/规则/监控）+ cli（relay 自测/SQL 模板） |
| CI 冒烟 | `tools/ci/outbox-smoke.sql`、`.github/workflows/ci.yml` | 唯一约束 / 状态机 / 租约 / SKIP LOCKED / Inbox |
| 扩展机制 | `tools/schema-compiler`、`tools/contract-checker`、`extensions/README.md` | `kind: runtime` 跳过 DDL 编译、枚举校验 |

## 8. 验收用例

- `python3 tools/e2e-runner extensions/outbox/tests/outbox.test.yaml`：10/10；
- `python3 tools/relay --self-test`：20 条断言全过；
- `python3 tools/relay --print-sql`：含 `FOR UPDATE SKIP LOCKED` 与 `inbox_message`；
- `python3 tools/schema-compiler check`：运行时扩展跳过且全过；
- `python3 tools/e2e-runner --all`：全绿（用例计数随新增用例更新）；
- CI PostgreSQL：`outbox.ddl` + `outbox-smoke.sql` 全过（唯一约束/状态机/租约/Inbox）。
