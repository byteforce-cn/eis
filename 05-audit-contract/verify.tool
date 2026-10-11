#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.tool — EIS 审计链验证工具（Spec v1.0.0 参考实现）

用法:
  verify.tool CHAIN.json           验证审计链（JSON 数组、{"entries": [...]} 或 JSONL）
  verify.tool --json CHAIN.json    以 JSON 输出验证报告
  verify.tool --self-test          自测：构建链→验证通过→篡改→检出→缺口→检出

退出码:
  0  验证通过（或自测全部符合预期）
  1  验证失败（链无效 / 自测失败）
  2  用法或输入错误

规范化规则（权威定义见 05-audit-contract/hash-chain.spec.md）:
  canonical = "\\n".join([
      id(uuid, 小写), sequence(十进制字符串),
      timestamp(UTC 微秒, "YYYY-MM-DDTHH:MM:SS.ffffffZ"),
      actor(uuid, 小写), action,
      resource.type, resource.id(uuid, 小写; NULL → 空串),
      payload(规范 JSON: UTF-8、键排序、无空白),
      prev_hash(小写 hex)
  ])
  hash = sha256(utf8(canonical)) 的小写 hex
  创世: sequence == 1 且 prev_hash == 64 个 "0"
"""

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone

GENESIS_PREV_HASH = "0" * 64


# ---------------------------------------------------------------------------
# 规范化与哈希
# ---------------------------------------------------------------------------

def normalize_uuid(value) -> str:
    return str(value).lower()


def normalize_ts(value) -> str:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    dt = dt.astimezone(timezone.utc)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond:06d}Z"


def canonical_payload(payload) -> str:
    if payload is None:
        payload = {}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_string(entry: dict) -> str:
    resource = entry.get("resource") or {}
    resource_id = resource.get("id")
    fields = [
        normalize_uuid(entry.get("id", "")),
        str(entry.get("sequence", "")),
        normalize_ts(entry.get("timestamp", "")),
        normalize_uuid(entry.get("actor", "")),
        str(entry.get("action", "")),
        str(resource.get("type", "")),
        "" if resource_id is None else normalize_uuid(resource_id),
        canonical_payload(entry.get("payload")),
        str(entry.get("prev_hash", "")).lower(),
    ]
    return "\n".join(fields)


def compute_hash(entry: dict) -> str:
    return hashlib.sha256(canonical_string(entry).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------

def verify_chain(entries: list) -> list:
    """返回错误列表；空列表表示验证通过。"""
    errors = []
    if not entries:
        return [{"sequence": None, "type": "empty_chain", "message": "审计链为空"}]

    expected_seq = 1
    prev_hash = GENESIS_PREV_HASH
    for e in entries:
        seq = e.get("sequence")

        if seq != expected_seq:
            errors.append({
                "sequence": seq,
                "type": "sequence_gap",
                "message": f"期望 sequence={expected_seq}，实际={seq}",
            })

        stored_prev = str(e.get("prev_hash", "")).lower()
        if stored_prev != prev_hash:
            errors.append({
                "sequence": seq,
                "type": "prev_hash_mismatch",
                "expected": prev_hash,
                "actual": stored_prev,
                "message": "prev_hash 与上一条记录哈希不衔接",
            })

        stored_hash = str(e.get("hash", "")).lower()
        computed = compute_hash(e)
        if stored_hash != computed:
            errors.append({
                "sequence": seq,
                "type": "invalid_hash",
                "expected": computed,
                "actual": stored_hash,
                "message": "记录内容与哈希不符（可能被篡改）",
            })

        prev_hash = stored_hash or computed
        expected_seq = seq + 1 if isinstance(seq, int) else expected_seq + 1

    return errors


# ---------------------------------------------------------------------------
# 输入
# ---------------------------------------------------------------------------

def load_entries(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        raise ValueError("输入文件为空")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return [json.loads(ln) for ln in lines]

    if isinstance(data, dict):
        for key in ("entries", "chain"):
            if key in data:
                return data[key]
        raise ValueError("JSON 对象中缺少 entries/chain 字段")
    return data


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------

def _build_entry(seq: int, prev_hash: str, payload=None) -> dict:
    entry = {
        "id": "018f2e3a-1234-7000-8000-00000000000%d" % seq,
        "sequence": seq,
        "timestamp": "2026-10-08T09:00:00.%06d+00:00" % (seq * 1000),
        "actor": "018f2e3a-0000-7000-8000-000000000001",
        "action": "voucher.create",
        "resource": {
            "type": "voucher",
            "id": "018f2e3a-9999-7000-8000-000000000002",
        },
        "payload": payload if payload is not None else {"amount": "100.00", "currency": "CNY"},
        "prev_hash": prev_hash,
    }
    entry["hash"] = compute_hash(entry)
    return entry


def self_test(verbose: bool = True) -> bool:
    ok = True

    # 1) 合法链必须通过
    chain = []
    prev = GENESIS_PREV_HASH
    for seq in (1, 2, 3):
        e = _build_entry(seq, prev)
        chain.append(e)
        prev = e["hash"]
    errors = verify_chain(chain)
    if errors:
        ok = False
        if verbose:
            print("[FAIL] 合法链未通过: %s" % errors)
    elif verbose:
        print("[ok]   合法链验证通过（3 条）")

    # 2) 篡改 payload 必须被检出
    tampered = copy.deepcopy(chain)
    tampered[1]["payload"]["amount"] = "999.00"
    errors = verify_chain(tampered)
    if not any(x["type"] == "invalid_hash" for x in errors):
        ok = False
        if verbose:
            print("[FAIL] 篡改未被检出: %s" % errors)
    elif verbose:
        print("[ok]   篡改被检出（invalid_hash, sequence=%s）" % tampered[1]["sequence"])

    # 3) 序列缺口必须被检出
    gapped = [chain[0], chain[2]]
    errors = verify_chain(gapped)
    if not any(x["type"] == "sequence_gap" for x in errors):
        ok = False
        if verbose:
            print("[FAIL] 序列缺口未被检出: %s" % errors)
    elif verbose:
        print("[ok]   序列缺口被检出（sequence_gap）")

    # 4) 断链必须被检出
    broken = copy.deepcopy(chain)
    broken[2]["prev_hash"] = "f" * 64
    broken[2]["hash"] = compute_hash(broken[2])
    errors = verify_chain(broken)
    if not any(x["type"] == "prev_hash_mismatch" for x in errors):
        ok = False
        if verbose:
            print("[FAIL] 断链未被检出: %s" % errors)
    elif verbose:
        print("[ok]   断链被检出（prev_hash_mismatch）")

    if verbose:
        print("自测结果: %s" % ("通过" if ok else "失败"))
    return ok


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify.tool",
        description="EIS 审计链验证工具（Spec v1.0.0 参考实现）",
    )
    parser.add_argument("chain", nargs="?", help="审计链文件（JSON 数组 / {entries:[...]} / JSONL）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出验证报告")
    parser.add_argument("--self-test", action="store_true", help="运行自测")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    args = parser.parse_args(argv)

    if args.self_test:
        return 0 if self_test(verbose=not args.quiet) else 1

    if not args.chain:
        parser.print_usage(sys.stderr)
        print("错误: 需要提供审计链文件，或使用 --self-test", file=sys.stderr)
        return 2

    try:
        entries = load_entries(args.chain)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("错误: 无法读取审计链: %s" % exc, file=sys.stderr)
        return 2

    errors = verify_chain(entries)
    valid = not errors

    if args.json:
        report = {"valid": valid, "entries": len(entries), "errors": errors}
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif not args.quiet:
        if valid:
            print("审计链验证：通过（%d 条）" % len(entries))
        else:
            print("审计链验证：失败（%d 条，%d 个错误）" % (len(entries), len(errors)))
            for err in errors:
                print("  - [%s] sequence=%s: %s" % (err["type"], err.get("sequence"), err.get("message", "")))

    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
