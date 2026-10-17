# EIS 开放 issue #12/#13 处理计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（用户指示「将远程 issue 全部评估处理」，inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 处理 `byteforce-cn/eis` 两个开放 issue：#13 `extensions/hr` 的 Employee 增加`employment_type` / `work_location`（加法演进、迁移、用例、兼容性判定）；#12 AI 集成 RFC 完成技术评估并留痕（npm 发布等依赖维护者决策，本轮不实现）。

**Architecture:** #13 走扩展加法演进路线：验收用例先行 → Schema/OpenAPI/处理器 → 兼容性夹具 + 迁移（扩展 1.0.0 → 1.1.0，MINOR，ADR-0009）；顺带修 `tools/migration-generator` 不识别 `allOf` 扩展对象 Schema 的缺口，使真实 Employee 契约的迁移可由工具生成并被 `kind: migrate` 断言。#12 输出评估结论并以 issue 评论留痕。

**Tech Stack:** Python 3.10+（stdlib + PyYAML + jsonschema）、JSON Schema 2020-12、OpenAPI 3.1、PostgreSQL 16 DDL。

**Spec:** `https://github.com/byteforce-cn/eis/issues/13`、`https://github.com/byteforce-cn/eis/issues/12`；`00-freeze/version-policy.md`、`06-evolution-contract/compatibility.rules.yaml`、`extensions/README.md §3/§5`、`00-freeze/adr/template.md`。

## Global Constraints

- 每个任务结束必须 `python3 tools/e2e-runner --all` 全绿；用例计数变化同步 `README.md`/`CONTRIBUTING.md`/`CHANGELOG.md`/`docs/CONFORMANCE.md`/`docs/KNOWN-LIMITATIONS.md` 的计数口径。
- 扩展不得修改核心契约；Employee 变更为加法演进（MINOR），ADR-0009 记录判定与工件；扩展错误码用 `HR-` 前缀。
- 空值语义与既有可选字段一致：缺省/显式 null 均落 NULL；`employment_type` 受控枚举 `full_time|part_time|intern|contract`；`work_location` 非空字符串或 null。
- 迁移 V202 与 `tools/schema-compiler compile hr` 产物对齐（列类型、约束命名 `ck_hr_employee_employment_type`）；已分发的 V201 不改动。
- 测试必须确定性、离线可跑（无网络/外部服务/真实时钟）；提交前缀 `feat:`/`fix:`/`docs:`。
- 交付：分支 `feat/hr-employment-work-location` → PR（含 `Closes #13`）→ CI 全绿 → `--squash --delete-branch` 合并（按 `/root/opensource/AGENTS.md`：eis 用 squash）。
- #12 在维护者给出 npm scope/发布凭证/Node 工具链与交付范围决策前不实现。

## Review Focus

- 建档未带两字段 → 必须为 null，且不触发任何校验错误（历史数据兼容）。
- `employment_type` 非法取值、`work_location` 空串 → `HR-400-001` 拒绝且不落库。
- 更新命令可写两字段；终态员工仍不可更新。
- 读投影（`read_projection`）含新字段，`id_number_hash` 剔除语义不受影响。
- 兼容性判定恰为 MINOR「可选字段新增」×2：不得误报「枚举取值扩展」或 MAJOR。
- V202 回滚只 DROP 新列；不重写既有行、不迁移数据。
- `migration-generator` 的 `allOf` 支持不得影响平铺 Schema 既有行为（演进契约 migrate 用例回归）。

---

## Task 0（工作流）：分支与基线

**Files:** 无

- [x] **Step 1**：`git fetch origin`，`git switch -c feat/hr-employment-work-location origin/main`；确认基线 `bcc02de`、`git status` 干净、`python3 tools/e2e-runner --all` 基线 108/108 通过。

## Task 1（RED，issue #13）：验收用例先行

**Files:**
- Modify: `extensions/hr/tests/hr.test.yaml`

**Interfaces:**
- scenario `hr.employment-work-location`：T1 建档带 `employment_type: full_time` / `work_location: 上海`；T2 建档不带 → 断言 null；T3 `hr.employee.update` 改为 `intern` / `杭州`；断言含 `object-field`（`read_projection: true`，验证读投影返回新字段）。
- scenario `hr.employment-type-invalid`：T1 `employment_type: freelance` → `HR-400-001`；T2 `work_location: ""` → `HR-400-001`；断言两条均未落库。

- [x] **Step 1（RED）**：新增上述两条 `kind: scenario`；运行 `python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml` → 两条失败（字段未实现）。
- [x] **Step 2**：确认其余用例仍通过（未破坏既有语义）。

## Task 2（GREEN，issue #13）：契约与处理器

**Files:**
- Modify: `extensions/hr/objects/employee.schema.json`
- Modify: `extensions/hr/operations/employee-create.openapi.yaml`、`extensions/hr/operations/employee-update.openapi.yaml`
- Modify: `extensions/hr/handlers.py`
- Modify: `tools/lib/kernel.py`（`object-field` 断言支持 `read_projection: true`）

**Interfaces:**
- Schema：`employment_type`（`type: ["string","null"]`，`enum: [full_time, part_time, intern, contract]`，中文 description，可选）；`work_location`（`type: ["string","null"]`，`minLength: 1`，中文 description，可选）——均为加法。
- handlers：`EMPLOYMENT_TYPES = ("full_time","part_time","intern","contract")`；`_optional_choice(api, value, allowed, label)` / `_optional_text(api, value, label)`；create/update 写入两字段，非法值 `HR-400-001`。
- kernel 断言：`object-field` 新增可选 `read_projection: true`，走 `kernel.read_projection`（默认仍为 `as_of`）。

