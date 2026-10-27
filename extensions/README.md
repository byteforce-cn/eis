# 领域扩展（extensions/）

领域扩展是**独立版本化**的契约包：只依赖核心（`core_version`），不得修改核心。

## 1. 扩展结构（冻结）

```
extensions/{domain}/
├── manifest.yaml          # 扩展清单（入口，见下）
├── objects/               # 业务对象定义（allOf 追加核心元结构）
├── operations/            # 操作契约（OpenAPI）
├── rules/                 # 业务规则（可执行语义）
├── views/                 # 读模型（可选）
├── migrations/            # 迁移脚本（可选）
└── tests/                 # 测试用例
```

## 2. 扩展清单（manifest.yaml）

| 字段 | 说明 |
|------|------|
| `extension.id` | 全局唯一标识 |
| `extension.version` | 扩展版本（独立于核心） |
| `extension.kind` | 可选：`domain`（默认，业务扩展）/ `runtime`（跨域运行时扩展，无业务对象；DDL 由扩展自带，`schema-compiler` 跳过编译） |
| `extension.core_version` | 依赖的核心版本 |
| `dependencies` / `conflicts` | 依赖与冲突（组合校验用） |
| `objects` | 业务对象清单（name → schema 路径） |
| `operations` | 操作清单（name → 契约路径） |
| `rules` | 业务规则清单（name → 文件路径） |
| `invariants` | 不变量（name → 表达式） |
| `permissions` | 权限目录（可选；`command`/`read`/`service`，见 §7） |

所有清单项引用的文件必须存在（引用完整性由组合校验检查）。

## 3. 扩展纪律

- 扩展**不得修改**核心契约；只能通过 `allOf` 引用核心元结构（如 `object.schema.json`）
- 扩展内错误码使用扩展命名空间（如 `ACC-xxx`），不得占用核心 `EIS-` 命名空间
- 扩展变更只影响自身 MINOR/MAJOR，不触发核心升版

## 4. 扩展组合（cases/）

案例通过 `composition.yaml` 组合多个扩展：

```yaml
composition:
  id: "procurement"
  extensions:
    - id: "accounting"
      version: "1.0.0"
    - id: "inventory"
      version: "1.0.0"
    - id: "approval"
      version: "1.0.0"
```

组合校验（必须全部通过）：

1. 所有扩展的 `dependencies` 必须满足
2. 所有扩展的 `conflicts` 必须为空（无互相冲突）
3. 组合后的不变量必须兼容

## 5. 现有扩展

| 扩展 | 版本 | 内容 | 状态 |
|------|------|------|------|
| `accounting` | 1.0.0 | 科目/凭证/余额；过账、关账；借贷平衡、期间锁定 | 完整示例（含可执行用例） |
| `iam` | 1.0.0 | 身份与访问管理：账户/凭证/角色/绑定/会话；SoD 预检、root 保护 | 完整（含可执行用例） |
| `inventory` | 1.0.0 | 物品/出入库/库存余额；收货；库存非负 | 完整（含可执行用例） |
| `approval` | 1.1.0 | 审批申请/决定/区块；提交与决定、区块流转（顺序语义）、打回重确认、撤回；禁止自审 | 完整（含可执行用例） |
| `hr` | 1.3.0 | 组织/岗位/员工（含雇佣类型/工作地点）/任职/供给任务；双时间轴；证件散列防重；`activate`/`cancel` 仅限系统主体（ADR-0013）；`activate` 需已通过审批单（ADR-0019） | 完整（含可执行用例与 V201/V202 迁移） |
| `outbox` | 1.0.0 | 跨域运行时：Outbox/Inbox 投递契约（`kind: runtime`，无业务对象）；`outbox.ddl` + OBX-001..012 + `tools/relay` | 完整（static/cli 用例 + CI PostgreSQL 冒烟；ADR-0018） |
| `scheduler` | 1.0.0 | 跨域运行时：定时任务执行语义（`kind: runtime`，无业务对象）；`scheduler.ddl` + SCH-001..012 + `tools/scheduler` | 完整（static/cli 用例 + CI PostgreSQL 冒烟；ADR-0021） |
| `reconciliation` | 1.0.0 | 业务对账：运行/差异/只读报告；`run_key` 幂等、受控分类 + 容忍度、差异处理走命令 | 完整（scenario 用例 + CI PostgreSQL 冒烟；ADR-0022） |

