# ADR-0024：纳入数据范围契约 `scope-primitive-v1`（`schemas/scope-primitive/`）

- **状态**：Accepted
- **日期**：2026-11-22
- **决策者**：核心维护者
- **关联**：issue #59（提案与 Schema 全文）；`schemas/scope-primitive/v1.json`、`README.md`、`CHANGELOG.md`

## 1. 变更原因

数据权限（data-scope）在多个服务重复出现同一问题：策略引擎（Rego/OPA）需要输出「用户能看到
哪些行」的过滤意图，但方言差异散落在各业务仓库，同一规则被反复重写，策略引擎与翻译器之间只能
靠口头约定。业务侧已把「数据范围」收敛为 21 个原语、冻结为 JSON Schema，并在 Java 翻译器与
Rego 策略包中运行；但契约本身散落在业务仓库，缺少组织级权威来源与版本治理。

不纳入的后果：多个业务仓库各存一份并逐渐分叉；`$id` 无法稳定引用；语义变更没有统一评审入口。

## 2. 影响范围

- 契约：**核心六类契约无改动**；新增 `schemas/` 目录承载组织级数据契约
- 扩展：无（本契约不是领域扩展，不引入业务对象/命令）
- 案例：无
- 工具：无强制改动；业务侧翻译器与 Rego 包改为按 `$id` 引用（各自仓库跟进）

## 3. 兼容性分析

- 级别判定：**MINOR**（纯新增可选契约；不采用者不受影响，依据 `06-evolution-contract/compatibility.rules.yaml`）
- 破坏点：无

## 4. 迁移方案

1. `v1.json` 从业务侧冻结版本逐字迁入（仅把 `$comment` 由提案态更新为采纳态，并记录在
   `schemas/scope-primitive/CHANGELOG.md`）；
2. 业务侧 Java 翻译器 / Rego 包把引用从本地副本切换到
   `https://byteforce-cn.github.io/eis/schemas/scope-primitive/v1.json`（各自仓库 PR）；
3. 镜像副本可保留用于构建，但以 EIS 版本为准；两侧差异以 EIS 的 `CHANGELOG.md` 为准。

## 5. 回滚方案

删除 `schemas/scope-primitive/` 并回滚本 ADR；业务侧继续使用本地副本。无数据迁移、无运行时耦合，
回滚不影响既有系统。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 冻结 Schema | `schemas/scope-primitive/v1.json` | 25 个 `$defs`、21 个原语；JSON Schema 2020-12 |
| 使用与治理说明 | `schemas/scope-primitive/README.md` | 常量折叠真值表、fail-closed 约定、版本策略 |
| 变更记录 | `schemas/scope-primitive/CHANGELOG.md` | 纳入记录与后续勘误/v2 |
| 校验 | `python3 -c "import json;json.load(open('schemas/scope-primitive/v1.json'))"` | 结构合法性（CI 亦可接入） |

## 7. 验收用例

- issue #59 验收：`v1.json` 可被 JSON Schema 解析器加载，`$id` 与提案一致；
- 引用一致性：业务侧 Java/Rego 按 `$id` 引用，不再依赖仓库路径；
- 治理：后续结构变更必须新增 `v2.json`，`v1.json` 保留（README §4）。
