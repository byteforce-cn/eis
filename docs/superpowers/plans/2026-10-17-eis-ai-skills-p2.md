# EIS AI Skills P2 实施计划（issue #12）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（用户批准 P2；inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 交付 AI 集成 P2：`skills/` 下的 4 个 Agent Skills（`eis-create-contract` / `eis-verify-contract` / `eis-generate-audit` / `eis-generate-verifier`）+ `docs/AI-INTEGRATION.md`（Claude Code / Codex / Pi / OpenCode 接线）+ `CONTRIBUTING.md`「AI 辅助贡献」章节，并以可执行用例与子代理演练验收。

**Architecture:** 技能遵循 Agent Skills 规范（`SKILL.md` + YAML frontmatter：`name` / `description`「Use when…」仅写触发条件），内容聚焦触发条件、输入、步骤、验证命令与失败修复；跨工具接线放在 `docs/AI-INTEGRATION.md`（技能本体保持工具中立）。为让 `eis-create-contract` 的验证闭环可执行且不污染仓库，给 `tools/contract-checker` 增加 `--file` 单文件检查（把既有 per-file 逻辑抽出复用，并补 `$ref` 校验），示例契约随技能版本化并被 CI 校验。

**Tech Stack:** Markdown/Agent Skills 规范、Python 3.10+（stdlib + PyYAML + jsonschema）、e2e-runner `kind: static`/`cli`。

**Spec:** issue #12 与评估评论 P2 行；RFC 的技能表（输入/输出/验证方式）；`writing-skills`（技能结构，触发条件描述、<500 词为宜）、`00-freeze/adr/README.md`（契约变更纪律）。

## Global Constraints

- 技能描述只写「何时使用」，不概括流程；技能内的验证命令必须真实可运行。
- `--file` 为纯加法，不改变现有 CLI/退出码与仓库级检查结果（既有自测与用例锁定）。
- 契约变更仍走 ADR；AI 生成物必须通过验证方可提交（写入 CONTRIBUTING 与 AI-INTEGRATION）。
- 不引入 Node；`e2e-runner --all` 每个任务结束全绿；计数变化同步所有口径文档。
- 交付：分支 `feat/ai-skills` → PR（`Refs #12`，不关闭）→ CI 全绿 → squash 合并 → #12 交付评论（P2 完成、P3/P4 待决策）。

## Review Focus

- **`--file` 与仓库级口径一致**：同一文件经 `--file` 与仓库级检查应得到一致结论；`$ref` 校验在单文件模式同样生效（示例契约的 `../../../01-data-contract/object.schema.json` 必须可解析）。
- **技能可被路由**：frontmatter `name`/`description` 符合规范（description 以 `Use when` 开头、不总结流程），4 个技能名与 RFC 表一致。
- **验证命令不是摆设**：每个技能引用的命令在用例中实际执行；`eis-create-contract` 的示例契约必须通过 `contract-checker --file`。
- **子代理可跟随**：用无上下文的子代理按技能生成契约并通过验证（P2 的 RED/GREEN 演练）。
- **工具中立**：技能正文不写死工具路径；Claude Code / Codex / Pi / OpenCode 的差异只在 `docs/AI-INTEGRATION.md`。
- **不越界**：不改契约目录；`dist/`/`build/` 等生成物不入库；技能不复制规范内容，只引用权威路径。

---

## Task 0（工作流）：分支与基线

- [x] **Step 1**：`git fetch origin`；`git switch -c feat/ai-skills origin/main`；确认基线 `1629169`、工作区干净、`python3 tools/e2e-runner --all` → 116/116。

## Task 1（RED/GREEN）：contract-checker `--file` 单文件检查

**Files:** Modify `tools/contract-checker`

**Interfaces:**
- `check_schemas(report, files=None)` / `check_openapi(report, files=None)` / `check_asyncapi(report, files=None)`：抽出 per-file 逻辑以支持指定文件列表（不改既有仓库级行为）；Schema 检查补 `check_refs`（单文件模式同样校验 `$ref`）；
- CLI `--file PATH`：按后缀分派（`*.schema.json` / `*.openapi.yaml` / `*.api.yaml` / `*.asyncapi.yaml`），`report.print(verbose=True)`，不支持的类型退出 2；
- 自测新增：单文件 `$ref` 可解析通过、坏引用必须失败、未知类型退出 2。

- [x] **Step 1（RED）**：自测新增两条单文件断言（含坏引用负例）→ 运行 `tools/contract-checker --self-test` 失败（函数不存在）。
- [x] **Step 2（GREEN）**：完成抽取与 `--file`；`--self-test` 与仓库级 `tools/contract-checker` 全过（引用校验加入后既有契约不得回归）。
- [x] **Step 3（样例）**：`tools/contract-checker --file skills/eis-create-contract/examples/im-message.schema.json`（Task 2 产物）→ `[ok]`。

## Task 2（GREEN，issue #12 P2）：4 个 Agent Skills

