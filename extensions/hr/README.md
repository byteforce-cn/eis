# extensions/hr — 人力资源域扩展（v1.0.0）

人事事实的唯一来源：向身份域供给登录用户（建号/启用/禁用），向授权判定与审批提供
组织/岗位/职级/汇报链上下文。双时间轴对象，独立版本化，只依赖核心 `core_version: 1.0.0`。

## 1. 对象

| 对象 | 说明 | 关键不变量 |
|------|------|-----------|
| `Employee` | 员工主数据；`employee_no` 服务端生成；`id_number_hash` 写入专用 | 工号唯一；证件散列在非终态唯一；在职必有主岗 |
| `OrganizationUnit` | 组织单元树（company/department/team） | 上级链无环；子级组织必须挂在启用组织下 |
| `Position` | 岗位；`reports_to_position_id` 汇报链 | 汇报链无环；必须属于启用组织 |
| `Assignment` | 员工-岗位任职（有效期段，`is_primary` 主岗） | 同一员工至多一个有效主岗；组织与岗位一致 |
| `ProvisioningTask` | 向身份域的供给任务（建号/启用/禁用） | 动作与员工状态匹配；由 system 主体回写 |

## 2. 员工状态机

```
                 hr.employee.cancel
pending_onboarding ────────────────► cancelled
      │ hr.employee.activate
      ▼（需已有有效主岗）
   active ──── hr.assignment.end（结束主岗）────► terminated
```

四态与材料齐全度/审批节点解耦：证明材料与单据流转属审批域（`extensions/approval`），不进员工状态。

## 3. 命令

| 命令 | 说明 | 主要错误码 |
|------|------|-----------|
| `hr.org.unit.define` | 定义组织单元（编码唯一、上级存在） | HR-409-001 / HR-404-001 |
| `hr.org.unit.update` | 更新名称/上级/状态（组织树无环） | HR-409-005 |
| `hr.position.define` | 定义岗位（编码唯一、组织启用） | HR-409-001 / HR-409-006 |
| `hr.position.update` | 更新岗位/汇报链（无环） | HR-409-005 |
| `hr.employee.create` | 建档；服务端生成工号；证件散列防重 | HR-409-002 |
| `hr.employee.update` | 更新姓名/联系方式/主组织（终态不可更新） | HR-403-001 |
| `hr.employee.activate` | 转在职（必须有有效主岗） | HR-409-004 |
| `hr.employee.cancel` | 取消入职（仅待入职） | HR-403-001 |
| `hr.assignment.assign` | 分配任职（主岗唯一、岗位/组织启用） | HR-409-003 / HR-409-006 |
| `hr.assignment.end` | 结束任职；结束主岗令在职员工转终态 | HR-403-001 |
| `hr.provisioning.run` | system 主体回写供给任务（动作与状态匹配） | HR-409-006 |

命令模式（OpenAPI）与错误响应见 `operations/*.openapi.yaml`。

## 4. 敏感字段

- `Employee.id_number_hash`：证件号的 HMAC-SHA256 散列，`writeOnly`；
  命令记录经 `handlers.py` 的 `SENSITIVE_FIELDS` 声明脱敏（幂等指纹仍基于原文）。
- 读投影不得输出 `id_number_hash`（对齐 `Credential.secret_hash` 先例）。

## 5. 规则与不变量

- `rules/employee-no-unique.yaml`：工号服务端生成、跳过已占用，DDL 唯一索引兜底；
- `rules/id-document-dedup.yaml`：证件散列在 `pending_onboarding/active` 唯一，终态允许返聘；
- `rules/reporting-acyclic.yaml`：组织树与岗位汇报链无环；
- `rules/position-org-consistent.yaml`：岗位/任职组织必须存在且启用，任职组织由岗位派生；
- `rules/primary-assignment-unique.yaml`：主岗唯一、在职必有主岗、结束主岗转终态。

不变量清单见 `manifest.yaml` 的 `invariants`。

## 6. 迁移

- `migrations/V201__hr_initial.sql`：初始迁移（与 `tools/schema-compiler compile hr` 产物对齐）；
- `migrations/V201__hr_initial.rollback.sql`：回滚（逆序 DROP）。

CI 在 PostgreSQL 16 上执行 `build/ddl/hr.ddl` 冒烟；生产部署以迁移脚本为准并纳入版本表。

## 7. 可执行用例

```bash
python3 tools/e2e-runner extensions/hr/tests/hr.test.yaml
```

用例覆盖：全链路上岗、工号生成、组织/岗位唯一与无环、主岗唯一、在职必有主岗、
证件防重与返聘、敏感字段脱敏与幂等、结束主岗级联终态、供给任务状态匹配。

处理器实现见 `handlers.py`（通过内核注册机制加载，无需修改内核源码，见 `extensions/README.md` §6）。
