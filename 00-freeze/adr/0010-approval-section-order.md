# ADR-0010：审批区块顺序语义（ApprovalSection.step_order）

- **状态**：Accepted
- **日期**：2026-10-17
- **决策者**：核心维护者
- **关联**：issue #18；`extensions/approval/objects/approval-section.schema.json`、`extensions/approval/objects/approval-request.schema.json`、`extensions/approval/rules/section-order.yaml`、`extensions/approval/handlers.py`、`extensions/approval/operations/*.openapi.yaml`、`cases/procurement/composition.yaml`

## 1. 变更原因

入职审批要求**分阶段确认**（先 HR、后财务）：消费方把阶段模型放在 coord workflow，但写路径命令走 EIS 内核 `approval.section.confirm.<owner>`。现状契约没有顺序语义：

- `ApprovalSection` 无阶段/顺序字段；
- `rules/block-readiness.yaml` 只声明「全部就绪 ⟺ 单据完成」，与顺序无关；
- `ApprovalRequest.section_ids` 数组顺序未声明业务含义（读侧只能注明「契约未声明区块次序」）。

结果：「HR 未确认前财务不能确认」只能靠界面隐藏按钮，直接调命令可绕过；消费方不得在本地自造未声明的顺序不变量（issue #18 引用的 AGENTS §3.2）。issue #18 要求二选一并在契约中写死口径，本 ADR 采用其中的「声明阶段/顺序」方案。

## 2. 影响范围

- 契约：approval 扩展（数据契约 `ApprovalSection` / `ApprovalRequest`，操作契约 submit/confirm/complete/resubmit，规则目录）
- 扩展版本：approval 1.0.1 → 1.1.0（MINOR，独立版本化）
- 案例：`cases/procurement/composition.yaml` 的 approval 版本锁定同步至 1.1.0
- 核心契约（01–06）与工具：不变

## 3. 兼容性分析

级别判定：**MINOR**。依据 `06-evolution-contract/compatibility.rules.yaml` 与 `00-freeze/version-policy.md`：

| 变更 | 判定 | 依据 |
|------|------|------|
| `ApprovalSection.step_order` 可选新增（`integer\|null`，≥0） | MINOR | 可选字段新增（`kind: compat` 用例锁定） |
| 新错误码 `APR-409-007`（前序未就绪） | MINOR | 新错误码新增（不改变既有含义） |
| 新规则 `section_order`（manifest 注册） | MINOR | 规则新增（不改既有规则语义） |
| `section_ids` description 明确「数组顺序 = 处理顺序」 | PATCH | 文档口径明确（此前未定义） |
| 确认/回写增加顺序前置 | 语义收紧 | 此前乱序确认属**未定义行为**；合规按序客户端不受影响；打回路径不受限 |

- 破坏点：无字段删除 / 类型变更 / 必填新增；简单模式与既有区块用例语义不变（既有 15 条回归全部通过）。
- 历史数据：`step_order` 可空、不回填；处理器在空值时按 `section_ids` 位置回退，等价于旧实现的提交顺序。
- 未采用方案 2（引擎阶段作为命令前置）：会把外部流程引擎状态引入契约判定域，超出 EIS 内核可验证范围；顺序作为契约内事实更可审计。

## 4. 迁移方案

- 生成：`tools/migration-generator --old tests/compat/approval-section-v1.schema.json --new objects/approval-section.schema.json --table approval_section` 产出 `ADD COLUMN step_order BIGINT;` 与回滚（`kind: migrate` 用例锁定片段）；
- 部署：既有部署在 approval 当前迁移基线后执行该可空列；新部署由 `tools/schema-compiler compile approval` 产物含列；
- 回填：不强制；消费方如需显式化，可按 `section_ids` 位置回填 `step_order`；
- 对账：顺序语义由处理器保证，回填不改变状态机。

## 5. 回滚方案

- 回滚代码提交即恢复旧行为（顺序门消失）；已写入的 `step_order` 列可保留（无害）或 DROP；
- 回滚 SQL：`ALTER TABLE approval_section DROP COLUMN IF EXISTS step_order;`（迁移生成器回滚片段）；
- 验证：`python3 tools/e2e-runner extensions/approval/tests/approval.test.yaml`。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 对象 Schema | `extensions/approval/objects/approval-section.schema.json`、`approval-request.schema.json` | `step_order` 可选字段；`section_ids` 顺序口径 |
| 操作契约 | `extensions/approval/operations/*.openapi.yaml`（7 份，1.1.0） | confirm/complete 顺序前置与 `APR-409-007`；submit 顺序写入；resubmit 保留序号 |
| 处理器 | `extensions/approval/handlers.py` | `_sections_in_order` / `_require_prerequisites`；submit 写 `step_order` |
| 规则 | `extensions/approval/rules/section-order.yaml` + `manifest.yaml` | 规则与不变量登记 |
| 用例 | `extensions/approval/tests/approval.test.yaml` | 乱序拒绝 / 不适用前序 / 重提重走 / compat / migrate |
| 兼容性夹具 | `extensions/approval/tests/compat/approval-section-v1.schema.json` | v1.0.1 基线 |
| 案例 | `cases/procurement/composition.yaml` | approval 版本锁定 1.1.0 |

## 7. 验收用例

- `python3 tools/e2e-runner extensions/approval/tests/approval.test.yaml`（20/20）；
- `python3 tools/e2e-runner --all`（131/131，用例新增 5 条）；
- `python3 tools/contract-checker`（144 通过 / 0 失败，含案例组合版本一致性）。