**Files:** Create `skills/README.md`、`skills/eis-create-contract/SKILL.md`（+ `examples/im-message.schema.json`）、`skills/eis-verify-contract/SKILL.md`、`skills/eis-generate-audit/SKILL.md`、`skills/eis-generate-verifier/SKILL.md`

**Interfaces:**
- 每个 `SKILL.md`：frontmatter（`name` 同目录名；`description` 以 `Use when` 开头、仅触发条件）+ 触发条件 / 输入 / 步骤 / 验证命令 / 失败修复 / 权威路径引用；
- 验证命令固定为：create → `tools/contract-checker --file` / 仓库级；verify → `tools/compatibility-checker --standalone`；audit → `tools/audit-verifier --vector` / `verify.tool --self-test`；verifier → `verify.tool --self-test` + §3.1/§3.2 向量；
- `skills/README.md`：4 行索引（技能/用途/验证）+ 安装方式指向 `docs/AI-INTEGRATION.md`；
- 示例 `im-message.schema.json`：`allOf` 引用核心 object 元结构，`$id` 含 `/v1`，可选枚举字段演示 null 语义。

- [x] **Step 1**：按 writing-skills 结构写 4 个技能与索引、示例。
- [x] **Step 2**：`tools/contract-checker --file skills/eis-create-contract/examples/im-message.schema.json` 通过。

## Task 3（GREEN，issue #12 P2）：集成指南与贡献规范

**Files:** Create `docs/AI-INTEGRATION.md`；Modify `CONTRIBUTING.md`

**Interfaces:**
- `docs/AI-INTEGRATION.md`：规格包获取（P1 产物；npm 待 P3/P4）→ 技能表 → 通用硬约束（契约/兼容性/审计/验证器/e2e 的验证命令，PR 注明 AI 工具）→ 四工具接线（Claude Code `.claude/skills/`；Codex `AGENTS.md` + `~/.agents/skills/`；Pi `.agents/skills/` 与 `/skill:<name>`；OpenCode `AGENTS.md`/instructions）→ `AGENTS.md` 模板 → 失败反馈闭环；
- `CONTRIBUTING.md`：新增「AI 辅助贡献」章节（ADR、验证命令、PR 注明工具与版本），后续章节顺延。

- [x] **Step 1**：写文档；确认所述命令与仓库现状一致（不虚构工具配置项，格式随工具文档的以「以当前文档为准」标注）。

## Task 4（用例与计数）：验收套件与口径同步

**Files:** Create `00-freeze/tests/ai-skills.test.yaml`；Modify `README.md`、`CONTRIBUTING.md`、`CHANGELOG.md`、`docs/ROADMAP.md`、`docs/CONFORMANCE.md`、`docs/KNOWN-LIMITATIONS.md`、`docs/LANDING-IAM.md`

**Interfaces:**
- 用例：4 条 static（每个 SKILL.md 含 name/description/验证命令）、1 条 static（skills 索引 4 技能）、1 条 static（AI-INTEGRATION 覆盖 4 工具）、1 条 static（CONTRIBUTING 章节）、3 条 cli（示例契约 `--file`、compatibility `--json` MINOR、audit-verifier 自测）→ 预期 126/126；
- CHANGELOG：P2 新增条目 + 计数（53 + 73 = 126）；README/CONTRIBUTING/CONFORMANCE/KNOWN-LIMITATIONS/LANDING-IAM 计数同步；ROADMAP 标记 P2 完成、P3–P4 待决策。

- [x] **Step 1**：新增用例 → `python3 tools/e2e-runner 00-freeze/tests/ai-skills.test.yaml` 全绿。
- [x] **Step 2**：全量 `python3 tools/e2e-runner --all` 记录计数并同步文档。

## Task 5（验收）：子代理演练 `eis-create-contract`

- [x] **Step 1**：派发无上下文子代理，仅给技能路径与任务（在 `build/skill-test/` 生成一个数据契约并运行技能中的验证命令），要求回报命令与输出。
- [x] **Step 2**：主会话复核产物（`tools/contract-checker --file build/skill-test/*.schema.json`），据结果修正技能措辞（REFACTOR），结果写入 PR。

## Task 6（收尾）：推送、PR、CI、合并与 #12 评交付

- [x] **Step 1**：提交（feat 工具与技能、docs 文档计数）；`git push -u origin feat/ai-skills`；`gh pr create`（标题 `feat(skills): AI 集成 P2——4 个 Agent Skills 与集成指南（issue #12）`，正文含技能表、验证结果、子代理演练、`Refs #12`）。
- [x] **Step 2**：`gh pr checks --watch` 全绿；`gh pr merge --squash --delete-branch`；`git switch main && git pull`。
- [x] **Step 3**：在 #12 评论 P2 交付（技能、集成指南、验收证据）与剩余 P3/P4 决策项。
- [x] **Step 4**：标记本计划完成（小 docs PR）。
