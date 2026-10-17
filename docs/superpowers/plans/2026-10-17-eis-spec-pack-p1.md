# EIS Spec Pack P1 实施计划（issue #12）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（用户批准评估建议的 P1；inline 执行）。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 交付 AI 规格包 P1：`tools/build-spec-pack` 从规范源生成自包含的 `dist/eis-spec-pack/`（六类契约 + 冻结向量 + 参考工具 + `MANIFEST.json` 逐文件 SHA-256 + 面向 AI 的 README），CI 构建并在产物内完成自校验。

**Architecture:** 产物保持与源仓库一致的相对路径（`01-…`–`06-…` 直接镜像，`tools/` 带 `lib/` 依赖），因此 `verify.tool`、`audit-verifier`、`compatibility-checker`、`contract-checker` 零修改即可在包内运行（已用临时镜像实测：26/0 与全部自测通过）。`MANIFEST.json` 记录源路径 → 包内路径的映射与哈希，`--check` 可复算；`SOURCE_DATE_EPOCH` 固定时构建可复现。RFC 提议的 `contracts/` 分组属 npm 封装阶段（P3）的展示层，P1 不重命名目录。

**Tech Stack:** Python 3.10+（stdlib；规范版本从 `acceptance.yaml` 正则读取）、PyYAML/jsonschema（仅产物内工具需要）、GitHub Actions。

**Spec:** issue #12 与[评估评论](https://github.com/byteforce-cn/eis/issues/12#issuecomment-6227113095) 的 P1 行；`docs/superpowers/plans/2026-10-17-eis-open-issues-12-13.md`。

## Global Constraints

- 产物为生成物：`dist/` 必须加入 `.gitignore`，不提交；`MANIFEST.json` 是唯一的完整性凭据。
- 不引入 Node；不改动既有工具行为与「流水线 5/5」；用例计数随新增同步到 `README.md`/`CONTRIBUTING.md`/`CHANGELOG.md`/`docs/CONFORMANCE.md`/`docs/KNOWN-LIMITATIONS.md`/`docs/LANDING-IAM.md`。
- `tools/build-spec-pack` 不依赖 PyYAML/jsonschema 本体（仅产物内工具的调用方需要），保持与参考工具一致的 CLI 风格（`--self-test`、中文输出、退出码 0/1/2）。
- 规范版本单一来源：`acceptance.yaml` 的 `version`；找不到必须显式失败。
- 测试确定性、离线；CI 在 PR 上即构建校验（漂移即红），产物作为 artifact 上传。
- 交付：分支 `feat/spec-pack-p1` → PR（正文 `Refs #12`，**不**关闭 #12）→ CI 全绿 → squash 合并；在 #12 评论 P1 交付结果与待决策项。

## Review Focus

- **包内路径可运行**：`audit-verifier` 依据 `eis_common.ROOT` 找 `05-audit-contract/verify.tool`；镜像必须包含六个契约目录原名，且 `tools/lib/{eis_common,eis_compat}.py` 同层就位。
- **MANIFEST 可复算**：每个文件 `sha256`/`size` 与磁盘一致；篡改任一文件后 `--check` 必须报错；缺文件、多余文件（如 `__pycache__`/`.pyc`）必须失败。
- **确定性**：固定 `SOURCE_DATE_EPOCH`/`generated_at` 时两次构建的 `MANIFEST.json` 字节一致；文件列表按路径排序且不重复。
- **向量口径**：`vectors/audit/` 含合法/篡改/断链/缺口夹具与事件导出；`audit-verifier --all` 会故意失败（含篡改夹具），因此自校验只逐条验证合法链与 digest 链，不扫全目录。
- **负例**：`compatibility-checker` 对 breaking 夹具必须退出 1（`--fail-on MAJOR`），防止「校验永远绿」。
- **不越界**：不打包 `extensions/`/`cases/`/`00-freeze`/`dist` 自身；不把生成器放进产物；CI 失败时不产出 artifact 可用性判断（验证步骤在 upload 之前）。

---

## Task 0（工作流）：分支与基线

- [x] **Step 1**：`git fetch origin`；`git switch -c feat/spec-pack-p1 origin/main`；确认基线 `d1b604e`、工作区干净、`python3 tools/e2e-runner --all` → 114/114。

## Task 1（RED，issue #12 P1）：验收用例先行

**Files:** Create `00-freeze/tests/spec-pack.test.yaml`

**Interfaces:** `suite: spec-pack`；`kind: cli`（`tools/build-spec-pack --self-test`，stdout 含 `自测结果: 通过`）；`kind: static`（`.github/workflows/ci.yml` 同时含 `build-spec-pack --out`、`verify.tool --self-test`、`upload-artifact`，`min_matches: 3`）。

- [x] **Step 1（RED）**：新增两条用例；`python3 tools/e2e-runner 00-freeze/tests/spec-pack.test.yaml` → 两条失败（工具与 CI 任务尚不存在）。

