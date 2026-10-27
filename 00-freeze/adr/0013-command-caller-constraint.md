# ADR-0013：命令调用方约束（manifest.permissions[].callers + x-eis-callers）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #30（步骤 1）；ADR-0012 §4.2；先例 ATR-008（属性端点仅限服务间）、ADR-0006（扩展权限目录）；`extensions/README.md` §7、`extensions/hr/manifest.yaml`、`extensions/hr/operations/employee-{activate,cancel}.openapi.yaml`、`tools/contract-checker`、`tools/lib/kernel.py`、`02-operation-contract/error-codes.yaml`

## 1. 变更原因

AUD-01（issue #30）：SPA 可直接调用 `hr.employee.activate` 绕过审批单与 coord workflow。服务端只校验「待入职 + 有有效主岗」，契约层也没有任何位置声明「这个命令只能由谁调」：

- `extensions/hr/operations/employee-activate.openapi.yaml` 只声明 `202/400/409` 与错误码；
- `manifest.permissions` 只有 `kind`（`command`/`read`/`service`），表达不了「仅系统主体可调」；
- 结果：只要持有权限，用户会话即可调用——UI 隐藏与角色绑定都不构成服务端约束。

EIS 已有同类先例：ATR-008 要求属性快照端点「以服务身份（system principal）认证且持有 service 权限」。但 ATR-008 是属性协议专用，命令面仍无通用机制。本 ADR 补上这一层。

## 2. 影响范围

- 核心契约：`02-operation-contract/error-codes.yaml` 新增错误码（语义加法）
- 扩展契约机制：`manifest.permissions[].callers`（机器可读、可校验）+ operations 契约的 `x-eis-callers` 投影
- 扩展：`extensions/hr` 1.1.0 → 1.2.0；`hr.employee.activate` / `hr.employee.cancel` 声明 `callers: ["system"]`
- 工具：`tools/contract-checker`（双向校验）、`tools/lib/kernel.py`（命令级预检）
- 案例：无（`cases/procurement` 不锁定 hr 版本）

## 3. 兼容性分析

- 级别判定：**MINOR**。

| 变更 | 判定 | 依据 |
|---|---|---|
| 新增错误码 `EIS-403-002`（`caller_not_allowed`） | MINOR | `error-codes.yaml` conventions：「新增错误码属于 MINOR」 |
| `manifest.permissions[].callers` 可选字段 | MINOR | 可选字段新增（`compatibility.rules.yaml` 数据契约同条） |
| operations 契约 `x-eis-callers` 可选 vendor extension | MINOR | 可选参数新增 |
| `hr.employee.activate/cancel` 允许主体收紧为 `system` | 语义收紧 | 此前「任何持权限主体可调」是未定义行为，且是 AUD-01 的绕过路径；合规调用方（审批服务身份）不受影响 |

- 破坏点：以用户会话直接调用 `hr.employee.activate/cancel` 的部署会被拒绝（`EIS-403-002`）——这是本 ADR 的目的。
- 未声明 `callers` 的命令行为完全不变。

## 4. 决策

### 4.1 声明位置与权威

- **权威**：`extensions/{id}/manifest.yaml` 的 `permissions[].callers`（`["person"|"system", ...]`，非空、去重、无通配）。内核只读这一处，避免两套判定。
- **投影**：扩展 operations 契约在命令 operation 上加 `x-eis-callers`（OpenAPI vendor extension），供 API 消费方与代码评审阅读；`tools/contract-checker` 强制**双向一致**：
  - 有投影无声明 → 失败；
  - 有声明无投影 → 失败；
  - 两处值不一致 → 失败；
  - 枚举越界/空数组/重复 → 失败。
- 为什么不在 operations 契约里做唯一权威：内核（运行时）只加载 manifest，不解析 OpenAPI；把唯一权威放在被运行时读取的地方，OpenAPI 侧做可校验投影，是「判定权威唯一 + 对外可读」的最小成本解。

### 4.2 判定语义

- 时机：命令级预检（`Kernel.submit`），在 `/check` 放行之后、处理器执行之前——与既有命令权限预检同一位置。
- 缺省：未声明 `callers` 即不做类型限制（向后兼容）。
- 失败：`EIS-403-002`（`caller_not_allowed`），**fail-closed**：主体不存在、`type` 缺失/未知一律按违规处理。
- 未装载授权夹具（无 `authz`）时不判定主体类型，与既有「无夹具即不做权限判定」一致（夹具只用于测试与参考实现）。

### 4.3 明确不做

| 不做项 | 理由 |
|---|---|
| 调用方 ID 白名单（固定服务 UUID） | 多实例服务的身份不是固定实例 ID；正确抽象是「主体类型 + 审批单前置」（步骤 2） |
| IP / 网段 / mTLS / token scope 约束 | 传输层与部署边界，不进契约（ADR-0012 三层判据） |
| 用 `EIS-403-001` 表达调用方越权 | `EIS-403-001` 专指 `/check` 判定拒绝；混用会让审计无法区分「无权限」与「主体类型不对」 |
| 审批单前置（`employee.status == pending_onboarding implies exists(approval.request ... approved)`） | 需扩展跨引用机制（hr → approval）+ `contract-checker` 引用完整性校验，另立 ADR（#30 步骤 2） |

## 5. 迁移方案

- 契约：`manifest.yaml` 增 `callers`；operations 契约增 `x-eis-callers`；hr 版本 1.2.0。
- 实现：部署侧把 `hr.employee.activate/cancel` 的调用方切换为审批服务身份（system principal），用户会话不再持有该命令的调用路径。
- 数据：无 DDL / 无回填。
- 对账：`contract-checker` 双向一致性 + `e2e-runner` 场景断言（用户主体拒绝 / 服务主体允许）。

## 6. 回滚方案

- 删除 `callers` 与 `x-eis-callers` 两处声明并回退 hr 版本即恢复旧行为（内核「无声明不判定」）。
- 回滚验证：`python3 tools/e2e-runner --all` 与 `python3 tools/contract-checker` 全绿。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 错误码 | `02-operation-contract/error-codes.yaml` | `EIS-403-002` `caller_not_allowed` |
| 扩展契约机制 | `extensions/README.md` §7 | `callers` 字段、`x-eis-callers` 投影、fail-closed 口径 |
| hr 声明 | `extensions/hr/manifest.yaml`、`operations/employee-activate.openapi.yaml`、`operations/employee-cancel.openapi.yaml` | `callers: ["system"]` + 投影 |
| hr 说明 | `extensions/hr/README.md` | 调用方约束与部署要求 |
| 校验工具 | `tools/contract-checker` | `callers` 枚举/非空/去重 + 投影双向一致 + 自测三条断言 |
| 运行时 | `tools/lib/kernel.py` | `permission_callers` 载入 + `submit` 预检 + `EIS-403-002` |
| 用例 | `extensions/hr/tests/hr.test.yaml` | 服务主体成功、用户主体（持有权限）拒绝；既有 activate/cancel 步骤改用审批服务主体 |

## 8. 验收用例

- `python3 tools/contract-checker --self-test`：三条漂移断言（缺声明/值不一致/非法枚举）全过；
- `python3 tools/contract-checker`：全过（hr 声明与投影一致）；
- `python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml`：全绿，含「用户主体调用 → `EIS-403-002`」「审批服务主体 → 成功」；
- `python3 tools/e2e-runner --all`：全绿（用例计数随新增场景更新）。
