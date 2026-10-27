# ADR-0014：命令响应携带 `{locator, version}`（命令契约与查询契约的桥）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #32（①）；裁决 ADR-0012 §4.2；`02-operation-contract/command.openapi.yaml`、`01-data-contract/object.schema.json`、`tools/lib/kernel.py`、`02-operation-contract/tests/operation-contract.test.yaml`、`extensions/hr/tests/hr.test.yaml`

## 1. 变更原因

CQRS 下「命令完成」与「读模型追平」是两个时刻。EIS 的命令契约只定义了 `202/400/409` 与 `GET /commands/{id}` 的异步终态，`CommandAccepted` 只有 `command_id / status / event_ids`：

- 调用方拿不到「这次写落在哪个聚合、写到了哪个版本」，无法把命令结果与随后的读请求对齐；
- 参考内核的处理器**已经**返回 `{"type": ..., "id": ...}`（如 `extensions/hr/handlers.py` 的 activate），即 locator 事实上存在但未契约化；`version` 完全没有出口；
- 结果是写后读一致性只能由每个实现各自发明（轮询、sleep、读模型读旧数据冒充当前状态）。

`locator + version` 是命令契约与查询契约之间唯一的桥：命令只说「写到了哪、版本是多少」，业务数据一律由读接口返回。

## 2. 影响范围

- 核心契约：`02-operation-contract/command.openapi.yaml` 的 `CommandAccepted`（可选字段 + MUST 口径）
- 工具：`tools/lib/kernel.py` 的 `submit` 返回值（`locator` / `version`）
- 用例：`02-operation-contract/tests/operation-contract.test.yaml`（静态）、`extensions/hr/tests/hr.test.yaml`（场景断言）
- 扩展 / 案例 / DDL：无
- 未涉及：`min_version` 读后写等待语义（#32②，单独 ADR）

## 3. 兼容性分析

- 级别判定：**MINOR**。依据 `06-evolution-contract/compatibility.rules.yaml` 操作契约「可选参数新增」。
- 变更清单：

| 变更 | 判定 | 说明 |
|---|---|---|
| `CommandAccepted.locator`（可选，uuid） | MINOR | 纯新增字段 |
| `CommandAccepted.version`（可选，integer ≥1） | MINOR | 纯新增字段 |
| 把「命令响应不携带读模型投影」写成 MUST | 语义明确 | 此前未声明；参考实现本就不携带业务字段 |
| 失败响应不携带 `locator`/`version` | 语义明确 | 与既有失败响应形状一致 |

- 破坏点：无必填新增、无字段删除/改型；旧客户端忽略新字段即可。

## 4. 决策

### 4.1 语义

- `locator`：**聚合根 ID**（单聚合命令）或**流程实例 ID**（长流程命令）。
- `version`：`locator` 对应对象的版本，与 `01-data-contract/object.schema.json` 的 `version` **同一语义**（每次写 +1）——不引入第二套版本概念（投影水位由读接口的 `min_version` 表达，#32② 再定义）。
- 命令响应**不得**携带读模型投影（业务字段 / 关联字段 / 计算字段）；`event_ids` 保留——它是投递凭据，不是投影。
- 失败响应（`400/409`）不携带 `locator` / `version`（失败没有「写到哪」可言）。
- 创建命令：`locator` = 新建聚合根 ID，`version = 1`。

### 4.2 参考实现

- `submit()` 在受理成功后输出 `locator = created.id`（处理器返回的定位符）与 `version = 写入后当前行的 version`（`_find_current` 读取）。
- 处理器未返回定位符时不伪造（不以 `command_id` 冒充 `locator`）——该命令不返回这两个字段。

### 4.3 明确不做

| 不做项 | 理由 |
|---|---|
| HTTP `200/201 = 已完成` 的完成度分层（#32③） | 同一命令同时可能同步/异步响应，调用方兼容成本为负；完成度属 `GET /commands/{id}` 的 `status` |
| 命令响应内联业务数据 | 会让敏感字段绕过读投影与授权（ADR-0006 读取面授权） |
| 本次定义 `min_version` | 属读接口语义（#32②），需单独 ADR 与「未就绪」表达（建议 `409 + Retry-After`） |

## 5. 迁移方案

- 无 DDL / 无数据迁移。
- 服务端：命令 handler 返回定位符（参考内核已具备），响应输出 `locator`/`version`；未实现的端点在过渡期可不返回（字段可选）。
- 调用方：以 `locator + version` 作为读请求的起点；`min_version` 落地前，读方需自行处理投影滞后。

## 6. 回滚方案

- 回退契约中两个可选字段与内核的两行赋值即可；可选字段回滚不破坏既有消费方。
- 回滚验证：`python3 tools/e2e-runner --all` 与 `python3 tools/contract-checker` 全绿。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 命令契约 | `02-operation-contract/command.openapi.yaml` | `CommandAccepted` 增 `locator`/`version` + 不得携带读模型投影的 MUST |
| 参考内核 | `tools/lib/kernel.py` | 受理结果输出 `locator`（created.id）与 `version`（写入后当前行版本） |
| 静态用例 | `02-operation-contract/tests/operation-contract.test.yaml` | 契约含 `locator`/`version` 声明 |
| 场景用例 | `extensions/hr/tests/hr.test.yaml` | 激活返回的 `version` == 随后读到的对象 `version`；`locator` 指向该员工 |

## 8. 验收用例

- `python3 tools/e2e-runner 02-operation-contract/tests/operation-contract.test.yaml`：静态用例通过；
- `python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml`：`object-field` 断言 `version == ${steps.T5.result.version}` 且 `locator` 命中同一对象；
- `python3 tools/e2e-runner --all`：全绿（计数随新增用例更新）；
- `python3 tools/contract-checker`：通过（纯新增可选字段）。
