# Approval 区块顺序语义实施计划（issue #18）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（用户「评估处理全部 issue」授权；inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 处理 issue #18：为 `extensions/approval` 声明**区块阶段/顺序语义**，使「HR 未确认前财务不能确认」成为服务端权威（而非界面行为），含稳定错误码、`not_applicable` 跳过与重提重置口径、兼容性 MINOR 判定与可执行用例。

**Architecture:** 采用 issue 倾向的「契约声明顺序」方案，并把顺序做成**显式可选字段 `ApprovalSection.step_order`**（而非仅依赖 `section_ids` 数组位置）：新增可选字段使 `compatibility-checker` 可给出 MINOR 机器判定；序号随读投影可见、规则实现不依赖父对象数组；`section_ids` 数组顺序仍定义为与 `step_order` 一致。规则前置于 `approval.section.confirm` 与 `approval.section.complete`（任何 pending→confirmed 的写路径），违规返回 `APR-409-007`；`reject` 不打顺序门（打回直接令单据 rejected）。历史数据 `step_order` 为空时按 `section_ids` 位置回退。

**Tech Stack:** JSON Schema 2020-12、OpenAPI 3.1、Python 参考内核处理器、e2e-runner（scenario/compat/migrate）。

**Spec:** issue #18；`extensions/approval/{manifest.yaml,rules/*,objects/*,operations/*,handlers.py}`；ADR 模板与版本政策。

## Global Constraints

- 扩展不得修改核心；approval 1.0.1 → 1.1.0（MINOR）；错误码用 `APR-` 前缀。
- 既有用例语义不得破坏（现存区块用例均按顺序确认，应保持通过）。
- 字段名不得与 PostgreSQL 保留字冲突：**不得用 `order`**，采用 `step_order`。
- 顺序门覆盖 `confirm` 与 `complete`（system 回写同为确认语义）；`not_applicable` 就绪不阻塞；`resubmit` 重置状态但保留 `step_order`。
- 每个任务后 `python3 tools/e2e-runner --all` 全绿；计数变化同步全部口径文档。
- 交付：分支 `feat/approval-section-order` → PR（`Closes #18`）→ CI 全绿 → squash 合并 → #18 交付评论。

## Review Focus

- **乱序必经拒绝**：`[hr, finance]` 先确认 finance（含 system `complete`）→ `APR-409-007` 且不落状态；按序确认全通过。
- **not_applicable 语义**：不适用的前序不阻塞；但更早的 `pending` 区块仍阻塞（不得把「不适用」误当「全部跳过」）。
- **重提后顺序生效**：`resubmit` 只重置状态，`step_order` 不变；重走后仍先 hr 后 finance。
- **兼容判定恰为 MINOR**：「可选字段新增」×1；不得误报 MAJOR/枚举类变更；fixture 的外部 `$ref` 字符串与现行 schema 逐字一致。
- **迁移可生成**：`kind: migrate` 产出 `ADD COLUMN step_order BIGINT;` 与回滚 `DROP COLUMN IF EXISTS step_order;`；历史行为 NULL 不回填。
- **权限先于顺序**：属主不匹配仍先报 `APR-403-002`（不泄露顺序信息给无权限主体）。
- **既有回归**：简单模式、撤回、重提、属主不匹配等既有用例语义不变。

---

## Task 0（工作流）：分支与基线

- [x] **Step 1**：`git fetch origin`；`git switch -c feat/approval-section-order origin/main`；基线 `cbd7abb`、工作区干净、`e2e-runner --all` → 126/126。

## Task 1（RED，issue #18）：验收用例先行

**Files:** Modify `extensions/approval/tests/approval.test.yaml`

**Interfaces:**
- scenario `approval.section-order-reject`：`[hr, finance, system]`，先 finance confirm 与 system complete → `APR-409-007`；按序后完成；断言 `step_order` = 0/1/2、request approved；
- scenario `approval.section-order-not-applicable`：`[hr, pm(applicable=false), finance]`，先 finance → `APR-409-007`；hr 确认后 finance 通过并完成；
- scenario `approval.section-order-resubmit`：hr 确认 → finance 打回 → 重提 → 先 finance → `APR-409-007`；再按序完成；
- `kind: compat`：`tests/compat/approval-section-v1.schema.json`（不含 `step_order`）vs 现行 schema → MINOR、`["可选字段新增"]`；
- `kind: migrate`：同上两文件、表 `approval_section` → `ADD COLUMN step_order BIGINT;` / `DROP COLUMN IF EXISTS step_order;`。

