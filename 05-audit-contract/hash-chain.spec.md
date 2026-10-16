# 哈希链规范（hash-chain.spec.md）

- **版本**：1.1.0（2026-10-16，加法演进：新增可选 `payload_digest`；v1.0 条目哈希与冻结向量不变）
- **历史**：1.0.0（2026-10-08 冻结）
- **范围**：审计链（`audit_entry`）的哈希计算、链接、验证语义
- **参考实现**：`verify.tool`（可执行，跨实现必须与本规范及测试向量一致）

---

## 1. 链结构

```
AuditEntry[n].hash = SHA256( canonical(AuditEntry[n]) )
AuditEntry[n].prev_hash = AuditEntry[n-1].hash
Genesis: AuditEntry[0].sequence = 1 且 AuditEntry[0].prev_hash = 64 × "0"
```

序列号从 1 开始、单调递增且连续（无缺口）。

## 2. 规范化规则（canonicalization）

为消除跨语言/跨实现的歧义，参与哈希的内容必须先规范化为字符串：

```
canonical = "\n".join([
  id_uuid_小写,
  sequence_十进制字符串,
  timestamp(规范 UTC 微秒, "YYYY-MM-DDTHH:MM:SS.ffffffZ"),
  actor_uuid_小写,
  action,
  resource.type,
  resource.id（uuid 小写；NULL → 空串）,
  payload(规范 JSON),
  prev_hash(小写 hex),
  payload_digest(小写 hex；可选，存在时追加为最后一行)
])
hash = 小写 hex( SHA256( UTF-8(canonical) ) )
```

- **编码**：UTF-8，不转义非 ASCII 字符
- **payload 规范 JSON**：键按字典序排序；无多余空白（`{"a":1,"b":2}`）；空 payload 视为 `{}`
- **时间戳规范化**：任意合法 ISO 8601 / RFC 3339 输入（含 `Z` 或 `±hh:mm`）先转换为 UTC，再格式化为恰好 6 位小数
- **UUID 规范化为小写**；`prev_hash`、`hash` 与 `payload_digest` 规范化为小写 hex
- **分隔符**：固定 LF（`\n`）
- **`payload_digest`（v1.1，可选）**：字段存在且非空时才作为最后一行参与规范化；缺失时保持 v1.0 公式——
  **既有条目哈希逐字节不变**（兼容性依据）。字段值必须为 64 位小写 hex（Schema 校验）

## 2.1 payload_digest 计算（v1.1）

`payload_digest` 将审计条目所引用事件的语义核心（事件 id / 类型 / 正文）纳入承诺：

```
投影 = [
  { "id": 事件 id, "type": 事件类型, "payload": 事件正文 },
  ...
]  # 按审计条目 payload.event_ids 的顺序
payload_digest = 小写 hex( SHA256( UTF-8( canonical_json(投影) ) ) )
```

- `canonical_json` 与上文 payload 规范 JSON 相同（键排序、无空白、不转义非 ASCII）；
- 空事件列表（投影 `[]`）的摘要为冻结常量
  `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`；
- 事件正文、事件类型或事件 id 任一被篡改，复算摘要即不匹配（`payload_digest_mismatch`）；
- **大对象内容寻址**：若事件 payload 引用外部大内容（文件/消息体等），应在事件 payload 中携带
  内容摘要（如 `content_sha256`），审计条目 digest 随事件 payload 一并承诺该摘要——
  外部内容篡改可由内容摘要与 digest 两级检出。

## 3. 测试向量

### 3.1 创世条目（v1.0 公式）

输入条目：

