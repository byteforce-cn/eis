# EIS Wave 3 实施计划：推进 ADR-0012 裁决的剩余开放项

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 按 ADR-0012 §4.2 的裁决，逐项推进仍未交付的开放 issue；**规范保持通用**——核心
（01–06）只定义元结构语义，业务字段/规则一律留在 `extensions/*`，核心不出现 HR/财务等
领域名词。

**Spec:** ADR-0012 §4.2；issue #28/#29、#30、#31、#32②、#35–#41；各 ADR 的「明确不做」表。

## Global Constraints

- 核心契约改动走 ADR + 可执行工件；扩展自包含；一个 issue 一个分支一个 PR。
- 每个任务结束 `python3 tools/e2e-runner --all` 必须全绿；计数口径同步 README/CONTRIBUTING/
  CONFORMANCE/KNOWN-LIMITATIONS/CHANGELOG。
- 不新增第七类核心契约；引擎/中间件/部署拓扑不进契约（ADR-0012 三层判据）。
- 不可验收的 MUST 不写；informative 文档首页必须标明「不构成合规等级」。

## Task 1：#28 + #29 授权条件声明面（P1）

- [x] ADR-0015：`manifest.permissions[].condition` 受限 DSL（单层 `all`/`any` + `attribute`/`op`/`values`）
- [x] `04-authz-contract/attribute.rules.yaml`：ATR-009 + `condition_language`
- [x] `04-authz-contract/resolution.api.yaml`：条件只由声明侧求值；`/check` 不接收条件
- [x] `contract-checker`：路径（`AttributeSet`）/op/结构校验 + 7 条自测
- [x] `authz-resolver`：声明侧求值；移除 `require_attributes` / `--require-attribute`（调用方传条件的反模式）
- [x] `tools/lib/eis_conditions.py`：共享 DSL（存在/全称语义、fail-closed）
- [x] 参考内核：加载声明并传给判定方；命令级条件判定
- [x] 用例：匹配/不匹配/stale/missing/source_unavailable/`any`/`[*]` 全称/无条件权限不受影响
- [x] 移除 `extensions/hr` 中两条调用方传条件的反模式用例（条件改为声明侧）

## Task 2：#32② 读接口 `min_version` 等待语义（P2）

- [ ] ADR：`GET` 对象支持 `min_version`；未就绪统一 `409 + Retry-After`（不使用 202/阻塞）
- [ ] `02-operation-contract/query.openapi.yaml`：参数 + 409 响应 + 语义（对象版本，非投影水位）
- [ ] 参考内核：读接口按 `min_version` 判定；scenario 断言「落后 → 409；追平 → 200 且 `version >= N`」
- [ ] 用例 + 计数

## Task 3：#31 Outbox/Relay 投递契约（P1，扩展层）

- [ ] `extensions/outbox/`：`manifest.yaml`、`outbox.ddl`（状态机 + 租约 + `(aggregate_id, seq)` 唯一 + 分片索引）、
      `rules/delivery.rules.yaml`（原子捕获/分片内串行/确认后置/租约回收/死信/清理）、`README.md`
- [ ] Inbox 最小语义并入（#34 已裁决）：`(consumer_group, event_id)` 唯一 + `processing/done/dead`
- [ ] `tools/relay`：`SKIP LOCKED` + 退避 + 毒消息；`--self-test`（确定性存储）
- [ ] 用例：`kind: static` + `kind: migrate`；DDL 由 CI PostgreSQL 任务冒烟

## Task 4：#40② 参考内核执行扩展对象 Schema（P1）

- [ ] ADR：内核允许可选依赖 `jsonschema`；缺失/无法解析 → fail-closed（拒绝写入，不静默跳过）
- [ ] `tools/lib/kernel.py`：按 `manifest.objects` 加载 `objects/*.schema.json`，写入前校验
- [ ] 用例：合法写入通过；Schema 违约被拒（新错误码）；既有场景全绿

## Task 5：#30 步骤 2 跨扩展前置（P2）

- [ ] ADR：扩展 `dependencies` 生效 + 声明式前置（引用其它扩展对象/状态）+ `contract-checker` 引用完整性
- [ ] 运行时可加载组合并求值前置；hr `activate` 要求「已通过审批单」
- [ ] 用例：无审批单拒绝 / 有审批单允许；组合缺失 fail-closed

## Task 6：informative 文档（P2）

- [ ] `docs/ORCHESTRATION-BOUNDARY.md`（#35）：步骤走命令、补偿=反向命令、`locator` 贯通审计
- [ ] `docs/INTEGRATION-BOUNDARY.md`（#38）：EIS 不定义集成方式；`external_refs` 约定；冲突由属主域命令裁决
- [ ] `docs/OPERATIONS.md`（#39）：备份范围/恢复后校验/RPO-RTO 模板；首页标明不构成合规等级

## Task 7：RFC #41 IM 扩展

- [ ] 回帖评审结论（收窄为「持久化业务状态的协作触达层」；Transient 机制不入契约）；
      接受则按扩展 PR 交付，不接受则记录理由并关闭
