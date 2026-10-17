---
name: eis-verify-contract
description: Use when a contract change needs a compatibility verdict (PATCH/MINOR/MAJOR), when deciding whether a version bump or migration is required, or when a compatibility checker run failed and needs explanation
---

# EIS 兼容性判定

## 触发条件

- 修改/新增字段、命令、事件、枚举后需要判定 PATCH/MINOR/MAJOR；
- 升级扩展或核心版本前，需要配套动作清单（迁移 / 双写 / 回滚 / 回填）；
- 兼容性检查失败，需要向评审解释具体原因。

## 输入

- 旧、新两个契约文件（或 git 前后版本、规格包内文件）；
- 判定权威：`06-evolution-contract/compatibility.rules.yaml`；版本语义：`00-freeze/version-policy.md`。

## 步骤

1. 取旧、新文件（同一对象/命令；外部 `$ref` 两侧保持相同字符串）。
2. 运行判定（`--standalone` 不依赖仓库，可在任意 CI 使用）：
   ```bash
   python3 tools/compatibility-checker --old old.schema.json --new new.schema.json --standalone --json
   ```
3. 读 `overall` 与 `changes[]`：每条 change 的 `kind` 对应规则表条目，`requires` 为配套动作（`migration` / `dual_write` / `rollback` / `backfill`）；取最高 `level` 为整体级别。
4. 按级别落实：
   - **PATCH**：修复/文档，不改契约语义；
   - **MINOR**：可选字段、新 API/事件/错误码 → 升 MINOR 并补用例；
   - **MAJOR**：删字段/改类型/新增必填/语义变更 → ADR + 迁移 + 回滚 + 双写下线后才升 MAJOR。
5. 记录：ADR（`00-freeze/adr/template.md`）+ CHANGELOG + 契约用例。

## 验证

```bash
python3 tools/compatibility-checker --old old.schema.json --new new.schema.json --standalone --fail-on MAJOR
python3 tools/e2e-runner 06-evolution-contract/tests/evolution-contract.test.yaml
```

`--fail-on MINOR` 可作为人工评审闸门；`--json` 供 CI 解析。

## 失败修复

| 信号 | 含义与动作 |
|------|-----------|
| `$ref 无法解析` → MAJOR | 保持两侧相同的外部 `$ref` 字符串；无法解析的引用保守判 MAJOR |
| `枚举取值收缩` | 删除枚举值属 MAJOR：恢复取值，或走迁移 + 旧值下线 |
| `字段类型变更` | 属 MAJOR：新字段两阶段迁移后再删旧字段 |
| `必填字段新增` | 属 MAJOR：给 default + 回填，或改为可选字段 |
| 结构判 PATCH 但有行为变化 | 工具只判结构；行为语义变化必须按 MAJOR 处理 |

## 参考

- `06-evolution-contract/compatibility.rules.yaml`、`compatibility.rules.schema.json`
- 迁移/回滚模板：`06-evolution-contract/migration.template.sql`、`rollback.template.sql`
- 示例：`extensions/hr/` 的 v1.0→v1.1 加法演进（ADR-0009）与 `extensions/hr/tests/compat/`
