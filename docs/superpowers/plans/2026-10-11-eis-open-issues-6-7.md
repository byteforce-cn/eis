# EIS 开放 issue #6/#7 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（用户已指定"直接落 EIS"，inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 修复 `byteforce-cn/eis` 开放 issue：#6 写入专用散列字段（`id_number_hash`/`secret_hash`）的哈希生产者与密钥托管；#7 `extensions/hr` 读取面（名册/详情/属性快照）授权口径。

**Architecture:** #6 选"服务端派生"口径（原始值经 `writeOnly` 载荷进入域服务，域服务用注入式用途密钥做 HMAC-SHA256 落库；原始值与散列在读投影/命令记录/日志剔除；密钥环支持版本化轮换）；#7 选"扩展声明权限目录"口径（`manifest.permissions` + `/check` 判定；核心通用查询维持部署边界，属性端点限定服务间）。核心变更走 ADR + 可执行工件 + e2e 用例；参考内核保持离线可跑（注入式密钥），coord Transit 仅作未来映射并另提需求。

**Tech Stack:** Python 3.10+（stdlib + PyYAML + jsonschema）、JSON Schema 2020-12、OpenAPI 3.1、HMAC-SHA256、PostgreSQL 16 DDL。

**Spec:** issue #6、issue #7（`https://github.com/byteforce-cn/eis/issues/6`、`/issues/7`）；上游裁决证据：`docs/COORD-REQUIREMENTS.md`（coord T4 定位）、`docs/LANDING-IAM.md`（应用侧散列、coord 失败可降级）。

## Global Constraints

- 每个任务结束必须 `python3 tools/e2e-runner --all` 全绿；用例计数随新增变化并同步文档。
- 核心契约（01–06）冻结：变更一律 ADR（`00-freeze/adr/` 模板）+ 可执行工件 + 验收用例。
- 扩展错误码沿用 `HR-` 命名空间；不得占用 `EIS-`。
- 测试必须确定性、离线可跑（不得依赖网络/外部服务；字段密钥由场景显式钉住）。
- hr v1.0.0 尚未发布（CHANGELOG `[Unreleased]`）：`id_number_hash` → `id_number` 为发布前修正，不升 MAJOR；撤销调用方自行提供散列的路径，禁止保留"未声明明文入口"。
- 提交信息 `fix:`/`feat:`/`docs:` 前缀；一个 issue 一个 commit 起步；工作分支 = 本地 `main`（用户明确"直接落 EIS / 对齐本地 branch"，`main == origin/main == e04237e`）。

## Review Focus

- 派生散列的**确定性域分离**：同一原始值在不同 scope 下必须得到不同散列；实现不得省略 `scope + 0x00` 前缀。
- **轮换窗口**：旧密钥下的存量散列必须仍能参与防重（`write_only_variants`），新写入必须用主密钥；旧密钥退役口径写清。
- **剔除范围**：命令记录（含整条记录递归扫描）、读投影、事件载荷、失败响应都不得出现原始值或散列；幂等指纹不得可逆。
- **权限目录完整性**：扩展测试中引用的每个 permission 都必须在 manifest 声明；核心通用查询不得因本次变更被要求域权限（避免核心行为破坏）。
- **属性端点边界**：服务间专用必须有可执行判据（authz 用例区分 person/system），不得只在文档里写。

---

## Task 1（issue #6）：写入专用派生字段的服务端派生与密钥托管

**Files:**
- Modify: `tools/lib/kernel.py`（`DEFAULT_FIELD_HASH_KEYS`、`derive_hmac`、`Kernel.field_hash_keys`/`write_only_fields`、`register_write_only`、`read_projection`、`ExtensionAPI.derive_write_only`/`write_only_variants`、`load_extension_handlers` 读 `WRITE_ONLY_FIELDS`、`run_scenario` 透传 `field_hash_keys`）
- Modify: `tools/e2e-runner`（新增 `kind: object-absent` 断言）
- Modify: `extensions/hr/handlers.py`、`extensions/hr/operations/employee-create.openapi.yaml`、`extensions/hr/objects/employee.schema.json`、`extensions/hr/README.md`、`extensions/hr/tests/hr.test.yaml`
- Create: `00-freeze/adr/0005-write-only-derived-fields.md`、`01-data-contract/write-only-fields.rules.yaml`
- Modify: `01-data-contract/object.schema.json`、`02-operation-contract/command.openapi.yaml`、`extensions/README.md`、`docs/IMPLEMENTATION.md`、`docs/KNOWN-LIMITATIONS.md`、`01-data-contract/tests/data-contract.test.yaml`、`CHANGELOG.md`

