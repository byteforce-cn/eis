# 已知限制与规范缺口（Known Limitations）

> 本文件诚实记录 EIS Spec v1.0 参考实现的边界与规范中已知的缺口。每条给出【已核实】证据
> （文件:行号或工具行为），并按「现状 / 影响 / 使用者应对」说明。这些不是承诺清单，而是供
> 采用者评估风险与自行补齐的依据。
>
> 计数口径：`python3 tools/e2e-runner --all` 的实际输出为唯一来源（当前 `用例 99/99`）。

## 1. 时间契约

### 1.1 T-R009「有效区间不重叠」未在 DDL 落地

- 【已核实】`03-time-contract/temporal.ddl:33-40`：排他约束（`EXCLUDE USING gist`）与
  `uq_<table>_current` 唯一索引均标注为「可选（推荐）」且为注释，未成为可执行 DDL。
  规则定义见 `03-time-contract/temporal.rules.yaml:74`（T-R009，`enforced_by: ddl-exclusion-constraint`）。
- 现状：规范要求区间不重叠，参考 DDL 不强制。
- 影响：数据库层可写入互相重叠的有效区间。
- 使用者应对：生产建表时启用模板中的排他约束，并补充重叠拒绝的回归测试。

### 1.2 T-R011「迟到事件追加写入」与内核封口语义存在差异

- 【已核实】`03-time-contract/temporal.rules.yaml:88`（T-R011）要求迟到事实以新的系统时间
  追加写入、允许有效区间覆盖历史并以 `superseded` 留痕；而 `tools/lib/kernel.py` 的
  `_update_object`/`Kernel.advance` 仅处理时钟单调前进的常规封口，无迟到回填历史的路径。
- 现状：参考内核不对迟到写入建模。
- 影响：内核不能作为迟到场景的行为基准，相关用例只覆盖单调时钟。
- 使用者应对：需要迟到写入时，按 T-R011 自行实现并补齐可执行用例。

### 1.3 `as_of` 多版本重叠时静默择一

- 【已核实】`tools/lib/kernel.py` 的 `Kernel.as_of`：当多个版本同时匹配时返回
  `max(candidates, key=lambda r: r["version"])`，不报错。T-R008（`temporal.rules.yaml:67`）
  要求「至多返回一个版本」，其唯一性依赖 T-R009；而 T-R009 未强制（见 1.1）。
- 现状：重叠数据下查询结果取决于版本号大小，而非确定语义。
- 使用者应对：启用 1.1 的约束，使重叠在写入时即被拒绝。

## 2. 内核与 Schema

### 2.1 内核不执行扩展对象 Schema

- 【已核实】`tools/lib/kernel.py` 的命令处理器（`Kernel._handle` 及各 `_*` 方法）以手写
  字段校验实现，不加载 `extensions/**/objects/*.schema.json`，也不运行 JSON Schema 校验。
- 现状：对象 Schema 是契约文档与工具（`schema-compiler`/`contract-checker`）的校验对象，
  不是内核运行时的输入约束。
- 影响：内核可能接受契约 Schema 会拒绝的输入；内核行为不等价于 Schema 语义的完整实现。
- 使用者应对：实现侧必须自行执行对象 Schema 校验，不以内核接受作为合规依据。

### 2.2 审计链不覆盖事件 payload

- 【已核实】`tools/lib/kernel.py` 的 `_append_audit`：审计条目 `payload` 仅含
  `{"command_id", "event_ids"}`，不含事件正文。
- 现状：审计链保证「命令受理记录」的完整性与顺序，不承诺事件 payload 的不可篡改。
- 影响：事件内容被篡改时，链校验无法发现。
- 使用者应对：如需事件级不可篡改，把事件摘要纳入审计 payload 或另行锚定。

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
