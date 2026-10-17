---
name: eis-generate-audit
description: Use when implementing or reviewing audit write paths that must satisfy the EIS audit contract, including payload_digest computation, hash-chain linking, and tamper detection
---

# EIS 审计写入生成

## 触发条件

- 为目标系统实现/改造审计写入（命令 → 事件 → 审计链）；
- 需要校验审计实现是否符合 `hash-chain.spec.md`（哈希公式、规范化、篡改可检出）；
- 链验证失败（`invalid_hash` / `payload_digest_mismatch`）需要定位。

## 输入

- `05-audit-contract/audit.schema.json`、`audit.ddl`（append-only 表）；
- `05-audit-contract/hash-chain.spec.md`（§1 链结构、§2 规范化、§2.1 digest、§3 冻结向量）；
- 事件语义：`01-data-contract/event.schema.json`、`02-operation-contract/event.asyncapi.yaml`。

## 步骤

1. **表结构**：按 `audit.ddl` 建 append-only 表；UPDATE/DELETE 必须被拒绝；链字段由单一写入者维护。
2. **规范化**（规范 §2）：`canonical` 为固定 LF 连接的规范行序列；payload 用规范 JSON（键排序、无空白、UTF-8 不转义非 ASCII）；时间戳转 UTC 且恰好 6 位小数；UUID/hex 小写。
3. **哈希**：`hash = SHA256(canonical)`；`prev_hash` 前一条 `hash`，创世为 64×"0"，`sequence` 从 1 连续递增。
4. **payload_digest**（§2.1，v1.1 可选）：对条目引用的事件投影 `[{id,type,payload}]` 做规范 JSON 后 SHA-256；字段存在且非空时作为 `canonical` 最后一行参与哈希（缺失时保持 v1.0 公式）；空事件为冻结常量 `4f53cda1…`。
5. **写入顺序**：先落业务对象与事件，再追加审计条目（同事务或 outbox 按部署架构保证不丢）。
6. **不得自算派生值**：`payload_digest` 必须由服务端从事件投影复算；调用方传入的派生值一律拒绝（对齐 write-only 纪律）。
7. **事件导出**：提供 `{events:[…]}` / JSONL 导出，供验证器复算 digest。

## 验证

```bash
# 冻结向量（§3.1 无 digest + §3.2 含 digest）
python3 tools/audit-verifier --vector
python3 05-audit-contract/verify.tool --self-test
# 真实链 + 事件导出复算（篡改事件正文应报 payload_digest_mismatch）
python3 tools/audit-verifier <chain.json> --events <events.json>
```

参考语义可对照 `tools/lib/kernel.py` 的 `_append_audit`，但审计写入实现不得依赖它。

## 失败修复

| 报错 | 定位 |
|------|------|
| `invalid_hash` | 规范化字符串（键序/空白/LF/时间戳精度）或链字段写入顺序不一致 |
| `payload_digest_mismatch` | 事件投影 `{id,type,payload}` 与审计条目不一致，或事件导出字段缺失 |
| `payload_digest_missing_event` | 导出缺少条目引用的事件（fail-closed） |
| 篡改正文未检出 | 实现未写 `payload_digest`；新实现必须写入 |
| `schema_invalid` | 条目字段与 `audit.schema.json` 不一致（时间格式、hash 长度） |

## 参考

- `05-audit-contract/hash-chain.spec.md`（唯一权威）、ADR-0007（payload_digest 演进）
- 夹具与向量：`05-audit-contract/tests/fixtures/`、`tools/audit-verifier --vector`
