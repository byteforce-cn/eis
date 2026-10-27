# EIS Wave 1 实施计划：T-R009 排他约束 + 边界裁决 ADR

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 落地 open issue 评估中两个「零前置、可立即合并」项——#40① T-R009 有效区间不重叠的排他约束（参考实现对齐冻结规则），#33 跨边界缺口归属裁决（ADR-0012，一次钉死 #34–#39 的归属层）。

**Architecture:** #40① 由 `tools/schema-compiler` 在每张对象表后生成 `EXCLUDE USING gist`，`01-data-contract/core.ddl` 同步为 `business_object` 声明同一约束；约束采用**四维形式**（`id` 相等 + 系统时间区间相交 + 业务时间区间相交），因为 T-R005 已保证每个 id 至多一条当前记录，仅 `WHERE superseded_at IS NULL` 的写法在 T-R005 下恒不触发、属死约束。#33 产出 ADR-0012，把 #28/#29/#30/#31/#32/#34/#35/#36/#37/#38/#39/#41 逐条归入「核心契约 / 扩展契约 / 实现与运维」三层，并记录不做项与触发条件。

**Tech Stack:** Python 3.10+（stdlib + PyYAML + jsonschema）、PostgreSQL 16（btree_gist / GiST / partial exclusion）、JSON Schema、OpenAPI 3.1。

**Spec:** issue #40（T-R009 部分）与 #33；裁决依据 `03-time-contract/temporal.rules.yaml` T-R005/T-R009/T-R011、`docs/KNOWN-LIMITATIONS.md` §1.1/§1.3、`00-freeze/adr/template.md`、`06-evolution-contract/compatibility.rules.yaml`。

## Global Constraints

- 核心契约（01–06）冻结：任何工件改动走 ADR（`00-freeze/adr/template.md`）+ 可执行工件 + 验收用例。
- 每个任务结束 `python3 tools/e2e-runner --all` 必须全绿；无新增 e2e 用例时计数保持 `134/134`，不得改写期望值。
- DDL 断言放在 `tools/ci/ddl-smoke.sql`（CI 的 PostgreSQL 16 任务），本地用 `docker run postgres:16` 复现；测试不得依赖真实时钟。
- 提交信息 `fix:`/`docs:` 前缀；一个 issue 一个分支一个 PR；不自行合并、不跳过 CI。

## Review Focus

- **约束不是死约束**：`WHERE superseded_at IS NULL` 写法在 T-R005 唯一索引下无法触发；必须用四维形式，且用例能证明触发原因是 `exclusion_violation`（23P01）而非 `unique_violation`（23505）。
- **半开区间不被误杀**：`valid_to == next.valid_from`（相邻）与 `superseded_at == next.recorded_at`（正常封口链）必须允许写入。
- **冻结语义不动**：不改任何 Schema 字段、错误码与哈希公式；`contract-checker`/`compatibility-checker` 判定保持通过。
- **ADR 不越权**：边界裁决只记录归属与触发条件，不把扩展类提案写成已交付特性。

---

## Task 0：分支基线

- [ ] **Step 1**：`git fetch origin && git switch -c fix/tr009-exclusion-constraint origin/main`，确认干净基线。

## Task 1：ADR-0011（T-R009 落地决策）

**Files:**
- Create: `00-freeze/adr/0011-tr009-valid-overlap-constraint.md`
- Modify: `00-freeze/adr/README.md`（索引表）

**Interfaces:** 产出约束的正式定义（四维 EXCLUDE）、级别判定（PATCH）、迁移检测 SQL、回滚 `DROP CONSTRAINT`。

- [ ] **Step 1**：写 ADR-0011，含「为什么不是 `WHERE superseded_at IS NULL`」的论证（T-R005 已限制当前记录唯一）与「为什么四维形式覆盖 T-R009 的『同一系统时间视图』」。
- [ ] **Step 2**：`00-freeze/adr/README.md` 索引追加 0011（Accepted）。

## Task 2：schema-compiler 生成排他约束

**Files:**
- Modify: `tools/schema-compiler`（`compile_extension` 输出、`check_extensions` 断言、`cmd_self_test` 断言）