**Interfaces:**
- `derive_hmac(keys: Sequence[str], scope: str, raw: str) -> str`：`HMAC-SHA256(keys[0], scope.encode() + b"\x00" + raw.encode())` 小写 hex，64 字符。
- `ExtensionAPI.derive_write_only(scope: str, raw: str) -> str`（主密钥）；`ExtensionAPI.write_only_variants(scope: str, raw: str) -> list[str]`（密钥环全量，主密钥在前）。
- 处理器模块级 `WRITE_ONLY_FIELDS = {object_type: (field, ...)}`；`SENSITIVE_FIELDS` 同时登记原始值与派生字段。
- hr scope 常量：`ID_NUMBER_CONTEXT = "eis:hr:hr_employee:id_number:v1"`。
- 场景 spec 可选 `field_hash_keys: [..]`（默认 `["eis-dev-field-hash-key"]`）。
- e2e 断言 `{kind: object-absent, type, id, fields: [...]}`：`read_projection` 中不得出现这些字段。

- [ ] **Step 1（RED）：改测试到目标行为**
  - `extensions/hr/tests/hr.test.yaml`：3 处 `id_number_hash:` 载荷改为 `id_number:` 原始值（`110101199001011234` / `110101198505054321` / `E12345678`），受影响场景加 `field_hash_keys: [eis-test-field-hash-key-v1]`。
  - `hr.hire-to-active`：加 `object-field id_number_hash == 3935748e52ed27e867bf65e8bb2a97ff58d59acf1d4b8adb920513b78fc492bf`；删除对 `id_number_hash` 的入参依赖。
  - `hr.id-dedup-rehire`：`object-count where id_number_hash == b2c2e29c4d2a8b7921bfa84859140de18df3d8824bd5602cedd3e910f8aa357a, expect: 2`。
  - `hr.sensitive-redaction`：`command-redacted fields: [id_number, id_number_hash]`；`object-field id_number_hash == f494079650af226598071c86526aeee36487f76a6e361fc64b1e1eda9c6f45e0`；`object-absent fields: [id_number, id_number_hash]`。
  - `hr.id-hash-format` → 改名"证件号原始值不得为空"：`id_number: ""`，`expect_code: HR-400-001`。
  - 新增场景 `hr.write-only-rotation`：`field_hash_keys: [new-field-hash-key-v1, old-field-hash-key-v1]`；`setup.objects` 预置一条 `id_number_hash == ef75360bccb3b5bdbd4cad8fae42bf9d1f32e43752ec0e1f36c40a3adc08879e` 的员工；T1 用原始值 `110101197001019999` 建档 → `expect_code: HR-409-002`。
- [ ] **Step 2（验证 RED）**：`python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml` → 失败（未识别 `id_number`、`object-absent` 未实现）。
- [ ] **Step 3（GREEN 内核）**：实现 `derive_hmac`、Kernel 密钥环/注册/投影、ExtensionAPI 两方法、`load_extension_handlers` 读 `WRITE_ONLY_FIELDS`、`run_scenario` 透传；e2e-runner 加 `object-absent`。
- [ ] **Step 4（GREEN 扩展）**：`create_employee` 改为 `id_number` → 校验非空 → 派生 + 变体防重 → 落 `id_number_hash`；OpenAPI/对象 schema/README 同步。
- [ ] **Step 5（验证 GREEN）**：`python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml` 全绿。
- [ ] **Step 6（核心工件）**：ADR-0005 + `write-only-fields.rules.yaml`（DRV-001..006）+ object/command 描述 + extensions/README §6（`derive_write_only`/`WRITE_ONLY_FIELDS`）+ IMPLEMENTATION.md 密钥服务映射 + KNOWN-LIMITATIONS 开发缺省密钥条目 + data-contract 静态用例。
- [ ] **Step 7**：`python3 tools/e2e-runner --all` 全绿；`git commit -m "feat(core): 写入专用派生字段的服务端派生与密钥托管 (#6)"`。

## Task 2（issue #7）：扩展权限目录与读取面授权口径

