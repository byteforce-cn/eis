# Coord 业务缺口需求（IAM/EIS 落地视角 · 提给 coord team）

> **面向**：coord team（评审、排期与验收）
> **来源**：消费方（IMS/EIS 平台）在 IAM 首落地评估中对 coord `v0.2.1`（HEAD `2c61f23`）的逐服务复核；评估全文 `eis/docs/LANDING-IAM.md` v0.3 §3.4，证据锚点见本文附录 A。
> **落地回执（v1.1，2026-10-10）**：coord team 已全量承接（ADR-0010，accepted，2026-10-09）并随 **coord v0.2.2**（2026-10-10 发布）+ **coord-java-sdk 0.2.1**（Maven Central）交付；逐条闭环状态、验收判据与消费方实测见 **§7**。
> **性质**：**能力需求 + 验收口径**——不是缺陷清单，也不改约既有边界声明（ADR-0001/0002、`docs/production/ops/boundaries.md`）。每条缺口给出「业务需求 → 现状与证据 → 请求的能力 → 验收口径 → 优先级」。
> **术语**：IAM = 本组织首个身份与授权服务；IMS/EIS = 承载它的系统与契约平台（coord 的消费方）。

## 0. 背景与口径

- **coord 是组织级基础设施**；IAM 是第一个重消费域（OAuth2 授权服务器 + 授权判定权威 + 身份管理），后续还有财务 / 库存 / 审批等域——本文件中的缺口影响**组织级复用**，不只服务 IAM 一家。
- **现状澄清**（避免误读为「coord 全部不可用」）：
  - **已在用（T1）**：registry / config / lock / ratelimiter / observability；
  - **已采用（T2）**：event（失效/唤醒脉冲）、leader election（单例任务）；
  - **已指定（T4）**：mq（跨服务事件通道）、pki（IAM 非对称密钥 KMS）、transit（可选加固）；
  - **暂缓接入**：policy / workflow / cache / scheduler —— 原因即本文件的各项缺口。（v1.1 注：本文件所列缺口已全部闭环，见 §7；各项接入结论以 `LANDING-IAM.md` 重评/表决为准。）
- **消费方接入纪律**（优先级依据）：正确性权威 = PG + EIS 契约；coord 只做协调、失败可降级。因此下列缺口**不阻塞 IAM v1**，但阻塞「**生产多实例化**」与「**组织级推广**」。
- **优先级定义**：**P1** = 阻塞已指定采纳路径的生产化；**P2** = 阻塞组织级复用/演进；**P3** = 观察或产品决策。

## 1. 缺口总表

| 编号 | 服务 | 缺口（一句话） | 优先级 | 阻塞对象 | 建议时点 |
| --- | --- | --- | :-: | --- | --- |
| G-POL-1 | policy | Rego bundle 无跨 agent 分发与启动加载（仅本机内存装配） | P1 | 多实例授权判定一致性 / policy 复用 | 现有 2026-12-31 契约期内 |
| G-POL-2 | policy | RBAC（`CheckPermission`）无管理面（策略仅 agent 本地内存、契约无装载 RPC） | P2 | CheckPermission 生产可用性 | 随 G-POL-1 一并定谳 |
| G-MQ-1 | mq | 跨 agent 消费路由未提供（ISR 下 subscribe/ack 仅分区 Leader；SDK 无路由方案） | P1 | 首个跨服务消费者（IMS 二期） | 2026-12-31 前（文档+SDK） |
| G-MQ-2 | mq | DLQ 闭环缺失（无公开「移入 DLQ」RPC；`move_to_dlq` 仅内部维护路径） | P2 | 毒消息运维 | 2026-12-31 |
| G-MQ-3 | mq | 消费组 lag/offset 指标缺失（现仅容量面指标） | P2 | 消费者告警与容量治理 | 2026-12-31 |
| G-MQ-4 | mq | topic 删除面缺失（契约无 DeleteTopic；存量行仍计配额，B-PL-4(d)） | P3 | topic 生命周期治理 | 产品决策 |
| G-PKI-1 | pki | 到期后 `IssueCert/RotateCert` 返回既有已过期记录（不重签）；恢复仅 `RenewCert(serial)` | P1 | 生产密钥生命周期（KMS 路径） | 尽早（建议补丁级） |
| G-PKI-2 | pki | 到期观测面缺失（`is_expiring_soon` 未暴露为指标/RPC） | P2 | 轮换运维 | 2026-12-31 |
| G-PKI-3 | pki | KMS 语义未闭环（read=任意 CN 私钥、无吊销、无 HSM 属性——设计级） | P2 | 组织级 KMS 定位 | 设计先行 |
| G-WF-1 | workflow | DSL 解释器 + Saga 补偿执行器未交付（模块头标注为蓝图）；实例 append-only 无保留策略 | P2 | 组织多域长流程 | 2027-03-31（请确认） |
| G-TR-1 | transit | KEK 材料轮换无内建流程（B-SE-6：换材料后旧密文不可读） | P2 | transit 作为密钥包裹的生产化 | 2026-12-31 |
| G-TR-2 | transit | 无非对称签名（不能做「私钥不出域」的签名服务） | P3 | 产品决策（org KMS 方向） | 待定 |
| G-X-1 | 全服务 | 消费方路由/鉴权指南缺失（每服务：任一 agent / Leader 专属 / 本地态 + 能力清单） | P1（文档） | 组织接入成本 | 2026-11 前 |
| G-EV-1 | event | 持久化游标（补投）未落地（v1.2 候选）——观察 | P3 | 轻量可补投通道 | 观察 |
| G-SC-1 | scheduler | result 不留档、KV 存储验收未过——观察 | P3 | coord 原生调度 | 2027-03-31 |

