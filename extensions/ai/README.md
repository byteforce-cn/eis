# extensions/ai — AI 参与者交互契约（EXPERIMENTAL v0.1.0）

> 状态：**EXPERIMENTAL**（ADR-0025 / issue #60）。至少一个 minor 周期内保持 experimental；
> 期间只做收窄与勘误，不做语义扩张。

EIS 核心六类契约假设参与者是**人类用户或确定性系统**。AI Agent 带来概率性输出、工具调用与
自主规划，缺口集中在四个维度：来源不可区分、委托链只在审计里、审计链在 AI 节点断点、模型/提示词
变更不触发行为回归。本扩展只回答一个问题：**当 Agent 行动时，它必须遵守哪些契约规则**。

它不修改核心、不建立平行的 Agent RBAC、不定义推理算法，也不替代
`docs/ORCHESTRATION-BOUNDARY.md` 的外置编排立场。

## 1. 结构（遵循 extensions/ 冻结结构）

```text
extensions/ai/
├── manifest.yaml                       # id: ai / kind: domain / version 0.1.0 / status: experimental
├── objects/ai-interaction-record.schema.json   # 审计记录（AI_TOOL_CALL / RESULT / HUMAN_APPROVAL）
├── rules/
│   ├── ai-operation.rules.yaml         # AI-001..005 白名单 / origin / 运行时检查点 / 人工批准
│   ├── ai-authz.rules.yaml             # AI-101..104 委托链完整性 / 最小范围 / SoD / 无平行 RBAC
│   ├── ai-audit.rules.yaml             # AI-201..205 三类事件 / GenAI 映射 / span 引用 / 链闭合
│   └── ai-evolution.rules.yaml         # AI-301..304 回归门禁 / 兼容判定 / 轨迹不变量 / breaking
├── artifacts/
│   ├── invariants.yaml                 # INV-AI-01..05（随扩展版本化）
│   └── golden-dataset.yaml             # 3 条种子用例（接入方只能追加）
└── tests/ai.test.yaml                  # 可执行验收用例（e2e-runner）
```

## 2. 最小可行范围（v0.1.0，三者不可拆分）

1. **操作**：来源标记 + 白名单 + 运行时策略检查点（AI-001..005）；
2. **审计**：三类 AI 审计事件 + GenAI 语义映射声明 + `on_behalf_of` 引用完整性（AI-201..205）；
3. **演进**：行为基线回归门禁作为配套工件要求，黄金数据集/阈值/不变量随扩展版本化（AI-301..304）。

拆分任何一项都会导致：白名单无法执行、委托链无法验证、或演进标签不可执行。

## 3. 审计字段 → OpenTelemetry GenAI 语义映射（AI-202）

| AiInteractionRecord | OTel GenAI（工具调用 span） | 说明 |
| --- | --- | --- |
| `tool.name` | `gen_ai.tool.name` | 工具/命令名 |
| `tool.args_sha256` | `gen_ai.tool.call.arguments` 的摘要 | 只存哈希，参数原文不入审计 |
| `outcome` | span status（`ok` / `error`） | `denied` / `pending_approval` 映射为 error + 事件 |
| `model.id` / `model.version` | `gen_ai.request.model` / `gen_ai.response.model` | 模型标识 |
| `on_behalf_of.delegation_ref` | `gen_ai.agent.id` + 自定义 `eis.on_behalf_of` | 委托链引用（外部身份标准） |
| `otel_span_ref` | `trace_id` / `span_id` | 双向跳转锚点 |
| `reasoning_summary_sha256` | —（并列存在，不替代 span） | 结构化摘要哈希 |

EIS 不重新定义 trace 格式；采集与传输由企业既有 OTel 基础设施承担。

## 4. 待决项（v0.1.0 评审中确定）

- **推理摘要的来源**：由 Agent 自报，还是由执行器旁路生成？旁路生成时，摘要与工具调用的一致性
  验证责任归属哪一方？——与 NIST AI 600-1「归因到人类身份」直接相关。
- **黄金数据集的领域边界**：v0.1.0 只给形状与 3 条种子用例，接入方按领域补充；
  跨领域共享数据集的治理方式（谁批准基线变更）待定。

## 5. 验证

```bash
python3 tools/contract-checker
python3 tools/e2e-runner extensions/ai/tests/ai.test.yaml
python3 tools/e2e-runner --all
```
