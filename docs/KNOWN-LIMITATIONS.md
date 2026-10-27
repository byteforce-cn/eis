# 已知限制与规范缺口（Known Limitations）

> 本文件诚实记录 EIS Spec v1.0 参考实现的边界与规范中已知的缺口。每条给出【已核实】证据
> （文件:行号或工具行为），并按「现状 / 影响 / 使用者应对」说明。这些不是承诺清单，而是供
> 采用者评估风险与自行补齐的依据。
>
> 计数口径：`python3 tools/e2e-runner --all` 的实际输出为唯一来源（当前 `用例 142/142`）。

## 1. 时间契约

### 1.1 T-R009「有效区间不重叠」（已修复：ADR-0011 四维排他约束）

- 【已修复】`tools/schema-compiler` 现随每张对象表输出 `ex_<table>_valid_overlap`：
  `EXCLUDE USING gist (id WITH =, tstzrange(recorded_at, superseded_at, '[)') WITH &&, tstzrange(valid_from, valid_to, '[)') WITH &&)`；
  `01-data-contract/core.ddl` 的 `business_object` 同步声明；`tools/ci/ddl-smoke.sql` §9 断言
  「同一系统时间视图内业务区间相交 → `exclusion_violation`」「封口链（`superseded_at == 新记录 recorded_at`）与
  相邻区间允许写入」，CI 的 PostgreSQL 16 任务全绿。
- 【为何不是 `WHERE superseded_at IS NULL`】T-R005 的 `uq_<table>_current` 已保证每个 id 至多一条当前记录，
  仅限定当前记录的排他约束恒不触发；T-R009 的「同一系统时间视图」需用系统时间区间维度表达（ADR-0011）。
- 残余：参考内核（`tools/lib/kernel.py`）是内存模型，不执行 DDL 约束；以 PostgreSQL 落地为准。

### 1.2 T-R011「迟到事件追加写入」与内核封口语义存在差异

- 【已核实】`03-time-contract/temporal.rules.yaml:88`（T-R011）要求迟到事实以新的系统时间
  追加写入、允许有效区间覆盖历史并以 `superseded` 留痕；而 `tools/lib/kernel.py` 的
  `_update_object`/`Kernel.advance` 仅处理时钟单调前进的常规封口，无迟到回填历史的路径。
- 现状：参考内核不对迟到写入建模。
- 影响：内核不能作为迟到场景的行为基准，相关用例只覆盖单调时钟。
- 使用者应对：需要迟到写入时，按 T-R011 自行实现并补齐可执行用例。

### 1.3 `as_of` 多版本重叠时静默择一

- 【已收窄】重叠写入已由 DDL 排他约束在数据库层拒绝（§1.1 / ADR-0011），T-R008 的唯一性不再依赖调用方自律。
- 残余 1：参考内核是内存模型，不执行 DDL 约束；直接构造重叠行时 `Kernel.as_of` 仍 `max(version)` 静默择一，
  因此内核不能作为重叠场景的合规基准。
- 残余 2：`03-time-contract/query-templates.sql` 的通用 `as_of_valid` 只含业务时间谓词，不叠加系统时间轴；
  对有修正历史的表，单轴业务时间查询仍可能命中多条记录。展开函数（如 `accounting_balance_as_of_valid`）
  已显式带 `superseded_at IS NULL`；通用模板的演进另行立项。
- 使用者应对：业务时间查询要么带系统时间（`as_of_bitemporal`），要么叠加 `superseded_at IS NULL`。

## 2. 内核与 Schema

### 2.1 内核执行扩展对象 Schema（已修复：ADR-0016）

- 【已修复】`tools/lib/kernel.py` 现按 `manifest.objects` 载入
  `extensions/**/objects/*.schema.json`，在 `_create_object` / `_update_object`（含 `seed`）
  写入前用 `jsonschema`（Draft 2020-12）校验**完整行**；缺依赖/缺 Schema/Schema 非法 →
  拒绝启动，未声明对象类型或 Schema 违约 → `EIS-400-001`（fail-closed）。更新路径先校验
  新行再封口旧行，校验失败不留下半更新状态。
- 对象类型同时接受 DDL 表名（`hr_employee`）与内核短名（`voucher`）；跨扩展别名冲突即拒绝启动。
- 残余 1：`jsonschema` 是可选依赖，未安装时内核拒绝启动（不降级）；`validate_objects=False`
  仅供隔离自测，关闭后不构成合规基准。
- 残余 2：只校验 `manifest.objects` 声明的对象类型；未声明类型不再被内核接受（fail-closed）。
- 残余 3：相对文件 `$ref` 会被内联；不支持远端/网络 `$ref`（参考内核必须离线确定性）。
- 修正：`extensions/hr/objects/employee.schema.json` 的 `employment_type` / `id_type`
  原为 `type: ["string","null"]` 但 `enum` 不含 `null`（自相矛盾），已补 `null`。
- 使用者应对：实现侧仍应以 `contract-checker` + 对象 Schema 为权威；内核放行不等于部署合规。

### 2.2 审计链不覆盖事件 payload（已修复：v1.1 payload_digest）

- 【已修复】`tools/lib/kernel.py` 的 `_append_audit` 现写入 `payload_digest`（事件投影
  `{id,type,payload}` 的规范 JSON SHA-256，见 `hash-chain.spec.md` v1.1），校验工具
  `verify.tool`/`audit-verifier --events` 可复算并检出事件正文篡改（`payload_digest_mismatch`）。
