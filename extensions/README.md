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
| `inventory` | 1.0.0 | 物品/出入库/库存余额；收货；库存非负 | 完整（含可执行用例） |
| `approval` | 1.0.0 | 审批申请/审批决定；提交与决定；禁止自审 | 完整（含可执行用例） |
