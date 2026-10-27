# ADR-0019：扩展跨引用与命令前置（`dependencies` + `rules.requires_objects`）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #30 步骤 2（上游 #30、ADR-0012 §4.2）；`extensions/README.md` §8；`extensions/hr/manifest.yaml`、`extensions/hr/rules/activation-requires-approval.yaml`；`tools/contract-checker`、`tools/lib/kernel.py`

## 1. 变更原因

#30 步骤 1（ADR-0013）解决了「谁能调」：`hr.employee.activate/cancel` 仅系统主体可调，
SPA 无法绕过。但服务端仍只校验「待入职 + 有有效主岗」，**没有校验审批单是否存在**——
持有 `hr.employee.activate` 的审批服务若被误用/漏校验，仍可无审批激活。

步骤 2 需要扩展机制具备两件能力：

1. **跨扩展引用**：扩展能声明「我依赖 approval」并引用其对象类型；
2. **命令前置**：声明「执行该命令前，必须存在满足条件的对象」，且可机械校验、fail-closed。

当前 `manifest.dependencies` 只是空数组占位，`contract-checker` 不校验跨扩展引用，内核也不执行任何
前置。若引入通用规则引擎，会重蹈 ADR-0012 明确拒绝的「运行期任意策略表达式」覆辙。本 ADR 选择
**窄口径存在性前置**：只判断「存在匹配的当前对象」，不做任意表达式。

## 2. 影响范围

- 扩展机制：`manifest.dependencies` 生效（`{id, version}`）；`rules/*.yaml` 支持 `rule.requires_objects`
- `tools/contract-checker`：依赖存在性/版本/环、`applies_to`、引用对象、`where`/`error_code` 校验 + 自测
- `tools/lib/kernel.py`：载入前置声明，在权限/调用方放行后、处理器前执行存在性判断
- `extensions/hr`：1.2.0 → 1.3.0；`dependencies: [approval 1.1.0]` + `rules/activation-requires-approval.yaml`
- 用例：hr 场景在激活前置入已通过审批单；新增「无审批单 → `HR-409-002`」反例
- 核心契约：**无改动**（扩展机制加法）

## 3. 兼容性分析

- 级别判定：**MINOR**（扩展机制加法 + 扩展版本 MINOR）。

| 变更 | 判定 | 依据 |
|---|---|---|
| `dependencies` 条目格式 `{id, version}` 生效 | MINOR | 既有 manifest 的 `[]` 行为不变 |
| `rules.requires_objects` 可选声明 | MINOR | 未声明者行为不变 |
| `hr.employee.activate` 增加审批单前置 | 语义收紧（安全修复） | 此前「无审批单可激活」是未定义行为；合规调用方（审批服务）应先有已通过审批单 |

- 破坏点：不满足前置的激活请求会被 `HR-409-002` 拒绝；这是本 ADR 的目的。
- 未声明 `requires_objects` 的命令行为不变。

## 4. 决策

### 4.1 依赖声明（权威）

`extensions/{id}/manifest.yaml`：

```yaml
extension:
  dependencies:
    - {id: "approval", version: "1.1.0"}   # 精确版本（semver）
```

- `contract-checker` 校验：目标扩展存在、版本精确匹配、依赖图无环；
- 依赖只表示「允许引用」；不自动加载/启用扩展（参考内核本就加载全部扩展）；
- 卸载依赖扩展时，引用它的前置规则会使命令 fail-closed（`current_objects` 为空）。

### 4.2 命令前置声明（窄口径）

`extensions/{id}/rules/*.yaml`：

```yaml
rule:
  id: "activation-requires-approval"
  applies_to: "hr.employee.activate"
  requires_objects:
    extension: "approval"
    object: "ApprovalRequest"       # 依赖扩展 manifest.objects 的 name
    where:                          # 精确匹配（AND）；键为对象字段路径
      operation: "hr.employee.activate"
      status: "approved"
      "target.type": "hr_employee"
      "target.id": "$payload.employee_id"   # 右值：字面量或 $payload.<点分路径>
  error_code: "HR-409-002"          # 扩展命名空间，不得占用 EIS-
  reason: "员工转在职必须存在已通过的入职审批单"
```

