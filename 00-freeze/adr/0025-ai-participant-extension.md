# ADR-0025：AI 参与者交互契约扩展（`extensions/ai/`，EXPERIMENTAL v0.1.0）

- **状态**：Accepted（方向）+ v0.1.0-EXPERIMENTAL（实现范围）
- **日期**：2026-11-22
- **决策者**：核心维护者
- **关联**：issue #60（RFC 全文与规范锚点）；`extensions/ai/`；`docs/ORCHESTRATION-BOUNDARY.md`、`docs/ROADMAP.md`

## 1. 变更原因

核心六类契约假设参与者是人类或确定性系统。AI Agent 进入企业系统后，四个维度出现契约外行为：

1. **操作**：命令不区分来源，无法在策略检查点执行时拦截；
2. **授权**：委托链（on_behalf_of）通常只落在审计里，未在运行时验证；
3. **审计**：无法记录 Agent 依据什么推理、调用了哪些工具、是否经人工确认，审计链在 AI 节点断点；
4. **演进**：模型/提示词/工具集变更不触发行为回归评估，行为漂移无门禁。

issue #60 提出的方向与 `extensions/im/`（ADR-0023）的纪律一致：**只收窄契约面，不改核心**。
维护者结论：**接受该方向**，以 `extensions/ai/` v0.1.0-EXPERIMENTAL 落地最小可行范围；
推理摘要来源等开放问题保留为 v0.1.0 评审待决项，不阻塞首批工件。

## 2. 影响范围

- 契约：**核心六类契约无改动**；新增领域扩展 `extensions/ai/` 0.1.0（EXPERIMENTAL）
- 扩展：新增 `AiInteractionRecord` 对象 + 四份规则文件 + 不变量/黄金数据集工件
- 案例：无（组合进 `composition.yaml` 后才生效；不采用者零改动）
- 工具：无强制改动；策略检查点/回归门禁由接入方实现，按规则 id 归因

## 3. 兼容性分析

- 级别判定：**MINOR**（纯新增、可选、opt-in；不采用者无需修改任何代码）
- 破坏点：无
- 明确不做：不修改核心字段与 MUST/SHOULD/MAY 语句；不存储完整 CoT；不建立平行 Agent RBAC；
  不定义规划算法；不要求下游自造委托协议或 trace 格式

## 4. 迁移方案

1. 采用方在 `composition.yaml` 组合 `ai` 0.1.0；
2. 实现两个钩子：**运行时策略检查点**（AI-001..005、AI-101..104）与 **审计事件投影**
   （AI-201..205，映射到 OTel GenAI）；
3. 以 `artifacts/golden-dataset.yaml` 为种子补充领域用例，按 `artifacts/invariants.yaml` 设置门禁；
4. 无数据迁移（扩展对象与审计记录均为新表/新事件，不触碰既有对象）。

## 5. 回滚方案

从 `composition.yaml` 移除 `ai` 并删除 `extensions/ai/`；既有核心契约与数据不受影响。
审计事件可保留（只读历史），策略检查点关闭即恢复原有行为。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 扩展清单 | `extensions/ai/manifest.yaml` | id `ai`、`kind: domain`、`0.1.0`、`status: experimental` |
| 审计对象 | `extensions/ai/objects/ai-interaction-record.schema.json` | allOf 核心对象元结构；origin/委托链/工具/span 引用 |
| 操作规则 | `extensions/ai/rules/ai-operation.rules.yaml` | AI-001..005 |
| 授权规则 | `extensions/ai/rules/ai-authz.rules.yaml` | AI-101..104 |
| 审计规则 | `extensions/ai/rules/ai-audit.rules.yaml` | AI-201..205 |
| 演进规则 | `extensions/ai/rules/ai-evolution.rules.yaml` | AI-301..304 |
| 不变量 / 黄金数据集 | `extensions/ai/artifacts/*.yaml` | INV-AI-01..05、3 条种子用例 |
| 验收用例 | `extensions/ai/tests/ai.test.yaml` | 13 条可执行用例（static / schema-doc） |

## 7. 验收用例

- issue #60 最小可行范围三项均有对应规则与可执行用例（白名单/origin/人工批准；委托链/SoD/无平行 RBAC；
  三类事件/GenAI 映射/链闭合）；
- 演进门禁：工具集 breaking change 必须标记 BEHAVIOR_CHANGING（AI-304）；黄金数据集通过率低于基线
  不得标记 BEHAVIOR_COMPATIBLE（AI-302）；
- 全量：`python3 tools/e2e-runner --all` 全绿（用例数随本扩展增加）。
