# 落地实现指南（Implementation Guide）

> 本规范指导两类实现：**seedj**（Java 基础类库，实现契约的内核能力）与
> **server**（业务系统，按扩展契约交付应用）。本文给出契约 → 实现的映射、
> 职责边界与验收方式。

## 0. 三层关系

```
eis（本仓库）     规范与参考实现（Python）——唯一语义权威 + 可执行验收
   │  约束
   ▼
seedj（Java）     契约内核：双时间轴数据、命令运行时、审计链、as_of 授权
   │  复用
   ▼
server（Java）    业务应用：按 extensions/* 组装领域服务（如 ims-finance）
```

**一致性判定**：实现是否合规，以本仓库工具链为准：
`python3 tools/e2e-runner --all`（规范侧）+ 各实现的契约定向测试（实现侧）。
Java 端行为必须与参考内核（`tools/lib/kernel.py`）语义一致——内核是"可执行规格"。

## 1. 契约 → seedj 模块映射

| 契约 | 规范工件（权威） | seedj 落点 | 实现要点 |
|------|------------------|------------|----------|
| 数据契约 | `01-data-contract/*` | `common/data-core`（实体基类；扩展双时间轴字段） | 元字段 10 项落实体基类；UUIDv7 生成器；乐观锁 `version`；JSONB 字段映射 |
| 操作契约 | `02-operation-contract/*` | `starter-web` + `common/web-core` + `starter-json` | 命令端点运行时：幂等键拦截（`command` 表/缓存）、202/400/403/409 语义、错误码对齐 `error-codes.yaml`、`ApiResponse` 承载 `code/message` |
| 时间契约 | `03-time-contract/*` | 建议新增 `starter-data-temporal` | 实体双时间轴 + 时点查询（`as_of`/`recorded_as_of`）SQL/拦截器；append-only 写入助手（封口旧版本、追加新版本） |
| 授权契约 | `04-authz-contract/*` | `starter-resource`（身份进上下文）+ 建议新增 `client-eis-authz` | JWT → principal 映射；调用 `/resolve`、`/check`（携带 `as_of`）；SoD 拒绝映射到 `EIS-403-001` + `reason_code=SOD-xxx` |
| 审计契约 | `05-audit-contract/*` | 建议新增 `starter-eis-audit`（可置于 `starter/` 家族） | 哈希链写入（命令受理后追加）；`verify.tool` 的 Java 移植必须通过冻结测试向量；链头锚定策略（部署侧） |
| 演进契约 | `06-evolution-contract/*` | 构建与发布流程（非运行时模块） | Schema/DDL diff 门禁：`tools/compatibility-checker --fail-on MAJOR`；迁移脚本产出走 `migration-generator` 模板；发布流程挂接 ADR 要求 |

**建议的 seedj 内核构件**（命名可按 seedj 规范调整）：

```
starter-eis-core      命令运行时（幂等、规则链、事件发布）+ 对象存储抽象（双时间轴）
starter-eis-audit     哈希链审计（写入 + 验证 + 锚定接口）
starter-eis-authz     授权解析客户端与本地缓存（as_of 语义）
starter-eis-temporal  时点查询支持（SQL 模板 → MyBatis/Spring Data 适配）
```

> 参考内核 `tools/lib/kernel.py` 是这四个构件的**行为基准**：Java 移植时逐方法对齐
> （受理→规则→事件→审计→版本封口的顺序、拒绝码、时间轴边界）。

### 写入专用派生字段的密钥服务映射（ADR-0005 / DRV-*）

- 规范路径：命令载荷携带原始值（`writeOnly`），字段属主域服务在写路径派生后落库，
  原始值与派生值在读投影/命令记录/日志剔除；密钥由部署侧注入（参考内核环境变量
  `EIS_FIELD_HASH_KEYS`，逗号分隔、首为主），轮换按密钥环窗口执行（DRV-005）。
- seedj/server：由 `starter-eis-core` 落派生与投影剔除；密钥从环境/密钥注入读取，不落仓、不入镜像、
  不进浏览器或通用 BFF。
- coord Transit（**可选映射，非 v1 默认**）：`Transit/HmacSign` 可充当受信密钥服务，但当前为
  单实例单 HMAC 密钥、签名无 key_id、历史材料不参与 HMAC（KEK 轮换后存量散列不可复算），
  暂不满足 DRV-002/DRV-005；前置需求见 `docs/COORD-REQUIREMENTS.md` G-TR-3。

## 2. 扩展 → server 应用映射

> server 现有项目已全部删除（仅保留 `docker/`），重建时按下表对应。

| 扩展（契约） | 建议 server 模块 | 说明 |
|--------------|------------------|------|
| `extensions/accounting` | `ims-finance` | 凭证过账/关账；借贷平衡与期间锁定为硬校验 |
| `extensions/inventory` | `ims-inventory`（或并入相关业务域） | 出入库/库存余额；非负不变量 |
| `extensions/approval` | `ims-approval` | 审批申请/决定/区块；禁止自审；区块属主权限与重提重确认 |
| `extensions/hr` | `ims-hr`（人事主数据） | 组织/岗位/员工/任职/供给；属性权威属主（ADR-0004） |
| `cases/procurement` | `ims-procurement`（试点） | 组合三扩展的端到端系统，直接对齐 `scenarios/procure-to-pay.yaml` |

**应用侧纪律**：

1. 每个 `ims-*` 只实现**扩展契约**声明的对象/操作/规则，不自定义核心语义；
2. 扩展的 `manifest.yaml` 是模块清单来源（对象表、命令、规则、不变量）；
3. 应用不直接写库表：写路径统一走命令运行时（幂等 + 审计 + 版本封口）；
4. 读路径统一支持 `as_of` / `recorded_as_of`（复用 `starter-eis-temporal`）；
5. `docker/` 保留的 coord 编排继续作为基础设施（注册/配置/协调）。

## 3. 落地路线（建议）

| 阶段 | 内容 | 验收 |
|------|------|------|
| P1 | seedj `eis-core` + `eis-audit`（对象存储、命令运行时、审计链） | Java 侧：哈希向量一致 + 内核对齐用例通过；规范侧 `e2e-runner --all` 全绿 |
| P2 | seedj `eis-temporal` + `eis-authz`；`starter-data-mybatis` 适配 | 时点查询/授权解析用例（移植 03/04 契约 tests） |
| P3 | `ims-finance`（accounting 首个应用） | 复用 `extensions/accounting/tests/*` 的等价 Java 测试 |
| P4 | `ims-inventory` + `ims-approval` + `ims-procurement` 试点 | 端到端对齐 `cases/procurement/scenarios/procure-to-pay.yaml`（7 步 12 断言） |

## 4. 验收挂钩（哪条契约由谁证明）

| 验收项（`acceptance.yaml`） | 规范侧证明 | 实现侧证明（seedj/server） |
|------------------------------|------------|------------------------------|
| DDL 生成 / Schema 一致 | `schema-compiler check` + CI PostgreSQL 冒烟 | Java 实体与 DDL 对齐测试 |
| 时点查询 / 时间旅行 | `03` 契约 scenario 用例 + DDL 冒烟 | `eis-temporal` 定向测试 |
| 授权解析 / SoD | `tools/authz-resolver --self-test` + `04` 用例 | `eis-authz` 客户端测试 |
| 审计链 / 篡改检测 | 冻结向量 + `05` 夹具用例 | Java 链实现跑同一向量 |
| 迁移 / 回滚 | `06` compat+migrate 用例 | Flyway/Liquibase 脚本接入门禁 |
| 端到端 | `cases/procurement` 场景 | `ims-procurement` 端到端测试 |
