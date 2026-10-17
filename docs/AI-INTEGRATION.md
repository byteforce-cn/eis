# AI 编码代理集成

EIS 的规范结构（Schema 约束 + 可执行验证）适合交给 AI 编码代理完成「读规范 → 生成契约/代码 →
验证」的组装工作。本文件说明如何把规范与技能接到各工具，以及**不可跳过的验证约束**。

## 1. 获取规范

- **规格包（推荐）**：`python3 tools/build-spec-pack --out dist/eis-spec-pack`
  （生成物不提交；包内含六类契约、冻结向量、参考工具、`MANIFEST.json` 与面向 AI 的 `README.md`）。
- **pnpm/npm 包形态**：`python3 tools/build-spec-pack --npm-out dist/npm`（`@byteforce/eis-spec`，含零依赖 CLI）
  → `cd dist/npm && pnpm pack`。安装后 `pnpm exec eis-spec manifest` / `pnpm exec eis-spec verify`
  （完整性 + 冻结向量自检）。CI 以 **staged release** 发布：`npm stage publish` 暂存（tag `v*` → `latest`、
  预发布 tag → `next`、手动 → `nightly`），维护者在 npmjs.com 的 **Staged Packages** 批准后公开
  （`.github/workflows/release-npm.yml`，`NPM_TOKEN` + provenance）；发布前可用本地 tarball。
- **直接使用本仓库**：契约目录 `01-data-contract/` … `06-evolution-contract/` + 本文件与 `skills/`。

## 2. Agent Skills（`skills/`）

| 技能 | 何时使用 | 验证命令（在仓库/规格包根目录执行） |
|------|----------|-----------------------------------|
| `eis-create-contract` | 从需求生成/扩展数据与操作契约 | `python3 tools/contract-checker --file <file>`；落地后 `python3 tools/contract-checker` |
| `eis-verify-contract` | 判定契约变更兼容性并按级别落实 | `python3 tools/compatibility-checker --old A --new B --standalone` |
| `eis-generate-audit` | 生成含 `payload_digest` 与哈希链的审计写入 | `python3 tools/audit-verifier --vector`；`python3 05-audit-contract/verify.tool --self-test` |
| `eis-generate-verifier` | 用目标语言独立实现审计链验证器 | `python3 05-audit-contract/verify.tool --self-test`（§3.1/§3.2 向量） |

技能遵循 [Agent Skills 规范](https://agentskills.io/specification)（`SKILL.md` + YAML frontmatter，
`name` / `description`）；索引见 [`skills/README.md`](../skills/README.md)。

## 3. 通用约束（必须）

1. **生成契约后**：先 `python3 tools/contract-checker --file <file>` 迭代，落地后跑仓库级
   `python3 tools/contract-checker`（含清单引用、权限目录、组合校验）。
2. **契约变更**：一律走 ADR 流程（`00-freeze/adr/template.md`），兼容性判定用
   `python3 tools/compatibility-checker --standalone`；MAJOR 必须附迁移 + 回滚 + 双写下线。
3. **审计写入代码**：必须通过 `python3 tools/audit-verifier --vector` 与
   `python3 05-audit-contract/verify.tool --self-test`；新实现必须写 `payload_digest`。
4. **独立验证器（Java/Go/TS 等）**：必须通过 `hash-chain.spec.md` §3.1/§3.2 冻结向量，
   **不得阅读 Python 参考实现源码**（`verify.tool` 只可作为事后交叉验证）。
5. **全部代码**：`python3 tools/e2e-runner --all` 全绿（用例 / 场景 / 流水线）。
6. **PR 注明所用 AI 工具与版本**，便于复现；未通过验证的生成物不得提交。

## 4. 各工具接线

### Claude Code

Agent Skills 的项目目录是 `.claude/skills/`；把本仓库技能链接进去：

```bash
mkdir -p .claude/skills
for s in skills/*/; do ln -sfn "$(pwd)/$s" ".claude/skills/$(basename "$s")"; done
```

示例：`用 eis-create-contract 为 IM 消息创建数据契约，并运行 contract-checker 验证`。

### Codex

- Codex 读取工作区根部的 `AGENTS.md`：把第 5 节模板写到规格包/仓库根，指向
  `README.md` 与 `skills/README.md`；
- 跨运行时技能目录：`~/.agents/skills/`（个人）或项目 `.agents/skills/`。

示例：`生成审计写入代码（含 payload_digest），并以 audit-verifier --self-test 验证`。

### Pi

Pi 实现 Agent Skills 规范，支持 `~/.agents/skills/` 与项目 `.agents/skills/`（递归发现 `SKILL.md`）：

```bash
mkdir -p .agents/skills
for s in skills/*/; do ln -sfn "$(pwd)/$s" ".agents/skills/$(basename "$s")"; done
```

手动加载：`/skill:eis-create-contract 为 IM 消息创建数据契约`。

### OpenCode

- 通过 `AGENTS.md` 注入规格包入口；`opencode.json` 的 instructions 等字段以该工具当前文档为准。
- 若版本支持 Agent Skills 目录，可直接指向 `skills/`（或按上节链接到 `.agents/skills/`）。

示例：`用 eis-generate-verifier 生成 Go 验证器，并通过 §3.1/§3.2 向量`。

## 5. `AGENTS.md` 模板（放入规格包工作区根）

```markdown
# EIS 规范包工作区

- 先读 `README.md`（规范版本、目录、自校验命令）与 `MANIFEST.json`（逐文件哈希）；
- 技能索引：`skills/README.md`（契约生成 / 兼容性 / 审计写入 / 独立验证器）；
- 生成契约后必须运行 `python3 tools/contract-checker --file <file>`；落地后运行 `python3 tools/contract-checker`；
- 契约变更走 ADR；审计与验证器必须通过冻结向量；不得提交未验证产物。
```

## 6. 失败反馈闭环

验证失败时，把命令的 stdout/stderr **原样**反馈给代理 → 修复 → 重跑，直到通过：

```bash
python3 tools/contract-checker --file generated.schema.json
python3 tools/compatibility-checker --old old.schema.json --new new.schema.json --standalone --json
python3 tools/audit-verifier chain.json --events events.json
python3 tools/e2e-runner --all
```

不得跳过验证或「先提交再修」；契约变更 PR 必须附 `e2e-runner` 汇总行与 ADR 链接（见 `CONTRIBUTING.md`）。
