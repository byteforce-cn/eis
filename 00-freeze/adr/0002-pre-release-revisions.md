# ADR-0002：开源发布前定稿修订（Pre-release）

- **状态**：Accepted
- **日期**：2026-10-08
- **决策者**：核心维护者
- **关联**：ADR-0001（v1.0 冻结）

## 1. 变更原因

EIS Spec v1.0.0 完成内部冻结后、公开发布前，核查发现少量工件缺陷与实现必需
但缺失的接口细节。由于本规范**尚未对外发布**（无外部消费者），这些修订属于
"发布前定稿"，不构成对既有消费者的契约变更。

具体问题：

1. `03-time-contract/query-templates.sql` 的通用函数使用 `RETURNS TABLE AS $$`，
   该语法在 PostgreSQL 中不成立（`RETURNS TABLE` 必须声明列定义），无法执行。
2. `02-operation-contract/command.openapi.yaml` 缺少命令结果查询接口：命令 API
   为异步语义（202 受理），实现方与端到端测试无法获取命令终态。
3. `02-operation-contract/error-codes.yaml` 缺少 `401`（未认证）与 `500`（内部
   错误）两个通用错误码；扩展错误码命名空间约定仅存在于 extensions/README，
   未在错误码目录中正式声明。
4. `04-authz-contract/resolution.api.yaml` 的 `scope` 未定义结构；`/check` 的
   `reason` 无机器可读原因码，无法承载 SoD 拒绝的具体规则号。
5. `04-authz-contract/sod.rules.yaml` 未定义作用域解析与强制方式的操作语义。
6. `02-operation-contract/event.asyncapi.yaml` 的通道键 `events/{eventType}` 含
   `/`，导致内部 `$ref`（`#/channels/events%7BeventType%7D`）不符合 JSON Pointer
   规范，无法解析（由 contract-checker 检出）。
7. `03-time-contract/temporal.ddl` 内嵌的展开示例建表语句（`accounting_balance`）
   与 `schema-compiler` 生成物**重名冲突**（真机 PostgreSQL 验证检出）；
   `query-templates.sql` 展开示例的 `account_id` 与 `balance.schema.json` 的
   `account_code` **不一致**。

## 2. 影响范围

- 契约：操作契约（命令 API、错误码）、时间契约（查询模板）、授权契约（解析 API、
  SoD 规则）。
- 扩展 / 案例：无（接口为新增，不破坏既有引用）。
- 工具：tools/*（这些修订是工具实现的前置条件）。

## 3. 兼容性分析

依据 `06-evolution-contract/compatibility.rules.yaml`：

| 修订 | 判定 | 依据 |
|------|------|------|
| 查询模板语法修复 | PATCH | Bug 修复（工件原先不可执行） |
| `GET /commands/{id}` 新增 | MINOR | API 新增 |
| 错误码新增（401/500） | MINOR | 新错误码新增（不改变既有含义） |
| 错误码命名空间声明 | PATCH | 文档明确既有约定 |
| Scope 结构 / reason_code 新增 | MINOR | 可选字段新增 |
| SoD 语义说明 | PATCH | 文档明确既有意图 |
| AsyncAPI 通道键 / $ref 修正 | PATCH | Bug 修复（原引用不可解析；线上地址仍为 `events.{eventType}`） |
| 展开示例对齐生成物 | PATCH | Bug 修复（原示例与 Schema/生成器冲突，不可同时执行） |

- 破坏点：无。
- 正式对外发布版本仍为 **1.0.0**（本 ADR 属发布前定稿；发布后任何变更必须按
  正常 ADR 流程并升版）。

## 4. 迁移方案

不适用（无既有消费者，无数据迁移）。

## 5. 回滚方案

回退至本 ADR 之前的提交；不影响任何部署。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 查询模板修复 | `03-time-contract/query-templates.sql` | plpgsql 动态 SQL，可直接执行 |
| 命令结果查询 | `02-operation-contract/command.openapi.yaml` | `GET /commands/{id}` + CommandStatus |
| 错误码补齐 | `02-operation-contract/error-codes.yaml` | EIS-401-001、EIS-500-001、命名空间约定 |
| 授权解析补全 | `04-authz-contract/resolution.api.yaml` | Scope Schema、reason_code、sod_warnings |
| SoD 语义 | `04-authz-contract/sod.rules.yaml` | 作用域解析与强制方式说明 |
| AsyncAPI 引用修正 | `02-operation-contract/event.asyncapi.yaml` | 通道键 `eventMessages`，地址仍为 `events.{eventType}` |
| 示例对齐生成物 | `03-time-contract/temporal.ddl`、`query-templates.sql` | 移除内嵌建表（指向 `build/ddl/`）；示例函数字段对齐 `account_code` |

## 7. 验收用例

- `03-time-contract/tests/time-contract.test.yaml`（模板可执行性由 DDL 冒烟测试覆盖）
- `02-operation-contract/tests/operation-contract.test.yaml`（命令/错误码结构检查）
- `04-authz-contract/tests/authz-contract.test.yaml`（SoD 可检测）
