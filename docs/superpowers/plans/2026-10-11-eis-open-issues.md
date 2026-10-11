# EIS 开放 issue 修复实施计划（#1–#5）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `byteforce-cn/eis` 的 5 个开放 issue：#1 保留字校验、#2 内核扩展处理器注册、#3 授权属性属主与来源、#4 审批区块级流转、#5 HR 扩展契约。

**Architecture:** 工具链遵循既有 Python 参考实现风格（stdlib + PyYAML + jsonschema，无第三方框架）；契约变更走「Schema/OpenAPI/规则/用例 + ADR」工件路线；内核改造保持行为兼容、以显式注册机制替换硬编码。

**Tech Stack:** Python 3.10+、JSON Schema 2020-12、OpenAPI 3.1、PostgreSQL 16 DDL、PyYAML。

## Global Constraints

- 每个任务结束必须 `python3 tools/e2e-runner --all` 全绿（用例数随新增变化，需同步文档计数）。
- 扩展错误码使用扩展命名空间（`HR-`、`APR-`、`ATR-`），不得占用核心 `EIS-`。
- 核心契约（01–06）冻结：仅 #3 以 ADR + 加法演进方式补充授权属性协议。
- 既有用例语义（`approval.request.decide`、procure-to-pay 场景）不得破坏。
- 提交信息 `fix:`/`feat:`/`docs:` 前缀，一个 issue 一个 commit 起步。

---

## Task 1（issue #1）：contract-checker 校验 PostgreSQL 保留字

**Files:**
- Modify: `tools/contract-checker`（新增 `PG_RESERVED_WORDS`、`check_schema_reserved_words`，挂入 `check_schemas` 与 `--self-test`）
- Test: `01-data-contract/tests/data-contract.test.yaml`（新增 `cli` 用例运行 `--self-test`）

**Steps:**
- [ ] 收集 PostgreSQL 保留字集合（reserved，不含 reserved-can-be-function-or-type）。
- [ ] 在 `check_schemas` 中对每个 schema 的 `properties` 名（含 allOf 展开后的领域字段）做大小写不敏感匹配；冲突输出字段、来源文件与建议名（boolean → `is_<name>`，否则 `<name>_value`）。
- [ ] 自测新增：含 `primary` 字段的临时 Schema 必须被拒绝且错误含保留字提示；`is_primary` 必须通过。
- [ ] `python3 tools/e2e-runner --all` 全绿；确认现有 iam/approval/accounting/inventory 无冲突。

## Task 2（issue #2）：内核扩展处理器注册机制

**Files:**
- Modify: `tools/lib/kernel.py`（`ExtensionAPI`、`load_extension_handlers`、`Kernel.command_handlers`、`Kernel._handle`、敏感字段注册）
- Create: `extensions/{iam,approval,accounting,inventory}/handlers.py`（迁移既有处理器）
- Modify: `extensions/README.md`、`CONTRIBUTING.md`（机制文档 + 模板）
- Test: 既有 53 用例全绿即为行为回归证明；HR 扩展（Task 3）证明「无内核改动可扩展」。

**约定接口:**
- `handlers.py` 暴露 `register(api) -> dict[str, handler]`（或 `COMMANDS`），handler 签名 `(api, payload, actor, command_id) -> (events, created)`。
- `ExtensionAPI` 方法：`now/advance/new_id/reject/create_object/update_object/find_current/current_objects/as_of/history/event/stock/check_permission`。
- 可选 `SENSITIVE_FIELDS = {command_type: [field]}`，加载后并入 `Kernel.sensitive_fields`；`submit` 按它脱敏。
- `load_extension_handlers(kernel)` 扫描 `extensions/*/handlers.py`，加载异常不静默。

**Steps:**
- [ ] 实现 API 与加载器，`_handle` 改为注册表查找。
- [ ] 机械迁移 4 个扩展全部处理器；运行全量用例。
- [ ] 文档补充机制说明与最小模板。
- [ ] 提交。

## Task 3（issue #5）：extensions/hr 人力资源域扩展

