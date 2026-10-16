# EIS 开放 issue #8/#9/#10 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（用户指定「尝试 PR 解决」，inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 修复 `byteforce-cn/eis` 三个开放 issue：#8 `approval` 读面权限声明；#9 审计链 `payload_digest` 覆盖事件正文；#10 `compatibility-checker` 可脱离 EIS 运行时独立运行。

**Architecture:** #8 沿用 ADR-0006 的「manifest.permissions 权限目录」形态，并为动态属主权限 `approval.section.confirm.<owner>` 在 contract-checker 增加**尾部通配 `.*`** 声明；读面 403 不新增 `APR-` 契约码（与 hr 先例一致，明确口径）。#9 在审计条目新增**可选** `payload_digest`（事件投影 `{id,type,payload}` 的规范 JSON SHA-256），哈希公式**仅在该字段存在时追加一行**——v1.0 条目哈希逐字节不变（冻结向量不动），验证工具新增 `--events` 模式对事件正文篡改给出 `payload_digest_mismatch`。#10 把兼容性 diff 内核提取为纯 stdlib 模块 `tools/lib/eis_compat.py`，新增 `--standalone`（内置规则缺省，不读仓库规则/不依赖 `eis_common`）、规则 JSON Schema 与独立验证指南。

**Tech Stack:** Python 3.10+（stdlib + PyYAML + jsonschema）、JSON Schema 2020-12、PostgreSQL 16 DDL、SHA-256、OpenAPI 3.1。

**Spec:** issue #8/#9/#10（`https://github.com/byteforce-cn/eis/issues/8`、`/9`、`/10`）；既有裁决证据：ADR-0006（读取面授权）、`00-freeze/version-policy.md §2`、`05-audit-contract/hash-chain.spec.md`、`docs/KNOWN-LIMITATIONS.md §2.2`、`docs/IMPLEMENTATION.md`。

## Global Constraints

- 每个任务结束必须 `python3 tools/e2e-runner --all` 全绿；用例计数随新增变化并同步 `README.md`/`CONTRIBUTING.md`/`CHANGELOG.md` 中的计数口径。
- 核心契约（01–06）冻结：修改一律 ADR（`00-freeze/adr/template.md`）+ 可执行工件 + 验收用例；扩展错误码不得占用 `EIS-`。
- 测试必须确定性、离线可跑（无网络/外部服务/真实时钟）。
- 兼容性判定依据 `06-evolution-contract/compatibility.rules.yaml`；#9 判 MINOR（可选字段新增）、#10 为工具重构（PATCH），均需 ADR 论证。
- 提交信息 `feat:`/`fix:`/`docs:` 前缀；一个 issue 一个 commit。
- **交付方式（用户指定）**：工作分支 `fix/open-issues-8-9-10`（基于 `main@37f6a56`），完成后 push 并 `gh pr create`，PR 正文含 `Closes #8`/`Closes #9`/`Closes #10` 与 `e2e-runner --all` 汇总行；不自行合并。

## Review Focus

- **#8 通配不弱化精确声明**：`approval.section.confirm.*` 只匹配 `<前缀>.<合法段>`，不得匹配 `approval.section.confirm`、`approval.section.confirmx` 或其他扩展命名空间；未声明引用仍必须失败。
- **#9 旧哈希逐字节不变**：无 `payload_digest` 的条目走 v1.0 规范化，冻结向量 `447c6e29…` 与既有四个 `.chain.json` 夹具验证结果不得变化（防止「顺手重构」破坏冻结语义）。
- **#9 digest 自身在哈希内**：篡改条目的 `payload_digest`（事件导出不变）必须报 `invalid_hash`；篡改事件正文（审计条目不变）必须由 `--events` 报 `payload_digest_mismatch`——两条路径都要有用例。
- **#9 边界确定性**：零事件命令的 digest 必须是 `canonical_payload([])="[]"` 的 SHA-256（常量钉住），不得省略字段或写入 null。
- **#10 独立模式行为等价**：`--standalone` 对四条 data 规则的 `requires` 与仓库规则文件一致；`compatibility-checker`/`eis_compat.py` 不得 import `eis_common`/`kernel`，从任意目录复制两文件即可运行。

---

## Task 0（工作流）：分支与 PR 基线

**Files:**
- 无文件变更

