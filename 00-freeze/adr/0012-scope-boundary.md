# ADR-0012：跨边界缺口的三层归属裁决（核心契约 / 扩展契约 / 实现与运维）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #33（跟踪）及子项 #34–#40；#28/#29/#30/#31/#32/#41；`extensions/README.md`、`docs/CONFORMANCE.md`、`docs/ROADMAP.md`、`docs/KNOWN-LIMITATIONS.md`

## 1. 变更原因

issue #33 汇总了「单聚合/单命令边界外」的 7 类缺口（Outbox/Inbox、Saga、对账、调度、主数据、备份灾备、已知内部缺口），并由 #34–#40 逐条展开；另有一批独立提案（#28/#29 授权条件声明面、#30 调用方约束、#31 Outbox、#32 命令响应、#41 IM 扩展）。

逐条评估暴露了三个治理问题：

1. **事实漂移**：#33 表格中「Outbox/Saga/调度核心仓库无命中」3 行不成立——结论已在 `docs/LANDING-IAM.md` §3.4/§8 与 `docs/COORD-REQUIREMENTS.md` 做出，只是未升格为契约（登记于 `docs/KNOWN-LIMITATIONS.md` §5）；
2. **缺关键列**：现有讨论只在问「做不做」，没有统一的「**在哪一层做**」判据，导致同一提案在核心/扩展/文档之间反复；
3. **重复裁决**：#39 与 KL §3.1/§3.2、#40 与 KL §1.1/§1.2/§2.1 是同一事实的两次表述。

EIS 的射程是六类元结构（对象/命令/时间/授权/审计/演进）。缺口进入哪一层，必须有可复用判据，否则每来一个提案都要重新吵一次。

## 2. 影响范围

- 契约：无工件变更（本 ADR 是裁决记录，不改 01–06）
- 扩展：无
- 案例：无
- 文档：本 ADR、`00-freeze/adr/README.md` 索引、`docs/ROADMAP.md` 指针
- 工具：无

## 3. 兼容性分析

- 级别判定：**PATCH**（纯治理文档新增；无 Schema/API/DDL/哈希变化，`compatibility.rules.yaml` 四条数据规则不适用）。
- 破坏点：无。既有判定、验收命令与合规等级均不变。

## 4. 决策

### 4.1 三层判据（按序适用，前者命中即止）

| 层 | 判据 | 形态 | 版本与门禁 |
|---|---|---|---|
| **核心契约** | 定义六类元结构的语义（对象/命令/时间/授权/审计/演进的通用规则），且**与部署形态无关** | `01`–`06` 的 Schema/OpenAPI/DDL/规则 | 冻结；改动走 ADR + 兼容性判定（PATCH/MINOR/MAJOR） |
| **扩展契约** | ① 某业务域的实体/命令/规则（可用既有元结构表达）；或 ② **跨域运行时能力**，需要 DDL/relay/调度等运行时假设 | `extensions/{domain}/`（独立版本、自带 `handlers.py` + 用例） | 不得改核心；扩展自身 MINOR/MAJOR；ADR 只记录边界 |
| **实现与运维** | 依赖部署拓扑、中间件选型、运行状态或运维演练（RPO/RTO、锁算法、CDC/ESB、选主、备份） | informative 文档 / 部署侧合规声明 | **不进契约、不进 `CONFORMANCE.md` 等级**；不得写成不可验收的 MUST |

补充规则：

- **不新增第七类核心契约**：跨域运行时能力一律落 `extensions/*`（如 `extensions/outbox`），六类核心契约保持冻结（ADR-0001）。
- **判定与执行权威唯一**：不自建第二权威——Saga/TCC 执行引擎外置（coord workflow）；授权判定唯一权威为 `eis-authz`，不接入可编辑策略引擎。
- **不可验收的 MUST 一律不写**：`CONFORMANCE.md` 每一级都必须有可执行验收命令；无法用 `e2e-runner` 验证的运行态要求只能进 informative 文档。
- **新提案模板**：任何新缺口 issue 必须写明「归属层 + 触发条件 + 可执行工件」；缺任一项不接受为特性。

### 4.2 逐条裁决

