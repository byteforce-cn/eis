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
| `approval` | 1.0.1 | 审批申请/决定/区块；提交与决定、区块流转、打回重确认、撤回；禁止自审 | 完整（含可执行用例） |
| `hr` | 1.0.0 | 组织/岗位/员工/任职/供给任务；双时间轴；证件散列防重 | 完整（含可执行用例与 V201 迁移） |

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
| 双时间轴对象 | `create_object` `update_object` `find_current` `objects` `current_objects` `as_of` `history` |
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

## 7. 权限目录（manifest.permissions，ADR-0006）

扩展（含读取面）的权限标识应在 manifest 声明；一旦声明 `permissions`（推荐全部扩展），消费方与参考实现只使用已声明的标识：

| 字段 | 说明 |
|------|------|
| `id` | 全局唯一，必须以 `<extension.id>.` 开头（如 `hr.employee.read`）；动态属主权限可用且仅可用尾部 `.*`（如 `approval.section.confirm.*`） |
| `kind` | `command`（命令）/ `read`（读取面）/ `service`（仅服务间，如属性快照拉取） |
| `description` | 权限语义（中文一句话） |
| `scope` | 可选：行级范围语义标识（如 `same_department`），以属性快照 ABAC 条件求值（ADR-0004） |
| `scope_description` | 可选：`scope` 的语义说明（人读） |

纪律：

- 声明目录后未声明即不可用：消费方不得自造 `<extension>.*` 权限；测试中引用的权限必须全部在目录内
  （`tools/contract-checker` 校验，未声明引用即失败）；未声明目录的扩展不参与该校验（存量扩展按需补齐）；
- 通配声明仅限**尾部** `.*`，匹配 `<前缀>.<合法段>`（段边界，不得放宽为任意前缀，`approval.section.confirm`/
  `approval.section.confirmx` 均不匹配 `approval.section.confirm.*`）；
- 读取面接入 `/check`（fail-closed）；命令面沿用内核命令级预检；
- `kind: service` 的权限不得授予用户会话或经 BFF/SPA 暴露；
- 核心通用查询 API 由部署边界保护，不要求域级权限（ADR-0006）。