- [ ] **Step 1**：`git fetch origin && git switch -c fix/open-issues-8-9-10 origin/main`，确认 `git status` 干净、基线 `37f6a56`。

## Task 1（issue #8）：approval 读面权限与动态属主权限声明

**Files:**
- Modify: `tools/contract-checker`（`PERMISSION_ID_RE`、新增 `permission_matches`、`check_manifest_permissions`、`cmd_self_test`）
- Modify: `extensions/approval/manifest.yaml`（新增 `permissions`）、`extensions/approval/README.md`、`extensions/approval/tests/approval.test.yaml`、`extensions/README.md`（§7 通配说明）、`CHANGELOG.md`
- Create: `extensions/approval/tests/fixtures-authz.yaml`

**Interfaces:**
- `PERMISSION_ID_RE = ^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+(\.\*)?$`（仅允许**尾部** `.*`）。
- `permission_matches(ref: str, declared: set[str]) -> bool`：`ref in declared`，或存在 `d.endswith(".*")` 且 `ref` 匹配 `PERMISSION_ID_RE` 且 `ref.startswith(d[:-1])`（`d[:-1]` 含尾点，保证段边界）。
- approval `permissions`（7 条）：`approval.request.submit`/`approval.request.decide`/`approval.section.confirm.*`/`approval.section.complete`/`approval.request.resubmit`/`approval.request.withdraw` 均为 `kind: command`；`approval.request.read` 为 `kind: read`（覆盖列表/详情/决策/按 target 反查，非命令、不参与命令级 `/check`）。
- 授权夹具主体：`approval-reader`（person，有 `approval.request.read`）、`hr-service`（system，有 `approval.request.read`，对应 ims-hr 对账）、`approver`（person，无 read）。

- [ ] **Step 1（RED）**：`tools/contract-checker --self-test` 新增三条断言：①manifest 声明 `demo.section.confirm.*` 时测试引用 `demo.section.confirm.ops` 通过；②引用 `demo.section.confirm`（缺属主段）失败；③引用 `demo.section.confirmx` 失败。运行 → 自测失败（通配未实现）。
- [ ] **Step 2（GREEN checker）**：实现 `PERMISSION_ID_RE` 通配形态与 `permission_matches`（`ids` 精确集合 → 声明列表），`check_manifest_permissions` 的 `undeclared` 判定改用之。
- [ ] **Step 3（扩展声明）**：approval `manifest.yaml` 增加 7 条权限；README「命令」表补权限列/新增「读取面权限」小节，写明：4 个读端点、`kind: read` 非命令、未授权 fail-closed 403 且 **读面 403 无契约码**（reason_code 由 authz `/check` 给出 `NO_PERMISSION`）、IMS-HR 服务身份经 `approval.request.read` 反查。
- [ ] **Step 4（判据用例）**：新增 `fixtures-authz.yaml`；`approval.test.yaml` 增 3 条 `kind: authz`：reader 有 read 允许；approver 无 read 拒绝（`NO_PERMISSION`）；hr-service 有 read 允许。运行 `python3 tools/e2e-runner extensions/approval/tests/approval.test.yaml` 全绿。
- [ ] **Step 5（文档与全量）**：`extensions/README.md §7` 补通配声明规则（仅尾部 `.*`、段边界、命名空间校验）；`CHANGELOG.md` Unreleased 补记；`python3 tools/e2e-runner --all` 全绿；`git commit -m "feat(extensions/approval): 声明读面权限与动态属主权限目录 (#8)"`。

## Task 2（issue #9）：审计链 payload_digest 与事件正文篡改检出

**Files:**
- Modify: `05-audit-contract/audit.schema.json`、`05-audit-contract/hash-chain.spec.md`、`05-audit-contract/audit.ddl`、`05-audit-contract/verify.tool`、`05-audit-contract/tests/audit-contract.test.yaml`、`tools/audit-verifier`、`tools/lib/kernel.py`、`docs/KNOWN-LIMITATIONS.md`、`CHANGELOG.md`
- Create: `00-freeze/adr/0007-audit-payload-digest.md`、`05-audit-contract/tests/fixtures/digest-events.json`、`valid-digest.chain.json`、`tampered-events.json`

