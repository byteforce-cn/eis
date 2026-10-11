# ADR-0006：读取面授权口径与扩展权限目录

- **状态**：Accepted
- **日期**：2026-10-11
- **决策者**：核心维护者（EIS Spec 维护方）
- **关联**：issue #7；`extensions/hr/manifest.yaml`、`04-authz-contract/attributes.api.yaml`、`attribute.rules.yaml`（ATR-008）、`tools/contract-checker`、`extensions/README.md` §7

## 1. 变更原因

`extensions/hr` v1.0.0 声明了 11 个命令与 5 条规则，但**没有声明任何读取面权限**；
消费方按「契约沉默」实现为「认证即可读」：任何持有效令牌的主体都能读取任意员工/任意部门的
名册、详情与属性快照。这既不符合「领域权限目录属于扩展契约、只使用契约声明的权限标识」的
平台纪律，也让跨部门数据可见性在财务/审批视角接入时成为明确风险（issue #7）。

同时，`/principals/{id}/attributes` 作为判定链路的内部协议，其调用方边界
（服务间 vs 用户直读）未在契约中写明。

## 2. 影响范围

- 契约：`extensions/README.md` 新增 manifest `permissions` 约定（加法）；`04-authz-contract/attributes.api.yaml`
  补调用方边界与 403（加法）；`attribute.rules.yaml` 新增 ATR-008；`02-operation-contract/query.openapi.yaml`
  补读面口径描述（PATCH 级）；
- 扩展：`extensions/hr` 声明 11 命令 + 2 读取权限并补可执行授权用例；
- 案例：不涉及；
- 工具：`tools/contract-checker` 校验权限目录结构与测试引用（未声明引用即失败）。

## 3. 兼容性分析

- 级别判定：**MINOR**（新增可选 manifest 段、权限标识与规则；既有请求/响应语义不变）。
- 核心通用查询 API（`GET /objects/{objectType}/{id}`）**不引入域级 permission**，保持
  「资源服务器认证 + 部署网络策略」边界，因此不对既有消费方产生行为变化；
  扩展自有读面（如 hr 名册/详情）由扩展声明的 read 权限约束，消费方按新目录接入。
- 破坏点：无。

## 4. 迁移方案

- 消费方（ims-hr 等）：读取面按 manifest 声明接入 `starter-eis-authz` `/check`；
  行级 `same_department` 以属性快照条件（ADR-0004）求值；不得自造 `hr.*` 权限标识。
- 属性派生/判定方：`/principals/{id}/attributes` 仅以服务身份调用（ATR-008），不经 BFF/SPA。
- 数据迁移：不涉及。

## 5. 回滚方案

移除 `manifest.permissions`、ATR-008 与 contract-checker 校验即可回到变更前；声明为纯加法，
不影响既有用例与数据。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 权限目录 | `extensions/hr/manifest.yaml`（`permissions`） | 11 命令 + `hr.employee.read`（read/same_department）+ `hr.attributes.read`（service） |
| 校验器 | `tools/contract-checker`（`check_manifest_permissions`） | 命名空间/唯一性/kind/描述 + 测试引用不得自造，含自测 |
| 属性端点边界 | `04-authz-contract/attributes.api.yaml`、`attribute.rules.yaml`（ATR-008） | 服务间专用 + fail-closed |
| 核心口径 | `02-operation-contract/query.openapi.yaml` 描述、`extensions/README.md` §2/§7 | 核心查询部署边界；扩展读面声明权限 |
| 用例 | `extensions/hr/tests/fixtures-authz.yaml`、`hr.test.yaml`（6 条 `kind: authz`） | 允许/拒绝/服务间/ABAC 条件 |

## 7. 验收用例

- `hr.employee.read`：hr-admin 允许、hr-employee 拒绝（`NO_PERMISSION`）；
- `hr.attributes.read`：hr-service（system）允许、hr-admin（person）拒绝；
- `same_department` ABAC：属性条件匹配允许（`attribute_state=fresh`）、不匹配拒绝（`ATTRIBUTE_MISMATCH`）；
- `tools/contract-checker --self-test`：未声明权限引用与非命名空间 id 被拒；
- `python3 tools/e2e-runner --all` 全绿。
