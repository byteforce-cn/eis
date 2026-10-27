# EIS Wave 2 实施计划：命令调用方约束（#30 步骤 1）+ 命令响应 locator/version（#32①）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** ① 让扩展契约能声明「谁能调这个命令」，并在参考内核里真正拒绝越权主体（issue #30 步骤 1，安全缺口）；② 把命令响应的 `{locator, version}` 固化为契约（issue #32①，命令契约与查询契约之间唯一的桥）。

**Architecture:** ① `manifest.permissions[].callers`（`person|system`）是**唯一权威**（内核命令级预检直接读它），扩展 operations 契约用 `x-eis-callers` 做同值投影、由 `contract-checker` 双向校验（缺投影/值不一致即红），新增核心错误码 `EIS-403-002`；hr 的 `activate`/`cancel` 限定为系统主体，既有用例改用审批服务主体，并补「用户主体持有权限仍被拒」的反例。② `CommandAccepted` 增可选 `locator`（聚合根 ID / 流程实例 ID）与 `version`，内核命令结果同步返回，scenario 断言「命令返回的 version == 随后读到的对象 version」。

**Tech Stack:** Python 3.10+（stdlib + PyYAML + jsonschema）、OpenAPI 3.1（vendor extension）、JSON Schema、参考内核 `tools/lib/kernel.py`。

**Spec:** issue #30（步骤 1）、#32①；裁决 ADR-0012 §4.2；先例 ATR-008（服务间专用）/ `extensions/README.md` §7、ADR-0010（新错误码判 MINOR）。

## Global Constraints

- 核心契约（01–06）冻结：改动走 ADR（`00-freeze/adr/template.md`）+ 可执行工件 + 验收用例。
- 每个任务结束 `python3 tools/e2e-runner --all` 必须全绿；用例计数变化需同步 `README.md` / `CONTRIBUTING.md` / `CHANGELOG.md` 的计数口径。
- 扩展自包含：新增扩展不得要求改内核；本次是**内核机制加法**（读 manifest 的 `callers`）+ 扩展声明，不是新增扩展。
- 确定性：用例不依赖真实时钟/网络；主体声明在夹具内。
- 一个 issue 一个分支一个 PR，不自行合并、不跳过 CI。

## Review Focus

- **权威唯一**：`callers` 只写在 manifest；operations 的 `x-eis-callers` 是投影，`contract-checker` 必须能检出「只有投影没有声明」「声明与投影不一致」两种漂移。
- **fail-closed**：主体不存在、类型无法解析、声明空数组 → 一律拒绝（不得退化为放行）。
- **不误伤**：未声明 `callers` 的命令行为完全不变（既有 134 条用例中除 hr activate/cancel 外全部不受影响）。
- **错误码语义**：越权主体用 `EIS-403-002`（调用方不允许），不得复用 `EIS-403-001`（/check 判定拒绝）或 `NO_PERMISSION`。
- **§32① 不夹带读写投影**：`locator/version` 不是读模型字段，命令响应仍不得携带业务字段。

---

## Task 0：分支基线

- [ ] **Step 1**：`git fetch origin && git switch -c feat/command-caller-constraint origin/main`。

## Task 1：ADR-0013 + 错误码

**Files:**
- Create: `00-freeze/adr/0013-command-caller-constraint.md`
- Modify: `00-freeze/adr/README.md`
- Modify: `02-operation-contract/error-codes.yaml`

**Interfaces:**
- `manifest.permissions[].callers: ["person"|"system", ...]`（非空、去重、无通配）
- operations 契约：`x-eis-callers: ["system"]`（与 manifest 同值）
- 新错误码：`EIS-403-002` `caller_not_allowed`

- [ ] **Step 1**：写 ADR-0013（原因/影响/兼容性 MINOR/迁移/回滚/工件/验收），在索引登记。
- [ ] **Step 2**：`error-codes.yaml` 增 `EIS-403-002`（403，`caller_not_allowed`，`emitted_when`: 主体类型不在 `callers` 内）。

## Task 2：contract-checker 双向校验

**Files:**
- Modify: `tools/contract-checker`（`check_manifest_permissions`、新增 `check_operation_callers`、`cmd_self_test`）

