# EIS Spec Pack P3（pnpm 形态）实施计划（issue #12）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（用户决策「引入 pnpm」；inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 交付 P3：由 `tools/build-spec-pack --npm-out` 生成 pnpm/npm 可消费的 `@byteforce/eis-spec` 包形态（package.json + `bin/eis-spec` CLI + 规格/工具/向量内容），CI 构建、校验并 `pnpm pack` 归档 tarball 作为 artifact；**不发布 registry**（P4 待 npm 凭证决策）。

**Architecture:** npm 包 = 现有 spec-pack 内容（保持源仓库相对路径，参考工具零修改可运行）+ 打包层（`package.json`、`bin/eis-spec.js`、`LICENSE`/`NOTICE`、README 的 pnpm 段落）；打包层文件同样纳入 `MANIFEST.json`（kind: packaging），因此 `--check` 与 Node CLI 的哈希复算对整包成立。`bin/eis-spec.js` 只用 Node 内置模块（fs/crypto/child_process）：`manifest` 输出摘要/全量 JSON，`verify` 复算哈希并可调用包内 Python 工具跑冻结向量自检（`--no-python` 可跳过）。

**Tech Stack:** Node >= 18（内建模块，零第三方依赖）、pnpm（CI pin 12，本地 12.9.1）、Python 3.10+ 生成器、GitHub Actions。

**Spec:** issue #12 与评估评论 P3 行、RFC 补充评论的 npm 结构（npm 包名 `@byteforce/eis-spec`；`dist/` 不提交；package.json 由构建生成）；P1 计划（canonical 路径决策）。

## Global Constraints

- `dist/` 不提交；`pnpm pack` 产物（`*.tgz`）与 `node_modules/` 不入库；registry 发布不在本次范围。
- 不改变 P1 canonical pack 行为（`--out`/`--check`/既有自测断言全部保留）。
- 包名固定 `@byteforce/eis-spec`，版本 = 规范版本（`acceptance.yaml`）。
- `bin/eis-spec.js` 零第三方依赖；Python 自检为可选路径（缺 python3 时 `--no-python` 仍可完成完整性校验）。
- 每任务后 `python3 tools/e2e-runner --all` 全绿；计数变化同步口径文档。
- 交付：分支 `feat/spec-pack-p3-pnpm` → PR（`Refs #12`，不关闭）→ CI 全绿 → squash 合并 → #12 留 P3 交付评论。

## Review Focus

- **整包完整性**：npm 形态的 `MANIFEST.json` 必须覆盖 package.json/bin/LICENSE/NOTICE/README，`--check` 与 `node verify` 均通过；篡改任一器包文件必须检出。
- **零依赖可跑**：`node bin/eis-spec.js manifest|verify --no-python` 在无 `node_modules`、无网络时可运行；`verify`（默认）在 python3 可用时执行包内 `verify.tool --self-test` / `audit-verifier --vector` / `contract-checker`。
- **pnpm 产物正确**：`pnpm pack` 输出的 tarball 含 `package/package.json` 与 `package/bin/eis-spec.js`；版本号与规范版本一致；不产生 `node_modules` 污染（用 `--pack-destination` 输出到包外）。
- **CI 顺序**：npm 构建 → `--check` → node 自检 → `pnpm pack` → artifact；失败不产出可用 tarball；canonical pack 与其产物验证保持原样。
- **确定性**：固定 `generated_at`/commit 时两次 npm 构建的 `MANIFEST.json` 字节一致；`package.json` 不含时间戳。
- **不越界**：不改契约目录与工具行为；包内不含 `extensions/`/`cases/`/生成器自身。

---

## Task 0（工作流）：分支与基线

- [x] **Step 1**：`git fetch origin`；`git switch -c feat/spec-pack-p3-pnpm origin/main`；基线 `c5f9920`、工作区干净、`e2e-runner --all` → 131/131。

## Task 1（RED）：npm 形态用例先行

**Files:** Modify `00-freeze/tests/spec-pack.test.yaml`

**Interfaces:** 新增 static 用例：`.github/workflows/ci.yml` 同时含 `--npm-out`、`pnpm/action-setup`、`pnpm pack`、`eis-spec-npm`（`min_matches: 4`）。

- [x] **Step 1（RED）**：新增用例；`python3 tools/e2e-runner 00-freeze/tests/spec-pack.test.yaml` → 失败。