**Interfaces:**
- `verify.tool.compute_payload_digest(events: list) -> str`：对 `[{"id": e.get("id"), "type": e.get("type"), "payload": e.get("payload")} for e in events]` 用现有 `canonical_payload`（键排序、无空白、UTF-8）序列化后 SHA-256 小写 hex；空列表 → `"[]"` 的 SHA-256（冻结常量 `4f53cda1…`，在自测中断言）。
- `canonical_string(entry)`：`payload_digest` 存在且非空时在 `prev_hash` 行后追加 `"\n" + payload_digest.lower()`；否则保持 v1.0 原样。
- `verify_payload_digests(entries: list, events: list) -> list[dict]`：对含 `payload_digest` 的条目按其 `payload.event_ids` 顺序取事件重算；不一致 → `{type: "payload_digest_mismatch", sequence, expected, actual}`；事件缺失 → `{type: "payload_digest_missing_event", sequence, event_id}`；无 digest 条目跳过（v1.0 兼容）。
- CLI：`verify.tool CHAIN.json --events EVENTS.json`（EVENTS 支持 JSON 数组或 `{"events":[...]}`）；`tools/audit-verifier CHAIN.json --events EVENTS.json` 透传。
- kernel `_append_audit`：`entry["payload_digest"] = _VT.compute_payload_digest(events)`（在 `entry["hash"] = ...` 之前）。
- kernel 断言 `kind: audit-chain` 新增可选 `verify_payload_digest: true`：逐条按 `kernel.events` 重算比对。
- schema：`payload_digest` 可选、`^[0-9a-f]{64}$`；`audit.ddl` 增 `payload_digest TEXT` + `CHECK (payload_digest IS NULL OR payload_digest ~ '^[0-9a-f]{64}$')`。

- [ ] **Step 1（RED）**：`verify.tool` 自测新增 4 条断言（①含 digest 的链通过；②篡改事件正文 → `payload_digest_mismatch`；③零事件 → 冻结常量；④改 `payload_digest` 字段 → `invalid_hash`），运行 `05-audit-contract/verify.tool --self-test` → 失败（函数不存在）。同时把 `audit.schema.json` 加字段、自测夹具带 digest 断言。
- [ ] **Step 2（GREEN 规范层）**：实现 `compute_payload_digest`/规范化追加行/`verify_payload_digests`/`--events`；`audit-verifier` 透传与自测补充；`audit.schema.json` + `audit.ddl` 列与 CHECK。生成并提交三个夹具（用参考实现算出 hash/digest），保证 `valid-digest.chain.json` 通过、`tampered-events.json` 触发 mismatch。
- [ ] **Step 3（GREEN 内核）**：kernel 写入 `payload_digest`；`audit-chain` 断言支持 `verify_payload_digest`；kernel 自测补「digest 存在且可由事件复算」与「篡改事件正文可检出」。
- [ ] **Step 4（用例）**：`audit-contract.test.yaml` 增：`kind: chain` 合法 digest 链；`kind: cli` `verify.tool valid-digest --events digest-events` 通过；`kind: cli` `--events tampered-events` `expect_exit: 1` 且 stdout 含 `payload_digest_mismatch`；既有 `valid.chain.json`（无 digest）保持通过（v1.0 兼容回归）。运行 `python3 tools/e2e-runner 05-audit-contract/tests/audit-contract.test.yaml` 全绿。
- [ ] **Step 5（文档与 ADR）**：`hash-chain.spec.md` 版本升 1.1.0（加法演进声明）、§2 规范化追加行、§2.1 digest 定义、§3 增第二条含 digest 的测试向量（值由实现产出）、§5 篡改语义（正文篡改需事件导出；大对象正文建议在事件 payload 携带 `content_sha256`，digest 即承诺之）；ADR-0007（MINOR 论证：可选字段 + 旧条目哈希不变 + 旧验证器局限）；`docs/KNOWN-LIMITATIONS.md §2.2` 标注已修复与残余口径（无事件导出时仅验证链内自洽）；`CHANGELOG.md` 补记。
- [ ] **Step 6（全量）**：`python3 tools/e2e-runner --all` 全绿（含 PG 无关流水线/契约检查）；`git commit -m "feat(audit): 审计条目 payload_digest 与事件正文篡改检出 (#9)"`。

## Task 3（issue #10）：compatibility-checker 独立模式与规则 JSON Schema

