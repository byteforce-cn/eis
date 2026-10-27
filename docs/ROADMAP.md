# 路线图（Roadmap）

## v1.x（规范稳定期）

> 缺口归属（核心契约 / 扩展契约 / 实现与运维）一律按 **ADR-0012** 判定；新提案须写明
> 「归属层 + 触发条件 + 可执行工件」。本轮裁决对应的扩展项：Outbox/Inbox（#31/#34）、
> 调度（#37）、对账（#36）、授权条件声明面（#28/#29）、调用方约束（#30）、命令响应
> `locator/version`（#32①）；informative 项：编排边界（#35）、集成边界（#38）、运维（#39）。

- [x] **跨扩展前置**（issue #30 步骤 2）：`extensions/hr` 1.3.0 依赖 `approval 1.1.0`，`hr.employee.activate` 要求已通过审批单（ADR-0019）；
- [x] **边界说明（informative）**：编排边界（#35）、集成边界（#38）、运维与灾备（#39）——不新增合规等级；
- [x] **可靠投递扩展**（issue #31/#34）：`extensions/outbox/`（Outbox + Inbox、`outbox.ddl`、OBX-001..012）+ `tools/relay`（状态机参考 + PG 语句模板）+ CI PostgreSQL 冒烟（ADR-0018）；
- [x] **定时任务执行语义扩展**（issue #37）：`extensions/scheduler/`（`scheduler.ddl`、SCH-001..012、`kind: runtime`）+ `tools/scheduler`（幂等/互斥/租约抢占参考）+ CI PostgreSQL 冒烟（ADR-0021）；
- [ ] **多语言绑定生成**：`schema-compiler` 输出 Java / TypeScript 类型（seedj 与
      前端直接消费），生成物纳入 CI 一致性校验；
- [ ] **工具增强**：`migration-generator` 支持索引/约束 diff；`contract-checker`
      增加 AsyncAPI 全量 schema 校验与 OpenAPI lint 集成；
- [ ] **独立验证工件**（issue #10 后续项）：六类契约的公开 JSON Schema（数据/操作/时间/
      授权/审计/演进）与独立契约 lint CLI；当前已交付 `compatibility-checker --standalone`、
      纯 stdlib 核心 `tools/lib/eis_compat.py` 与 `compatibility.rules.schema.json`（ADR-0008）；
- [x] **AI 规格包 P1**（issue #12）：`tools/build-spec-pack` 从规范源生成自包含规格包（六类契约 +
      `vectors/` 冻结夹具 + 参考工具 + `MANIFEST.json` 逐文件 SHA-256），CI 构建并在产物内自校验；
- [x] **AI 规格包 P2**（issue #12）：4 个 Agent Skills（`skills/`）与 `docs/AI-INTEGRATION.md`、`CONTRIBUTING.md`「AI 辅助贡献」；
- [x] **AI 规格包 P3**（issue #12）：npm/pnpm 包形态（`--npm-out` 生成 `@byteforce/eis-spec` + 零依赖 CLI）+ CI `pnpm pack` 归档；
- [x] **AI 规格包 P4**（issue #12）：CI staged release（`.github/workflows/release-npm.yml`：`npm stage publish`；tag `v*` → `latest`、预发布 tag → `next`、手动 → `nightly`；`NPM_TOKEN` + provenance；维护者在 npmjs.com「Staged Packages」批准后公开）；
- [ ] **审计增强**：链头锚定参考方案（按期签名并发布链头 hash）、审计导出/归档格式；
- [x] **扩展扩充**：`extensions/hr`（人员/组织/任职/供给）已引入 v1.0.0（含可执行用例与 V201 迁移），当前 v1.1.0（员工雇佣类型/工作地点，V202，issue #13）；
      `extensions/asset`（资产）待社区贡献（见 CONTRIBUTING）；
- [ ] **PostgreSQL 集成测试扩展**：时序索引建议验证、分区表模板（非契约、性能域）。

## 生态落地（seedj / server）

- [x] **P1**：seedj `eis-core` + `eis-audit`（命令运行时 + 审计链，对齐参考内核）；
- [x] **P2**：seedj `eis-temporal` + `eis-authz`（时点查询 + as_of 授权）；
- [x] **P3′**：**`ims-iam` 全量落地**（EIS 首个域服务：OAuth2 授权服务器 + 授权解析权威 + 身份管理域；验收 53/53 + 21/21 + 15/15 + 冒烟全过）——执行回报见 `docs/LANDING-IAM.md` v1.0.0 §11；
- [ ] **P3**：`ims-finance` 落地 accounting 扩展；
- [ ] **P4**：`ims-inventory` / `ims-approval` / `ims-procurement` 试点；
- [ ] 试点验收：业务（金额/数量/期间）、合规（审计链）、运维（部署/回滚）三方签署。

## 版本规划

| 版本 | 主题 | 兼容性 |
|------|------|--------|
| 1.0.x | 修复与文档（无契约变更） | PATCH |
| 1.1.0 | 语言绑定、扩展扩充、工具增强 | MINOR（纯新增） |
| 2.0.0 | 预计不早于首个 L4 外部采用者出现后评估 | MAJOR（需 ADR + 迁移） |

> 任何契约级变更必须走 ADR 流程（`00-freeze/adr/README.md`）；无工件的变更一律拒绝。