- [x] **Step 1（GREEN 契约）**：Schema 与两份 OpenAPI 载荷增加两字段（含 description）。
- [x] **Step 2（GREEN 处理器）**：handlers create/update 校验并写入；非法枚举/空串拒绝。
- [x] **Step 3（GREEN 断言）**：kernel `object-field` 支持 `read_projection`。
- [x] **Step 4**：运行 `python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml` → 全绿。

## Task 3（issue #13）：兼容性、迁移与工具修复

**Files:**
- Create: `extensions/hr/tests/compat/employee-v1.schema.json`（现行 Employee 去掉两新字段；外部 `$ref` 字符串逐字保留）
- Create: `extensions/hr/migrations/V202__hr_employee_employment_fields.sql`、`V202__hr_employee_employment_fields.rollback.sql`
- Modify: `extensions/hr/tests/hr.test.yaml`（compat / migrate / static 用例）
- Modify: `tools/migration-generator`（`allOf` 领域属性合并 + 自测）

**Interfaces:**
- `domain_properties(doc) -> (props: dict, required: set)`：顶层 `properties`/`required` + `allOf` 内联项合并（跳过外部 `$ref`）；`generate()` 改用它。
- 用例：`kind: compat`（old fixture vs 现行 schema，`expect_level: MINOR`，`expect_kinds: ["可选字段新增"]`）；`kind: migrate`（table `hr_employee`，`expect_contains` 两 `ADD COLUMN ... TEXT;`，`rollback_contains` 两 `DROP COLUMN IF EXISTS ...;`）；`kind: static`（V202 含 `ADD COLUMN employment_type` / `ADD COLUMN work_location` 与 `ck_hr_employee_employment_type`）。
- V202：`ALTER TABLE hr_employee ADD COLUMN employment_type TEXT;`、`ADD COLUMN work_location TEXT;`、`ADD CONSTRAINT ck_hr_employee_employment_type CHECK (employment_type IN ('full_time','part_time','intern','contract'));`；回滚逆序 DROP。

- [x] **Step 1（RED 工具）**：`tools/migration-generator --self-test` 增 allOf 断言（旧平铺行为不变 + allOf 可选新增生成 ADD COLUMN）→ 失败。
- [x] **Step 2（GREEN 工具）**：实现 `domain_properties` 并接入 `generate()`；自测通过。
- [x] **Step 3（夹具与用例）**：建 compat 夹具；`hr.test.yaml` 增 compat/migrate/static 三条 → 先失败。
- [x] **Step 4（GREEN 迁移）**：`python3 tools/migration-generator --old ... --new ... --table hr_employee` 产出草案，按 schema-compiler 产物补齐约束与注释，落 V202 + rollback；运行 `python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml 06-evolution-contract/tests/evolution-contract.test.yaml` 全绿。

## Task 4（issue #13）：版本、ADR 与文档计数

**Files:**
- Modify: `extensions/hr/manifest.yaml`（1.0.0 → 1.1.0）、`extensions/hr/operations/*.openapi.yaml`（`info.version` → 1.1.0）、`extensions/hr/README.md`、`extensions/README.md`、`README.md`、`CONTRIBUTING.md`、`CHANGELOG.md`、`docs/CONFORMANCE.md`、`docs/KNOWN-LIMITATIONS.md`
- Create: `00-freeze/adr/0009-hr-employment-work-location.md`；Modify `00-freeze/adr/README.md`（目录表）

**Interfaces:**
- ADR-0009：变更原因（issue #13，spa/server 阻塞证据）、影响范围（hr 扩展，核心不动）、兼容性（MINOR「可选字段新增」×2，无破坏点）、迁移（V202 + 回滚 + 空值语义）、可执行工件清单、验收（scenario/compat/migrate/static）。
- 计数：以实际 `e2e-runner --all` 输出为准，同步全部文档计数。

- [x] **Step 1**：版本载体升 1.1.0（manifest + 11 份 operation）。
- [x] **Step 2**：写 ADR-0009 与 ADR 目录表；更新各 README/CHANGELOG 口径。
- [x] **Step 3**：`python3 tools/e2e-runner --all` → 全绿并记录计数；同步计数文档；提交。

## Task 5（issue #12）：评估与留痕

**Files:** 无（评估结论以 issue 评论留痕）

- [x] **Step 1**：评估：无外部依赖的阶段（CI 生成 spec-pack + MANIFEST + 自校验、4 个 Skills、AI-INTEGRATION 指南）与有依赖阶段（npm 打包/发布、provenance、Node 工具链）分离；列出需维护者决策项（npm scope 与凭证、版本/通道策略、Skills 归属、1 小时验收的演练可复现性）。
- [x] **Step 2**：`gh issue comment 12 --body-file <评估>`（修正原提案中与仓库现状不符的路径：`verify.tool` 在 `05-audit-contract/`、时间契约目录为 `03-time-contract/`；冻结向量以 `audit-verifier --vector` 与 `05-audit-contract/tests/fixtures/` 为准）。
- [x] **Step 3**：不实现 #12（依赖维护者决策与 npm 发布权限）。

## Task 6（收尾）：推送、PR、CI 与合并

- [x] **Step 1**：`git push -u origin feat/hr-employment-work-location`。
- [x] **Step 2**：`gh pr create --base main --title "feat(extensions/hr): 员工增加雇佣类型/工作地点（issue #13）"`，正文含验收对照、ADR 链接、`Closes #13`、`e2e-runner --all` 汇总行。
- [x] **Step 3**：`gh pr checks --watch` 全绿；`gh pr merge --squash --delete-branch`。
- [x] **Step 4**：`git switch main && git pull`；确认 #13 关闭；在 #13 留 PR 链接评论。