**建议落地顺序**：先 **G-POL-1 / G-MQ-1 / G-PKI-1** 三项（已指定采纳路径的生产阻塞项），G-X-1 文档随行；其余按上表。

## 2. 缺口详情

### G-POL-1【P1】policy：bundle 跨 agent 分发与启动加载

- **业务需求**：多实例环境下，同一 (query, input) 在任一实例必须给出一致判定；重启不得丢策略；Put / Rollback / SetEnabled 全域一致收敛。
- **现状与证据**：`PutBundle` / `RollbackBundle` / `SetBundleEnabled` 仅把策略装入**处理该 RPC 的那一个 agent** 的本地 OpaEngine；`start()` 不读 KV、无 Watch 订阅（`coord-agent/src/services/policy.rs`）；`agent_opa_test.rs` 头注仍将「策略包由 Server 经 KV/Watch 下发」列为实施中。存储面（KV 版本化 + Txn CAS + rollback）已完备。
- **请求的能力**：
  1. agent 启动时从 KV 加载全部 enabled bundles；
  2. 变更传播通道（Watch 或版本轮询）与**收敛时限**；
  3. 版本一致性语义（并发 Put / 回滚后的最终状态、错误语义）；
  4. proto 边界声明同步（现声明只提「bundle 在 Server KV」，未声明分发/加载行为）。
- **验收口径**：
  - a) A 上 Put → 重启 A → `Evaluate` 与重启前一致；
  - b) 同集群 agent B（未处理写入）对相同输入同结果（收敛时限内，建议 ≤10s 量级并文档化）；
  - c) Rollback / SetEnabled 在全体 agent 收敛一致；
  - d) 并发 Put 版本号单调、无丢更新。
- **备注**：达成后，消费方将按 `LANDING-IAM.md` §3.4.1 的四条件整体重评「coord policy 是否进入 IAM 判定路径」（其中「契约→Rego 生成验证」由消费方提供）。

### G-POL-2【P2】policy：RBAC 管理面（提供或明确弃用）

- **业务需求**：`CheckPermission` 是 policy 契约中的显式入口，消费者需要「装载策略 → 判定」的完整路径。
- **现状与证据**：RBAC 策略仅存于 agent 本地内存（进程内 `add_policy` 可装载）；`policy.proto` 无 RBAC CRUD/装载 RPC——生产消费者无法装载策略。
- **请求的能力**：二选一并文档化——(a) 提供 RBAC 策略管理（持久化 + 跨 agent 分发）；或 (b) 明确 `CheckPermission` 为嵌入式/本地用途，生产统一走 OPA bundle + `Evaluate`（proto 边界声明 + SDK 文档标注）。
- **验收口径**：按选定方向有一条端到端可复现路径（装载→判定→重启仍生效；或文档 + demo 明示替代路径）。