| Issue | 裁决 | 归属层 | 落点 / 形态 | 优先级 |
|---|---|---|---|---|
| #28 | 部分接受 | 核心 04（授权） | 条件进**权限声明**：`manifest.permissions[].condition`（受限结构化 DSL：`attribute/op/values`），`contract-checker` 校验属性路径与 op 白名单；**`/check` 不接受调用方传入条件**（判定条件不能由被判定方提供） | P1，与 #29 合并 |
| #29 | 部分接受（① + ③） | 核心 04 + 扩展 | ① 条件声明化（同 #28）；③ `attribute.rules.yaml` 增 ATR-009「条件结构只随契约版本演进，不提供任意策略表达式编辑面」。② 业务阈值改走**领域对象 + 受审计命令**（如 `approval.threshold.set`），不建策略引擎 | P1 |
| #30 | 部分接受，拆两步 | 扩展 operations 契约机制 + `extensions/hr` | 步骤 1（可立即做）：operations 契约声明**调用方身份约束**，hr 把 `hr.employee.activate/cancel` 限定为审批服务身份，用例断言用户主体被拒；步骤 2（需 ADR）：跨扩展前置（hr → approval 的「必须存在已通过审批单」），依赖扩展跨引用机制 | 步骤 1 P1；步骤 2 P2 |
| #31 | 接受 | 扩展契约（跨域运行时） | `extensions/outbox/`：`outbox.ddl`（状态机 `pending/processing/sent/dead` + 租约列 + `(aggregate_id, seq)` 唯一 + 按聚合分片索引）+ `rules/delivery.rules.yaml` + `tools/relay`（`SKIP LOCKED` + 退避；无 relay 则租约/毒消息不可验收）+ static/migrate 用例 | P1 |
| #34 | 归并 #31 后关闭 | 扩展契约（同上） | Inbox 语义并入 #31：`(consumer_group, event_id)` 唯一 + `processing/done/dead` + 死信可重放 | 与 #31 同批 |
| #32 | 部分接受，拆两条；**不做 200/201** | 核心 02（操作） | ① `CommandAccepted` 增 `locator`/`version`（命令与查询之间唯一的桥），命令响应不携带读模型投影写成 MUST；② 读接口 `min_version`，「未就绪」统一 `409 + Retry-After`。完成度用 `GET /commands/{id}` 的 `status` 表达，不新增 HTTP 码 | ① P1；② P2 |
| #33 | 本 ADR | 治理 | ADR-0012（本文件）；跟踪 issue 关闭，子项按本表继续 | 完成 |
| #35 | 不纳入核心 | 实现与运维（编排层外置） | `docs/ORCHESTRATION-BOUNDARY.md`（informative）：步骤仍走 EIS 命令（幂等键必填、不得直写业务表）、补偿=反向命令且自身幂等可重放、编排实例 ID 作为 `locator` 贯通审计、部分完成状态必须可在查询面读到。若将来固化，形态是 `extensions/orchestration/` 的**声明式** Schema，执行器仍外置 | P2，触发=首个跨域长流程立项 |
| #36 | 接受为领域扩展 | 领域扩展 | 独立 `extensions/reconciliation/`（不并入 `accounting`：库存/支付/总账都要复用）：`run_key = domain + period + sequence` 唯一、差异受控分类枚举 + 容忍度、差异处理走命令 + 审计、报告为只读投影 | P2，触发=首个财务/库存对账实需 |
| #37 | 接受为窄口径扩展 | 扩展契约（跨域运行时） | `extensions/scheduler/`：`job_id` + `schedule` + 版本；`run_key = job_id + scheduled_for` 唯一；`scope` + `lease_owner`/`lease_expires_at`（过期可抢占，旧持有者写入以 `lease_id` 版本比对拒绝）；执行记录 `running/succeeded/failed/skipped`。**不写**锁算法、选主、cron 解析器实现 | P2，触发=首个日终批处理实需 |
| #38 | 部分接受 | 实现与运维（informative） | 系统内唯一性已由扩展 `invariants` + `contract-checker` 覆盖（不是缺口）；跨系统同步纳入 `docs/INTEGRATION-BOUNDARY.md`：EIS 不定义集成方式（CDC/API/ESB 由部署方选型）、外部引用用扩展对象字段 `external_refs: [{system, id}]`、冲突解决由**属主域命令**裁决、对外事件复用 `extensions/outbox` | P2 |
| #39 | 接受为 informative | 实现与运维 | `docs/OPERATIONS.md`（首页标明「不构成合规等级」）：备份范围分级（业务表/事件存储/审计链 + 链头锚同恢复点）、恢复后必跑 `audit-verifier` + 锚比对（可做成 1 条 `kind: chain` 用例）、RPO/RTO 自填模板、恢复后不得重签审计链。**不加 L5** | P2 |
| #40 | 接受为**参考实现缺陷**（非契约缺口） | 工具/内核 | ① T-R009 排他约束：**已交付**（ADR-0011）；② 内核加载扩展对象 Schema：需先裁决「参考内核是否允许第三方依赖」（建议可选依赖 + 缺失 fail-closed）；③ T-R011 迟到事件：改 `Kernel.advance` 核心语义，单独 PR + 独立回归集 | ① 完成；② P1（依赖裁决）；③ P2（依赖 ①） |
| #41 | 待评审（RFC 草案） | 领域扩展 | `extensions/im/`：收窄为「持久化业务状态的协作触达层」——消息/版本/群组/成员/已读位点/好友黑名单进契约面；网关、长连接、离线推送、typing 等 Transient 机制**不入契约**；`serverSeq` 为扩展领域规则 | 待评审结论 |

