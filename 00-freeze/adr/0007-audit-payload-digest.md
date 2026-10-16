# ADR-0007：审计链 payload_digest（事件正文承诺）

- **状态**：Accepted
- **日期**：2026-10-16
- **决策者**：核心维护者
- **关联**：issue #9；`05-audit-contract/hash-chain.spec.md` v1.1、`audit.schema.json`、`audit.ddl`、`tools/lib/kernel.py`、`05-audit-contract/verify.tool`、`tools/audit-verifier`

## 1. 变更原因

审计条目 `payload` 仅含 `{"command_id", "event_ids"}`，事件正文不受链承诺（`docs/KNOWN-LIMITATIONS.md` §2.2）：
事件内容被篡改时链校验无法发现，直接削弱审计规范在 IM 消息、工单正文、审批意见等场景的可信度。issue #9 要求把事件正文摘要纳入审计条目，并让公开验证工具能独立检出正文篡改。

## 2. 影响范围

- 契约：审计（`05-audit-contract`）
- 扩展：无（扩展仍只产生事件，由内核写链）
- 案例：无
- 工具：`tools/lib/kernel.py`（写链携带 digest）、`05-audit-contract/verify.tool`（`--events` 复算）、`tools/audit-verifier`（透传）

## 3. 兼容性分析

- 级别判定：**MINOR**（依据 `06-evolution-contract/compatibility.rules.yaml` 数据规则「可选字段新增」）
- 依据：
  - `payload_digest` 为**可选**字段；规范化仅在字段存在且非空时追加一行，**v1.0 条目哈希逐字节不变**
    （冻结向量 3.1 `447c6e29…` 保持不变，新增向量 3.2 钉住 v1.1 公式）；
  - 无 digest 的既有条目与夹具（valid/tampered/gap/broken）验证行为无回归；
  - `audit.ddl` 仅增可空列 + CHECK，纯加法。
- 已知互操作边界：仅实现 v1.0 公式的旧验证器无法验证含 digest 的新条目（会判 `invalid_hash`）；
  生产者如面向旧验证器可暂不写 digest（可选）。该边界登记于 `docs/KNOWN-LIMITATIONS.md`。

## 4. 迁移方案

- 新写入条目自动携带 digest（参考内核）；存量条目保持 v1.0 公式，无需回填或重算；
- DDL 变更：`ALTER TABLE audit_entry ADD COLUMN payload_digest TEXT;` + CHECK 约束；
- 审计导出建议同时提供事件导出（`{"events":[...]}`），供 `verify.tool --events` 复算。

## 5. 回滚方案

- 停止写入 digest 即回到 v1.0 行为；已写入条目仍可验证（v1.1 验证器向后兼容 v1.0 条目）；
- DDL 回滚：`ALTER TABLE audit_entry DROP COLUMN payload_digest;`
- 回滚验证：`verify.tool --self-test` 与既有四个链夹具全部通过。

## 6. 可执行工件

| 工件 | 路径 | 说明 |
|------|------|------|
| Schema | `05-audit-contract/audit.schema.json` | 可选 `payload_digest`（`^[0-9a-f]{64}$`） |
| DDL | `05-audit-contract/audit.ddl` | 可空列 + CHECK 约束 |
| 规范 | `05-audit-contract/hash-chain.spec.md` v1.1 | §2 规范化、§2.1 摘要定义、§3.2 向量、§4/§5 语义 |
| 参考实现 | `05-audit-contract/verify.tool`、`tools/audit-verifier --events` | 摘要复算、`payload_digest_mismatch` 检出 |
| 参考内核 | `tools/lib/kernel.py` | 写链携带 `payload_digest`；`audit-chain` 断言可复算 |
| 夹具/用例 | `05-audit-contract/tests/fixtures/*`、`tests/audit-contract.test.yaml` | 合法 digest 链 / 未篡改 / 篡改 / 零事件边界 |

## 7. 验收用例

- `05-audit-contract/verify.tool --self-test`（含 payload_digest 四断言）；
- `python3 tools/e2e-runner 05-audit-contract/tests/audit-contract.test.yaml`（10/10）；
- `python3 tools/e2e-runner --all`（全绿，无回归）。
