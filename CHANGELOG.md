# Changelog

本项目版本语义遵循 [00-freeze/version-policy.md](00-freeze/version-policy.md)（SemVer）。

## [Unreleased] — 2026-10-11（开放 issue 修复）

### 修复

- `extensions/approval` 声明读取面权限目录（`approval.request.read`；6 命令 + 1 读取，动态属主以 `approval.section.confirm.*` 声明），`contract-checker` 支持尾部 `.*` 通配且保持段边界校验（issue #8）；
- 扩展权限目录与读取面授权口径（ADR-0006）：`manifest.permissions`（hr 声明 11 命令 + `hr.employee.read`/`hr.attributes.read`），`contract-checker` 拦截未声明权限引用；属性快照端点限定服务间（ATR-008）；核心通用查询 API 明确部署边界（issue #7）；
- 写入专用派生字段口径（ADR-0005 / DRV-001..006）：载荷携带原始值（`writeOnly`）、域服务用注入密钥派生、密钥环轮换窗口、读投影/命令记录/日志剔除；`extensions/hr` 载荷 `id_number_hash` → `id_number`（发布前修正），参考内核支持 `derive_write_only`/`write_only_variants`/`read_projection`/`object-absent`，iam 凭证 `secret_hash` 同步登记读投影剔除（issue #6）；
- `tools/contract-checker`：拦截与 PostgreSQL 保留字冲突的对象字段名（issue #1）；
- `tools/lib/kernel.py`：扩展命令处理器注册机制（`extensions/*/handlers.py`），内核不再按扩展硬编码（issue #2）。

### 新增

- `extensions/hr` 1.0.0：人力资源域扩展（组织/岗位/员工/任职/供给任务，含 V201 迁移，issue #5）；
- `extensions/approval` 1.0.1：区块级流转（分派/条件参与/打回重确认/撤回，MINOR，issue #4）；
- 审计条目 `payload_digest`（ADR-0007 / hash-chain v1.1）：事件投影 `{id,type,payload}` 规范 JSON 的 SHA-256，可选字段且仅存在时参与链哈希（v1.0 条目哈希不变）；`verify.tool`/`audit-verifier --events` 复算并检出事件正文篡改（issue #9）；
- 授权属性协议：`04-authz-contract/attributes.api.yaml`、`attribute.rules.yaml`（ATR-001..007）与 ADR-0004（issue #3）。

### 变更

- `tools/compatibility-checker` 独立模式（ADR-0008）：核心判定提取为纯 stdlib `tools/lib/eis_compat.py`，新增 `--standalone`/`--rules` 与规则 JSON Schema `06-evolution-contract/compatibility.rules.schema.json`；默认输出与判定语义不变（issue #10）；
- `tools/e2e-runner`：`object-field`/`object-count` 断言支持 `${...}` 令牌；`kind: authz` 支持属性快照与条件断言；
- 用例 100/100（相对首发 53 条新增 47 条），PG16 DDL 冒烟含 `hr`/`approval` 新区块表。

## [1.0.0] — 2026-10-08（开源首发）

### 冻结

- 六份契约首次冻结：数据 / 操作 / 时间 / 授权 / 审计 / 演进（ADR-0001）。

### 参考实现（本次发布的完整工具链，Python）

- `tools/schema-compiler`：扩展 Schema → PostgreSQL DDL；核心 DDL ↔ Schema 一致性检查；
- `tools/contract-checker`：Schema/OpenAPI/AsyncAPI/错误码/清单/组合 全面结构校验；
- `tools/authz-resolver`：时点解析、代理展开、`/check` 语义与 SoD（prevent/warn）；
- `tools/compatibility-checker`：新旧 Schema diff → MAJOR/MINOR/PATCH + 配套动作；
- `tools/migration-generator`：diff → 迁移 SQL + 回滚 SQL（必填新列：有 `default` 直接 `DEFAULT ... NOT NULL`；无 `default` 生成可空 `ADD COLUMN` + 回填提示，不自动 `SET NOT NULL`）；
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

- 全部 53 条验收用例可执行化（static / schema-doc / chain / authz / compat / migrate / scenario / cli）；
- 新增审计链夹具（valid / tampered / gap / broken 四类）与演进夹具（破坏性/兼容两对）；
- 采购试点场景可执行版：7 步（含自审负例）、12 项断言、6 条审计链；
- 审计链冻结测试向量（`447c6e29...`）经参考实现验证一致。

### 工程与文档

- LICENSE（Apache-2.0）、NOTICE、SECURITY、CONTRIBUTING、CODE_OF_CONDUCT；
- CI（GitHub Actions）：规范与工具校验 + PostgreSQL 16 DDL 冒烟（`tools/ci/ddl-smoke.sql`）；
- 落地文档：`docs/IMPLEMENTATION.md`（seedj/server 映射）、`docs/CONFORMANCE.md`（合规等级）、`docs/ROADMAP.md`。