### 4.3 明确不做

| 不做项 | 来源 | 理由 |
|---|---|---|
| `/check` 接受调用方传入条件 | #28 | 调用方可漏传/放宽条件拿到 `allowed=true`（AUD-01 的通用形式） |
| 运行期可编辑的任意策略表达式（Rego 等） | #29 | 破坏 as_of 判定的离线可复现与审计链自证；策略变更须随契约版本走 ADR |
| HTTP `200/201 = 命令已完成` 的完成度分层 | #32③ | 让同一命令同时可能同步/异步响应，调用方兼容成本为负；完成度属命令状态 |
| `contracts/07-delivery-contract`（第七类核心契约） | #31/#34 | 等于改核心，与「纯新增、MINOR」矛盾；六类契约已冻结（ADR-0001） |
| EIS 自建 Saga/TCC 执行引擎 | #35 | 执行引擎不是契约；已有外置路径（coord workflow），再造一套即第二权威 |
| CDC/ESB/黄金记录的契约与跨系统事务语义 | #38 | 集成拓扑因企业而异，且中间件选型已定为部署方职责（`docs/LANDING-IAM.md` §3.4） |
| `CONFORMANCE.md` 新增 L5（备份灾备） | #39 | RPO/RTO 无法用 `e2e-runner` 验证，会稀释「每级都可验证」的承诺 |
| 把 #39/#40 的已知限制再登记一遍 | #33 | 已在 `docs/KNOWN-LIMITATIONS.md` §1.1/§1.2/§2.1/§3.1/§3.2 登记 |

### 4.4 事实更正（写入决策记录，避免重复讨论）

- Outbox/Inbox 的投递形态**已存在**于 `docs/LANDING-IAM.md` §3.4.2（relay → `Publish(idempotency_key=event_id)` → 消费方 Poll+Ack、`MoveToDlq`、容量背压），`docs/KNOWN-LIMITATIONS.md` §5 已登记「仅见于落地文档、非契约」；#31 的价值是**升格为可验收契约**，不是新设计。
- Saga 的归属**已裁决**：`docs/LANDING-IAM.md` §3.4.3 与 §8 #15——v1 无 saga 需求，业务事务留单 PG 事务；coord workflow 的补偿执行器已交付（`compensatedBy` + 三步逆序补偿）。
- 调度分层**已裁决**：`docs/LANDING-IAM.md` §8 #12——长驻单例→选主、短临界区→锁、数据串行→PG（`SKIP LOCKED`），「锁只做内务，正确性不外包」。
- 主数据**系统内**唯一性不是缺口：`extensions/*/manifest.yaml` 的 `invariants` + `contract-checker` 已是表达与校验机制。

## 5. 迁移方案

不适用（无契约/数据迁移）。落地动作：

1. `00-freeze/adr/README.md` 索引登记本 ADR；
2. `docs/ROADMAP.md` 在 v1.x 增一行指针（避免另建 `docs/SCOPE-BOUNDARY.md` 形成双份权威）；
3. 在 #33/#34 回帖裁决并关闭跟踪项；#35–#41 回帖归属层与触发条件（保持 open，等触发条件）。

## 6. 回滚方案

- 回滚 = revert 本 ADR 与索引/指针提交；无数据与工件影响；
- 已按本 ADR 关闭的 issue 需重新打开（回帖说明）。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 裁决记录 | `00-freeze/adr/0012-scope-boundary.md` | 本文件（判据 + 逐条裁决 + 不做项） |
| ADR 索引 | `00-freeze/adr/README.md` | 0012 登记 |
| 路线图指针 | `docs/ROADMAP.md` | v1.x 一行指向本 ADR |
| 已交付的先行项 | `00-freeze/adr/0011-tr009-valid-overlap-constraint.md` | #40① 已按本判据落地 |

## 8. 验收用例

- `python3 tools/e2e-runner --all` → 用例 134/134；场景 1/1；流水线 5/5（本 ADR 无工件变更，计数不变）；
- `python3 tools/contract-checker` → 通过（无 Schema/契约变更）；
- 人工验收：本 ADR 表格覆盖 #28–#41 全部 open issue，且每个「接受」项都写明落点形态与触发条件（无 TBD）。
