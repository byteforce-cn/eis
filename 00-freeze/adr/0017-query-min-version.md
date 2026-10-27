# ADR-0017：读接口 `min_version` 等待语义（409 + Retry-After）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #32②（上游 #32、#33）；ADR-0012 §4.2；ADR-0014（命令响应 `{locator, version}`）；`02-operation-contract/query.openapi.yaml`、`error-codes.yaml`、`tools/lib/kernel.py`

## 1. 变更原因

ADR-0014 让命令响应携带 `{locator, version}`，调用方因此知道「本次写入产生了哪个对象的哪个版本」。
但读侧没有对应契约：命令完成后投影可能尚未追平，调用方无法表达「我要读到包含版本 N 的状态」，
只能在应用层轮询并自行判断「读到的旧数据算不算当前状态」。

issue #32② 要求补上这个桥的另一半。三种候选表达（202 / 阻塞 / 409）中，202 会让缓存与代理
语义歧义，阻塞把超时策略推给服务端；**409 + Retry-After** 最不歧义，且与既有「冲突」语义
（`EIS-409-*`）同一族。

## 2. 影响范围

- 核心契约：`02-operation-contract/query.openapi.yaml` 增可选 `min_version` 参数与
  `409 + Retry-After` 响应；`error-codes.yaml` 增 `EIS-409-003`（MINOR）
- 参考内核：`Kernel.read_object()` 按 `min_version` 返回 200/409；scenario 断言 `read-min-version`
- 用例：`02-operation-contract/tests/read-after-write.test.yaml`（未追平 409 / 追平 200）
- 文档：本 ADR、`docs/KNOWN-LIMITATIONS.md`（参考内核无异步投影的残余）

## 3. 兼容性分析

- 级别判定：**MINOR**。

| 变更 | 判定 | 依据 |
|---|---|---|
| `GET /objects/{objectType}/{id}` 增可选 `min_version` | MINOR | 可选参数新增，既有请求行为不变 |
| 新错误码 `EIS-409-003`（`read_model_not_ready`） | MINOR | `error-codes.yaml` conventions：「新增错误码属于 MINOR」 |
| 409 响应要求 `Retry-After` | MINOR | 新增响应形态，只在使用 `min_version` 时出现 |

- 破坏点：无。不带 `min_version` 的读行为完全不变。

## 4. 决策

### 4.1 参数与语义

- `GET /objects/{objectType}/{id}?min_version=N`，`N` 为整数且 `>= 1`；
- 语义：**返回包含版本 N 的状态**——返回对象的 `version >= N`；
- `min_version` 是**对象版本**（`01-data-contract/object.schema.json` 的 `version`，每次写 +1），
  不是投影水位；不引入第二套版本概念；
- 与 `as_of` / `recorded_as_of` 组合时，同样比较「返回版本的 `version`」；历史时点天然可能
  低于 N，调用方不应把 `min_version` 与时点查询组合使用（契约不做特殊放行）。

### 4.2 未就绪表达

- 当前可读版本 `< N`：返回 **409**，`reason_code=EIS-409-003`，并带 `Retry-After`（秒）；
- **不得**以 200 返回低版本数据冒充当前状态；
- 不使用 202（缓存/代理语义歧义）、不使用阻塞等待（超时策略属于调用方/部署方）；
- 调用方按 `Retry-After` 退避重试；重试直到 200，或按业务超时放弃。

### 4.3 参考实现

- `Kernel.read_object(obj_type, id, min_version=None, valid_at=None, recorded_at=None)`
  返回 `{status, version, object}` 或 `{status: 409, reason_code: EIS-409-003, retry_after: 1, version, min_version}`；
- 参考内核的读模型是同步内存，**不存在真实投影滞后**；用例通过「请求版本 > 当前版本」验证
  比较语义与 409/200 分支（残余见 `docs/KNOWN-LIMITATIONS.md` §2.4）；
- scenario 断言 `read-min-version`：断言状态码、`Retry-After`、版本下界与 409 不返回已追平数据。

### 4.4 明确不做

| 不做项 | 理由 |
|---|---|
| `202 Accepted` 表达未就绪 | GET 返回 202 对缓存/代理语义不友好；202 专用于命令受理 |
| 阻塞等待 / 长轮询 | 超时与重试策略属于调用方；契约只表达「未就绪」 |
| 投影水位（投影自己的版本号） | 会引入第二套版本概念；`min_version` 只认对象版本 |
| 用 ETag / If-Match 表达读后写 | 属 HTTP 缓存/并发控制语义，与对象版本契约重复 |
| 余额读接口的 `min_version` | 余额是投影聚合，缺对象版本语义；需要时另立 ADR（按聚合版本或新增字段） |
| 命令响应携带读模型数据 | ADR-0014 已定：命令响应不承担查询职责 |

## 5. 迁移方案

- 契约：新增可选参数与错误码；客户端可选择使用（`locator + version` 来自命令响应）。
- 实现：读接口实现 409 分支与 `Retry-After`；不带 `min_version` 的路径不变。
- 数据：无 DDL / 无回填。
- 对账：`e2e-runner` 用例 + `contract-checker`（错误码/查询契约）。

## 6. 回滚方案

- 移除 `min_version` 参数与 `EIS-409-003` 即恢复旧行为；客户端忽略 409 分支即可。
- 回滚验证：`python3 tools/e2e-runner --all` 全绿。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 查询契约 | `02-operation-contract/query.openapi.yaml` | `min_version` 参数、409 + `Retry-After`、语义说明 |
| 错误码 | `02-operation-contract/error-codes.yaml` | `EIS-409-003` `read_model_not_ready`（retryable） |
| 参考内核 | `tools/lib/kernel.py` | `read_object` + `read-min-version` 断言 |
| 用例 | `02-operation-contract/tests/read-after-write.test.yaml` | 未追平 → 409；追平 → 200 且 version >= N |
| 文档 | `docs/KNOWN-LIMITATIONS.md` §2.4 | 参考内核同步读模型，无法复现真实滞后 |

## 8. 验收用例

- `python3 tools/e2e-runner 02-operation-contract/tests/read-after-write.test.yaml`：2/2；
- `python3 tools/e2e-runner --all`：全绿（用例计数随新增用例更新）；
- `python3 tools/contract-checker`：全过（新错误码/查询契约合法）；
- 反例：`min_version=2` 而当前版本为 1 → 409 + `Retry-After >= 1`，且响应版本 `< 2`；
  写入后 `min_version=2` → 200 且 `version >= 2`。
