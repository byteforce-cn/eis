# ADR-0004：授权属性的属主与来源（拉取为准，推送为可选物化）

> **后续演进（ADR-0015）**：本文提到的「调用方传条件」（`/check --require-attribute` /
> `require_attributes`）已被 ADR-0015 取代——条件改为声明侧 `manifest.permissions[].condition`，
> `/check` 不再接受调用方传入的条件。本文其余内容（属性属主、拉取为准、快照三态）不变。


- **状态**：Accepted
- **日期**：2026-10-11
- **决策者**：核心维护者（EIS Spec 维护方）
- **关联**：issue #3；`04-authz-contract/attributes.api.yaml`、`04-authz-contract/attribute.rules.yaml`、`extensions/hr`

## 1. 变更原因

核心 04 契约定义了 `/resolve` 与 `/check`，但主体属性（组织、岗位、职级、雇佣类型、汇报链）
**从哪来、谁写、失败怎么办**没有规定。ABAC 条件求值必须依赖这些属性，其权威在人事域（`extensions/hr`），
判定权威在授权引擎。不补齐会导致：

- 属性形状（单值主岗 vs 多岗集合）不一致，`/check` 语义随实现漂移；
- 属性缺失/过期/属主不可达时可能静默放行（不安全）；
- 业务侧（人事域）与审批域（条件参与）各自造字段，返工风险高。

## 2. 影响范围

- 契约：授权（04）加法补充属性快照协议与失败口径；主体 Schema（04-authz-contract/principal.schema.json）仅更新 `attributes` 字段描述（PATCH）；
- 扩展：`extensions/hr` 是属性权威属主（其对象/事件已可派生快照）；
- 案例：不涉及；
- 工具：`tools/authz-resolver` 支持属性夹具、`attributes` 子命令与 `--require-attribute` 条件；
  `tools/e2e-runner`（kind: authz）支持属性断言。

## 3. 兼容性分析

- 级别判定：**MINOR**（依据 `compatibility.rules.yaml` 数据/操作规则：可选字段新增、枚举取值扩展；
  既有请求/响应字段与语义不变）。
- 破坏点：无。不提供属性的调用方行为与 v1.0.0 相同；新增字段均可选。

## 4. 迁移方案

不涉及数据迁移（属性为运行时快照，不是持久化契约）。采用方按 `attributes.api.yaml` 实现拉取端点；
若采用推送物化，按 ATR-002 的写入协议（幂等键 = principal + as_of + source_version）实现。

## 5. 回滚方案

移除新增的可选字段与规则文件即可，不影响既有判定语义；工具侧 `--require-attribute` 为可选参数。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 属性快照拉取 API | `04-authz-contract/attributes.api.yaml` | GET /principals/{id}/attributes?as_of=&recorded_as_of= |
| 属性规则 | `04-authz-contract/attribute.rules.yaml` | ATR-001..007（属主/拉取/推送/形状/as_of/fail-closed/缓存） |
| 判定 API 加法 | `04-authz-contract/resolution.api.yaml` | 请求可选 attributes；响应 attribute_state |
| 权威属主扩展 | `extensions/hr/` | 组织/岗位/任职/员工对象可派生快照 |
| 参考实现 | `tools/authz-resolver` | attributes 子命令、--require-attribute、失效态 |
| 夹具与用例 | `04-authz-contract/tests/fixtures-attributes.yaml`、`04-authz-contract/tests/authz-contract.test.yaml` | 新鲜/过期/缺失/条件匹配与拒绝 |

## 7. 验收用例

- `acceptance.yaml`「授权契约：解析测试 / SoD 测试」；
- 新增：`attributes` 新鲜/过期/缺失三态；`/check --require-attribute` 条件不匹配拒绝
  （ATTRIBUTE_MISMATCH）；过期/缺失/属主不可达 fail-closed（ATTRIBUTE_STALE / ATTRIBUTE_MISSING /
  ATTRIBUTE_SOURCE_UNAVAILABLE）。
