# ADR-0011：T-R009 有效区间不重叠落地为排他约束（四维形式）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #40（① T-R009）；`03-time-contract/temporal.rules.yaml`（T-R005 / T-R006 / T-R009 / T-R011）、`03-time-contract/temporal.ddl`、`01-data-contract/core.ddl`、`tools/schema-compiler`、`tools/ci/ddl-smoke.sql`、`docs/KNOWN-LIMITATIONS.md` §1.1/§1.3

## 1. 变更原因

T-R009 是 `severity: error` 的冻结规则，且自声明 `enforced_by: [ddl-exclusion-constraint]`——但参考 DDL 从未真正输出该约束：

- `03-time-contract/temporal.ddl` §D 只有注释，且列名写作不存在的 `entity_id`（实际列为 `id`）；
- `tools/schema-compiler:247` 只生成 `uq_<table>_current`，从不生成 `EXCLUDE USING gist`；
- 结果：数据库层可写入互相重叠的有效区间（`docs/KNOWN-LIMITATIONS.md` §1.1），而 T-R008「时点查询至多返回一个版本」的唯一性依赖 T-R009（同文 §1.3），参考内核对重叠数据 `max(version)` 静默择一。

`docs/CONFORMANCE.md` 的 L2 要求「边界行为与参考内核一致」，L1 要求 DDL 可执行——约束缺失使 L1/L2 无法自证。这不是契约缺口（规则本身正确），而是**参考实现未等价于规范**（#40 的定性），唯一正确路径是修实现。

## 2. 影响范围

- 契约：时间契约（`03-time-contract/temporal.ddl` 说明与模板）与数据契约参考 DDL（`01-data-contract/core.ddl`）
- 扩展：全部 `extensions/*` 的 `schema-compiler` 生成产物（新增约束语句，无字段变化）
- 案例：无
- 工具：`tools/schema-compiler`（生成与校验）、`tools/ci/ddl-smoke.sql`（PostgreSQL 断言）
- Schema / 错误码 / 审计哈希：**不变**

## 3. 兼容性分析

- 级别判定：**PATCH**。依据 `06-evolution-contract/compatibility.rules.yaml`——无字段删除、无类型变更、无必填新增、无 API 增删；本次只让 DDL 与已冻结规则一致。
- 破坏点：**行为收紧**。此前可写入的违规数据（同 id、系统时间区间相交、业务时间区间相交）在加约束后会被拒绝；合规数据与既有用例不受影响（参考内核封口时 `prev.superseded_at == next.recorded_at` 且 `prev.valid_to == next.valid_from`，区间恒相邻）。
- 未采用方案：把约束写成 `WHERE superseded_at IS NULL`（issue #40 评估中的初版写法）。理由见 §4。

## 4. 决策：四维排他约束，而非当前记录谓词

```sql
ALTER TABLE <table> ADD CONSTRAINT ex_<table>_valid_overlap
    EXCLUDE USING gist (
        id WITH =,
        tstzrange(recorded_at, superseded_at, '[)') WITH &&,
        tstzrange(valid_from, valid_to, '[)') WITH &&
    );
```

**为什么不是 `... (id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&) WHERE (superseded_at IS NULL)`：**

1. T-R005 的 `uq_<table>_current`（`ON <table> (id) WHERE superseded_at IS NULL`）已保证每个 id **至多一条**当前记录。因此「仅当前记录」上的排他约束**恒不可能触发**——是死约束，只能制造「已强制」的假象。
2. T-R009 的原文是「同一实体在**同一系统时间视图下**的有效区间互不重叠」。形式化即：两条记录的系统时间区间相交（二者同处一个系统时间视图）**且**业务时间区间相交，即违规。这正是上式的两个 `&&` 维度。
3. 该形式与既有语义一致，不会误杀合法链路：
   - 正常封口与迟到的追加（T-R006 / T-R011）：旧记录 `superseded_at` 等于新记录 `recorded_at`，系统区间**相邻**（半开区间）→ 允许，即便业务区间重叠（修正历史正是 T-R011 允许的形态）；
   - 相邻业务区间（`prev.valid_to == next.valid_from`）→ 允许；
   - 被拒绝的只有「同一系统时间视图内两条记录同时声称同一业务时点」——这正是 T-R008 要排除的情形。

**残余（不在本 ADR 射程）**：`03-time-contract/query-templates.sql` 的通用 `as_of_valid` 只含业务时间谓词，不叠加系统时间轴；对存在修正历史的表，单轴业务时间查询仍可能命中多条记录。展开函数（如 `accounting_balance_as_of_valid`）已显式带 `superseded_at IS NULL`。该残余记入 `docs/KNOWN-LIMITATIONS.md` §1.3，待查询模板单独演进。

## 5. 迁移方案

- 新部署：`schema-compiler compile --all` 的产物与 `core.ddl` 直接含约束。
- 存量部署：先检测违规对，修正后加约束。

```sql
-- 检测：同 id、系统区间相交且业务区间相交的记录对
SELECT a.id, a.version AS v_a, b.version AS v_b
  FROM <table> a JOIN <table> b ON a.id = b.id AND a.version < b.version
 WHERE tstzrange(a.recorded_at, a.superseded_at, '[)') && tstzrange(b.recorded_at, b.superseded_at, '[)')
   AND tstzrange(a.valid_from,   a.valid_to,     '[)') && tstzrange(b.valid_from,   b.valid_to,     '[)');
```

- 加约束：`ALTER TABLE <table> ADD CONSTRAINT ex_<table>_valid_overlap EXCLUDE USING gist (...);`
- 前提：`CREATE EXTENSION IF NOT EXISTS btree_gist;`（`id` 的 `=` 走 btree_gist 的 GiST 算子类）。

## 6. 回滚方案

```sql
ALTER TABLE <table> DROP CONSTRAINT IF EXISTS ex_<table>_valid_overlap;
```

回滚后行为回到「规范要求但 DDL 不强制」，须同步把 `docs/KNOWN-LIMITATIONS.md` §1.1 复记为未修复。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 生成器 | `tools/schema-compiler` | 每表输出 `ex_<table>_valid_overlap`；`check_extensions`/`--self-test` 断言存在 |
| 核心 DDL | `01-data-contract/core.ddl` | `btree_gist` + `business_object` 同约束 |
| 时间契约说明 | `03-time-contract/temporal.ddl` | §D 由「可选（推荐）」改为「已强制」，修正 `entity_id` 笔误 |
| DDL 冒烟 | `tools/ci/ddl-smoke.sql` | 重叠拒绝（23P01）/ 相邻允许 / 封口链允许 / 扩展表同约束 |
| 已知限制 | `docs/KNOWN-LIMITATIONS.md` | §1.1 标记已修复；§1.3 收窄为查询模板残余 |
| 变更记录 | `CHANGELOG.md` | Unreleased |

## 8. 验收用例

- `tools/ci/ddl-smoke.sql` 第 9 节：4 条断言全过（CI `PostgreSQL DDL 冒烟` 任务）；
- `python3 tools/e2e-runner --all`：用例 134/134、场景 1/1、流水线 5/5（含 `schema-compiler check` 对生成物的约束断言）；
- `python3 tools/contract-checker`：通过（无 Schema/契约变更）；
- `python3 tools/schema-compiler --self-test`：通过（含 `ex_accounting_balance_valid_overlap` 断言）。