### G-MQ-1【P1】mq：跨 agent 消费路由方案

- **业务需求**：多实例生产下生产者与消费者可能在不同 agent；需保证「至少一次投递、消费者知道去哪里消费、Leader 迁移后可恢复」。
- **现状与证据**：跨 agent 投递需启用 `replication`（ISR）并遵循分区 Leader（`mq.rs` 模块头：Follower 幂等应用 + 自动建 topic，subscribe/ack 仅 Leader；proto 声明「复制启用时偏移为分区 Leader 本地状态，非 Leader 返回 `FAILED_PRECONDITION`」）；**SDK 未见按分区 Leader 的消费路由实现**（`MqClientImpl` 无相关逻辑）；未见面向消费者的路由/重平衡指引文档。
- **请求的能力**：
  1. 官方消费路由方案：SDK 支持 Leader 发现与自动路由，或提供查询接口 + 明确「路由失败 → 按错误码重试直到成功」的消费范式；
  2. 文档：分区、Leader、ISR 拓扑与消费者部署的对应关系；
  3. Leader 不可达/切换时的错误码与恢复步骤（与现有 proto 语义一致）。
- **验收口径**：双 agent（启用 replication）：A 上 `Publish`、B 上 `Poll+Ack` 全量收到且分区内有序；kill Leader → 明确错误码，恢复后继续消费；**无静默丢失**。

### G-MQ-2【P2】mq：DLQ 闭环（毒消息流转）

- **业务需求**：消费者需要「坏消息不阻塞分区、且可观测/可处置」的闭环。
- **现状与证据**：`PollDlq` 仅可读；`move_to_dlq` 为内部维护路径、契约无该 RPC（`mq.rs`），消费者无法触发；无自动投毒判定。
- **请求的能力**：二选一——(a) 自动：按重试次数/策略超限自动入 DLQ（定义 reason/detail 约定）；(b) 显式：公开管理 RPC（能力门禁）供消费者/运维移入；并文档化处置流程。
- **验收口径**：构造毒消息 → 经自动策略或显式调用进入 DLQ；分区不被阻塞；DLQ 内容含原因可读。

### G-MQ-3【P2】mq：消费组可观测（lag/offset）

- **业务需求**：消费者侧需要有「跟不上」的早期信号（告警与容量治理）。
- **现状与证据**：容量面指标已有（`coord_agent_mq_active_bytes / limit_bytes / purged_entries_total / publish_rejected_total / reaper_faults_total`）；**未见消费组 lag/offset 指标**（`metrics.rs`）。
- **请求的能力**：每 (topic, group, partition) 的 committed offset / lag 指标；配套文档给出告警口径建议。
- **验收口径**：Prometheus 可查询 lag；滞后场景可观测、可告警。

### G-MQ-4【P3】mq：topic 生命周期（删除/回收）

- **现状与证据**：契约无 `DeleteTopic`；`delete_topic` 实现存在但无调用点；B-PL-4(d)：已删 topic 的存量行不被清扫但仍计入配额。
- **请求**：明确策略——(a) 提供删除（含数据回收与配额归还）；或 (b) 声明不支持删除并给出替代（改名 + 保留期治理），同步边界文档。
- **验收口径**：按选定方向文档化；（若提供）删除后配额归还可验证。

### G-PKI-1【P1】pki：到期重签语义修正

- **业务需求**：KMS 路径依赖「到期前轮换」纪律，但到期后的恢复路径必须可靠且语义一致。
- **现状与证据**：到期后 `IssueCert` 走重签，但因 `create_cert` CAS（Version==0）失败 → 返回**既有已过期记录**；`RotateCert` 对过期 active 走同一路径；恢复仅 `RenewCert(serial)`；而 `GetCertByCN` 对过期返回 `NOT_FOUND`——三者语义不一致（`pki.rs` / `pki_store.rs`）。
- **请求的能力**：明确并修正——建议「到期 = 换新触发」（IssueCert/RotateCert 对过期 active 走 replace 路径重签新密钥）；或返回明确错误码并文档化「必须 `RenewCert(serial)`」；无论哪种，保证与 `GetCertByCN` 行为一致。
- **验收口径**：短 TTL 用例——过期前 rotate 正常；过期后 IssueCert 得到新 serial/新密钥（或明确错误）；`RenewCert(serial)` 可恢复；并发/重启下行为一致。