- [x] **Step 1（RED）**：新增 5 条用例与 compat 夹具（先只建夹具占位）；运行 `python3 tools/e2e-runner extensions/approval/tests/approval.test.yaml` → 新增用例失败（乱序未被拒、migrate/compat 无差异、`step_order` 不存在）。

## Task 2（GREEN，issue #18）：契约、处理器与规则

**Files:** Modify `extensions/approval/objects/approval-section.schema.json`、`objects/approval-request.schema.json`、`handlers.py`、`manifest.yaml`；Create `extensions/approval/rules/section-order.yaml`

**Interfaces:**
- Schema：`ApprovalSection.step_order`（`["integer","null"]`、`minimum: 0`、中文 description：处理序号 / 前序就绪前置 / 历史可空按 section_ids 回退）；`ApprovalRequest.section_ids` description 声明「数组顺序 = 处理顺序，与各区块 step_order 一致」。
- handlers：`_sections_in_order(api, request)`（`step_order` 优先，空值按 `section_ids` 位置回退）；`_require_prerequisites(api, request, section)` 在 `confirm_section`（权限校验之后）与 `complete_section`（状态校验之后）调用，违规 `APR-409-007`；`submit_request` 按数组索引写 `step_order`。
- manifest：`version: "1.1.0"`；rules 增 `section_order`；invariants 增「确认顺序受前序就绪约束」。
- rule 文件：`approval.section_order`（statement/applies_to/on_violation `APR-409-007`/tests）。

- [x] **Step 1**：Schema 与 rule 文件、manifest 更新。
- [x] **Step 2**：handlers 写入顺序与前置校验；运行 `python3 tools/e2e-runner extensions/approval/tests/approval.test.yaml` → scenario 与 compat/migrate 全绿。
- [x] **Step 3**：`python3 tools/contract-checker`（清单/规则/保留字）与 `python3 tools/schema-compiler compile approval` 通过。

## Task 3（issue #18）：操作契约与扩展文档

**Files:** Modify `extensions/approval/operations/{submit-request,section-confirm,section-complete,section-reject,request-resubmit,request-withdraw,decide}.openapi.yaml`（`info.version` → 1.1.0；submit/confirm/complete/resubmit 描述补顺序语义与 `APR-409-007`）、`extensions/approval/README.md`、`extensions/README.md`

- [x] **Step 1**：操作契约与两处 README 更新（对象表补 `step_order`、命令表补顺序前置、错误码补 `APR-409-007`、规则清单补 `section-order`）。

## Task 4（收尾文档）：ADR、计数与变更记录

**Files:** Create `00-freeze/adr/0010-approval-section-order.md`；Modify `00-freeze/adr/README.md`、`CHANGELOG.md`、`README.md`、`CONTRIBUTING.md`、`docs/CONFORMANCE.md`、`docs/KNOWN-LIMITATIONS.md`、`docs/LANDING-IAM.md`

- [x] **Step 1**：ADR-0010（原因/影响/兼容 MINOR/迁移与回退/工件/验收）；ADR 目录表登记。
- [x] **Step 2**：`python3 tools/e2e-runner --all` 记录计数（预期 131/131）；同步计数与 CHANGELOG。

## Task 5（收尾）：推送、PR、CI、合并与 #18 评论

- [x] **Step 1**：提交（feat 契约与处理器、docs 文档计数）；`git push -u origin feat/approval-section-order`；`gh pr create`（标题 `feat(extensions/approval): 区块顺序语义与 APR-409-007（issue #18）`，正文含验收对照、ADR、`Closes #18`）。
- [x] **Step 2**：`gh pr checks --watch` 全绿；`gh pr merge --squash --delete-branch`；`git switch main && git pull`；确认 #18 关闭。
- [x] **Step 3**：在 #18 留交付评论（规则、错误码、兼容判定与验证结果）。
- [x] **Step 4**：标记本计划完成（小 docs PR）。
