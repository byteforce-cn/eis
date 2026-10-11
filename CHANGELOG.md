# Changelog

本项目版本语义遵循 [00-freeze/version-policy.md](00-freeze/version-policy.md)（SemVer）。

## [1.0.0] — 2026-10-08（开源首发）

### 冻结

- 六份契约首次冻结：数据 / 操作 / 时间 / 授权 / 审计 / 演进（ADR-0001）。

### 参考实现（本次发布的完整工具链，Python）

- `tools/schema-compiler`：扩展 Schema → PostgreSQL DDL；核心 DDL ↔ Schema 一致性检查；
- `tools/contract-checker`：Schema/OpenAPI/AsyncAPI/错误码/清单/组合 全面结构校验；
- `tools/authz-resolver`：时点解析、代理展开、`/check` 语义与 SoD（prevent/warn）；
- `tools/compatibility-checker`：新旧 Schema diff → MAJOR/MINOR/PATCH + 配套动作；
- `tools/migration-generator`：diff → 迁移 SQL + 回滚 SQL（必填三步：加列/回填/NOT NULL）；
- `tools/audit-verifier`：封装 `verify.tool`，含冻结测试向量校验与夹具批量验证；
- `tools/e2e-runner`：执行全部 `*.test.yaml` 用例与 `cases/*/scenarios` 场景；
- `tools/lib/kernel.py` **参考内核**：命令 → 规则 → 事件 → 哈希链审计 → 双时间轴对象 → 读模型，
  可执行端到端场景（procure-to-pay）。

### 修复与补全（发布前定稿，ADR-0002）

- `query-templates.sql` 修正为可执行 plpgsql（原 `RETURNS TABLE` 语法无效）；
- `event.asyncapi.yaml` 通道键 `$ref` 修正（原引用不符合 JSON Pointer）；
- 命令 API 新增 `GET /commands/{id}`（异步结果查询）；
- 错误码新增 `EIS-401-001` / `EIS-500-001` 与扩展命名空间约定；
- 授权解析补全 `Scope` / `reason_code` / `sod_warnings`；SoD 语义文档化。

### 测试工程

- 全部 43 条验收用例可执行化（static / schema-doc / chain / authz / compat / migrate / scenario / cli）；
- 新增审计链夹具（valid / tampered / gap / broken 四类）与演进夹具（破坏性/兼容两对）；
- 采购试点场景可执行版：7 步（含自审负例）、12 项断言、6 条审计链；
- 审计链冻结测试向量（`447c6e29...`）经参考实现验证一致。

### 工程与文档

- LICENSE（Apache-2.0）、NOTICE、SECURITY、CONTRIBUTING、CODE_OF_CONDUCT；
- CI（GitHub Actions）：规范与工具校验 + PostgreSQL 16 DDL 冒烟（`tools/ci/ddl-smoke.sql`）；
- 落地文档：`docs/IMPLEMENTATION.md`（seedj/server 映射）、`docs/CONFORMANCE.md`（合规等级）、`docs/ROADMAP.md`。