### G-PKI-2【P2】pki：到期观测面

- **现状与证据**：`is_expiring_soon` 已有实现但未对外暴露；`ListCerts` 可给 `not_after`（自助可行、无告警面）。
- **请求的能力**：指标（如「X 小时内到期」计数）或管理 RPC，便于消费方/平台统一告警。
- **验收口径**：Prometheus 查询/告警示例；文档化。

### G-PKI-3【P2】pki：KMS 语义与访问控制（设计先行）

- **业务需求**：若组织将以 PKI 作为多租户/多服务 KMS，需要明确的权限与应急模型。
- **现状与证据**：能力级门禁（`pki:cert:read` 即取任意 CN 私钥，无按 CN 隔离，`coord-core/src/grpc_auth.rs` L233–240）；无吊销/CRL/删除；存储 = KV+Barrier（非 HSM）；私钥以 `key_pem` 交付调用方。
- **请求的能力（设计先行）**：① 访问控制模型建议（按 CN/用途 scope 化，或明确「read = 私钥读取权」的定级指南）；② 吊销/泄露应急 playbook（CN 轮换流程；未来 revocation 设计）；③ HSM/外部 KMS 路线（对接 B-SE-2 讨论）。
- **验收口径**：设计文档评审通过；选定最小实现（若采纳）另行验收。

### G-WF-1【P2】workflow：补偿执行器与保留策略

- **业务需求**：组织多域长流程（如人事入转离跨 IAM/财务/库存）需要编排 + 补偿；IAM 首域不需要，但平台路线图明确需要。
- **现状与证据**：模块头自述「基础定义 CRUD + 实例状态管理；完整 DSL 解释器与 Saga 补偿执行器为后续扩展蓝图」（`workflow.rs`）；`KvWorkflowStore` 已具备（KV+Txn+Watch+CAS）；boundaries B-WF-1：实例/定义 append-only、无保留/归档 API。
- **请求的能力**：① 确认补偿执行器 + 端到端验收在 2027-03-31 承诺内交付（当前「蓝图」措辞存在歧义风险）；② 保留/归档策略；③ 语义文档：补偿幂等、重试/超时、信号/取消（对齐 proto 中 `SuspensionMeta` 等已定义字段）。
- **验收口径**：三步流程中途失败 → 逆序补偿且可重放；重启恢复；实例生命周期管理可用；文档齐备。

### G-TR-1【P2】transit：KEK 材料轮换（含 rewrap）

- **现状与证据**：B-SE-6——换 KEK 材料后旧材料 DEK 不可解；无内建多材料/轮换流程（`kek_id` 已有版本化语义但未接线多材料）。
- **请求的能力**：多材料并存解密窗口 + rewrap 流程（API 或工具）+ 演练文档。
- **验收口径**：旧材料密文在新材料实例可解密读；rewrap 后仅新材料可解；演练含回退路径。

### G-TR-2【P3】transit：不对称签名（产品决策）

- **现状**：transit 仅 `Encrypt/Decrypt/HmacSign/HmacVerify`，无 Sign——不能做「私钥不出域」的签名服务。
- **请求**：若组织 KMS 方向需要远程签名（token/审计锚点等），评估新增 ES256 签名能力或独立 KMS 服务；IAM 当前接受「密钥交付持有方」（PKI）模型，故仅列为产品决策。

### G-X-1【P1·文档】消费方路由与鉴权指南

- **业务需求**：组织内多团队接入 coord 的认知成本必须降下来：每服务「任一 agent 可用 / 分区 Leader 专属 / agent 本地态」的差异、能力清单（CCT）与 SDK 推荐用法要一目了然。
- **请求**：① `docs` 一页「Consumer Contract（按服务）」：一致性/路由/失败语义 + 推荐消费范式（如 MQ 必须 `Poll+Ack`，`Subscribe` 仅实时场景）；② SDK README 对齐；③ 每服务一条规范示例。
- **验收口径**：新消费者按文档可在 1 天内完成接入且对边界无歧义（以 IMS 二期接入作为试点回执）。

### G-EV-1 / G-SC-1【P3】观察项

