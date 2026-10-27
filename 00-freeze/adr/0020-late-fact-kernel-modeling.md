# ADR-0020：参考内核建模迟到事实（T-R011）

- **状态**：Accepted
- **日期**：2026-10-27
- **决策者**：核心维护者
- **关联**：issue #45（上游 #40③、#33）；ADR-0011（T-R009 四维排他约束）；ADR-0012 §4.2；`03-time-contract/temporal.rules.yaml` T-R011；`tools/lib/kernel.py`；`docs/KNOWN-LIMITATIONS.md` §1.2

## 1. 变更原因

`03-time-contract` 的 T-R011 要求：迟到的业务事实（`occurred_at` 早于已记录事实）必须以**新的
系统时间**追加写入，允许其有效区间覆盖历史区间（以 `superseded` 留痕），不得回改已记录历史。

参考内核此前只处理「时钟单调前进」的更新：`_update_object` 把新版本 `valid_from` 设为当前时刻，
旧版本 `valid_to` 也设为当前时刻。它没有「业务时间回填」的路径，因此不能作为迟到场景的行为基准
（`docs/KNOWN-LIMITATIONS.md` §1.2）。本 ADR 补齐参考内核的建模，契约本身（T-R011）不变。

## 2. 影响范围

- 参考内核：`Kernel.apply_late_fact()` / `ExtensionAPI.apply_late_fact()`；scenario 新增 `late_fact` 步骤
- 测试断言：`temporal-history` 支持 `expect_recorded_adjacent` / `expect_valid_adjacent`（默认沿用 `expect_adjacent`）
- 用例：`03-time-contract/tests/time-contract.test.yaml` 增「迟到事实」场景；内核自测增 5 条断言
- 文档：本 ADR、`docs/KNOWN-LIMITATIONS.md` §1.2、`extensions/README.md` §6
- 核心契约：**无改动**（T-R011 既有；本 ADR 只补参考实现）

## 3. 兼容性分析

- 级别判定：**PATCH**（参考实现缺口修复；无 Schema/API/DDL 变化）。

| 变更 | 判定 | 依据 |
|---|---|---|
| 新增 `apply_late_fact`（内核/扩展 API） | 加法 | 既有 `update_object` 路径不变 |
| scenario 新增 `late_fact` 步骤 | 测试工具加法 | 既有场景不受影响 |
| `temporal-history` 新增两个可选标志 | 加法 | 默认值保持既有行为 |

- 破坏点：无。单调时钟路径的语义与既有用例不变。

## 4. 决策

### 4.1 迟到事实的写入语义

- 新版本：`recorded_at = now`（新的系统时间）、`valid_from`/`valid_to` 由调用方给出历史业务区间；
  `version = 当前版本 + 1`；
- 旧版本：只把 `superseded_at = now`（系统时间封口），**不改**其 `valid_from`/`valid_to`
  （T-R011「不得回改已记录历史」）；
- 校验：`valid_from < now`（否则 `EIS-400-003`）、`valid_to > valid_from`（半开区间）；
  写入前仍执行扩展对象 Schema 校验（ADR-0016）；
- 不修改 DDL/排他约束：T-R009 的四维排他约束按「同一系统时间视图」生效，迟到事实的
  recorded 区间与旧版本不重叠，业务区间覆盖是 T-R011 明确允许的。

### 4.2 `as_of` 的确定性

- 不带 `recorded_as_of`：候选版本中取 `version` 最大者（迟到事实是后记录的，version 更大）——
  当前系统视图下仍是「单一版本」；
- 带 `recorded_as_of`：按 recorded 区间过滤（`recorded_at <= t < superseded_at`），
  可重建迟到事实记录之前的视图；
- 业务时间与系统时间轴都保持半开区间语义。

### 4.3 测试与断言

- scenario 步骤 `late_fact`：`{type, id, actor, valid_from, valid_to?, data}`；
- `temporal-history`：
  - 默认仍要求业务区间与系统区间都相接（既有用例语义不变）；
  - `expect_valid_adjacent: false` 用于迟到事实（业务区间允许覆盖），系统区间仍校验相接；
- 内核自测覆盖：version 递增、旧版本只封口系统时间、当前视图取新版本、历史 `recorded_as_of`
  取旧版本、未来 `valid_from` 拒绝。

### 4.4 明确不做

| 不做项 | 理由 |
|---|---|
| 回写/修改 `recorded_at` | 系统时间轴 append-only；回写会破坏审计可复现 |
| 删除/重写已记录行 | T-R011 要求留痕；只允许 `superseded` 封口 |
| 自动检测迟到（比较 occurred_at） | 领域事件时间由属主域提供；参考内核不推断业务时间 |
| 提供通用「更正/冲正」工作流 | 领域语义；由属主域命令 + 审计表达 |
| 在内存内核执行 DDL 排他约束 | 参考内核是内存模型；约束以 PostgreSQL 为准（ADR-0011） |

## 5. 迁移方案

- 实现：需要迟到补正的域处理器调用 `api.apply_late_fact(...)`；普通更新继续用 `update_object`；
- 数据：无 DDL/回填；
- 对账：`03-time-contract` 场景 + 内核自测 + `e2e-runner --all`。

## 6. 回滚方案

- 删除 `apply_late_fact` 与 `late_fact` 步骤支持即恢复旧内核；T-R011 契约与 DDL 不受影响；
- 回滚验证：`python3 tools/e2e-runner --all` 全绿。

## 7. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| 内核 API | `tools/lib/kernel.py` | `Kernel.apply_late_fact` / `ExtensionAPI.apply_late_fact` |
| 测试步骤 | `tools/lib/kernel.py` | scenario `late_fact`；`temporal-history` 两个可选标志 |
| 用例 | `03-time-contract/tests/time-contract.test.yaml` | 迟到事实：当前视图 v2 / 历史 recorded 视图 v1 / 系统区间相接 |
| 自测 | `tools/lib/kernel.py` | version、superseded、as_of 两视图、未来 valid_from 拒绝 |
| 文档 | `docs/KNOWN-LIMITATIONS.md` §1.2 | 已修复 + 残余（无自动检测、内存不执行 DDL） |

## 8. 验收用例

- `python3 tools/e2e-runner 03-time-contract/tests/time-contract.test.yaml`：5/5；
- `python3 tools/lib/kernel.py`：自测含 5 条迟到事实断言；
- `python3 tools/e2e-runner --all`：全绿（用例计数随新增场景更新）；
- 反例：`valid_from >= now` → `EIS-400-003`；旧版本 `valid_from/valid_to` 保持不变。
