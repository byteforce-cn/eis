# EIS 工具链（tools/）

工具是契约的实现；工具可替换（语言/算法自选），但**必须通过契约测试**。
本仓库提供 Python 参考实现（依赖：PyYAML、jsonschema），一键全量验证：

```bash
pip install pyyaml jsonschema
python3 tools/e2e-runner --all
```

## 工具清单（v1.0.0，已全部实现）

| 工具 | 用途 | 输入 | 输出 | 状态 |
|------|------|------|------|------|
| `schema-compiler` | Schema 编译 / 核心一致性检查 | 核心 + 扩展 JSON Schema | `build/ddl/*.ddl`、检查报告 | ✅ |
| `contract-checker` | 契约检查（结构/引用/命名/清单/组合） | Schema/OpenAPI/AsyncAPI/错误码 | 报告 | ✅ |
| `migration-generator` | 迁移 + 回滚生成 | 新旧 Schema | migration/rollback SQL | ✅ |
| `compatibility-checker` | 兼容性判定（MAJOR/MINOR/PATCH + 配套动作） | 新旧 Schema + 规则表 | 报告 | ✅ |
| `authz-resolver` | 时点/代理/SoD 授权解析 | 授权夹具 + 时点 | roles/permissions、`allowed+reason` | ✅ |
| `audit-verifier` | 审计验证（封装 `verify.tool`，含冻结向量） | 审计链文件/夹具目录 | 通过/失败 + 错误明细 | ✅ |
| `e2e-runner` | 端到端执行器（流水线 + 用例 + 场景） | `*.test.yaml`、`cases/*/scenarios` | 报告 | ✅ |
| `lib/kernel.py` | 参考内核（可执行规格） | 场景（YAML） | 命令流执行 + 断言 | ✅ |
| `relay` | Outbox/Inbox 投递状态机参考 + PG 语句模板 | 确定性自测 / `--print-sql` | 断言、SQL 模板 | ✅ |
| `ci/ddl-smoke.sql` | PostgreSQL 冒烟断言 | 已建库（core+扩展 DDL） | 断言通过/失败 | ✅ |
| `ci/outbox-smoke.sql` | Outbox/Inbox DDL 冒烟（唯一约束/状态机/租约/Inbox） | 已建 outbox 表 | 断言通过/失败 | ✅ |

## 常用命令

```bash
python3 tools/schema-compiler check                 # 核心 DDL ↔ Schema 一致性
python3 tools/schema-compiler compile --all         # 扩展 → build/ddl/*.ddl
python3 tools/contract-checker --verbose            # 契约全量检查
python3 tools/authz-resolver --self-test            # 授权语义（时点/代理/SoD）
python3 tools/compatibility-checker --old A --new B # 兼容性判定
python3 tools/migration-generator --old A --new B --table t
python3 tools/audit-verifier --vector               # 冻结测试向量
python3 tools/audit-verifier chain.json --json      # 链验证
python3 tools/e2e-runner --all                      # 全量（推荐入口）
python3 tools/lib/kernel.py                         # 内核自测
python3 tools/relay --self-test                     # Outbox/Inbox 状态机自测
python3 tools/relay --print-sql                     # PostgreSQL 投递语句模板
```

## 约定

- 退出码：`0` 通过 / `1` 判定失败 / `2` 未实现或用法错误
- 每个工具必须能消费纯文件输入（不依赖数据库），以便在 CI 中运行
- 判定权威：各契约目录的 `tests/*.test.yaml` 与 `06-evolution-contract/compatibility.rules.yaml`
- 全部工具提供 `--self-test`；审计链规范与参考实现（`05-audit-contract/verify.tool`）
  单源共享，冻结测试向量由 `audit-verifier --vector` 强制校验

## 参考内核（tools/lib/kernel.py）

把六份契约落成一段可运行代码：**命令受理（幂等）→ 规则（双时间轴/借贷平衡/
期间锁定/库存非负/禁止自审）→ 事件 → 哈希链审计 → 双时间轴对象（版本封口）→
读模型（余额/库存）**，并支持时点/双时间点查询与场景断言。

- 它是 seedj/server 的**行为基准**（Java 移植逐方法对齐，见 `docs/IMPLEMENTATION.md`）；
- 明确不做（生产实现需补齐）：持久化、并发控制、真实时钟、分区与索引优化。

## 工具链流程

```
开发阶段：
  Schema → schema-compiler → DDL + 一致性检查
  契约文件 → contract-checker → 报告
  Schema diff → migration-generator → 迁移 + 回滚
  Schema diff → compatibility-checker → MAJOR/MINOR/PATCH

测试阶段：
  *.test.yaml + 场景 → e2e-runner → 报告（内核执行）
  Audit Chain → audit-verifier → 通过/失败（含冻结向量）
  Principal + Time → authz-resolver → Roles / allowed+reason

部署阶段：
  core.ddl + build/ddl/*.ddl → PostgreSQL（CI 冒烟：tools/ci/ddl-smoke.sql）
  SQL 迁移/回滚 → 按 06 契约模板执行（双写 → 切换 → 清理）
```
