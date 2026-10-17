---
name: eis-create-contract
description: Use when generating a new EIS data or operation contract from a requirement description, or when adding fields, commands, or events to an existing contract package
---

# EIS 契约生成

## 触发条件

- 把业务需求变成 EIS 数据契约（对象 Schema）或操作契约（命令 OpenAPI）；
- 为既有扩展增加字段、命令、事件或读模型；
- 把非 EIS 数据模型迁移为 EIS 兼容工件。

## 输入

- 需求描述：对象/命令名、字段、生命周期、约束、读法；
- 目标落点：`extensions/<ext>/objects|operations/`（新扩展先建 `manifest.yaml`）；改核心契约必须先走 ADR。

## 步骤

1. **定类型**：数据对象 → `01-data-contract/object.schema.json`；命令 → `02-operation-contract/command.openapi.yaml`；事件 → `event.asyncapi.yaml`；读模型 → `view.schema.json`。
2. **数据对象**（`allOf` 两段式，领域字段放第 2 段）：
   - `$id` 形如 `eis://extensions/<ext>/object/<name>/v1`（必须含 `/v<数字>`）；`title` 必填；
   - 必填字段进 `required`；可选字段用 `"type": ["string", "null"]`；受控取值加 `enum`，description 写中文语义；
   - 字段名不得与 PostgreSQL 保留字冲突（如 `primary`；冲突时用 `is_` 前缀或 `_value` 后缀）；
   - 写入专用派生字段（散列等）不收调用方自算值：载荷传原文并标 `writeOnly`，规则见 `01-data-contract/write-only-fields.rules.yaml`；
   - 双时间轴元字段由 `allOf` 引用 `01-data-contract/object.schema.json` 提供，不要手写。
3. **命令**（仿 `extensions/hr/operations/*.openapi.yaml`）：
   - 路径 `/commands/<ext>.<domain>.<action>`；`type.const` 必须等于路径段；命名匹配 `^[a-z][a-z0-9_.]*$`；
   - 请求必含 `payload` 与 `idempotency_key`；响应至少 `202`/`400`/`409`；错误码用扩展前缀（如 `HR-409-002`）。
4. **落地与登记**：更新 `extensions/<ext>/manifest.yaml`（objects/operations/rules/permissions）；需要规则、用例或迁移时一并提交。
5. **行为用例**：涉及命令行为时，在 `extensions/<ext>/tests/*.test.yaml` 增加 `kind: scenario` 用例。

## 验证

```bash
# 生成中随时迭代（单文件，含 $ref 解析）
python3 tools/contract-checker --file <生成的文件>
# 落地后仓库级（含清单引用、权限目录、组合校验）
python3 tools/contract-checker
# 涉及命令行为时
python3 tools/e2e-runner --all
```

## 失败修复

| 报错 | 修复 |
|------|------|
| `$id 缺少版本段 /v{n}` | `$id` 末尾加 `/v1`（或对应版本） |
| `字段名与 PostgreSQL 保留字冲突` | 改名（`primary` → `is_primary`），同步操作契约 |
| `$ref ... 文件不存在` | 修正相对路径或补引用目标；不要复制核心元结构正文 |
| `type.const(...) != 路径段` | 让 `type.const` 与 `/commands/<type>` 完全一致 |
| `缺少 idempotency_key（required）` | 请求 schema 的 `required` 加入 `idempotency_key` |
| `缺少响应 ['409']` | 按 `02-operation-contract/error-codes.yaml` 补响应 |

## 参考

- 元结构与规则：`01-data-contract/`、`02-operation-contract/`
- 完整示例：`extensions/hr/`（对象 + 命令 + 用例 + 迁移）、`extensions/accounting/`（业务规则）
- 可验证示例工件：`examples/im-message.schema.json`