**Files:**
- Create: `00-freeze/adr/0006-read-face-authorization.md`、`extensions/hr/tests/fixtures-authz.yaml`
- Modify: `tools/contract-checker`（`check_manifests` 增加 permissions 校验 + 测试引用扫描 + 自测）、`extensions/hr/manifest.yaml`、`extensions/hr/README.md`、`extensions/hr/tests/hr.test.yaml`
- Modify: `04-authz-contract/attributes.api.yaml`、`04-authz-contract/attribute.rules.yaml`、`02-operation-contract/query.openapi.yaml`、`extensions/README.md`、`docs/KNOWN-LIMITATIONS.md`、`CHANGELOG.md`

**Interfaces:**
- `manifest.yaml` 可选段 `extension.permissions`：`[{id, kind: command|read|service, description, scope?}]`；id 必须以 `<extension.id>.` 开头。
- contract-checker：`check_manifests(report, root=ROOT)`；当扩展声明 `permissions` 时，扫描 `extensions/<id>/tests/*.yaml` 的 `permission`/`permissions` 值，未声明即失败。
- hr 权限目录：11 条 command + `hr.employee.read`（read；`same_department` ABAC 语义）、`hr.attributes.read`（service，仅服务间）。
- `kind: authz` 用例夹具：`hr-admin`（有 `hr.employee.read`）允许；`employee`（无）拒绝 `NO_PERMISSION`；`hr-service`（system，有 `hr.attributes.read`）允许；person 拒绝。

- [ ] **Step 1（RED）**：先在 `tools/contract-checker --self-test` 中写两个失败断言：①含未声明权限引用的临时扩展必须报"未声明"；②非命名空间权限 id 必须被拒。运行 → 自测失败（校验未实现）。
- [ ] **Step 2（GREEN checker）**：实现 permissions 结构校验 + 引用扫描；自测通过。
- [ ] **Step 3（hr 目录与用例）**：manifest 声明权限；新增 `fixtures-authz.yaml` 与 4 条 `kind: authz` 用例；`hr.test.yaml` 全绿。
- [ ] **Step 4（核心文档）**：ADR-0006（读取面口径、核心查询部署边界与风险、属性端点服务间边界）；`attributes.api.yaml` 加 403 与调用方边界；`attribute.rules.yaml` 加 ATR-008；`query.openapi.yaml` 描述补充；extensions/README manifest 表 + 权限目录章节；KNOWN-LIMITATIONS §5 更新。
- [ ] **Step 5**：`python3 tools/e2e-runner --all` 全绿；`git commit -m "feat(authz): 扩展权限目录与读取面授权口径 (#7)"`。

## Task 3：coord Transit HMAC 用途化/轮换需求（另提 issue）

**Files:**
- Modify: `docs/COORD-REQUIREMENTS.md`（G-TR-3 行 + 详情 + 证据锚点）
- 尝试 `gh issue create --repo byteforce-cn/coord`（无凭据则记录裁决并给出可直接提交的正文）

- [ ] **Step 1**：补 G-TR-3：请求能力 = 用途化 HMAC 密钥（或 context/key 名参数，未声明用途 fail-closed）+ 签名 key_id/历史材料验签（轮换窗口）+ 轮换迁移口径；验收 = 两用途密钥互不可验、轮换后旧签名在历史窗口内可验、窗口外 fail-loud。
- [ ] **Step 2**：尝试提 issue；若环境无 GitHub 凭据（已核实无 `gh` auth / token / credential helper），把 issue 正文落到 `docs/COORD-REQUIREMENTS.md` 详情并在总结中给出可直接粘贴的 issue 正文。
- [ ] **Step 3**：`git commit -m "docs: coord transit HMAC 用途化与轮换需求（G-TR-3）"`。

## Task 4：计数对齐与最终验证

- [ ] **Step 1**：`python3 tools/e2e-runner --all` 取实际用例数。
- [ ] **Step 2**：更新 `README.md`、`CONTRIBUTING.md`、`docs/KNOWN-LIMITATIONS.md`、`docs/CONFORMANCE.md` 中的当前计数（`docs/LANDING-IAM.md` 是历史快照，不改）；`CHANGELOG.md` 汇总 #6/#7。
- [ ] **Step 3**：`git commit -m "docs: 对齐用例计数与 CHANGELOG（#6/#7）"`。
- [ ] **Step 4**：最终全量验证 + 变更清单（文件 → 原因 → API 影响）；fresh reviewer（如可用）复核 diff，Critical/Important 一次修复。