- **event 持久化游标**（v1.2 候选）：落地后可作为轻量可补投通道；当前不影响消费方（投递通道由 MQ 承担）。
- **scheduler**：KV 存储验收、result 持久化未过；在此之前消费方用「选主 + 应用内触发」替代。

## 3. 边界确认（无需变更，仅请求保持与文档化）

以下边界消费方**已接受**并按此设计（不请求改动，仅请求保持语义稳定 + 在 SDK/README 中显式列出）：

- cache：跨节点提交非原子（ADR-0002）；静态分区 Leader、失联分区不可写；
- event：断线不补投（持久化游标为后续候选）；
- ratelimiter / circuitbreaker：agent 本地态；
- idgen：节段/雪花（非 UUIDv7——消费方 ID 契约自持）；
- lock：不可重入 + 看门狗续约；
- mq：`Subscribe` = best-effort（背压即丢）；at-least-once 仅 `Poll+Ack`；容量逐写严格拒绝（B-PL-4）。

## 4. 非请求项（明确不要求 coord 承担）

- 业务数据存储/查询（EIS 状态权威在 PG，不经 coord KV）；
- 分布式事务/XA（跨系统一致性由 PG outbox + MQ 投递承担）；
- 授权判定语义（EIS 04 契约自持；coord policy 若接入仅为执行面，语义与向量验收在 EIS 侧）；
- 消息全局有序 / exactly-once / 跨服务 2PC 等强承诺。

## 5. 与 STATUS 承诺日期的关系（建议）

- 本文件 P1 项的**能力域**均在现有契约承诺内（policy / mq / pki 均为 2026-12-31），但 **STATUS 现有验收项未覆盖**「分发（G-POL-1）/ 消费路由（G-MQ-1）/ 到期语义（G-PKI-1）/ 到期观测（G-PKI-2）」——**请求将其补入对应契约期的验收项**；
- G-PKI-1 属语义修正，建议不等待大版本（补丁级修复亦可）；
- G-WF-1 依赖既有 2027-03-31 日期，仅请求**书面确认**补偿执行器在该日期内交付。

## 6. 验收协作

- **消费方将提供**：seedj `coord-it` 集成测试扩展（真实 coord 容器）——逐条缺口编写消费侧验收用例并回传结果，作为交叉验证；
- **coord 侧建议**：`coord-agent/tests` 对应单测/IT + proto 边界声明更新 + `docs/production/ops/boundaries.md` 同步；
- **变更流程提醒**：新增 RPC 必须登记 `coord-core/src/grpc_auth.rs` 能力表（漏登记 = 鉴权开启时全部拒绝）。

## 7. 落地回执与消费方验证（v1.1，2026-10-10）

### 7.1 发布事实（已核对）

- **coord v0.2.2**：标签 `v0.2.2`（commit `3fa9b31`），GitHub Release 2026-10-10T12:26Z 发布（非 pre/draft）；容器镜像 `ghcr.io/byteforce-cn/coord:v0.2.2` 已开放（amd64）。
- **coord-java-sdk 0.2.1**：`cn.byteforce:coord-java-sdk:0.2.1` 已发布 Maven Central（POM/JAR 均 HTTP 200）；新增 `getTopicLeader` / `moveToDlq` / `deleteTopic` / `rewrap` / `deleteInstance` / `deleteDefinition` / event cursor 支持 / `CoordException#getLeaderHint`。
- **coord 侧承接文档**：`docs/adr/0010-eis-consumer-gaps-full-landing.md`（accepted，**全量承接、无驳回项**；批次：G-PKI-1/G-X-1 立即，G-POL/G-MQ/G-PKI-2/3/G-TR-1 契约期内，G-WF-1/G-SC-1 2027-03-31；**实际交付均早于批次目标**）。
- **契约增量**：`apis/contracts/CHANGELOG.md` [contracts/v1.3.0]（Minor：+6 RPC [MQ×3、Transit×1、Workflow×2]、+4 字段 [MqMessage.dlq_reason/detail、event.cursor/seq]；`buf breaking` 基线 v1.2.0）；STATUS 验收项已按 §5 请求增补（G-POL-1/G-MQ-1/G-PKI-1/G-PKI-2 等已入行）。

### 7.2 逐条闭环状态

