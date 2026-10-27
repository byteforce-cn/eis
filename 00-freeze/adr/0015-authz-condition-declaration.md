# ADR-0015：授权条件声明面（manifest.permissions[].condition 受限 DSL）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #28、#29；ADR-0012 §4.2 裁决；ADR-0004（属性属主与拉取为准）、ADR-0006（扩展权限目录）；`04-authz-contract/attribute.rules.yaml`（ATR-003/006/007/009）、`04-authz-contract/attributes.api.yaml`、`04-authz-contract/resolution.api.yaml`、`extensions/README.md` §7、`tools/contract-checker`、`tools/authz-resolver`、`tools/lib/kernel.py`

## 1. 变更原因

ABAC 条件目前**没有契约位置**：

- `manifest.permissions[]` 只有 `kind`（`command`/`read`/`service`）、`scope`、`callers`，表达不了「该权限只在某属性条件下成立」；
- 参考实现 `tools/authz-resolver` 的 `check(..., require_attributes=...)` 与 CLI
  `--require-attribute` 允许**调用方传入条件**——调用方可以漏传/放宽条件拿到 `allowed=true`，
  这正是 AUD-01「UI 隐藏等于授权」的通用形式（#28）；
- `require_attribute` 是 seedj 的加法字段，名称/形状/语义与参考实现不一致，未进契约；
- 业务方想要的「不发版就调策略」实际是阈值参数，不是条件结构；开放任意策略表达式
  （Rego 等）会破坏 `as_of` 判定的离线可复现与审计链自证（#29）。

EIS 已有可复用的判定语汇：属性快照（`attributes.api.yaml` 的 `AttributeSet`）、
ATR-003（主岗/任一岗位必须显式声明）、ATR-006/007（fail-closed 与不匹配拒绝）。
本 ADR 把条件**声明化**，补上这一层。

## 2. 影响范围

- 核心契约：`04-authz-contract/attribute.rules.yaml` 新增 ATR-009 与 `condition_language`；
  `04-authz-contract/resolution.api.yaml` 明确「条件只由声明侧求值」（无 Schema 字段新增）
- 扩展契约机制：`manifest.permissions[].condition`（可选、机器可读、`contract-checker` 校验）
- 工具：`contract-checker`（路径/op/结构校验 + 自测）、`authz-resolver`（声明侧求值；移除
  调用方条件入口）、`e2e-runner`（`kind: authz` 支持 `conditions`）、`tools/lib/eis_conditions.py`（共享 DSL）
- 参考内核：加载 `extensions/*/manifest.yaml` 的条件声明并传给判定方；命令级预检与处理器内
  `check_permission` 同一语义
- 扩展：无新增业务扩展；`extensions/hr/tests` 移除两条调用方传条件的反模式用例

## 3. 兼容性分析

- 级别判定：**MINOR**。

| 变更 | 判定 | 依据 |
|---|---|---|
| `manifest.permissions[].condition` 可选字段 | MINOR | 可选字段新增（`compatibility.rules.yaml` 数据契约同条） |
| `attribute.rules.yaml` 新增 ATR-009 + `condition_language` | MINOR | 规则加法；不改变已声明权限的行为 |
| `/check` 语义明确为「按声明求值」 | PATCH | 契约文档澄清；请求/响应 Schema 无变化 |
| 移除参考实现的 `require_attributes` / `--require-attribute` | 工具级破坏 | 该入口从未进契约，且是本次要消除的**安全反模式**；不是契约破坏 |

- 破坏点：依赖「调用方自带条件」获得放行的部署会在迁移后失去该行为（这是本 ADR 的目的）。
- 未声明 `condition` 的权限行为完全不变。

## 4. 决策

### 4.1 声明位置与权威

- **权威**：`extensions/{id}/manifest.yaml` → `permissions[].condition`。
- `contract-checker` 校验；参考实现（authz-resolver / 参考内核）只读这一处，避免两套判定。
- **调用方不得提供条件**：`/check` 请求只含 `principal` / `permission` / `as_of` /
  `recorded_as_of` / `attributes`（属性快照）。条件由判定方按声明求值。
- 条件**只收窄、不授予**：先判「权限是否持有」，再求值条件；未持有直接 `NO_PERMISSION`，
  不因属性状态泄漏额外信息。

### 4.2 DSL（受限、可机械校验）

```yaml
permissions:
  - id: "demo.document.read"
    kind: read
    description: 读取文档
    condition:
      all:                                   # 或 any；二选一、单层、不递归
        - {attribute: "primary_position.grade", op: "in", values: ["M2", "P1"]}
        - {attribute: "positions[*].grade", op: "not_in", values: ["P9"]}
```

| 约束 | 规定 |
|---|---|
| 逻辑 | `all` / `any` **二选一**，非空数组，单层；嵌套或混合即拒绝 |
| 子句 | 只允许 `attribute` / `op` / `values` 三个字段 |
| `op` | 白名单：`eq` / `neq` / `in` / `not_in` / `exists` |
| `attribute` | `04-authz-contract/attributes.api.yaml` 的 `AttributeSet` 内点分路径；段可带 `[*]`；终值必须是标量（或标量数组经 `[*]`）；不得引用整个对象/数组 |
| `values` | 非空标量数组（字符串/数字/布尔/null）；`exists` 只接受 `[true]` 或 `[false]` |
| 语义 | `eq`/`in` 对候选集为**存在**语义；`neq`/`not_in` 为**全称**语义；`[*]` 表示「任一岗位」（ATR-003） |
| 失败 | 快照 `missing`/`stale`/`source_unavailable`、路径缺失 → `ATTRIBUTE_MISSING`/`ATTRIBUTE_STALE`/`ATTRIBUTE_SOURCE_UNAVAILABLE`；不满足 → `ATTRIBUTE_MISMATCH`（ATR-006/007） |
| 泄漏 | 拒绝原因只含属性**路径**与状态，不含属性值全文 |

