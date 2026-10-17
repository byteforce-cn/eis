# EIS Spec Pack P4（npm 发布）实施计划（issue #12）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（用户确认仓库已有 NPM_TOKEN，可在 CI 发布；inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 交付 P4：新增 npm 发布工作流，用仓库 secret `NPM_TOKEN` 从 CI 发布 `@byteforce/eis-spec`（tag `v*` → `latest`；预发布 tag → `next`；每日/手动 → `nightly`），带 provenance；并完成首个正式发布 `v1.0.0` 与验证。

**Architecture:** 发布走独立工作流 `.github/workflows/release-npm.yml`（不污染 PR 校验流程）：构建 `--npm-out`（新增 `--npm-version` 覆盖版本，nightly/预发布用）→ `--check` → node 完整性自检 → `pnpm publish --registry https://registry.npmjs.org --tag <channel> --provenance`（`id-token: write`）。版本与通道由 workflow 从 `acceptance.yaml` 规范版本 + tag/输入推导；tag 版本必须匹配规范版本（预发布比基版本）。

**Tech Stack:** GitHub Actions（pnpm 12、Node 22、OIDC provenance）、npm registry、Python 生成器。

**Spec:** issue #12 评估评论 P3/P4 行、RFC 补充评论（npm 主交付、版本对齐、nightly/latest/next 通道）；用户确认 `NPM_TOKEN` secret 可用。

## Global Constraints

- 发布只在 `byteforce-cn/eis` 仓库执行；工作流共享锁 `release-npm`，不并发发布。
- 显式 `--registry https://registry.npmjs.org`（本地/镜像环境不影响）；scoped 包 `--access public`。
- provenance 开启（`id-token: write` + `--provenance`）；缺 `NPM_TOKEN` 必须显式失败。
- 发布版本必须为合法 semver；tag 版本与规范版本不一致时失败（预发布按基版本比较）。
- 不改 canonical/npm 构建既有行为；`--check` 与 Node 自检在发布前必须通过。
- 不发布 nightly 以外的额外通道；不修改受保护分支策略。
- 交付：分支 `feat/spec-pack-p4-npm-publish` → PR（`Refs #12`）→ CI 全绿 → squash 合并 → dry-run 验证 → tag `v1.0.0` 正式发布 → npm 验证 → #12 收口。

## Review Focus

- **版本一致性**：`--npm-version` 覆盖后 `package.json`、npm README 的 tarball 名、`MANIFEST.package_version` 三者一致；`MANIFEST.spec_version` 仍为规范版本。
- **通道正确**：`v1.0.0` → latest；`v1.0.0-rc.1` → next 且基版本比对通过；手动/每日 → nightly（`<spec>-nightly.<date>.<sha7>`）；非法版本必须 rc≠0。
- **发布安全**：dry-run 时不得触网发布；真实发布前必须自检通过；`NPM_TOKEN` 缺失必须失败而不是静默跳过。
- **可追溯**：provenance 与 tag 关联；发布日志打印 channel/version/registry。
- **不越界**：工作流不执行任何写仓库操作（无 push/tag 创建）；不改 `ci.yml` 既有行为（仅可能追加静态断言）。

---

## Task 0（工作流）：分支与基线

- [x] **Step 1**：`git fetch origin`；`git switch -c feat/spec-pack-p4-npm-publish origin/main`；基线 `3f959dc`、工作区干净、`e2e-runner --all` → 132/132。

## Task 1（RED）：发布工作流用例先行

**Files:** Modify `00-freeze/tests/spec-pack.test.yaml`

**Interfaces:** 新增 static 用例：`release-npm.yml` 同时含 `tags:`、`cron:`、`pnpm publish`、`NPM_TOKEN`、`--provenance`（`min_matches: 5`）。

- [x] **Step 1（RED）**：新增用例；运行 spec-pack 套件 → 失败（工作流不存在）。

## Task 2（GREEN）：`--npm-version` 与发布工作流

**Files:** Modify `tools/build-spec-pack`；Create `.github/workflows/release-npm.yml`

**Interfaces:**
- `build_pack(..., npm_version=None)`：包版本 = `npm_version or spec_version`；MANIFEST 增 `package_version`，`spec_version` 保持规范版本；npm README 段落按包版本渲染。
- CLI `--npm-version V`（仅与 `--npm-out` 同用；校验 `^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$`，否则 rc 2）。
- 自测新增：覆盖版本构建 → package.json / MANIFEST.package_version 断言；非法版本 rc 2。
- 工作流：见 Architecture；`workflow_dispatch` 输入 `channel`/`version`/`dry_run`；tag 触发按 semver 预发布后缀选 next/latest；`schedule` 每日 nightly；job 级 `env` 固定 registry；发布前 `--check` + `node verify --no-python`。

- [x] **Step 1**：实现版本覆盖与自测；`python3 tools/build-spec-pack --self-test` 全绿。
- [x] **Step 2**：新增工作流；`python3 tools/e2e-runner 00-freeze/tests/spec-pack.test.yaml` 全绿。
- [x] **Step 3**：本地按工作流顺序 dry-run 复跑（`--npm-version 1.0.0-nightly.<date>.<sha>`、`--check`、node verify、`pnpm publish --dry-run`）。

## Task 3（文档与计数）

**Files:** Modify `README.md`、`docs/AI-INTEGRATION.md`、`docs/ROADMAP.md`、`CHANGELOG.md`、`CONTRIBUTING.md`、`docs/CONFORMANCE.md`、`docs/KNOWN-LIMITATIONS.md`、`docs/LANDING-IAM.md`

- [x] **Step 1**：README/AI-INTEGRATION 发布口径（tag → latest、nightly、provenance）；ROADMAP P4 完成；CHANGELOG 条目与计数（预期 133/133）；其余口径同步。

## Task 4（收尾）：PR、CI、合并

- [x] **Step 1**：提交（feat 生成器与工作流、docs 文档计数）；`git push -u origin feat/spec-pack-p4-npm-publish`；`gh pr create`（标题 `feat(ci): npm 发布工作流与版本覆盖（issue #12 / P4）`，正文含通道表、dry-run 结果、`Refs #12`）。
- [x] **Step 2**：`gh pr checks --watch` 全绿；`gh pr merge --squash --delete-branch`；`git switch main && git pull`。

## Task 5（发布与收口）：

- [ ] **Step 1**：`gh workflow run release-npm.yml -f channel=latest -f dry_run=true` → 运行成功（日志含版本/channel 与 dry-run 跳过发布）。
- [ ] **Step 2**：`git tag v1.0.0 && git push origin v1.0.0` → 工作流发布 `@byteforce/eis-spec@1.0.0`（latest，provenance）；`npm view @byteforce/eis-spec version dist-tags` 验证。
- [ ] **Step 3**：`gh workflow run release-npm.yml -f channel=nightly` → 验证 nightly 版本发布与通道隔离（`npm view ... dist-tags`）。
- [ ] **Step 4**：在 #12 收口评论（P1–P4 全交付 + 发布证据 + 验收演练状态），关闭 #12；标记本计划完成（小 docs PR）。
