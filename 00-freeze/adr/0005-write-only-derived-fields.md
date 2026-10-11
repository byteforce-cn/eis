# ADR-0005：写入专用派生字段的服务端派生与密钥托管

- **状态**：Accepted
- **日期**：2026-10-11
- **决策者**：核心维护者（EIS Spec 维护方）
- **关联**：issue #6；`01-data-contract/write-only-fields.rules.yaml`、`extensions/hr`、`extensions/iam`、`docs/COORD-REQUIREMENTS.md`（G-TR-3）

## 1. 变更原因

核心契约把 `Employee.id_number_hash`（`extensions/hr`）与 `Credential.secret_hash`（`extensions/iam`）
定义为「写入专用散列」，字段名与形状说明散列由写入方提供，但**没有规定哈希生产者与密钥托管**：

- 浏览器（SPA）依约不接触令牌与密钥，BFF 是通用 OIDC/路由代理，均无合法生产者；
- 纯浏览器表单要么把 HMAC 密钥发到浏览器（安全回退），要么绕过契约新增未声明的明文入口（违反 §3.2 写路径唯一）；
- 无密钥 custody/轮换口径时，防重能力在真实使用中不可用（`ims-hr` 建档缺证件号、`ims-iam` 凭证入口受限）。

同时，`tools/lib/kernel.py` 的敏感字段机制只覆盖命令记录脱敏，没有原始值入参、服务端派生
与读投影剔除的可执行语义，契约声明无法被验收。

## 2. 影响范围

- 契约：`01-data-contract` 新增规则文件（加法）；`02-operation-contract/command.openapi.yaml` 补充描述（PATCH 级）；
- 扩展：`extensions/hr` 载荷由 `id_number_hash` 改为原始 `id_number`（发布前修正，见 §3）；`extensions/iam` 明确适用同一 custody 口径（指定生产者过渡）；
- 案例：不涉及；
- 工具：`tools/lib/kernel.py` 新增密钥环与派生/投影 API 与 `object-absent` 断言；`docs/IMPLEMENTATION.md` 增加密钥服务映射。

## 3. 兼容性分析

- 级别判定：**MINOR**（新增规则文件与可选能力；不改变既有字段语义与读路径行为）。
- hr 载荷修正：`hr` v1.0.0 处于 `[Unreleased]` 窗口、尚未发布，`id_number_hash` 入参属发布前修正
  （替换为 `id_number` 原始值）。已发布的 `iam` 契约不动：`secret_hash` 的「指定生产者」
  （引导程序，受信后端）被显式承认（DRV-006），待原始值入口出现时再迁移到 DRV-001。
- 破坏点：无（核心）；hr 未发布窗口内的接口形状修正已在 CHANGELOG 标注。

## 4. 迁移方案

- 消费方（ims-hr 等）：建档/更新载荷改传原始值 `id_number`；不计算、不存储散列；读投影继续剔除。
- 参考内核：`Kernel(field_hash_keys=[...])` 或环境变量 `EIS_FIELD_HASH_KEYS` 注入密钥环；
  处理器经 `api.derive_write_only(scope, raw)` 派生、`api.write_only_variants(scope, raw)` 防重；
  模块级 `WRITE_ONLY_FIELDS` 声明读投影剔除。
- 生产部署：注入用途密钥（首为主）；轮换按 DRV-005 密钥环窗口执行，旧密钥保留至无在库依赖。
- 数据迁移：不涉及（原始值不落库；存量散列在其密钥仍在环内时继续参与防重）。

## 5. 回滚方案

移除规则文件与内核新增 API，hr 载荷恢复 `id_number_hash` 即回到变更前语义（未发布窗口内无存量数据问题）；
内核 `read_projection`/`object-absent` 为纯加法，可保留不影响既有用例。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 规则表 | `01-data-contract/write-only-fields.rules.yaml` | DRV-001..006（生产者/托管/派生/剔除/轮换/凭据） |
| 参考内核 | `tools/lib/kernel.py` | `derive_hmac`、密钥环、`derive_write_only`/`write_only_variants`、`read_projection`、`WRITE_ONLY_FIELDS` |
| e2e 断言 | `tools/lib/kernel.py`（`object-absent`） | 读投影剔除的可执行判据 |
| hr 契约 | `extensions/hr/operations/employee-create.openapi.yaml`、`objects/employee.schema.json`、`README.md`、`handlers.py` | 原始值入参与服务端派生 |
| iam 契约 | `extensions/iam/handlers.py` | `Credential.secret_hash` 读投影剔除（`WRITE_ONLY_FIELDS`）；custody 口径声明（DRV-006） |
| 用例 | `extensions/hr/tests/hr.test.yaml` | 派生确定性、防重、脱敏、读投影剔除、轮换窗口、空值拒绝 |
| 落地映射 | `docs/IMPLEMENTATION.md` | 受信密钥服务映射（含 coord Transit 前置） |
| coord 需求 | `docs/COORD-REQUIREMENTS.md`（G-TR-3） | 用途化 HMAC 密钥 + 轮换窗口 |

## 7. 验收用例

- `extensions/hr/tests/hr.test.yaml`：`hr.hire-to-active`（派生散列确定值）、`hr.id-dedup-rehire`（防重）、
  `hr.sensitive-redaction`（命令记录 + 读投影剔除、幂等重放）、`hr.write-only-rotation`（轮换窗口）、
  `hr.id-number-required`（空值拒绝）、`hr.id-number-hash-rejected`（拒绝调用方自算散列）；
- `extensions/iam/tests/iam.test.yaml`：凭证轮换后读投影剔除 `secret_hash`（`object-absent`）；
- `01-data-contract/tests/data-contract.test.yaml`：规则文件存在且含 DRV-001..006（静态用例）；
- `python3 tools/e2e-runner --all` 全绿；对应 `acceptance.yaml`「所有 Schema 通过校验 / 所有用例可执行」。