| 缺口 | coord 侧落地（工件/提交锚点） | 消费方实测（2026-10-10 本机，全过） |
| --- | --- | --- |
| G-POL-1 | `policy.rs`：`load_all_bundles`（启动加载）+ `run_bundle_watch`（Watch 收敛/溢出全量对账）；commit `a94b7ff`；proto/STATUS 边界声明同步 | `coord/tests/policy_bundle_distribution_test.rs`：双 agent 收敛 ≤10s、重启重载、Rollback/SetEnabled 收敛、并发 Put 版本单调（1..5 互异） |
| G-POL-2 | 定谳 = 方向 (b)：`CheckPermission` 明确 agent 本地/嵌入式；生产走 OPA bundle `Evaluate`；policy.proto 头注 + 消费方契约页 §8.1（装载→判定→重启 demo） | 文档面核对（proto 声明 + consumer-contract.md §8 / SDK README） |
| G-MQ-1 | proto `GetTopicLeader`；非 Leader = `x-coord-error-code: NOT_LEADER` + `coord-leader-hint` trailer（可编程判别）；SDK `MqClient#getTopicLeader` / `CoordException#getLeaderHint` | `agent_isr_test`：`test_follower_write_rejected_not_leader`、`test_leader_query_dlq_and_delete_across_agents` |
| G-MQ-2 | 公开 `MoveToDlq`（能力 `coord:mq:manage`，净额记账）；`MqMessage.dlq_reason/detail` 字段 | `agent_mq_test::test_move_to_dlq_net_accounting_and_not_found` |
| G-MQ-3 | 指标 `coord_agent_mq_consumer_lag/offset/next_offset` + 告警 `CoordMqConsumerLag`（prometheus-rules + runbook §6） | `metrics.rs::test_render_mq_consumer_lag_and_policy_bundle_metrics` |
| G-MQ-4 | 公开 `DeleteTopic`（全量回收 + 配额归还；ISR 全域一致；先停读写前置）；B-PL-4(d) 更新 | `agent_mq_test::test_delete_topic_full_reclaims_all_state` |
| G-PKI-1 | 到期 = 换新触发：`replace_active_cert_cas` 版本化 CAS 重签（新 serial/新密钥）；commit `c148e6c` | `test_expired_current_record_is_reissued_not_returned`（+ 库内 issue/rotate 过期替换 2 条） |
| G-PKI-2 | 指标 `coord_agent_pki_certs_expiring_soon`（窗口 `expiry_warn_hours` 默认 6h）+ 告警 `CoordPkiCertExpiringSoon` | 指标渲染测试 + 告警门禁脚本（gate-drills exit 0） |
| G-PKI-3 | 设计三件套落档：`security.md` §3.1（GetCertByCN=私钥读取权定级）/§3.2（吊销应急 CN 轮换 playbook；revocation 不在本轮）/§3.3（非 HSM 边界+重估触发）；runbook §4.5；新边界 B-PKI-1 | 文档面核对 |
| G-WF-1 | **提前交付**：`sw` 编译器 `compensatedBy` + 补偿执行；保留策略 `DeleteInstance`（终态守卫）/`DeleteDefinition`（引用守卫）；`workflow-semantics.md`；B-WF-1 更新 | `test_sw_compensated_by_runs_compensation_end_to_end`、`test_sw_three_step_failure_compensates_in_reverse_order_and_replays`、engine delete 2 条 |
| G-TR-1 | KEK 多材料解密窗口 + 公开 `Rewrap`；`COORD_TRANSIT_KEK_OLD` 注入；B-SE-6 更新（迁移完成前不得下线旧材料）；runbook §4.4 | `test_multi_material_decrypt_window_and_rewrap` 等（材料批 18 条全过） |
| G-TR-2 | 产品决策定谳：不新增远程非对称签名（触发条件另行立项）；新边界 B-TR-1 | 文档面核对（proto / consumer-contract §10） |
| G-X-1 | 新增 `docs/production/consumer-contract.md`（14 节：一致性/路由/失败语义 + 能力表 + 边界索引 + 接入检查清单）；Java SDK README 对齐；SDK 每服务示例 | 文档面核对；**试点回执（IMS 二期接入）待我方交付** |
| G-EV-1 | 持久化游标：`EventSubscribeRequest.cursor` + `CloudEventMessage.seq`；默认实时不补投、显式游标保留窗口内补投；边界更新 | `coord/tests/event_cursor_replay_test.rs` |
| G-SC-1 | `KvSchedulerStore`（CAS 认领）+ result 随任务持久化（首个结果为准、幂等） | `test_complete_persists_result_across_restart_and_is_idempotent` |

