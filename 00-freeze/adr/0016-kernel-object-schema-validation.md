# ADR-0016：参考内核执行扩展对象 Schema（可选依赖 + fail-closed）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #40②（上游 #40、#33）；ADR-0012 §4.2；`docs/KNOWN-LIMITATIONS.md` §2.1；`extensions/README.md` §6；`tools/lib/kernel.py`；`extensions/*/manifest.yaml`、`extensions/*/objects/*.schema.json`

## 1. 变更原因

`docs/KNOWN-LIMITATIONS.md` §2.1 记录：参考内核以手写字段校验实现，不加载
`extensions/**/objects/*.schema.json`，也不运行 JSON Schema。后果是**同一输入在契约 Schema
与内核执行下可能结论不同**，使 CONFORMANCE L2「边界行为与参考内核一致」无法自证：

- Schema 是扩展对象的契约权威（`schema-compiler` 据此生成 DDL、`contract-checker` 校验）；
- 内核却可能接受 Schema 会拒绝的输入（或拒绝 Schema 允许的输入），双方无共同判据。

本 ADR 决定内核在写入路径执行对象 Schema，并把依赖策略与失败口径固定下来。

## 2. 影响范围

- 参考内核：`tools/lib/kernel.py` 载入 `manifest.objects` 声明的 Schema；创建/更新/夹具装载
  写入前校验；缺依赖/缺 Schema/Schema 非法 → 拒绝启动或拒绝写入（fail-closed）
- 契约数据：修正 `extensions/hr/objects/employee.schema.json` 的两处**自相矛盾**
  （`type: ["string","null"]` 但 `enum` 不含 `null`：`employment_type`、`id_type`）
- 工具：`tools/schema-compiler` 的 nullable enum 不再把 `null` 渲染成 `'None'` 字符串
  （列可空性已表达 null，`CHECK` 只列非空取值）
- 文档：`docs/KNOWN-LIMITATIONS.md` §2.1、`extensions/README.md` §6
- 用例：`01-data-contract/tests` 增 CLI 用例；内核自测增对象 Schema 断言
- 契约机制：无新增字段；`manifest.objects` 既有结构不变

## 3. 兼容性分析

- 级别判定：**PATCH**（契约工件仅为 Schema 自相矛盾修正；内核严格化属参考实现行为）。

| 变更 | 判定 | 依据 |
|---|---|---|
| `employee.schema.json` 两处 nullable enum 补 `null` | PATCH | `type` 已声明 `null`，`enum` 缺失是笔误；修正使 Schema 自洽，不引入新业务取值 |
| `schema-compiler` nullable enum 过滤 `null` | PATCH（工具缺陷） | 避免生成 `'None'` 字符串取值；可空列本就允许 NULL |
| 内核写入前执行 Schema | 实现严格化 | 此前「未知/违约输入可能落库」是未定义行为（§2.1），收紧到契约声明 |
| 内核默认依赖 `jsonschema`（可选依赖，缺失即拒绝启动） | 部署依赖 | CONTRIBUTING 与 CI 已要求 `pip install pyyaml jsonschema`；不改变契约版本 |

- 破坏点：未安装 `jsonschema` 的嵌入式用法将无法启动内核（这是 fail-closed 的目的）；
  依赖「内核放行违反 Schema 的写入」的测试/夹具会被拒绝（已修复本仓库内的两处夹具与两处 Schema 笔误）。

## 4. 决策

### 4.1 依赖策略（路线 A）

- 采用 `jsonschema`（Draft 2020-12）作为**可选依赖**：内核启动时尝试导入；
- `validate_objects=True`（默认）且依赖缺失 → `RuntimeError` **拒绝启动**（fail-closed）：
  无法证明与契约一致时，不提供「看起来能跑」的内核；
- `validate_objects=False` 仅供隔离自测，不是对外开关；关闭后内核不符合本 ADR，不得作为合规基准。

### 4.2 Schema 载入与对象类型

- 来源：`extensions/{id}/manifest.yaml` 的 `objects[]`（`name` + `schema`），与
  `schema-compiler` 同一权威；Schema 文件的相对 `$ref` 按**文件路径**内联（`$id` 是
  `eis://`，不能作为检索 URI）；`$ref` 循环、缺失、Schema 非法 → 启动失败。