## 6. 命令处理器注册（可执行用例）

命令契约的行为由扩展自带的 `handlers.py` 提供；参考内核通过
`tools/lib/kernel.py` 的 `load_extension_handlers()` 自动加载 `extensions/*/handlers.py`，
**新增扩展无需修改内核源码**即可让 `tools/e2e-runner` 执行自己的契约用例。

```python
# extensions/{domain}/handlers.py
COMMANDS = {}

def register(api):
    return {"domain.object.action": handle_action}

def handle_action(api, payload, actor, command_id):
    # 校验 / 规则 / 不变量；用 api.reject 拒绝（携带扩展错误码）
    if not payload.get("name"):
        raise api.reject("DOM-400-001", "name 必填")
    row = api.create_object("domain_object", {"name": payload["name"]}, actor)
    event = api.event("domain.object.action-done", actor, [row["id"]], {"object_id": row["id"]})
    return [event], {"type": "domain_object", "id": row["id"]}
```

处理器签名固定为 `(api, payload, actor, command_id) -> (events, created)`，只能通过 `api`
访问内核能力：

| 能力 | 方法 |
|------|------|
| 时钟/标识/值转换 | `now` `advance` `new_id` `ts` `parse_ts` `dec` `dec_eq` |
| 拒绝命令 | `reject(code, reason, reason_code=None)`（抛出内核统一捕获的异常） |
| 双时间轴对象 | `create_object` `update_object` `apply_late_fact`（迟到事实，T-R011）`find_current` `objects` `current_objects` `as_of` `history` |
| 事件 | `event(event_type, actor, subjects, payload)` |
| 读模型/状态 | `stock(item_id, warehouse)` `locked_periods` |
| 授权 | `authz` `principal_of(actor)` `check_permission(actor, permission)` |
| 写入专用派生 | `derive_write_only(scope, raw)` `write_only_variants(scope, raw)` |

可选模块级声明：

- `SENSITIVE_FIELDS = {"domain.cmd": ("secret",)}`：命令记录脱敏（幂等指纹仍基于原文）；
- `WRITE_ONLY_FIELDS = {"domain_object": ("secret_hash",)}`：读投影剔除（writeOnly 派生字段，
  见 `01-data-contract/write-only-fields.rules.yaml`）；
- `DEFERRED_AUTHZ = {"domain.cmd"}`：内核跳过命令级预检，处理器用
  `api.check_permission` 做细粒度判定（如区块属主权限）。

加载按扩展目录名排序；命令处理器重复注册会立即报错（快速失败）。

参考内核同时按 `manifest.objects` 载入对象 Schema，在创建/更新写入前校验完整行（ADR-0016）；
Schema 违约以 `EIS-400-001` 拒绝，未声明 Schema 的对象类型 fail-closed。

## 7. 权限目录（manifest.permissions，ADR-0006）

扩展（含读取面）的权限标识应在 manifest 声明；一旦声明 `permissions`（推荐全部扩展），消费方与参考实现只使用已声明的标识：

| 字段 | 说明 |
|------|------|
| `id` | 全局唯一，必须以 `<extension.id>.` 开头（如 `hr.employee.read`）；动态属主权限可用且仅可用尾部 `.*`（如 `approval.section.confirm.*`） |
| `kind` | `command`（命令）/ `read`（读取面）/ `service`（仅服务间，如属性快照拉取） |
| `description` | 权限语义（中文一句话） |
| `scope` | 可选：行级范围语义标识（如 `same_department`），以属性快照 ABAC 条件求值（ADR-0004） |
| `scope_description` | 可选：`scope` 的语义说明（人读） |
| `callers` | 可选：允许的调用方**主体类型**（数组，取值 `person` / `system`）；缺省不限制（ADR-0013） |
| `condition` | 可选：授权条件声明（受限 DSL，`all`/`any` + `attribute`/`op`/`values`）；由判定方按声明求值，快照缺失/过期/路径缺失 fail-closed（ADR-0015） |