> 验证环境：本机克隆 `/root/coord-r1-pub` @ `v0.2.2`（`3fa9b31`）；`CARGO_TARGET_DIR=/root/coord-r1/target cargo test --offline`；另跑 `apis/contracts/scripts/check-wire-sync.sh`（exit 0）与 `scripts/check-gate-drills.sh`（15 告警↔runbook 一一对应，exit 0）。

### 7.3 遗留与消费方后续动作

- **消费方交叉验证（§6 承诺）**：seedj `coord-it` 扩展（消费侧用例逐条回传）待做——可随 IMS 二期接口落地一并推进；
- **G-X-1 试点回执**：IMS 二期接入按契约页执行后回填（§6 验收协作的闭环项）；
- **语义变化点（消费方需知）**：① event 边界从「断线不补投」变为「默认不补投；显式游标可在保留窗口内补投」；② MQ 毒消息处置升级为显式 `MoveToDlq`；③ PKI 过期语义修正（Issue/Rotate 换新）——LANDING-IAM v0.3.1 已同步；
- **接入版本建议**：IMS dev 配方/镜像建议升级 `v0.2.0 → v0.2.2`（ghcr 已开放）；`coord-java-sdk` 升至 `0.2.1`（Maven Central）。

### 7.4 变更记录

- v1.0（2026-10-09）：初稿（15 条缺口）。
- v1.1（2026-10-10）：新增本章落地回执与消费方验证（coord 全量承接 + v0.2.2/SDK 0.2.1 发布；逐条实测通过）。

## 附录 A：证据锚点（coord v0.2.1 @ `2c61f23`，缺口成立性证据；落地证据见 §7）

| 缺口 | 锚点 |
| --- | --- |
| G-POL-1/2 | `coord-agent/src/services/policy.rs`（put_bundle 仅本机装配、`start()` 不加载）、`coord-agent/tests/agent_opa_test.rs`（KV/Watch 下发 = 实施中）、`apis/contracts/proto/coord/policy/v1/policy.proto`、`apis/contracts/STATUS.md`（policy 行） |
| G-MQ-1..4 | `coord-agent/src/services/mq.rs`（模块头 per-agent/ISR/Leader；`move_to_dlq`；`delete_topic` 无调用点）、`apis/contracts/proto/coord/mq/v1/mq.proto`（无 DeleteTopic）、`docs/production/ops/boundaries.md` B-PL-4(d)、`coord-java-sdk/.../MqClientImpl.java`（无路由）、`coord-agent/src/metrics.rs`（无 lag 指标） |
| G-PKI-1..3 | `coord-agent/src/pki.rs`（`issue_cert` 过期路径 / `rotate_cert` / `get_cert_by_cn` / `is_expiring_soon`）、`coord-agent/src/pki_store.rs`（CAS / `replace_active_cert` / list 过滤）、`coord-agent/tests/agent_pki_test.rs`、`coord-core/src/grpc_auth.rs` L233–240 |
| G-WF-1 | `coord-agent/src/services/workflow.rs`（模块头）、`docs/production/ops/boundaries.md` B-WF-1..4 |
| G-TR-1/2 | `coord-agent/src/services/transit.rs`（模块头 KEK/DEK/无不对称签名）、boundaries B-SE-2 / B-SE-6 |
| G-EV-1 | `apis/contracts/proto/coord/event/v1/*.proto`（断线不补投） |
| 消费方评估全文 | `eis/docs/LANDING-IAM.md` v0.3 §3.4（逐服务证据表、再评估条件） |

## 附录 B：流转记录

- 对接人：IMS/EIS 侧 ___ ｜ coord 侧 ___
- 评审会：2026-10-09 coord 受理评审（ADR-0010 accepted，全量承接）｜ 排期回执：批次表见 ADR-0010 §1
- 版本：v1.0 初稿（2026-10-09）；v1.1 落地回执（2026-10-10，coord v0.2.2 / coord-java-sdk 0.2.1；消费方实测全过，见 §7）
