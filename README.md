# EIS Spec v1.0 — 企业信息系统规范

> **EIS 规范 = 数据契约 + 操作契约 + 时间契约 + 授权契约 + 审计契约 + 演进契约。**

| 属性 | 值 |
|------|-----|
| 规范版本 | 1.0.0 |
| 冻结日期 | 2026-10-08 |
| 状态 | 核心已冻结（见 `00-freeze/core-freeze.md`）；**参考工具链已实现且全部验收可执行** |
| 许可 | Apache-2.0（见 `LICENSE`） |
| 原则 | 可实例化、可验证、可演进 |

**核心冻结，扩展独立，案例自由。**

## 快速开始

```bash
pip install pyyaml jsonschema
python3 tools/e2e-runner --all
# 预期：用例 100/100；场景 1/1；流水线 5/5；总判定：通过
```

- 审计链验证（可直接运行）：`05-audit-contract/verify.tool --self-test`
- 合规等级与自验命令：[docs/CONFORMANCE.md](docs/CONFORMANCE.md)
- 已知限制与规范缺口：[docs/KNOWN-LIMITATIONS.md](docs/KNOWN-LIMITATIONS.md)
- 实现落地（seedj / server 映射）：[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)
- 版本与规划：[docs/ROADMAP.md](docs/ROADMAP.md)、[CHANGELOG.md](CHANGELOG.md)

---

## 规范的本质

每条契约必须满足：

1. **可实例化**：契约以具体工件落地——数据契约经 `schema-compiler` 编译为 DDL，
   操作/事件契约以 OpenAPI/AsyncAPI 文件提供并由 `contract-checker` 校验
2. **可验证**：契约带有可执行测试用例，通过/失败有明确判定
3. **可演进**：能定义兼容性规则与迁移路径

这三条不是口号：`tools/` 提供参考实现，一条命令即可验证本仓库全部契约——
`python3 tools/e2e-runner --all`（100 条用例 + 端到端场景 + 工具链流水线；
DDL 由 CI 在 PostgreSQL 16 上冒烟断言）。

---

## 目录结构