## Task 2（GREEN，issue #12 P1）：build-spec-pack

**Files:** Create `tools/build-spec-pack`

**Interfaces:**
- 常量：`CONTRACT_DIRS = ("01-data-contract", …, "06-evolution-contract")`；`TOOL_FILES = ("tools/contract-checker", "tools/compatibility-checker", "tools/audit-verifier", "tools/lib/eis_common.py", "tools/lib/eis_compat.py")`；`VECTOR_DIRS = (("05-audit-contract/tests/fixtures", "vectors/audit"), ("06-evolution-contract/tests/fixtures", "vectors/evolution"))`。
- `build_pack(out: Path, *, generated_at: str | None = None, commit: str | None = None) -> dict`：清空并重建 `out`；镜像契约目录（排除 `__pycache__`/`.pyc`）；复制工具；导出向量；渲染 `README.md`（`string.Template` 注入 `spec_version`/`generated_at`/`source_commit`/`file_count`）；写 `MANIFEST.json`（`pack_schema_version`/`spec_version`/`generated_at`/`source_commit`/`generator`/`files[{path,source,kind,sha256,size}]`，`sort_keys` + 缩进 2、末尾换行）。
- `verify_manifest(pack: Path) -> list[str]`：逐条复算哈希、比对 size、检查未登记文件。
- `_spec_version()`：读 `acceptance.yaml` `^version:\s*"([^"]+)"`；`_source_commit()`：`git rev-parse HEAD`，失败返回 `None`；`_generated_at()`：`SOURCE_DATE_EPOCH` 优先，否则 UTC 当前秒。
- CLI：无参数构建到 `dist/eis-spec-pack`；`--out DIR`；`--check DIR`；`--json`；`--self-test`（临时目录构建 → 必需路径/哈希/排序/无缓存文件/README 注入/二次构建确定性 → 包内子进程跑 `verify.tool --self-test`、`audit-verifier --vector`、两条合法链、minor 兼容性（含 breaking 负例）、`contract-checker`；篡改文件后 `verify_manifest` 必须报错）。

- [x] **Step 1（GREEN 构建）**：实现镜像/清单/README/`--check`；运行 `python3 tools/build-spec-pack --out dist/eis-spec-pack` 与 `--check` 通过。
- [x] **Step 2（GREEN 自测）**：实现 `--self-test` 全部断言；`python3 tools/build-spec-pack --self-test` → `自测结果: 通过`。
- [x] **Step 3**：`python3 tools/e2e-runner 00-freeze/tests/spec-pack.test.yaml` → cli 用例通过（static 待 Task 3）。

## Task 3（GREEN，issue #12 P1）：CI 任务与忽略规则

**Files:** Modify `.github/workflows/ci.yml`、`.gitignore`

**Interfaces:**
- 新 job `spec-pack`（name `Spec Pack 构建与自校验`）：checkout + setup-python 3.12 + `pip install pyyaml jsonschema`；`python3 tools/build-spec-pack --out dist/eis-spec-pack`；`--check`；`working-directory: dist/eis-spec-pack` 下依次运行 README 中的六条自校验命令；`actions/upload-artifact@v4`（`name: eis-spec-pack`，`path: dist/eis-spec-pack`）。
- `.gitignore` 增加 `dist/`。

- [x] **Step 1**：加入 job 与忽略规则；本地按 CI 步骤手动复跑全部命令（构建、check、包内六条）确认退出码 0。
- [x] **Step 2**：`python3 tools/e2e-runner --all` → 全绿，记录新计数（预期 116/116、流水线 5/5）。

## Task 4（issue #12 P1）：文档与计数

**Files:** Modify `README.md`（新增「AI 规格包（spec-pack，P1）」节 + 计数）、`CONTRIBUTING.md`（目录速查 + 计数）、`CHANGELOG.md`（新增/变更 + 计数）、`docs/ROADMAP.md`（P1 完成、P2–P4 待排期）、`docs/CONFORMANCE.md`/`docs/KNOWN-LIMITATIONS.md`/`docs/LANDING-IAM.md`（计数）

- [x] **Step 1**：文档更新；`python3 tools/e2e-runner --all` 复核计数口径；提交。

## Task 5（收尾）：推送、PR、CI、合并

- [ ] **Step 1**：`git push -u origin feat/spec-pack-p1`；`gh pr create --base main`，标题 `feat(tools): spec-pack P1——CI 生成与产物内自校验（issue #12）`，正文含交付物、六条自校验结果、`Refs #12`（不关闭）。
- [ ] **Step 2**：`gh pr checks --watch` 全绿；`gh pr merge --squash --delete-branch`；`git switch main && git pull`。
- [ ] **Step 3**：在 #12 评论 P1 交付（产物结构、MANIFEST、CI 任务、验证命令与结果），并复述仍待决策的 P2–P4 项。