**Files:** `extensions/hr/{manifest.yaml,README.md,objects/*.schema.json,operations/*.openapi.yaml,rules/*.yaml,handlers.py,tests/hr.test.yaml,migrations/V201__hr_initial.sql}`

**验收（issue #5）:** `contract-checker`、`schema-compiler compile hr` 通过；V2xx 迁移随契约；`hr.test.yaml` 可执行；敏感字段仅散列留存。

**Steps:**
- [ ] objects：Employee/OrganizationUnit/Position/Assignment/ProvisioningTask（allOf 核心 object，双时间轴）。
- [ ] operations：11 条命令 OpenAPI（hr.employee.create|update|activate|cancel、hr.org.unit.define|update、hr.position.define|update、hr.assignment.assign|end、hr.provisioning.run）。
- [ ] handlers：工号服务端生成、 uniqueness、返聘允许、组织/岗位一致性、汇报无环、在职必有主岗、主岗唯一、id 散列脱敏、供给任务。
- [ ] rules + invariants + README。
- [ ] tests：覆盖唯一性、返聘、无环、主岗不变量、敏感字段脱敏、审计链、供给任务。
- [ ] migration（由 `schema-compiler compile hr` 产物对齐）。
- [ ] `e2e-runner --all` 全绿。

## Task 4（issue #4）：approval 区块级流转

**Files:** `extensions/approval/{objects/approval-section.schema.json,objects/approval-request.schema.json,operations/*.openapi.yaml,rules/*.yaml,handlers.py,tests/approval.test.yaml,README.md,manifest.yaml}`

**验收（issue #4）:** compatibility-checker MINOR；用例覆盖正常流转、条件不适用、打回→重提→全部重确认、有人确认后撤回被拒、区块属主不匹配被拒；既有 decide 语义不破坏。

**Steps:**
- [ ] 对象 `ApprovalSection`（key/title/owner/state/confirmer/decided_at/comment/applicable）与 request 可选 `sections` 关联。
- [ ] 命令：`approval.section.confirm|reject|complete`、`approval.request.resubmit|withdraw`。
- [ ] 权限：区块属主 `approval.section.confirm.<owner>`（handler 内校验）。
- [ ] 不变量与规则文件；重提重置全部区块；完成⟺全部就绪。
- [ ] 用例 + compat 用例（旧 schema → 新 schema = MINOR）。
- [ ] `e2e-runner --all` 全绿。

## Task 5（issue #3）：授权属性属主与来源（核心 04）

**Files:** `04-authz-contract/attributes.api.yaml`（新增 pull 协议）、`04-authz-contract/attribute.rules.yaml`（新增）、`04-authz-contract/resolution.api.yaml`（加法：attributes 入参/返回）、`00-freeze/adr/0004-*.md`（ADR）、`docs/KNOWN-LIMITATIONS.md`（若口径变化）、`04-authz-contract/tests/*`、`tools/authz-resolver`（属性快照只读支持）

**验收（issue #3）:** 契约给出取属性接口或写入协议；明确缺失/过期/不可达口径（fail-closed）；明确属性快照形状（主岗单值 + 岗位集合）及对 /check 的影响。

**Steps:**
- [ ] 定义 snapshots 形状与 `as_of` 语义。
- [ ] Pull API 契约 + fail-closed 规则（ATR-xxx）。
- [ ] `/check` 增加可选 attributes 上下文与 `attribute_state` 返回；ADR 记录取舍。
- [ ] authz-resolver 支持属性夹具并补 e2e 用例。
- [ ] `e2e-runner --all` 全绿。

---

## Review Focus

- 保留字集合应覆盖 `primary`/`user`/`order` 等常见词，且不误伤既有契约。
- 内核重建（Task 2）必须逐条命令行为等价：运行全量 53 用例 + 场景。
- HR 工号生成必须确定性（不依赖真实时钟/随机）。
- 区块流程的时序边界：撤回只允许「无人确认」；重提必须清空确认；不适用区块不阻塞完成。
- 属性快照缺失/过期必须 fail-closed，不得静默放行。