- 对象类型同时登记两个别名，兼容既有内核语汇：
  - DDL 表名：`{extension.id}_{snake(name)}`（如 `hr_employee`，与 `schema-compiler` 一致）；
  - 短名：`snake(name)`（如 `voucher`、`approval_request`，既有处理器使用）。
- **跨扩展别名冲突 → 启动失败**（不静默择一）。

### 4.3 校验时机与失败口径

- 时机：`_create_object` / `_update_object`（`seed` 走同一路径）在**写入前**校验**完整行**
  （元字段 + 领域字段）；
- 更新路径先构造并校验新行，**再**封口旧行：校验失败不得留下半更新状态；
- 失败：`EIS-400-001`（`invalid_payload`），reason 含对象类型、字段路径与 Schema 错误摘要；
  未声明 Schema 的对象类型同样 fail-closed；
- `writeOnly` 字段：按存储行校验（派生后的散列值），不校验读投影。

### 4.4 明确不做

| 不做项 | 理由 |
|---|---|
| 自实现 JSON Schema 子集（路线 B） | 语义（`oneOf`/`allOf`/`format`/`pattern`/`$ref`）与边界容易与权威实现漂移，自测成本高于依赖 |
| 运行时热加载/热更新 Schema | 契约随扩展版本发布；热更新会破坏审计可复现 |
| 用 Schema 校验替代处理器业务规则 | Schema 管结构与格式；跨字段不变量/状态机仍由扩展处理器与 `rules/` 表达 |
| 远端 `$ref` / 网络检索 | 参考内核必须离线确定性；只允许文件内/相对文件引用 |
| 为 Schema 违约新增错误码 | `EIS-400-001` 已覆盖「请求体不满足命令 Schema」；避免错误码膨胀 |

## 5. 迁移方案

- 部署：确保运行环境安装 `jsonschema`（CI 已安装）；未安装时内核拒绝启动，不降级。
- 实现：内核不再接受 Schema 会拒绝的输入；发现契约 Schema 自相矛盾时按 PATCH 修正 Schema
  （本次两处 nullable enum），不得在核心里放宽。
- 数据：无 DDL / 无回填。
- 对账：`tools/lib/kernel.py` 自测 + `01-data-contract` CLI 用例 + `e2e-runner --all`。

## 6. 回滚方案

- 回滚 = revert 本 ADR 与内核改动：内核恢复手写校验，`KNOWN-LIMITATIONS` §2.1 恢复为缺口；
- Schema 的 nullable enum 修正可独立保留（它只让 Schema 与既有 `type` 声明自洽）；
- 回滚验证：`python3 tools/e2e-runner --all` 全绿。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 内核 | `tools/lib/kernel.py` | Schema 载入（别名/冲突/`$ref` 内联）、写入前校验、`validate_objects` |
| Schema 修正 | `extensions/hr/objects/employee.schema.json` | `employment_type` / `id_type` 的 enum 补 `null` |
| 编译器修正 | `tools/schema-compiler` | nullable enum 过滤 `null`，不生成 `'None'` 字面量 |
| 用例 | `01-data-contract/tests/data-contract.test.yaml` | CLI 用例：内核自测（Schema 违约被拒） |
| 自测 | `tools/lib/kernel.py` | 合法写入通过 / 违约拒绝 / 未声明类型 fail-closed / 非法更新无半更新 |
| 文档 | `docs/KNOWN-LIMITATIONS.md` §2.1、`extensions/README.md` §6 | 已修复口径与残余边界 |
| 裁决 | 本 ADR | 依赖策略、对象类型解析、失败口径、不做项 |

## 8. 验收用例

- `python3 tools/lib/kernel.py`：自测全过（含 4 条对象 Schema 断言）；
- `python3 tools/e2e-runner 01-data-contract/tests/data-contract.test.yaml`：7/7；
- `python3 tools/e2e-runner --all`：全绿（用例计数随新增用例更新）；
- `python3 tools/contract-checker`：全过（Schema 修正后仍合法）；
- 反例：`hr_employee` 的 `status=bogus` / `employee_no=X` / `hire_date=not-a-date` 被 `EIS-400-001` 拒绝；
  未声明对象类型被拒绝；更新失败不改变当前版本。
