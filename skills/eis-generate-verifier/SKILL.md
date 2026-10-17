---
name: eis-generate-verifier
description: Use when implementing an independent EIS audit-chain verifier in another language (Java, Go, TypeScript, Rust), when porting the reference verifier without reading Python sources, or when a ported verifier fails the frozen vectors
---

# EIS 独立验证器生成

## 触发条件

- 用目标语言重写 EIS 审计链验证器（技术中立验收、供应链隔离）；
- 移植实现需要对照 §3.1/§3.2 冻结向量；
- 移植后向量不通过，需要定位规范化差异。

## 输入（只读；不得依赖 Python 参考实现源码）

- `05-audit-contract/hash-chain.spec.md`：§2 规范化、§2.1 digest、§3 冻结向量全文；
- `05-audit-contract/audit.schema.json`：条目结构；
- `05-audit-contract/tests/fixtures/`：合法 / 篡改 / 断链 / 缺口夹具。

## 步骤

1. 按规范 §2 实现规范字符串：确定性键排序、无多余空白、UTF-8 不转义非 ASCII、UTC 微秒时间戳、UUID/hex 小写、固定 LF 分隔。禁止直接把语言默认 JSON 序列化结果拿去哈希。
2. 实现条目哈希与链校验：`prev_hash` 衔接、`sequence` 连续、逐条重算（不能只验字段格式）。
3. 实现 `payload_digest`（§2.1）：仅当字段存在且非空时作为规范字符串最后一行；事件投影 `[{id,type,payload}]` 的规范 JSON 后 SHA-256；空投影为冻结常量 `4f53cda1…`。
4. 把 §3.1/§3.2 向量作为单元测试常量（genesis 期望 `447c6e29…` 全值抄自规范），并覆盖夹具正/负例：合法通过；正文、digest 字段、断链、缺口必须失败且错误类型可区分。
5. 跨语言注意数字与 Unicode：整数/小数按规范 JSON 的字面表示、字符串不转义非 ASCII、`null` 与缺省不混淆。

## 验证

```bash
# 参考实现语义对照（仅在移植实现完成后用于交叉验证，不作为移植实现的一部分）
python3 05-audit-contract/verify.tool --self-test
python3 tools/audit-verifier --vector
```

移植实现的验收：自有测试复现 §3.1/§3.2 全部断言，并对 `05-audit-contract/tests/fixtures/` 得到与参考实现一致的正/负结论。

## 失败修复

| 症状 | 常见原因 |
|------|---------|
| genesis 哈希不一致 | 键排序/分隔符/尾随换行与 §2 不一致 |
| 含 digest 条目不一致 | digest 行位置错误（必须是最后一行）或事件投影序列化差异 |
| 合法链被判失败 | 时间戳精度/时区归一化、Unicode 转义差异 |
| 篡改未检出 | 缺少逐条重算或 `prev_hash` 衔接校验 |
| 数字比较不一致 | 规范 JSON 要求字面精度（如 `"100.00"` 字符串而非浮点） |

## 参考

- `05-audit-contract/hash-chain.spec.md` §2–§3（唯一权威）
- 交叉验证：`tools/audit-verifier`（`--vector` 与夹具语义）