- 语义：**存在**一条当前对象（`superseded_at IS NULL`）满足 `where` 全部键值 → 放行；否则拒绝；
- 只做精确匹配，**不允许** `>`/`<`/正则/嵌套/OR/否定等表达式；
- `object` 解析为参考内核的对象类型（`snake(name)`，如 `ApprovalRequest → approval_request`）；
- `$payload.<path>` 只读当前命令载荷；缺失视为不匹配；
- 规则文件通过 `manifest.rules[].file` 引用；未引用/未声明的规则不生效。

### 4.3 执行时机与失败口径

- 时机：命令级权限预检与 `callers` 预检**之后**、处理器之前（不向未授权调用方泄漏对象存在性）；
- 失败：`Rejected(error_code, reason)`，命令状态 `rejected`，不产生事件/审计；
- fail-closed：对象类型未加载、无匹配对象、规则文件缺失（启动期）→ 拒绝；
- 幂等重放：已受理命令的 replay 在预检前返回，不重复执行前置。

### 4.4 校验器边界

`contract-checker` 只做**静态引用完整性**（不执行规则）：

- `dependencies`：目标/版本/环；
- `applies_to`：必须是本扩展已声明的 `kind: command` 权限；
- `requires_objects.extension`：必须在 `dependencies` 内；
- `requires_objects.object`：必须在依赖扩展的 `manifest.objects` 内；
- `where`：非空、路径语法、值只能是标量或 `$payload.<路径>`；
- `error_code`：扩展命名空间格式（`^[A-Z][A-Z0-9]{1,9}-\d{3}-\d{3}$`，禁止 `EIS-`）。

### 4.5 明确不做

| 不做项 | 理由 |
|---|---|
| 通用规则引擎（表达式/脚本/正则/比较运算符） | 破坏 `as_of` 可复现与审计自证；ADR-0012 已拒绝 |
| 跨扩展写操作 | 前置只读；写仍走属主域命令（不得直写他域对象） |
| 自动加载/启用依赖扩展 | 组合与部署是部署方职责；参考内核加载全部扩展 |
| 依赖传递闭包的条件求值 | 只允许直接依赖；传递引用须显式声明 |
| 把前置写成 operations OpenAPI 字段 | 内核不解析 OpenAPI；权威在 manifest + rules |
| 动态/热更新规则 | 规则随扩展版本发布；运行期变更破坏审计可复现 |

## 5. 迁移方案

- 扩展：声明 `dependencies` + `rules/*.yaml`，并在 manifest 引用；本仓库 `extensions/hr` 1.3.0 已迁移；
- 部署：审批服务在调用 `hr.employee.activate` 前，确保存在已通过审批单（正常审批流程本应如此）；
- 数据：无 DDL / 无回填；
- 对账：`contract-checker` 引用完整性 + hr 场景正反例。

## 6. 回滚方案

- 删除 `requires_objects` 声明（或 hr 规则文件/依赖）即恢复旧行为；
- 回滚 = revert 本 ADR + 扩展声明 + checker/kernel 支持；核心契约无影响；
- 回滚验证：`python3 tools/e2e-runner --all` 全绿。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 扩展机制说明 | `extensions/README.md` §8 | `dependencies` + `requires_objects` 格式/语义/不做项 |
| hr 依赖 | `extensions/hr/manifest.yaml` | `dependencies: [approval 1.1.0]`；规则引用 |
| hr 前置 | `extensions/hr/rules/activation-requires-approval.yaml` | 已通过审批单的存在性前置 |
| 校验器 | `tools/contract-checker` | 关系/规则检查 + 7 条自测 |
| 参考内核 | `tools/lib/kernel.py` | 载入前置、执行顺序、fail-closed、`seed` 步骤支持 |
| 用例 | `extensions/hr/tests/hr.test.yaml` | 无审批单 → `HR-409-002`；有审批单 → 激活成功 |
| 文档 | `extensions/hr/README.md` | 激活前置与依赖说明 |

## 8. 验收用例

- `python3 tools/contract-checker --self-test`：30 条全过（新增 7 条跨扩展断言）；
- `python3 tools/contract-checker`：全过（hr 依赖/规则引用完整）；
- `python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml`：29/29（含无审批单拒绝）；
- `python3 tools/e2e-runner --all`：全绿（用例计数不变：154/154）；
- 反例：删除依赖声明、引用未声明对象、`applies_to` 错配、版本漂移、占用 `EIS-` 错误码、`where` 非标量、依赖环——均被 `contract-checker` 检出。