`scope`（ADR-0006）是**行级范围**（目标数据属于哪个部门/仓库）；`condition` 是
**调用方属性**（调用者本人是否满足）。两者不可互相替代，可同时存在。

### 4.3 判定时机

- 读取面：判定方 `POST /check` / 读取鉴权使用同一声明求值路径。
- 命令面：参考内核在命令级权限预检处求值（`Kernel.submit`）；`DEFERRED_AUTHZ` 命令在
  处理器的 `api.check_permission` 中求值——与既有权限判定同一位置。
- `resolve` 仍只列「持有」的角色/权限，不求值条件（条件不改变持有关系，只收窄 `check`）。

### 4.4 明确不做

| 不做项 | 理由 |
|---|---|
| `/check` 接受调用方传入条件 | 调用方可漏传/放宽（AUD-01 的通用形式）；条件必须由被判定方之外声明 |
| 任意策略表达式 / Rego / 运行期编辑 | 破坏 `as_of` 判定可复现与审计自证；阈值类需求走「领域对象 + 受审计命令」 |
| 嵌套 `all`/`any`、`not`、脚本/正则操作符 | 收敛为可机械校验的子集；需要更强表达时按 MINOR 演进 DSL |
| `deny` 条件 / 条件授予权限 | 授权模型只有「持有 + 收窄」；deny 会引入优先级与冲突裁决 |
| 引用其它扩展的对象字段作为条件 | 条件只读属性快照（ATR-001 属主唯一）；跨扩展前置见 #30 步骤 2 |
| 把条件写进 operations OpenAPI 作为权威 | 内核不解析 OpenAPI；权威必须在被运行时读取的 manifest，契约侧最多做投影（本次不做） |

## 5. 迁移方案

- 契约：权限目录增可选 `condition`；未声明者不变。
- 实现：把 seedj 等实现里的 `require_attribute` 调用方参数迁移为 manifest 声明；服务端
  只从声明求值，拒绝任何调用方提供的条件。
- 参考工具：`authz-resolver check` 移除 `--require-attribute`，新增 `--conditions FILE`
  （参考实现测试/嵌入用；缺省读 `extensions/*/manifest.yaml`）。
- 数据：无 DDL / 无回填。
- 对账：`contract-checker` 校验路径/op/结构；`kind: authz` 与内核自测覆盖匹配/不匹配/
  missing/stale/source_unavailable/任一岗位语义。

## 6. 回滚方案

- 删除扩展里的 `condition` 声明即恢复旧行为（未声明不求值）；参考工具可回退本次提交。
- 已被拒绝的「调用方传条件」路径**不恢复**——它从来不在契约内，且是本次修复的漏洞。
- 回滚验证：`python3 tools/e2e-runner --all` 与 `python3 tools/contract-checker` 全绿。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 规则 | `04-authz-contract/attribute.rules.yaml` | ATR-009 + `condition_language`（op/路径/失败口径/不做项） |
| 判定 API 说明 | `04-authz-contract/resolution.api.yaml` | 条件由声明侧求值；`/check` 不接收条件 |
| 扩展契约机制 | `extensions/README.md` §7 | `condition` 字段与纪律 |
| DSL 实现 | `tools/lib/eis_conditions.py` | 路径枚举、结构校验、求值（存在/全称语义） |
| 校验工具 | `tools/contract-checker` | 条件校验 + 7 条自测（合法/未知路径/op 越界/空值/嵌套/整体对象/exists 非布尔） |
| 判定实现 | `tools/authz-resolver` | 声明侧求值；移除调用方条件入口；自测 17 条 |
| 参考内核 | `tools/lib/kernel.py` | 载入声明并传入判定方；命令级条件判定（含 fail-closed） |
| 用例 | `04-authz-contract/tests/authz-contract.test.yaml`、`conditions.yaml` | 匹配/不匹配/stale/missing/source_unavailable/any/[*] 全称语义/无条件权限不受影响 |
| 用例 | `tools/e2e-runner` | `kind: authz` 的 `conditions` 声明文件入口（不再支持调用方条件） |

## 8. 验收用例

- `python3 tools/contract-checker --self-test`：7 条条件漂移断言全过；
- `python3 tools/contract-checker`：全过；
- `python3 tools/authz-resolver --self-test`：17 条全过（含条件匹配/不匹配/过期/缺失/任一岗位/全称语义）；
- `python3 tools/lib/kernel.py`：自测全过（含命令级条件匹配、`ATTRIBUTE_MISMATCH`、`ATTRIBUTE_MISSING`）；
- `python3 tools/e2e-runner 04-authz-contract/tests/authz-contract.test.yaml`：21/21；
- `python3 tools/e2e-runner --all`：全绿（用例计数随新增用例更新）。