**Interfaces:**
- 生成物每表追加：`ALTER TABLE <table> ADD CONSTRAINT ex_<table>_valid_overlap EXCLUDE USING gist (id WITH =, tstzrange(recorded_at, superseded_at, '[)') WITH &&, tstzrange(valid_from, valid_to, '[)') WITH &&);`
- `check_extensions`：编译产物不含 `EXCLUDE USING gist` 即 `report.fail`。

- [ ] **Step 1（RED）**：`check_extensions` 增加断言并运行 `python3 tools/e2e-runner --all` → schema-compiler check 失败。
- [ ] **Step 2（GREEN）**：`compile_extension` 在 `uq_<table>_current` 之后输出 ALTER；`--self-test` 增加 `ex_accounting_balance_valid_overlap` 断言。
- [ ] **Step 3**：`python3 tools/schema-compiler compile --all`，确认 5 份扩展 DDL 均含约束。

## Task 3：核心 DDL 与时间契约说明

**Files:**
- Modify: `01-data-contract/core.ddl`（`CREATE EXTENSION IF NOT EXISTS btree_gist` + `business_object` 的 ALTER）
- Modify: `03-time-contract/temporal.ddl`（§D 由「可选（推荐）」改为「已强制」，`entity_id` 笔误改为 `id`，补四维形式与生成器出处）

- [ ] **Step 1**：`core.ddl` 增加扩展与约束（位置在 `uq_business_object_current` 之后）。
- [ ] **Step 2**：`temporal.ddl` §D 与 §E 示例同步；`03-time-contract/README.md` 若引用「可选」一并改（先 grep 确认）。

## Task 4：DDL 冒烟断言与文档同步

**Files:**
- Modify: `tools/ci/ddl-smoke.sql`（新增第 9 节：重叠拒绝 / 相邻允许 / 封口链允许 / 扩展表同约束）
- Modify: `docs/KNOWN-LIMITATIONS.md`（§1.1 标记已修复，§1.3 收窄残余）
- Modify: `CHANGELOG.md`（Unreleased）

- [ ] **Step 1**：冒烟新增断言：① `business_object` 同 id、系统区间相交、业务区间重叠 → 必须 `exclusion_violation`；② 相邻业务区间 → 允许；③ `superseded_at == recorded_at` 的封口链即便业务区间重叠 → 允许；④ `accounting_balance`（生成物）同样拒绝重叠。
- [ ] **Step 2**：本地 `docker run --rm -d -e POSTGRES_PASSWORD=eis -e POSTGRES_USER=eis -e POSTGRES_DB=eis -p 55432:5432 postgres:16` 跑 core/temporal/扩展 DDL + `ddl-smoke.sql`，全绿后停容器。
- [ ] **Step 3**：KL 与 CHANGELOG 更新，读写口径与 ADR 一致。

## Task 5：校验与 PR

- [ ] **Step 1**：`python3 tools/e2e-runner --all`、`python3 tools/contract-checker`、`python3 tools/compatibility-checker --standalone --old <旧> --new <新>`（本变更不动 Schema，注明 PATCH）。
- [ ] **Step 2**：push 分支，`gh pr create --base main --fill`，PR 正文含 `Closes #40` 的口径说明（仅 ① 落地）+ e2e 汇总行 + 四维约束论证。
- [ ] **Step 3**：`gh pr checks --watch` 全绿 → `gh pr merge --squash --delete-branch` → 本地 `git switch main && git pull`。

## Task 6：ADR-0012 边界裁决（独立分支）

**Files:**
- Create: `00-freeze/adr/0012-scope-boundary.md`
- Modify: `00-freeze/adr/README.md`

- [ ] **Step 1**：写裁决表（核心 / 扩展 / 实现与运维），逐条覆盖 #28–#39 与 #41，含「不做」与触发条件。
- [ ] **Step 2**：`docs/SCOPE-BOUNDARY.md` 是否另建：本 ADR 即权威，文档只在 `docs/ROADMAP.md` 加一处指针（避免双份权威）。
- [ ] **Step 3**：e2e 全绿 → PR（`docs: 边界裁决 ADR-0012`）→ 合并；合并后按裁决在 issue 上回帖并关闭 #33/#34。

## Task 7：验收

- [ ] **Step 1**：`git log --oneline origin/main -5` 确认合并；`gh pr list --state merged` 确认两条。
- [ ] **Step 2**：汇总：PR 链接、CI 结论、e2e 汇总行、剩余 issue 的归属层。
