# ADR — 架构决策记录

EIS 的核心契约已冻结。任何修改（解冻请求）必须走以下流程：

```
变更提案 → ADR → 可执行工件 → 验证 → 合并
```

## ADR 必须有

| 章节 | 内容 |
|------|------|
| 变更原因 | 为什么必须改（问题、证据、影响面） |
| 影响范围 | 涉及哪些契约/扩展/案例/工具 |
| 兼容性分析 | 按 `06-evolution-contract/compatibility.rules.yaml` 判定的级别（MAJOR/MINOR/PATCH） |
| 迁移方案 | 脚本 + 数据迁移 + 双写/对账（如适用） |
| 回滚方案 | 回滚脚本与验证条件 |
| 可执行工件 | Schema/DDL/测试用例/工具变更的清单（路径） |
| 验收用例 | 对应 `acceptance.yaml` 的验收项 |

> **无工件的变更一律拒绝。**

## 命名与状态

- 文件名：`NNNN-<slug>.md`（四位序号，序号不复用）
- 状态：`Proposed` → `Accepted` / `Rejected` / `Superseded by NNNN`

## 现有记录

| 编号 | 标题 | 状态 |
|------|------|------|
| [0001](0001-eis-spec-v1.0-freeze.md) | EIS Spec v1.0 冻结 | Accepted |
| [0002](0002-pre-release-revisions.md) | 开源发布前定稿修订（Pre-release） | Accepted |
| [0003](0003-iam-extension-boundary-and-audit-scope.md) | IAM 首落地：扩展边界与审计范围 | Accepted |
| [0004](0004-authz-attributes-ownership.md) | 授权属性的属主与来源（拉取为准，推送为可选物化） | Accepted |
| [0005](0005-write-only-derived-fields.md) | 写入专用派生字段的服务端派生与密钥托管 | Accepted |
| [0006](0006-read-face-authorization.md) | 读取面授权口径与扩展权限目录 | Accepted |
| [0007](0007-audit-payload-digest.md) | 审计条目 payload_digest（事件正文篡改检出） | Accepted |
| [0008](0008-standalone-compatibility-checker.md) | compatibility-checker 独立模式（技术中立采纳） | Accepted |
| [0009](0009-hr-employment-work-location.md) | HR 扩展 Employee 增加雇佣类型/工作地点（加法演进） | Accepted |
| [0010](0010-approval-section-order.md) | 审批区块顺序语义（ApprovalSection.step_order） | Accepted |
| [0011](0011-tr009-valid-overlap-constraint.md) | T-R009 有效区间不重叠落地为四维排他约束 | Accepted |
| [0012](0012-scope-boundary.md) | 跨边界缺口的三层归属裁决（核心 / 扩展 / 实现与运维） | Accepted |
| [0013](0013-command-caller-constraint.md) | 命令调用方约束（manifest callers + x-eis-callers） | Accepted |
| [0014](0014-command-response-locator-version.md) | 命令响应携带 {locator, version}（命令与查询的桥） | Accepted |
| [0015](0015-authz-condition-declaration.md) | 授权条件声明面（manifest.permissions[].condition 受限 DSL） | Accepted |
| [0016](0016-kernel-object-schema-validation.md) | 参考内核执行扩展对象 Schema（可选依赖 + fail-closed） | Accepted |
| [0017](0017-query-min-version.md) | 读接口 min_version 等待语义（409 + Retry-After） | Accepted |
| [0018](0018-outbox-delivery-extension.md) | 可靠投递扩展（Outbox + Inbox，extensions/outbox） | Accepted |
| [0019](0019-cross-extension-preconditions.md) | 扩展跨引用与命令前置（dependencies + rules.requires_objects） | Accepted |
| [0020](0020-late-fact-kernel-modeling.md) | 参考内核建模迟到事实（T-R011） | Accepted |
| [0021](0021-scheduler-execution-semantics.md) | 定时任务 / 日终批处理执行语义（extensions/scheduler） | Accepted |