```json
{
  "id": "018f2e3a-1234-7000-8000-000000000001",
  "sequence": 1,
  "timestamp": "2026-10-08T09:00:00.000000+00:00",
  "actor": "018f2e3a-0000-7000-8000-000000000001",
  "action": "voucher.create",
  "resource": { "type": "voucher", "id": "018f2e3a-9999-7000-8000-000000000002" },
  "payload": { "amount": "100.00", "currency": "CNY" },
  "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

规范化字符串（各行以 LF 连接）：

```
018f2e3a-1234-7000-8000-000000000001
1
2026-10-08T09:00:00.000000Z
018f2e3a-0000-7000-8000-000000000001
voucher.create
voucher
018f2e3a-9999-7000-8000-000000000002
{"amount":"100.00","currency":"CNY"}
0000000000000000000000000000000000000000000000000000000000000000
```

**期望哈希**：

```
447c6e299d9adaec35d89e273b15d28752eeaac4674000b5df88d2e53a087410
```

> 任何实现（Rust/Java/Python/…）对本向量必须算出相同哈希；不一致即为实现缺陷。

### 3.2 含 payload_digest 的向量（v1.1 公式）

事件投影输入（digest 来源）：

```json
[
  {
    "id": "018f2e3a-aaaa-7000-8000-000000000001",
    "type": "voucher.created",
    "payload": { "amount": "100.00", "currency": "CNY" }
  }
]
```

输入条目：在 3.1 的条目上追加

```json
{ "payload_digest": "b3a88a20915cc5a9a3c4a5c05e90b32be38b4e3ecafdc5f94d0fe878fb402913" }
```

规范化字符串（在 3.1 的 10 行之后追加第 11 行）：

```
b3a88a20915cc5a9a3c4a5c05e90b32be38b4e3ecafdc5f94d0fe878fb402913
```

**期望哈希**：

```
fb4cc4620dba2250bca59861f177e5406e19b35136582386d0e15fb96bb98969
```

> 实现须同时通过 3.1（无 digest，v1.0 公式）与 3.2（有 digest，v1.1 公式）两个向量。

## 4. 验证算法

```
verify_chain(entries):
  1) 序列连续：entries[n].sequence == entries[n-1].sequence + 1，且首条 == 1
  2) 哈希链衔接：entries[n].prev_hash == entries[n-1].hash（首条 == 64×"0"）
  3) 逐条重算：compute_hash(entry) == entry.hash
  4) 若提供事件导出：对含 payload_digest 的条目按 payload.event_ids 复算摘要并比对；
     无 digest 条目跳过（v1.0 兼容）
  任一失败 → 验证失败（err），返回具体错误（sequence + 类型）
```

映射到错误类型（`verify.tool` 输出）：

| 错误类型 | 触发条件 | 含义 |
|----------|----------|------|
| `sequence_gap` | 序列不连续 | 记录缺失或被删除 |
| `prev_hash_mismatch` | 链接断裂（含创世不正确） | 历史被替换或拼接 |
| `invalid_hash` | 重算哈希 ≠ 存储哈希 | 条目内容被篡改 |
| `empty_chain` | 无条目 | 无审计数据 |
| `payload_digest_mismatch` | 事件正文复算摘要 ≠ 条目 digest（需 `--events`） | 事件正文被篡改 |
| `payload_digest_missing_event` | 事件导出缺少被引用事件（需 `--events`） | 无法复算，视为验证失败 |

## 5. 篡改检测语义

- 修改任意条目的任意字段 → 该条 `invalid_hash`
- 修改条目的 `payload_digest` 字段 → 该条 `invalid_hash`（digest 自身纳入哈希）
- 修改事件正文而审计条目不变 → 用事件导出复算 `payload_digest` 时检出（`payload_digest_mismatch`）
- v1.0 条目（无 `payload_digest`）仍可验证，但事件正文不受该条承诺保护（已知边界）
- 修改历史条目并顺链重算后续 hash → 仍会改变被修改条目的 hash；除非重算全链（需要同时覆盖链头，链头 hash 应被外部锚定/签名）
- 删除中间条目 → `sequence_gap` + `prev_hash_mismatch`
- 替换整链 → 需外部锚定（定期将链头 hash 与签名发布到独立位置）方可检测，属部署策略

## 6. 签名（可选）

`signature` 字段（CA 签名）不属于 v1 链验证范围；验证工具必须**忽略**该字段并照常验证链。

## 7. 参考实现（Rust）

```rust
// verify.rs
pub fn verify_chain(entries: &[AuditEntry]) -> Result<(), ChainError> {
    // 1. 检查序列号连续
    for i in 1..entries.len() {
        if entries[i].sequence != entries[i-1].sequence + 1 {
            return Err(ChainError::SequenceGap {
                expected: entries[i-1].sequence + 1,
                actual: entries[i].sequence,
            });
        }
    }

    // 2. 检查哈希链
    for i in 1..entries.len() {
        let expected_prev_hash = &entries[i-1].hash;
        if &entries[i].prev_hash != expected_prev_hash {
            return Err(ChainError::HashMismatch {
                sequence: entries[i].sequence,
                expected: expected_prev_hash.clone(),
                actual: entries[i].prev_hash.clone(),
            });
        }
    }

    // 3. 检查每条记录的哈希
    for entry in entries {
        let computed = compute_hash(entry);
        if computed != entry.hash {
            return Err(ChainError::InvalidHash {
                sequence: entry.sequence,
            });
        }
    }

    Ok(())
}
```

Python 参考实现见 `verify.tool`（含 `--self-test`）：

```bash
verify.tool chain.json                    # 验证
verify.tool chain.json --events E.json    # 复算 payload_digest（事件正文篡改检出）
verify.tool --self-test                   # 自测（合法/篡改/缺口/断链/payload_digest）
```