## Task 2（GREEN）：build-spec-pack npm 形态

**Files:** Modify `tools/build-spec-pack`

**Interfaces:**
- `build_pack(out, *, generated_at=None, commit=None, npm=False) -> dict`：`npm=True` 时在包内生成 `bin/eis-spec.js`（内建模块 CLI，模板常量，0755）、`package.json`（name/version/license/repository/engines/files/exports/bin/publishConfig）、复制 `LICENSE`/`NOTICE`，MANIFEST 将其记为 `kind: packaging`；README 注入 pnpm 消费段落（`$npm_section` 模板变量）。
- CLI `--npm-out DIR`：按 npm 形态构建到 DIR（默认 `dist/npm` 由调用方显式给出）；输出摘要。
- `verify_manifest`：运行时噪声忽略集合加入 `node_modules`（与 `__pycache__` 同类）。
- 自测新增：npm 包结构断言（package.json 字段/版本、bin 存在且在清单中、`verify_manifest` 通过、两次构建 MANIFEST 字节一致）；node 可用时运行 `node bin/eis-spec.js manifest --json` 与 `verify --no-python`（篡改后必须失败）；pnpm 可用时 `pnpm pack --pack-destination <tmp>` 产出 tarball 并按 `tar -tzf` 断言含 `package/package.json` 与 `package/bin/eis-spec.js`。

- [x] **Step 1**：实现生成与 CLI；`python3 tools/build-spec-pack --npm-out dist/npm`、`--check dist/npm` 通过。
- [x] **Step 2**：扩展 `--self-test` 全绿（node/pnpm 断言随环境执行）。
- [x] **Step 3**：`python3 tools/e2e-runner 00-freeze/tests/spec-pack.test.yaml` → 全绿。

## Task 3（GREEN）：CI 与忽略规则

**Files:** Modify `.github/workflows/ci.yml`、`.gitignore`

**Interfaces:**
- `spec-pack` job 增：`pnpm/action-setup@v4`（version: 12）+ `actions/setup-node@v4`（node 22）；`python3 tools/build-spec-pack --npm-out dist/npm`；`--check dist/npm`；`node dist/npm/bin/eis-spec.js manifest --json >/dev/null`；`node dist/npm/bin/eis-spec.js verify --no-python`；`pnpm pack --pack-destination ../npm-pack`（working-directory `dist/npm`）；`actions/upload-artifact@v4`（name `eis-spec-npm`，path `dist/npm` + `dist/npm-pack/*.tgz`）。
- `.gitignore` 增 `*.tgz`、`node_modules/`。

- [x] **Step 1**：工作流与忽略规则更新；本地按 CI 顺序逐步复跑（含 `pnpm pack`）确认退出码 0。
- [x] **Step 2**：`python3 tools/e2e-runner --all` 全绿并记录计数（预期 132/132）。

## Task 4（文档与计数）

**Files:** Modify `README.md`、`docs/AI-INTEGRATION.md`、`docs/ROADMAP.md`、`CHANGELOG.md`、`CONTRIBUTING.md`、`docs/CONFORMANCE.md`、`docs/KNOWN-LIMITATIONS.md`、`docs/LANDING-IAM.md`

- [x] **Step 1**：README「AI 规格包」补 npm/pnpm 命令；AI-INTEGRATION 获取章节补 pnpm 形态（发布待 P4）；ROADMAP P3 完成、P4 待凭证；CHANGELOG 条目与计数；其余口径同步。

## Task 5（收尾）：推送、PR、CI、合并与 #12 评论

- [x] **Step 1**：提交（feat 生成器与 CI、docs 文档计数）；`git push -u origin feat/spec-pack-p3-pnpm`；`gh pr create`（标题 `feat(tools): spec-pack P3——pnpm 包形态与 pack 产物（issue #12）`，正文含结构、验证结果、`Refs #12`）。
- [x] **Step 2**：`gh pr checks --watch` 全绿；`gh pr merge --squash --delete-branch`；`git switch main && git pull`。
- [x] **Step 3**：在 #12 评论 P3 交付（包结构、CLI、pnpm pack artifact、验证证据）与仅剩的 P4 凭证项。
- [x] **Step 4**：标记本计划完成（小 docs PR）。
