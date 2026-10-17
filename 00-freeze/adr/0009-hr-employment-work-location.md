# ADR-0009：HR 扩展 Employee 增加雇佣类型/工作地点（加法演进）

- **状态**：Accepted
- **日期**：2026-10-17
- **决策者**：核心维护者
- **关联**：issue #13；`extensions/hr/objects/employee.schema.json`、`extensions/hr/operations/employee-create.openapi.yaml`、`extensions/hr/operations/employee-update.openapi.yaml`、`extensions/hr/handlers.py`、`extensions/hr/migrations/V202__hr_employee_employment_fields.sql`

## 1. 变更原因

HR 招聘 / 入职场景需要区分**雇佣类型**（全职 / 兼职 / 实习 / 劳务）与**工作地点**（办公地 / 城市）：

- 名册需要「雇佣类型」「工作地点」两列（spa 走查 §3：设计 10 列、实现 7 列）；
- 新建员工表单需要这两个字段（走查 §4.3 C-1）；单据详情员工摘要条需要它们（走查 §4.4 E-4）。

`extensions/hr` 的 `Employee` 契约（v1.0.0）没有这两个字段；消费方约定（issue #13 所引 AGENTS §3.2）不得本地自造字段，故由契约加法演进提供。

## 2. 影响范围

- 契约：hr 扩展（数据契约 `Employee`、操作契约 `hr.employee.create` / `hr.employee.update`）
- 扩展版本：hr 1.0.0 → 1.1.0（MINOR，独立版本化）
- 核心契约（01–06）：不变
- 案例：无（`cases/procurement` 不引用 hr）
- 工具：`tools/migration-generator` 补 `allOf` 扩展对象 Schema 支持（使真实 Employee 契约的迁移可由工具生成）；`tools/lib/kernel.py` 的 `object-field` 断言支持 `read_projection`

## 3. 兼容性分析

级别判定：**MINOR**。依据 `06-evolution-contract/compatibility.rules.yaml`：

| 变更 | 判定 | 依据 |
|------|------|------|
| `Employee.employment_type` 可选新增（`string\|null`，受控枚举 4 值） | MINOR | 可选字段新增 |
| `Employee.work_location` 可选新增（`string\|null`，非空） | MINOR | 可选字段新增 |
| `hr.employee.create/update` 载荷可选新增两字段 | MINOR | 操作载荷可选字段新增（不改变既有必填与语义） |
| `migration-generator` allOf 支持 | PATCH | 工具修复（平铺 Schema 行为不变，既有自测 / 用例锁定） |
| kernel `object-field` 断言 `read_projection` 选项 | PATCH | 测试工具加法（默认行为不变） |

- 破坏点：无；旧客户端不带两字段时行为与 v1.0.0 一致（均落 NULL）。
- 空值语义：缺省与显式 null 等价；`employment_type` 仅接受 `full_time` / `part_time` / `intern` / `contract`；`work_location` 为非空字符串。
- 消费方提示：读投影与属性快照需按本契约回读新字段；本仓库以 `read_projection` 断言锁定契约面，服务侧落地由对应仓库跟进。

## 4. 迁移方案

- `V202__hr_employee_employment_fields.sql`：两列均 `ADD COLUMN`（可空；历史行 NULL，无需回填），并补受控枚举约束 `ck_hr_employee_employment_type`；
- 新部署：`tools/schema-compiler compile hr` 产物（`build/ddl/hr.ddl`）已含两列与约束；既有部署在 V201 之后执行 V202；
- 工具验证：`tools/migration-generator --old <v1 夹具> --new employee.schema.json --table hr_employee` 输出含两列与回滚（`kind: migrate` 用例锁定）；
- 对账：无数据迁移，无一致性问题。

## 5. 回滚方案

- `V202__hr_employee_employment_fields.rollback.sql`：先 DROP 约束，再 DROP 两列（新增列无下游依赖，丢弃新列数据可接受）；
- 回滚验证：`python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml`。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 对象 Schema | `extensions/hr/objects/employee.schema.json` | 两字段可选新增（`$id` 仍为 `/v1`） |
| 操作契约 | `extensions/hr/operations/employee-create.openapi.yaml`、`employee-update.openapi.yaml` | 载荷可选新增两字段；`info.version` → 1.1.0 |
| 处理器 | `extensions/hr/handlers.py` | create/update 校验并落库；非法值 `HR-400-001` |
| 迁移 | `extensions/hr/migrations/V202__hr_employee_employment_fields.sql`（+ rollback） | 可空列 + 受控枚举约束 |
| 兼容性夹具 | `extensions/hr/tests/compat/employee-v1.schema.json` | v1.0.0 基线，供 compat / migrate 判定 |
| 用例 | `extensions/hr/tests/hr.test.yaml` | 2 scenario + 2 static + 1 compat + 1 migrate |
| 工具 | `tools/migration-generator`（allOf）、`tools/lib/kernel.py`（read_projection 断言） | 支撑用例与后续扩展 |
| 清单元数据 | `extensions/hr/manifest.yaml` | version 1.1.0；`hr.employee.read` 描述补两字段 |

## 7. 验收用例

- `python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml`（30/30）：写入 / 更新 / 读投影回读、缺省 null、非法值拒绝、MINOR 判定、迁移可生成、V202 静态覆盖；
- `python3 tools/migration-generator --self-test`、`python3 tools/e2e-runner 06-evolution-contract/tests/evolution-contract.test.yaml`（8/8）；
- `python3 tools/e2e-runner --all`（全绿，无回归）。