**Files:**
- Create: `tools/lib/eis_compat.py`、`06-evolution-contract/compatibility.rules.schema.json`、`00-freeze/adr/0008-standalone-compatibility-checker.md`
- Modify: `tools/compatibility-checker`、`06-evolution-contract/tests/evolution-contract.test.yaml`、`README.md`（独立验证指南）、`docs/IMPLEMENTATION.md`（演进契约行）、`CHANGELOG.md`

**Interfaces:**
- `eis_compat.py`（仅 stdlib）：`diff_schemas(old,new)->list[dict]`、`classify(changes, rule_index=None)->dict`、`load_rule_index(path)->dict`、`DEFAULT_REQUIRES: dict[str,list[str]]`（8 类 kind，四类 data 规则与 `compatibility.rules.yaml` 逐项一致：字段删除/类型变更 `[migration,dual_write,rollback]`、必填新增 `[migration,backfill,dual_write]`、其余按现状）。
- CLI：`--standalone`（不读仓库规则，用 `DEFAULT_REQUIRES`）、`--rules PATH`（覆盖默认规则文件）；移除 `from eis_common import ...`，`load_json` 用 stdlib；输出 JSON 结构与退出码语义不变。
- 规则 Schema：`compatibility.rules.schema.json` 约束 `version` + `compatibility.{data,operation,event}[].{rule,level,requires}`（`level ∈ {PATCH,MINOR,MAJOR}`，`requires` 为字符串数组）。
- 自测新增 5 条（standalone 模式）：PATCH 相同、MINOR 可选新增、MAJOR 字段删除、重命名（删除+可选新增，整体 MAJOR）、类型变更 → MAJOR；并断言 standalone 的 `requires` 与读规则文件时一致、非法规则文档被 Schema 拒绝。

- [ ] **Step 1（RED）**：`tools/compatibility-checker --self-test` 增 5 条 standalone 断言 + `--standalone`/`--rules` 未实现 → 自测失败。
- [ ] **Step 2（GREEN 核心）**：创建 `eis_compat.py`（迁移 diff/classify 与常量，零仓库 import）；CLI 改为 import 之，实现 `--standalone`/`--rules`/本地 `load_json`；非 standalone 时按规则文件映射 `requires`（行为与现状逐字节一致——既有 `kind: compat` 用例回归）。
- [ ] **Step 3（规则 Schema）**：新增 `compatibility.rules.schema.json`；非 standalone 加载规则时校验（jsonschema 可用时），自测加非法文档负例。
- [ ] **Step 4（用例与文档）**：`evolution-contract.test.yaml` 增 2 条 `kind: cli`：`--standalone --json`（minor 夹具 stdout 含 `"overall": "MINOR"`）、`--standalone --fail-on MAJOR`（breaking 夹具 `expect_exit: 1`）；`README.md` 新增「独立验证（不依赖参考内核）」章节（命令、内置规则说明、规则 Schema 路径、六契约 Schema 现状与后续项）；`docs/IMPLEMENTATION.md` 演进契约行补 standalone 口径；ADR-0008（工具拆分、影响与回滚）。
- [ ] **Step 5（全量）**：`python3 tools/e2e-runner --all` 全绿；`git commit -m "refactor(tools): compatibility-checker 独立模式与规则 JSON Schema (#10)"`。

## Task 4（收尾）：计数同步、推送与 PR

- [ ] **Step 1**：`python3 tools/e2e-runner --all` 记录最终「用例 N/N；场景 1/1；流水线 5/5」；同步 `README.md`/`CONTRIBUTING.md`/`CHANGELOG.md`（必要时 `docs/CONFORMANCE.md`、`docs/LANDING-IAM.md`）中的计数与「已修复」口径；`git commit -m "docs: 同步用例计数与开放 issue 修复口径"`。
- [ ] **Step 2**：`git push -u origin fix/open-issues-8-9-10`；`gh pr create` 标题 `fix: 开放 issue #8/#9/#10（approval 读权限 / 审计 payload_digest / 独立兼容性检查）`，正文含三 issue 逐条验收对照、ADR 链接、`Closes #8`/`Closes #9`/`Closes #10`、`e2e-runner --all` 汇总行、验证命令清单；输出 PR URL。
- [ ] **Step 3**：在三个 issue 各留一条评论链接 PR（说明交付范围与验证结果），不关闭 issue（由 PR 合并关闭）。