- 残余边界：复算需要事件导出文件；仅有审计链时只能验证链内自洽（digest 自身纳入哈希，
  篡改条目字段仍报 `invalid_hash`）；仅实现 v1.0 公式的旧验证器无法验证含 digest 的新条目。
- 使用者应对：审计导出应同时提供事件导出（或由其复算的投影摘要）；跨实现验证器按
  `hash-chain.spec.md` v1.1 公式实现；外部大内容在事件 payload 中携带 `content_sha256`（§2.1）。

### 2.3 写入专用字段密钥的参考缺省值

- 【已核实】`tools/lib/kernel.py` 的 `DEFAULT_FIELD_HASH_KEYS` 提供开发缺省密钥
  （`eis-dev-field-hash-key`），生产必须经 `EIS_FIELD_HASH_KEYS` 注入（DRV-002）；
  参考内核不校验部署是否注入，也没有密钥服务/轮换编排。
- 现状：e2e 用例通过场景 `field_hash_keys` 显式钉住密钥，保证离线确定性。
- 影响：直接把参考缺省值用于生产等于无密钥隔离；coord Transit 当前也不能替代
  （HMAC 无用途化密钥与 key_id，轮换后存量散列不可复算，见 `docs/COORD-REQUIREMENTS.md` G-TR-3）。
- 使用者应对：部署侧注入用途密钥并纳入密钥管理；轮换按 DRV-005 密钥环窗口执行。

## 3. 审计

### 3.1 连续序列校验依赖部署侧锚表

- 【已核实】`05-audit-contract/audit.ddl` 只定义 append-only 审计表与 UPDATE/DELETE 拦截
  规则，不含锚表；链头锚表由落地实现自行引入（参考 `docs/LANDING-IAM.md` 的运行时物化）。
- 现状：规范保证链内自洽（序列连续、链接衔接、逐条重算），跨重启/截断的连续性以部署侧锚为准。
- 影响：若部署侧未维护锚，尾部截断无法由规范侧发现。
- 使用者应对：部署时建立链头锚表并定期核对/签名。

### 3.2 无外锚定参考实现

- 【已核实】`docs/ROADMAP.md` 将「链头锚定参考方案（按期签名并发布链头 hash）」列为
  v1.x 待办；当前 `05-audit-contract/verify.tool` 与 `tools/audit-verifier` 仅做链内校验。
- 现状：无开箱可用的外锚定实现。
- 影响：无法证明「链未被整体替换或回滚」。
- 使用者应对：按 ROADMAP 引入按期链头签名/发布，作为部署侧能力。

## 4. 演进

### 4.1 兼容性工具仅覆盖 JSON Schema（递归 diff），不含 OpenAPI/AsyncAPI

- 【已核实】`tools/compatibility-checker` 只对 data 域 JSON Schema 做递归 diff；
  `06-evolution-contract/compatibility.rules.yaml` 中的 `operation`/`event` 规则
  （API 删除/新增、参数类型变更、事件字段增删）无对应工具消费。
- 现状：操作/事件契约的兼容性无自动判定。
- 使用者应对：API/事件变更由人工评审，或另行构建 OpenAPI/AsyncAPI diff 工具。

### 4.2 迁移生成器输出需人工回填与评审

- 【已核实】`tools/migration-generator`：无 `default` 的必填新列生成可空 `ADD COLUMN` +
  回填提示，**不自动执行 `SET NOT NULL`**；类型变更以 `USING` 强转。
- 现状：生成物是草案，不是可直接在生产执行的最终迁移。
- 使用者应对：按 `06-evolution-contract/migration.template.sql` 走准备/双写/切换/清理，
  并对生成 SQL 人工评审与演练。

## 5. 企业基本面（未纳入核心契约）

以下能力在 `01`–`06` 契约中无对应元结构，属核心契约边界之外：

- 【已核实】多租户隔离：`01-data-contract/object.schema.json` 无 tenant/租户字段。
- 【已核实】outbox 投递语义：仅见于落地文档（`docs/LANDING-IAM.md` §3.4.2），非契约。
- 【已核实】状态机：对象契约无状态迁移约束，状态流转由内核按业务域手写。
- 【已核实】权限目录：`04-authz-contract` 定义主体/角色/绑定/代理，不含**全局**权限项目录；
  扩展级目录已由 ADR-0006 落地（`manifest.permissions`，`hr` 已声明 11 命令 + 2 读取权限，
  由 `contract-checker` 校验未声明引用）；核心通用查询 API 仍以部署边界保护，无域级 permission。
- 【已核实】数据分类与留存：无分类分级/留存期元数据。

- 影响：这些能力需实现方在扩展或实现层自行设计。
- 使用者应对：在扩展层补齐，并把差异记入自身合规文档。

## 6. 治理

- 【已核实】ADR 与 CI 无自动关联：`00-freeze/adr/` 与 `.github/workflows/ci.yml` 之间没有
  「契约变更必须附 ADR」的自动校验，PR 中的 `e2e-runner` 汇总行靠人工粘贴。
- 【已核实】用例计数的单一来源是 `tools/e2e-runner --all` 的输出；此前
  `README.md`/`CONTRIBUTING.md`/`CHANGELOG.md`/`docs/CONFORMANCE.md` 与实现不一致
  （43 vs 53），本次已对齐，但无自动防回归机制。
- 使用者应对：在 CI 中加入 ADR 链接检查；文档计数改为引用运行输出或加校验脚本。
