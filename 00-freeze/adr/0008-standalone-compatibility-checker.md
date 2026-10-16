# ADR-0008：compatibility-checker 独立模式（技术中立采纳）

- **状态**：Accepted
- **日期**：2026-10-16
- **决策者**：核心维护者
- **关联**：issue #10；`06-evolution-contract/compatibility.rules.schema.json`、`tools/lib/eis_compat.py`、`tools/compatibility-checker`、`docs/ROADMAP.md`

## 1. 变更原因

`compatibility-checker` 的兼容性判定此前与仓库布局耦合（导入 `tools/lib/eis_common.py`、
按仓库根定位 `compatibility.rules.yaml`）。第三方希望在自身 CI 中判定两个契约版本的
变更级别（PATCH/MINOR/MAJOR），但不引入 EIS 运行时与仓库结构（issue #10：阻碍技术中立采纳）。

## 2. 影响范围

- 契约：演进（`06-evolution-contract`）——新增规则文件的机器可读 Schema（纯新增）
- 扩展：无
- 案例：无
- 工具：`tools/compatibility-checker`（CLI 拆分与两个新参数）、`tools/lib/eis_compat.py`（新，纯 stdlib）

## 3. 兼容性分析

- 级别判定：**PATCH**（工具重构；判定规则与输出语义不变，无契约工件变更）
- 依据：
  - 默认调用（无新参数）仍读取仓库规则文件，`--json` 输出结构、退出码与 `--fail-on` 语义不变；
  - 既有 `kind: compat` 用例（MAJOR/MINOR 两对夹具）与 `--self-test` 全部保留并通过；
  - `compatibility.rules.yaml` 文件的规则权威地位不变，新增的 JSON Schema 仅作机器可读约束。
- 行为扩充（纯加法）：`--standalone`（不读规则文件，使用内置缺省 requires）、`--rules PATH`
  （覆盖规则文件）；规则文件缺失时自动降级为内置缺省并在 stderr 提示。

## 4. 迁移方案

- 仓库内使用：无迁移（命令与输出不变）；
- 独立使用：复制 `tools/compatibility-checker` 与 `tools/lib/eis_compat.py`（保持目录相对关系），
  运行 `--standalone` 即可；内置缺省与规则文件四条数据规则逐项一致；
- 规则表消费方：可按 `compatibility.rules.schema.json` 校验/生成规则文件。

## 5. 回滚方案

- 回滚该提交即可回到单体实现；判定结果不受影响（核心函数逐行迁移，行为由既有自测与 e2e 用例锁定）；
- 回滚验证：`tools/compatibility-checker --self-test`、`tools/e2e-runner 06-evolution-contract/tests/evolution-contract.test.yaml`、`tools/e2e-runner --all`。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 核心模块 | `tools/lib/eis_compat.py` | diff/classify，纯 stdlib，零仓库依赖 |
| CLI | `tools/compatibility-checker` | `--standalone` / `--rules`；默认行为不变 |
| 规则 Schema | `06-evolution-contract/compatibility.rules.schema.json` | 规则文件机器可读约束 |
| 用例 | `06-evolution-contract/tests/evolution-contract.test.yaml` | 新增 2 条 standalone CLI 用例 |
| 文档 | `README.md`「独立验证」、`docs/IMPLEMENTATION.md`、`docs/ROADMAP.md` | 独立验证指南与后续项 |

## 7. 验收用例

- `tools/compatibility-checker --self-test`（原 14 项 + standalone 5 项 + requires 等价 + 规则 Schema 负例）；
- `python3 tools/e2e-runner 06-evolution-contract/tests/evolution-contract.test.yaml`（8/8）；
- `python3 tools/e2e-runner --all`（全绿，无回归）。
