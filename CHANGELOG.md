# Changelog

本项目版本语义遵循 [00-freeze/version-policy.md](00-freeze/version-policy.md)（SemVer）。

## [Unreleased] — 2026-10-27

### 新增

- 授权条件声明面（ADR-0015 / issue #28、#29）：`manifest.permissions[].condition`（受限 DSL：单层 `all`/`any` + `attribute`/`op`/`values`）；路径必须落在 `04` 属性快照 `AttributeSet` 内（支持 `positions[*]` 的「任一岗位」语义），`contract-checker` 校验路径/op/结构；判定方按声明求值（`eq`/`in` 存在语义、`neq`/`not_in` 全称语义），快照缺失/过期/属主不可达/路径缺失一律 fail-closed；**移除参考实现的调用方条件入口**（`require_attributes` / `--require-attribute`），条件只由声明侧提供、只收窄不授予；`attribute.rules.yaml` 新增 ATR-009 与 `condition_language`；
- 命令响应定位（ADR-0014 / issue #32①）：`CommandAccepted` 增可选 `locator`（聚合根 ID / 流程实例 ID）与 `version`（对象版本，与 `01` 的 `version` 同语义）；明确 MUST「命令响应不携带读模型投影」与「失败响应不带定位符」；参考内核在受理结果输出 `locator`/`version`，hr 场景断言「返回的 version == 随后读到的对象 version」；`min_version` 读后写等待（#32②）仍待独立 ADR；
- 命令调用方约束（ADR-0013）：`manifest.permissions[].callers`（`person` / `system`）为唯一权威，扩展 operations 契约用 `x-eis-callers` 同值投影；`contract-checker` 双向校验（缺投影/缺声明/值不一致/非法枚举均失败），并新增自测断言；参考内核在 `/check` 放行后、处理器之前做主体类型预检，越权以新错误码 `EIS-403-002`（`caller_not_allowed`）拒绝，fail-closed（issue #30 步骤 1）；
- `extensions/hr` 1.2.0：`hr.employee.activate` / `hr.employee.cancel` 声明 `callers: ["system"]`——仅审批服务身份可调，用户会话持有权限同样被拒（AUD-01 的契约化堵口）；既有用例的 activate/cancel 步骤改用审批服务主体，并新增反例场景；

### 修复

- T-R009「有效区间不重叠」落地为 DDL 排他约束（ADR-0011）：`schema-compiler` 随每张对象表输出 `ex_<table>_valid_overlap`（`id` + 系统时间区间 + 业务时间区间四维 `EXCLUDE USING gist`），`business_object` 同步声明；`tools/ci/ddl-smoke.sql` §9 断言重叠拒绝（`exclusion_violation`）、封口链与相邻区间允许；`docs/KNOWN-LIMITATIONS.md` §1.1/§1.3 同步收窄（issue #40①）。

### 变更

- 用例 141/141（新增授权条件声明/求值/fail-closed 用例与内核自测；移除调用方传条件的反模式用例），同步 `README.md` / `CONTRIBUTING.md` / `docs/CONFORMANCE.md` / `docs/KNOWN-LIMITATIONS.md` 计数口径。

## [Unreleased] — 2026-10-17（开放 issue 修复）

### 修复

- `extensions/approval` 声明读取面权限目录（`approval.request.read`；6 命令 + 1 读取，动态属主以 `approval.section.confirm.*` 声明），`contract-checker` 支持尾部 `.*` 通配且保持段边界校验（issue #8）；
- 扩展权限目录与读取面授权口径（ADR-0006）：`manifest.permissions`（hr 声明 11 命令 + `hr.employee.read`/`hr.attributes.read`），`contract-checker` 拦截未声明权限引用；属性快照端点限定服务间（ATR-008）；核心通用查询 API 明确部署边界（issue #7）；
- 写入专用派生字段口径（ADR-0005 / DRV-001..006）：载荷携带原始值（`writeOnly`）、域服务用注入密钥派生、密钥环轮换窗口、读投影/命令记录/日志剔除；`extensions/hr` 载荷 `id_number_hash` → `id_number`（发布前修正），参考内核支持 `derive_write_only`/`write_only_variants`/`read_projection`/`object-absent`，iam 凭证 `secret_hash` 同步登记读投影剔除（issue #6）；
- `tools/contract-checker`：拦截与 PostgreSQL 保留字冲突的对象字段名（issue #1）；
- `tools/lib/kernel.py`：扩展命令处理器注册机制（`extensions/*/handlers.py`），内核不再按扩展硬编码（issue #2）。

### 新增