```
eis/
├── README.md                        # 本文件
├── 00-freeze/                       # 冻结与治理
│   ├── core-freeze.md               #   核心冻结清单
│   ├── version-policy.md            #   三层版本政策
│   └── adr/                         #   架构决策记录
├── 01-data-contract/                # 数据契约
│   ├── object.schema.json           #   业务对象元结构
│   ├── event.schema.json            #   事件元结构
│   ├── command.schema.json          #   命令元结构
│   ├── view.schema.json             #   读模型元结构
│   ├── temporal.schema.json         #   双时间轴组件库
│   ├── write-only-fields.rules.yaml #   写入专用派生字段规则（DRV-*）
│   ├── core.ddl                     #   核心 DDL（生成物）
│   └── tests/                       #   数据契约验证
├── 02-operation-contract/           # 操作契约
│   ├── command.openapi.yaml         #   命令 API
│   ├── query.openapi.yaml           #   查询 API
│   ├── event.asyncapi.yaml          #   事件 API
│   ├── error-codes.yaml             #   错误码目录
│   └── tests/
├── 03-time-contract/                # 时间契约
│   ├── temporal.rules.yaml          #   双时间轴规则
│   ├── temporal.ddl                 #   时间字段 DDL 片段
│   ├── query-templates.sql          #   时点查询模板
│   ├── time-travel.api.yaml         #   时间旅行 API
│   └── tests/
├── 04-authz-contract/               # 授权契约
│   ├── principal.schema.json        #   主体
│   ├── role.schema.json             #   角色
│   ├── binding.schema.json          #   授权绑定
│   ├── proxy.schema.json            #   代理绑定
│   ├── resolution.api.yaml          #   授权解析 API（含属性上下文）
│   ├── attributes.api.yaml          #   主体属性快照 API（属主/失败口径）
│   ├── attribute.rules.yaml         #   属性规则 ATR-001..007
│   ├── sod.rules.yaml               #   职责分离规则
│   └── tests/
├── 05-audit-contract/               # 审计契约
│   ├── audit.schema.json            #   审计条目
│   ├── audit.ddl                    #   审计表 DDL（append-only）
│   ├── hash-chain.spec.md           #   哈希链规范（含规范化规则）
│   ├── verify.tool                  #   审计链验证工具（参考实现，可执行）
│   └── tests/
├── 06-evolution-contract/           # 演进契约
│   ├── compatibility.rules.yaml     #   兼容性规则
│   ├── migration.template.sql       #   迁移脚本模板
│   ├── rollback.template.sql        #   回滚脚本模板
│   └── tests/
├── extensions/                      # 领域扩展（独立版本化）
│   ├── accounting/                  #   会计域 v1.0.0
│   ├── inventory/                   #   库存域 v1.0.0
│   ├── approval/                    #   审批域 v1.0.1（含区块级流转）
│   └── hr/                          #   人力资源域 v1.0.0（组织/岗位/员工/任职/供给）
├── cases/                           # 应用案例（独立版本化）
│   └── procurement/                 #   采购系统（端到端试点）
├── tools/                           # 工具链（参考实现，Python）
│   ├── schema-compiler              #   Schema → DDL；核心一致性检查（已实现）
│   ├── contract-checker             #   契约结构/引用/命名全量检查（已实现）
│   ├── migration-generator          #   迁移 + 回滚 SQL 生成（已实现）
│   ├── compatibility-checker        #   兼容性判定 MAJOR/MINOR/PATCH（已实现）
│   ├── authz-resolver               #   时点/代理/SoD 授权解析（已实现）
│   ├── audit-verifier               #   审计链验证（封装 verify.tool，含冻结向量）
│   ├── e2e-runner                   #   用例与场景执行器（流水线入口）
│   ├── lib/kernel.py                #   参考内核：可执行语义体（命令→事件→链→双时间轴）
│   └── ci/ddl-smoke.sql             #   PostgreSQL 冒烟断言（CI 使用）
├── docs/                            # IMPLEMENTATION / CONFORMANCE / ROADMAP
├── .github/workflows/ci.yml         # CI：规范校验 + PostgreSQL 16 DDL 冒烟
├── CHANGELOG.md / CONTRIBUTING.md / SECURITY.md / CODE_OF_CONDUCT.md
├── LICENSE / NOTICE                 # Apache-2.0
└── acceptance.yaml                  # 验收标准（core 项已可执行化；pilot 项为人工签署）
```

---

## 建议阅读顺序

1. `00-freeze/core-freeze.md` — 什么被冻结、变更要付出什么代价
2. `01` → `06` — 六份契约（每份含可执行 `tests/` 用例）
3. `extensions/accounting/` — 领域扩展的完整示例（含用例）
4. `cases/procurement/` — 扩展组合与可执行端到端场景
5. `tools/lib/kernel.py` — 参考内核：把六份契约读成一段可运行代码
6. `docs/IMPLEMENTATION.md` — 如何落到 seedj 与 server
7. `acceptance.yaml` 与 `docs/CONFORMANCE.md` — 验收与合规等级

---

## 变更纪律

> **每一次修改，必须对应一个可执行工件或一个验收用例。否则拒绝修改。**

变更流程（详见 `00-freeze/adr/README.md`）：

```
变更提案 → ADR → 可执行工件 → 验证 → 合并
```

- 核心契约（数据/操作/时间/授权/审计/演进的元结构）：冻结，修改须走 ADR 且按 MAJOR/MINOR 规则升版。
- 领域扩展：独立版本化，不得修改核心。
- 应用案例：自由组合扩展，不得修改核心与扩展。

---

## 当前可执行状态

| 工件 | 状态 |
|------|------|
| 契约 Schema / OpenAPI / AsyncAPI / DDL / 测试用例 | 已实例化；100 条用例全部可执行 |
| `tools/*` 工具链（8 件） | ✅ 参考实现全部可用（Python，仅 PyYAML/jsonschema 依赖） |
| 参考内核 `tools/lib/kernel.py` | ✅ 可执行端到端语义（命令→规则→事件→审计链→双时间轴） |
| `05-audit-contract/verify.tool` | ✅ 冻结测试向量经实现验证一致 |
| DDL（核心 + 生成扩展） | ✅ PostgreSQL 16 冒烟通过（CI 每提交执行） |
| 端到端试点 `cases/procurement` | ✅ 可执行场景：7 步 / 12 断言 / 6 条审计链 |
