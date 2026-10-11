# 路线图（Roadmap）

## v1.x（规范稳定期）

- [ ] **多语言绑定生成**：`schema-compiler` 输出 Java / TypeScript 类型（seedj 与
      前端直接消费），生成物纳入 CI 一致性校验；
- [ ] **工具增强**：`migration-generator` 支持索引/约束 diff；`contract-checker`
      增加 AsyncAPI 全量 schema 校验与 OpenAPI lint 集成；
- [ ] **审计增强**：链头锚定参考方案（按期签名并发布链头 hash）、审计导出/归档格式；
- [ ] **扩展扩充**：`extensions/hr`（人员/组织）、`extensions/asset`（资产）以
      社区贡献方式引入（见 CONTRIBUTING）；
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