纪律：

- 声明目录后未声明即不可用：消费方不得自造 `<extension>.*` 权限；测试中引用的权限必须全部在目录内
  （`tools/contract-checker` 校验，未声明引用即失败）；未声明目录的扩展不参与该校验（存量扩展按需补齐）；
- 通配声明仅限**尾部** `.*`，匹配 `<前缀>.<合法段>`（段边界，不得放宽为任意前缀，`approval.section.confirm`/
  `approval.section.confirmx` 均不匹配 `approval.section.confirm.*`）；
- 读取面接入 `/check`（fail-closed）；命令面沿用内核命令级预检；
- `kind: service` 的权限不得授予用户会话或经 BFF/SPA 暴露；
- 声明 `callers` 的命令：参考内核在 `/check` 放行后、处理器之前做主体类型预检，越权以 `EIS-403-002` 拒绝；**fail-closed**（主体不存在/类型缺失同样拒绝）；
- `callers` 的权威**只在 manifest**；operations 契约用 `x-eis-callers: [system]` 做同值投影供 API 消费方阅读，`contract-checker` 双向校验（缺投影 / 缺声明 / 值不一致 / 非法枚举均失败）；
- 核心通用查询 API 由部署边界保护，不要求域级权限（ADR-0006）；
- `condition` 的路径必须落在 `04-authz-contract/attributes.api.yaml` 的 `AttributeSet` 内（段可带 `[*]`，终值必须为标量）；`op` 只允许 `eq` / `neq` / `in` / `not_in` / `exists`，逻辑只允许单层 `all` / `any`（`contract-checker` 校验）；
- **权限条件只能由声明侧提供**：`/check` 只接收 `permission`，调用方不得传入条件；条件只收窄、不授予，拒绝原因只含属性路径与状态（ATR-009）；
- 需要「业务阈值/参数可调」时，建成**领域对象 + 受审计命令**（如 `approval.threshold.set`），不引入运行期策略表达式编辑面（ADR-0015）。

## 8. 跨扩展依赖与命令前置（ADR-0019）

扩展可以声明对另一扩展的依赖，并声明「执行命令前必须存在满足条件的对象」：

```yaml
# manifest.yaml
extension:
  dependencies:
    - {id: "approval", version: "1.1.0"}   # 精确版本
  rules:
    - {name: "activation_requires_approval", file: "rules/activation-requires-approval.yaml"}
```

```yaml
# rules/activation-requires-approval.yaml
rule:
  id: "activation-requires-approval"
  applies_to: "hr.employee.activate"          # 必须是本扩展 kind: command 权限
  requires_objects:
    extension: "approval"                     # 必须出现在 dependencies
    object: "ApprovalRequest"                 # 依赖扩展 manifest.objects 的 name
    where:                                    # 精确匹配（AND）；键为对象字段路径
      status: "approved"
      "target.id": "$payload.employee_id"     # 右值：字面量或 $payload.<路径>
  error_code: "HR-409-002"                    # 扩展命名空间，不得占用 EIS-
  reason: "员工转在职必须存在已通过的入职审批单"
```

纪律：

- **只做存在性判断**：`where` 精确匹配，不支持比较运算符/正则/嵌套/OR/否定/脚本；
- 执行时机：权限与 `callers` 预检之后、处理器之前（不向未授权调用方泄漏对象存在性）；
- fail-closed：依赖扩展未加载、无匹配对象、规则文件缺失 → 命令拒绝；
- `contract-checker` 校验依赖（存在/版本/环）、`applies_to`、引用对象、`where` 与 `error_code`；不执行规则；
- 前置只读：不得通过前置写他域对象；跨域写仍走属主域命令。