**Interfaces:**
- `CALLER_TYPES = {"person", "system"}`
- `check_operation_callers(report, manifests)`：遍历 `extensions/*/operations/*.openapi.yaml`，按 `/commands/<type>` 取 `x-eis-callers`，与 `manifests[ext]["permissions"]` 中同 id 的 `callers` 比对。

- [ ] **Step 1（RED）**：自测新增三条断言（投影缺声明 / 值不一致 / 非法枚举）→ `contract-checker --self-test` 失败。
- [ ] **Step 2（GREEN）**：实现 manifest `callers` 校验 + `x-eis-callers` 校验 + 双向一致性；接入 `main()`。
- [ ] **Step 3**：`python3 tools/contract-checker` 全过。

## Task 3：hr 声明调用方约束

**Files:**
- Modify: `extensions/hr/manifest.yaml`（`hr.employee.activate` / `hr.employee.cancel` 增 `callers: ["system"]`）
- Modify: `extensions/hr/operations/employee-activate.openapi.yaml`、`employee-cancel.openapi.yaml`（`x-eis-callers`）
- Modify: `extensions/README.md` §7、`extensions/hr/README.md`

- [ ] **Step 1**：manifest + 两份 operations 契约声明。
- [ ] **Step 2**：`python3 tools/contract-checker` 通过（双向一致）。

## Task 4：内核命令级预检

**Files:**
- Modify: `tools/lib/kernel.py`（`load_permission_callers()`、`submit()` 中的主体类型检查）

**Interfaces:**
- `Kernel.permission_callers: dict[str, tuple[str, ...]]`（命令 → 允许主体类型），来自 `extensions/*/manifest.yaml`
- 拒绝：`Rejected("EIS-403-002", "<命令> 仅限主体类型 <...>，实际 <...>")`

- [ ] **Step 1（RED）**：hr 用例改造（服务主体 + 用户主体反例）→ `e2e-runner extensions/hr/tests/hr.test.yaml` 失败。
- [ ] **Step 2（GREEN）**：内核实现；未装载授权夹具时不判定（与既有行为一致）；`Authz.principal()` 查不到主体时 fail-closed。
- [ ] **Step 3**：`e2e-runner extensions/hr/tests/hr.test.yaml` 全绿。

## Task 5：文档与变更记录

**Files:**
- Modify: `CHANGELOG.md`、`extensions/README.md`（§7 表格 + 纪律）、`docs/KNOWN-LIMITATIONS.md`（如涉及）

- [ ] **Step 1**：写清「声明位置/权威/投影校验/错误码/fail-closed」四条口径。
- [ ] **Step 2**：记录 #30 步骤 2（审批前置）未做，需扩展跨引用机制。

## Task 6：校验与 PR

- [ ] **Step 1**：`e2e-runner --all`、`contract-checker`、`compatibility-checker --standalone`（新错误码/可选字段 → MINOR）。
- [ ] **Step 2**：push + `gh pr create`；PR 正文含 `Closes #30`（步骤 1）口径与汇总行。
- [ ] **Step 3**：CI 全绿 → squash 合并 → 删分支。

## Task 7：命令响应 locator/version（#32①，独立分支）

**Files:**
- Create: `00-freeze/adr/0014-command-response-locator-version.md`
- Modify: `02-operation-contract/command.openapi.yaml`（`CommandAccepted` 增 `locator`/`version` + MUST 口径）
- Modify: `tools/lib/kernel.py`（命令结果返回 `locator`/`version`；`submit` 透出）
- Modify: `02-operation-contract/tests/*` 或 `cases/procurement/scenarios/*`（scenario 断言）

- [ ] **Step 1**：ADR-0014（MINOR：可选字段新增 + 语义明确）+ 兼容性判定。
- [ ] **Step 2**：契约与内核；scenario 断言「activate 返回的 version == 读取到的对象 version」。
- [ ] **Step 3**：e2e 全绿 → PR → CI → 合并。

## Task 8：验收与台账

- [ ] **Step 1**：`git log --oneline origin/main -4`、`gh pr list --state merged` 确认两条合并。
- [ ] **Step 2**：#30 回帖（步骤 1 已落地、步骤 2 待跨引用 ADR）；#32 回帖（① 已落地、② 待排期）。
