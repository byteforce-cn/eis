# 集成边界（Integration Boundary）

> **文档性质：informative（不构成合规等级，不得作为 MUST 验收）**。
> 归属：实现与运维层（ADR-0012 三层判据；issue #38 裁决）。
> 本文说明 EIS 与外部系统/主数据/集成中间件的边界；EIS 不定义集成拓扑。

## 1. 结论先行

- **集成方式由部署方选型**：CDC、API、ESB、消息中间件均可，EIS 不做契约级规定。
- **系统内唯一性不是缺口**：扩展 `manifest.invariants` + `contract-checker` 已覆盖。
- **跨系统没有分布式事务**：冲突由**属主域命令**裁决，不允许「谁最后写谁赢」的静默覆盖。
- 对外事件复用 `extensions/outbox/`（ADR-0018），不另造投递机制。

## 2. 外部引用约定（扩展字段，非核心改动）

扩展对象可声明外部引用（建议字段名 `external_refs`）：

```json
{
  "external_refs": [
    {"system": "erp", "id": "MAT-000123"},
    {"system": "crm", "id": "C-7788"}
  ]
}
```

- `system` 是部署方定义的稳定标识；`id` 是外部系统的主键；
- 外部引用是**从属信息**，不是权威主数据；权威属主仍是拥有该对象的扩展；
- 需要按外部 ID 反查时，由扩展读模型/投影提供索引，核心不新增字段；
- 该约定不改变 `01-data-contract/object.schema.json`（扩展追加字段即可）。

## 3. 主数据与冲突

| 场景 | 建议 |
|------|------|
| 主数据权威 | 单一属主域持有写权限；其他系统只读/复制，不得回写权威字段（ATR-001 同理） |
| 外部变更进入 | 通过属主域命令（带幂等键 + 审计），不得直写业务表 |
| 冲突 | 属主域命令按业务规则裁决（拒绝/合并/人工），并留下审计；不得跨系统静默覆盖 |
| 删除/失效 | 走命令 + 事件；消费方按事件更新本地投影 |
| 对账 | 差异由对账扩展（`extensions/reconciliation/`，触发后立项）输出，处理仍走命令 |

## 4. 对外事件

- 事件离开领域一律经 `extensions/outbox/`：原子捕获、聚合内有序、at-least-once、确认后置；
- 消费方用 Inbox（`(consumer_group, event_id)`）幂等；
- 事件回放使用事件存储/broker retention，**不得从 outbox 表回放**（OBX-009）；
- 跨系统关联使用事件 `subjects` 与 `external_refs`，不引入第二套事件身份。

## 5. 明确不做

- CDC/ESB/API 网关的选型、拓扑与配置；
- 跨系统分布式事务、两阶段提交、黄金记录（golden record）产品；
- 外部系统 Schema 的契约化（只约定引用形状与属主裁决原则）；
- 用集成中间件替代 EIS 命令/审计（会形成第二权威）。

## 6. 可验证的落地建议（非契约）

- 扩展 Schema 增 `external_refs` 后，用 `tools/contract-checker` 与 `schema-compiler check` 验证；
- 用 `kind: scenario` 覆盖「外部变更 → 属主域命令 → 事件 → 读模型」链路；
- 用 `tools/audit-verifier` 验证外部变更同样进入审计链；
- 对账差异报表为只读投影，处理动作必须是命令（可审计、可回滚）。

## 7. 相关

- `00-freeze/adr/0012-scope-boundary.md` §4.2（#38 裁决）
- `extensions/outbox/README.md`、`00-freeze/adr/0018-outbox-delivery-extension.md`
- `04-authz-contract/attribute.rules.yaml` ATR-001（属性属主唯一）
