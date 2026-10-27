# 贡献指南（Contributing）

感谢参与 EIS Spec。本仓库遵循 **契约先行、无工件不合并** 的治理原则。

## 1. 快速开始

```bash
# 环境：Python 3.10+（推荐 3.12）
pip install pyyaml jsonschema

# 一键跑全部：流水线（契约检查/编译/审计自测）+ 全部用例 + 试点场景
python3 tools/e2e-runner --all
```

预期输出：`用例 155/155；场景 1/1；流水线 5/5；总判定：通过`。

## 2. 贡献类型与流程

| 类型 | 流程 | 备注 |
|------|------|------|
| 缺陷修复（工具/文档/测试） | 直接提 PR | 需通过 `e2e-runner --all` |
| **契约变更**（数据/操作/时间/授权/审计/演进） | ADR → 可执行工件 → 验证 → PR | 模板 `00-freeze/adr/template.md`；兼容性判定依据 `06-evolution-contract/compatibility.rules.yaml`；无工件的变更一律拒绝 |
| 新增领域扩展 | `extensions/{domain}/` 按结构提交 + manifest + handlers + 用例 | 不得修改核心契约；错误码使用自有前缀（如 `Xxx-400-001`） |
| 新增应用案例 | `cases/{case}/`（composition + scenarios） | 场景须可由 `tools/e2e-runner` 执行 |
| 新增测试 | 按 `tools/e2e-runner` 的 kind 语义编写 | 测试必须可执行、可复现（确定性时钟/数据） |

## 3. 硬性要求

1. **可执行**：新增/修改的用例必须在 `tools/e2e-runner --all` 下通过；
2. **可验证**：契约变更必须附带工件（Schema/DDL/测试/工具变更清单）；
3. **可演进**：破坏性变更必须给出迁移 + 回滚 + 对账路径（模板见 `06-evolution-contract/`）；
4. **确定性**：测试不得依赖真实时钟、网络与外部数据库（DDL 冒烟由 CI 的 PostgreSQL 任务覆盖）；
5. **命名**：命令/事件类型形如 `^[a-z][a-z0-9_.]*$`；核心错误码 `EIS-` 前缀不可占用；
6. **扩展自包含**：命令处理器注册于 `extensions/{domain}/handlers.py`（见 `extensions/README.md` §6），
   新增扩展不得要求修改内核或其他工具源码。

## 4. 提交规范

- Commit message 建议：`feat: ...` / `fix: ...` / `docs: ...` / `test: ...` / `chore: ...`；
- 一个 PR 聚焦一件事；契约变更 PR 必须链接对应 ADR；
- PR 描述中附上 `e2e-runner` 的汇总行。

## 5. AI 辅助贡献

允许并鼓励使用 AI 编码代理（Claude Code / Codex / Pi / OpenCode 等）生成契约与代码，
但必须满足：

1. **契约变更走 ADR**：与人工贡献同一流程（§2）；AI 生成不是跳过 ADR 的理由；
2. **生成物必须通过对应验证**：
   - 契约：`python3 tools/contract-checker --file <file>`（迭代）/ `python3 tools/contract-checker`（落地后）；
   - 兼容性：`python3 tools/compatibility-checker --standalone`，按 PATCH/MINOR/MAJOR 落实配套动作；
   - 审计：`python3 tools/audit-verifier --vector` 与 `python3 05-audit-contract/verify.tool --self-test`；
   - 独立验证器：`hash-chain.spec.md` §3.1/§3.2 冻结向量全过，不得阅读 Python 参考实现源码；
   - 全量：`python3 tools/e2e-runner --all` 全绿；
3. **PR 注明 AI 工具与版本**（如「Claude Code 2.x + Opus 4.x」），便于复现与审计；
4. **不得提交未通过验证的产物**，也不得把验证命令改成永远通过。

技能定义（Agent Skills 规范）见 `skills/`，各工具接线与失败反馈闭环见 [`docs/AI-INTEGRATION.md`](docs/AI-INTEGRATION.md)。

## 6. 行为准则与许可

- 参与即表示同意 [行为准则](CODE_OF_CONDUCT.md)；
- 提交的代码与文档按 [Apache-2.0](LICENSE) 授权。

## 7. 目录速查

```
00-freeze/                 冻结与治理（ADR 在这里）
01..06-*-contract/         六份契约（含 tests/）
extensions/                领域扩展（独立版本化）
cases/                     应用案例（组合与场景）
skills/                    Agent Skills（AI 代理技能索引见 skills/README.md）
tools/                     工具链（参考实现）与参考内核（tools/lib/kernel.py）
tools/build-spec-pack      AI 规格包生成（canonical + pnpm 包形态）与 MANIFEST 校验（issue #12）
tools/ci/ddl-smoke.sql     PostgreSQL 冒烟（CI 使用）
docs/                      落地映射 / 合规等级 / 路线图 / AI 集成指南（docs/AI-INTEGRATION.md）
```