- `extensions/hr` 1.0.0：人力资源域扩展（组织/岗位/员工/任职/供给任务，含 V201 迁移，issue #5）；
- `extensions/hr` 1.1.0：Employee 增加 `employment_type` / `work_location`（可选，受控枚举 / 非空文本，加法演进 MINOR，含 V202 迁移与 ADR-0009，issue #13）；
- `tools/build-spec-pack`（issue #12 / P1）：从规范源生成自包含 AI 规格包（六类契约 + `vectors/` 冻结夹具 + 参考工具 + `MANIFEST.json` 逐文件 SHA-256），产物内可直接运行 `verify.tool --self-test` / `audit-verifier --vector` / `compatibility-checker --standalone` / `contract-checker`；
- `tools/build-spec-pack --npm-out`（issue #12 / P3）：生成 `@byteforce/eis-spec` pnpm/npm 包形态（零依赖 `bin/eis-spec.js` CLI：`manifest` / `verify`（含 python 冻结向量自检）；`LICENSE`/`NOTICE` 与打包文件作为 `kind: packaging` 纳入 MANIFEST）；CI 增加 node 自检与 `pnpm pack` artifact（不发布 registry）；
- npm 发布工作流（issue #12 / P4）：`release-npm.yml` 以 staged release 方式用仓库 `NPM_TOKEN` 暂存 `@byteforce/eis-spec`（`npm stage publish`；tag `v*` → `latest`、预发布 tag → `next`、手动 → `nightly`；`id-token: write` + `--provenance`），维护者在 npmjs.com「Staged Packages」批准后公开；首个正式版 `1.0.0` 已发布（维护者侧手工发布，无 provenance），nightly 通道经 staged release 验证（`1.0.0-nightly.20261017.ed73ebc`，含 provenance）；`build-spec-pack --npm-version` 支持包版本覆盖（MANIFEST 同时记录 `spec_version` 与 `package_version`）；
- `skills/`（Agent Skills，issue #12 / P2）：`eis-create-contract` / `eis-verify-contract` / `eis-generate-audit` / `eis-generate-verifier` 四个技能（含可验证示例 `examples/im-message.schema.json`）与 `skills/README.md` 索引；
- `docs/AI-INTEGRATION.md`：Claude Code / Codex / Pi / OpenCode 接线、通用验证约束与失败反馈闭环；`CONTRIBUTING.md` 新增「AI 辅助贡献」章节；
- `extensions/approval` 1.0.1：区块级流转（分派/条件参与/打回重确认/撤回，MINOR，issue #4）；
- `extensions/approval` 1.1.0：区块顺序语义（`ApprovalSection.step_order` 可选字段 + 规则 `section_order` + 错误码 `APR-409-007`；乱序确认/system 回写拒绝、`not_applicable` 不阻塞、重提保留序号，MINOR，issue #18 / ADR-0010）；
- 审计条目 `payload_digest`（ADR-0007 / hash-chain v1.1）：事件投影 `{id,type,payload}` 规范 JSON 的 SHA-256，可选字段且仅存在时参与链哈希（v1.0 条目哈希不变）；`verify.tool`/`audit-verifier --events` 复算并检出事件正文篡改（issue #9）；
- 授权属性协议：`04-authz-contract/attributes.api.yaml`、`attribute.rules.yaml`（ATR-001..007）与 ADR-0004（issue #3）。

### 变更

- `tools/compatibility-checker` 独立模式（ADR-0008）：核心判定提取为纯 stdlib `tools/lib/eis_compat.py`，新增 `--standalone`/`--rules` 与规则 JSON Schema `06-evolution-contract/compatibility.rules.schema.json`；默认输出与判定语义不变（issue #10）；
- `tools/e2e-runner`：`object-field`/`object-count` 断言支持 `${...}` 令牌；`kind: authz` 支持属性快照与条件断言；
- `tools/migration-generator`：支持 `allOf` 扩展对象 Schema（合并内联领域属性；平铺 Schema 行为不变，issue #13）；
- `tools/lib/kernel.py`：`object-field` 断言新增可选 `read_projection: true`（默认仍为 `as_of`）；
- `.github/workflows/ci.yml`：新增 `spec-pack` 任务（构建 + MANIFEST 校验 + 产物内自校验 + artifact 上传）；
- `tools/contract-checker`：新增 `--file` 单文件检查（`*.schema.json` / `*.openapi.yaml` / `*.api.yaml` / `*.asyncapi.yaml`），Schema 检查补充 `$ref` 解析校验；
- 用例 134/134（相对首发 53 条新增 81 条），PG16 DDL 冒烟含 `hr`/`approval` 新区块表。

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
