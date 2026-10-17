# EIS Agent Skills

本目录提供 4 个遵循 [Agent Skills 规范](https://agentskills.io/specification) 的技能，
让 AI 编码代理完成「读规范 → 生成工件 → 验证」的闭环。技能与规范同版本演进，
正文不复制规范内容，只引用权威路径；每条技能以可执行命令作为验收。

| 技能 | 用途 | 验证命令（仓库/规格包根目录执行） |
|------|------|-----------------------------------|
| `eis-create-contract` | 生成或扩展 EIS 数据与操作契约 | `python3 tools/contract-checker --file <file>`；落地后 `python3 tools/contract-checker` |
| `eis-verify-contract` | 判定契约变更兼容性（PATCH/MINOR/MAJOR）并给出配套动作 | `python3 tools/compatibility-checker --old A --new B --standalone` |
| `eis-generate-audit` | 生成含 `payload_digest` 与哈希链的审计写入实现 | `python3 tools/audit-verifier --vector`；`python3 05-audit-contract/verify.tool --self-test` |
| `eis-generate-verifier` | 用目标语言独立实现审计链验证器 | `python3 05-audit-contract/verify.tool --self-test`（§3.1/§3.2 冻结向量） |

## 安装到各工具

技能在工具中的发现路径不同（Claude Code `.claude/skills/`；Pi/Codex `.agents/skills/`），
接线示例见 [`docs/AI-INTEGRATION.md`](../docs/AI-INTEGRATION.md)。

## 验收

- 示例契约由 CI 校验（`00-freeze/tests/ai-skills.test.yaml`）；
- 技能引用的命令必须可由 `python3 tools/e2e-runner --all` 复现；
- AI 生成物未通过验证不得提交（见 `CONTRIBUTING.md`「AI 辅助贡献」）。
