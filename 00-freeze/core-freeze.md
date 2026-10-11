# 核心冻结清单（EIS Spec v1.0）

- **冻结日期**：2026-10-08
- **核心版本**：1.0.0
- **约束力**：以下内容一经冻结，只能通过 ADR（见 `adr/README.md`）修改，且必须附带可执行工件与验收用例。

---

## 1. 冻结范围

### 1.1 数据契约的元结构

- 业务对象必备元字段：`id`、`version`、`valid_from`、`valid_to`、`recorded_at`、`superseded_at`、`created_by`、`created_at`、`updated_by`、`updated_at`
- 核心域：`eis_id`（UUIDv7）、`eis_version`（BIGINT，≥1）、`eis_timestamp`（TIMESTAMPTZ(6)，UTC 微秒）
- 事件必备字段：`id`、`type`、`occurred_at`、`recorded_at`、`actor`、`payload`、`idempotency_key`
- 命令必备字段：`id`、`type`、`issued_at`、`issuer`、`payload`、`idempotency_key`、`status`
- 命名规则：`type` 形如 `^[a-z][a-z0-9_.]*$`

工件：`01-data-contract/*.schema.json`、`01-data-contract/core.ddl`

### 1.2 操作契约的元结构

- 命令 API：`POST /commands/{commandType}`，必含 `payload` + `idempotency_key`；响应 202/400/409
- 查询 API：支持 `as_of`（业务时间）与 `recorded_as_of`（系统时间）时点参数
- 事件发布：`events.{eventType}` 通道；事件负载必须引用 `eis://core/event/v1`
- 错误码格式：`EIS-{http_status}-{seq}`

工件：`02-operation-contract/*.yaml`

### 1.3 时间契约的语义

- 双时间轴：业务时间（`valid_from`/`valid_to`）+ 系统时间（`recorded_at`/`superseded_at`）
- 区间语义：半开区间 `[from, to)`；`NULL` 表示“直到无穷”
- 时区/精度：UTC、微秒（6 位小数）
- 时点查询：`as_of` 语义下每个实体至多返回一个版本
- 系统时间轴 append-only：`recorded_at` 记录不可修改，修正一律以新版本追加

工件：`03-time-contract/temporal.rules.yaml`、`query-templates.sql`

### 1.4 授权契约的接口

- 主体类型：`person`、`organization`、`system`、`proxy`
- 解析接口：`POST /resolve`（主体 + 时点 → 角色/权限）、`POST /check`（主体 + 权限 + 时点 → allowed + reason）
- 授权判定必须支持时点（`as_of`），即历史时点的角色必须可重建
- SoD 规则结构：冲突权限集合 + 作用域 + 强制方式（prevent/warn）

工件：`04-authz-contract/*.json`、`resolution.api.yaml`、`sod.rules.yaml`

### 1.5 审计契约的元结构

- 审计条目必备字段：`id`、`sequence`、`timestamp`、`actor`、`action`、`resource`、`payload`、`hash`、`prev_hash`
- 哈希链公式与创世规则（`prev_hash = 64×"0"`）见 `05-audit-contract/hash-chain.spec.md`
- 审计表 append-only：禁止 UPDATE / DELETE
- 序列号：从 1 开始，单调递增且连续

工件：`05-audit-contract/audit.schema.json`、`audit.ddl`、`hash-chain.spec.md`、`verify.tool`

### 1.6 演进契约的元规则

- 版本格式：`MAJOR.MINOR.PATCH`（定义见 `version-policy.md`）
- 破坏性变更必须标记 MAJOR，且必须提供迁移 + 回滚 + 对账路径
- 兼容性判定以 `06-evolution-contract/compatibility.rules.yaml` 为唯一权威
- 任何变更（含核心修改）必须走：ADR → 可执行工件 → 验证

工件：`06-evolution-contract/*`

---

## 2. 未冻结范围（可自由演进）

| 范围 | 说明 |
|------|------|
| 领域扩展 | `extensions/*` 独立版本化，不与核心同步升版 |
| 应用案例 | `cases/*` 自由组合扩展 |
| 工具实现 | `tools/*` 的实现语言与算法可替换，只要通过契约测试 |
| 性能与容量 | 非契约内容，由部署决定 |

## 3. 解冻流程

1. 提交 ADR（含变更原因、影响范围、兼容性分析、迁移方案、回滚方案）
2. 附带可执行工件（Schema / DDL / 测试用例 / 工具变更）
3. 通过 `acceptance.yaml` 中相关验收项
4. 按 `version-policy.md` 确定版本号并合并

> 无工件的变更一律拒绝。
