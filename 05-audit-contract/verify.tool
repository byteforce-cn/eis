#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.tool — EIS 审计链验证工具（Spec v1.0.0 参考实现）

用法:
  verify.tool CHAIN.json           验证审计链（JSON 数组、{"entries": [...]} 或 JSONL）
  verify.tool CHAIN.json --events E.json   复算 payload_digest（检出事件正文篡改）
  verify.tool --json CHAIN.json    以 JSON 输出验证报告
  verify.tool --self-test          自测：合法/篡改/缺口/断链/payload_digest

退出码:
  0  验证通过（或自测全部符合预期）
  1  验证失败（链无效 / 自测失败）
  2  用法或输入错误

验证流程：先按 05-audit-contract/audit.schema.json（Draft 2020-12）逐条 Schema 校验
（错误类型 schema_invalid，含条目 index/sequence 与 JSON 路径），再做哈希/链校验
（sequence_gap / prev_hash_mismatch / invalid_hash）。畸形输入转为结构化错误，不抛异常。

规范化规则（权威定义见 05-audit-contract/hash-chain.spec.md）:
  canonical = "\\n".join([
      id(uuid, 小写), sequence(十进制字符串),
      timestamp(UTC 微秒, "YYYY-MM-DDTHH:MM:SS.ffffffZ"),
      actor(uuid, 小写), action,
      resource.type, resource.id(uuid, 小写; NULL → 空串),
      payload(规范 JSON: UTF-8、键排序、无空白),
      prev_hash(小写 hex),
      payload_digest(可选，v1.1：存在时追加为最后一行；缺失时保持 v1.0 规范化)
  ])
  hash = sha256(utf8(canonical)) 的小写 hex
  payload_digest = sha256(canonical JSON of [{"id","type","payload"} for each event])
  创世: sequence == 1 且 prev_hash == 64 个 "0"
"""

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover — jsonschema 缺失时降级为仅哈希校验
    Draft202012Validator = None
    FormatChecker = None

GENESIS_PREV_HASH = "0" * 64
# 零事件投影（[]）的 SHA-256，冻结常量（与 hash-chain.spec.md §3 第二条向量一致）
EMPTY_PAYLOAD_DIGEST = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
AUDIT_SCHEMA_PATH = Path(__file__).resolve().parent / "audit.schema.json"


def _load_entry_validator():
    if Draft202012Validator is None:
        return None
    with open(AUDIT_SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    return Draft202012Validator(schema, format_checker=FormatChecker())


_ENTRY_VALIDATOR = _load_entry_validator()
SCHEMA_VALIDATION_ENABLED = _ENTRY_VALIDATOR is not None


def warn_if_degraded() -> None:
    """jsonschema 不可用时向 stderr 打一行明确警告；不影响退出码语义。"""
    if not SCHEMA_VALIDATION_ENABLED:  # pragma: no cover
        print("警告: 未安装 jsonschema，审计链验证已降级为仅哈希校验；"
              "Schema 完整性未验证（请 pip install jsonschema）", file=sys.stderr)


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
    # v1.1 可选字段：仅在存在时追加，v1.0 条目哈希逐字节不变
    digest = entry.get("payload_digest")
    if digest:
        fields.append(str(digest).lower())
    return "\n".join(fields)


def payload_projection(events) -> list:
    """事件投影：仅绑定语义核心（事件 id / 类型 / 正文），不含时间戳等易变字段。"""
    return [{"id": ev.get("id"), "type": ev.get("type"), "payload": ev.get("payload")}
            for ev in (events or []) if isinstance(ev, dict)]


def compute_payload_digest(events) -> str:
    """payload_digest = sha256(canonical_json(事件投影列表))，小写 hex；空列表为冻结常量。"""
    return hashlib.sha256(canonical_payload(payload_projection(events)).encode("utf-8")).hexdigest()


def verify_payload_digests(entries: list, events: list) -> list:
    """按条目 payload_digest 复算事件投影摘要；无 digest 条目跳过（v1.0 兼容）。"""
    by_id = {str(ev.get("id")): ev for ev in (events or []) if isinstance(ev, dict)}
    errors = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("payload_digest"):
            continue
        event_ids = ((entry.get("payload") or {}).get("event_ids")) or []
        missing = [eid for eid in event_ids if str(eid) not in by_id]
        if missing:
            errors.append({"sequence": entry.get("sequence"),
                           "type": "payload_digest_missing_event", "event_id": missing[0],
                           "message": "事件导出缺少被引用事件，无法复算摘要"})
            continue
        expected = compute_payload_digest([by_id[str(eid)] for eid in event_ids])
        actual = str(entry["payload_digest"]).lower()
        if actual != expected:
            errors.append({"sequence": entry.get("sequence"),
                           "type": "payload_digest_mismatch",
                           "expected": expected, "actual": actual,
                           "message": "事件正文与审计条目 payload_digest 不符（可能被篡改）"})
    return errors


def compute_hash(entry: dict) -> str:
    return hashlib.sha256(canonical_string(entry).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------

def schema_errors(entries: list) -> list:
    """逐条按 audit.schema.json 校验（先于哈希/链校验）；返回 schema_invalid 错误列表。"""
    if _ENTRY_VALIDATOR is None:
        return []
    errors = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append({"sequence": None, "index": index, "type": "schema_invalid",
                           "path": "$", "message": "条目不是 JSON 对象"})
            continue
        seq = entry.get("sequence")
        for err in _ENTRY_VALIDATOR.iter_errors(entry):
            path = "$" + "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}" for part in err.absolute_path)
            errors.append({"sequence": seq, "index": index, "type": "schema_invalid",
                           "path": path, "message": f"{path}: {err.message}"})
    return errors


def verify_chain(entries: list) -> list:
    """返回错误列表；空列表表示验证通过。先 Schema 校验，后哈希/链校验。"""
    errors = []
    if not entries:
        return [{"sequence": None, "type": "empty_chain", "message": "审计链为空"}]

    errors.extend(schema_errors(entries))

    expected_seq = 1
    prev_hash = GENESIS_PREV_HASH
    for e in entries:
        if not isinstance(e, dict):
            errors.append({"sequence": None, "type": "malformed_entry",
                           "message": "条目不是 JSON 对象，无法进行链校验"})
            continue
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
        try:
            computed = compute_hash(e)
        except (ValueError, TypeError) as exc:
            errors.append({
                "sequence": seq,
                "type": "invalid_hash",
                "actual": stored_hash,
                "message": f"条目字段畸形，无法计算哈希: {exc}",
            })
            computed = None
        if computed is not None and stored_hash != computed:
            errors.append({
                "sequence": seq,
                "type": "invalid_hash",
                "expected": computed,
                "actual": stored_hash,
                "message": "记录内容与哈希不符（可能被篡改）",
            })

        prev_hash = stored_hash or computed or prev_hash
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
        for key in ("entries", "chain", "events"):
            if key in data:
                return data[key]
        raise ValueError("JSON 对象中缺少 entries/chain/events 字段")
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

    # 5) 缺必填字段但哈希自洽 → schema_invalid（仅重算哈希会漏判）
    if SCHEMA_VALIDATION_ENABLED:
        missing = copy.deepcopy(chain)
        del missing[0]["action"]
        missing[0]["hash"] = compute_hash(missing[0])
        errors = verify_chain(missing)
        if not any(x["type"] == "schema_invalid" for x in errors):
            ok = False
            if verbose:
                print("[FAIL] 缺必填字段未被检出: %s" % errors)
        elif verbose:
            print("[ok]   缺必填字段被检出（schema_invalid）")
    elif verbose:  # pragma: no cover
        print("[skip] 缺必填字段检测（jsonschema 缺失，Schema 校验已降级）")

    # 6) 畸形 timestamp → 结构化错误（不抛异常）
    bad_ts = copy.deepcopy(chain)
    bad_ts[1]["timestamp"] = "not-a-date"
    try:
        errors = verify_chain(bad_ts)
        if not any(x["type"] in ("schema_invalid", "invalid_hash") for x in errors):
            ok = False
            if verbose:
                print("[FAIL] 畸形 timestamp 未报错: %s" % errors)
        elif verbose:
            print("[ok]   畸形 timestamp 返回结构化错误")
    except Exception as exc:  # noqa: BLE001 — 任何异常都视为未按结构化处理
        ok = False
        if verbose:
            print("[FAIL] 畸形 timestamp 抛出异常: %r" % exc)

    # 7) payload_digest（v1.1 加法演进）：含摘要链通过 / 零事件冻结常量 / 摘要纳入哈希
    digest_events = [
        {"id": "018f2e3a-1234-7000-8000-0000000000e1", "type": "voucher.created",
         "payload": {"amount": "100.00", "currency": "CNY"}},
        {"id": "018f2e3a-1234-7000-8000-0000000000e2", "type": "voucher.posted",
         "payload": {"amount": "100.00", "currency": "CNY"}},
    ]
    digest_chain, prev = [], GENESIS_PREV_HASH
    for seq, evs in ((1, digest_events[:1]), (2, digest_events[1:]), (3, [])):
        entry = _build_entry(seq, prev, payload={"event_ids": [ev["id"] for ev in evs]})
        entry["payload_digest"] = compute_payload_digest(evs)
        entry["hash"] = compute_hash(entry)
        digest_chain.append(entry)
        prev = entry["hash"]
    errors = verify_chain(digest_chain)
    if errors:
        ok = False
        if verbose:
            print("[FAIL] 含 payload_digest 的链未通过: %s" % errors)
    elif verbose:
        print("[ok]   含 payload_digest 的链验证通过（3 条）")

    if compute_payload_digest([]) != EMPTY_PAYLOAD_DIGEST:
        ok = False
        if verbose:
            print("[FAIL] 零事件摘要不等于冻结常量: %s" % compute_payload_digest([]))
    elif verbose:
        print("[ok]   零事件摘要为冻结常量（%s…）" % EMPTY_PAYLOAD_DIGEST[:8])

    if verify_payload_digests(digest_chain, digest_events):
        ok = False
        if verbose:
            print("[FAIL] 未篡改事件正文被误报: %s" % verify_payload_digests(digest_chain, digest_events))
    elif verbose:
        print("[ok]   未篡改事件正文通过（摘要复算一致）")

    tampered_events = copy.deepcopy(digest_events)
    tampered_events[1]["payload"]["amount"] = "999.00"
    perrors = verify_payload_digests(digest_chain, tampered_events)
    if not any(x["type"] == "payload_digest_mismatch" for x in perrors):
        ok = False
        if verbose:
            print("[FAIL] 事件正文篡改未被检出: %s" % perrors)
    elif verbose:
        print("[ok]   事件正文篡改被检出（payload_digest_mismatch, sequence=2）")

    digest_tampered = copy.deepcopy(digest_chain)
    digest_tampered[0]["payload_digest"] = "0" * 64
    errors = verify_chain(digest_tampered)
    if not any(x["type"] == "invalid_hash" for x in errors):
        ok = False
        if verbose:
            print("[FAIL] payload_digest 字段篡改未被检出: %s" % errors)
    elif verbose:
        print("[ok]   payload_digest 字段篡改被检出（invalid_hash）")

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
    parser.add_argument("--events", help="事件导出文件（JSON 数组 / {events:[...]}）；用于复算 payload_digest")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出验证报告")
    parser.add_argument("--self-test", action="store_true", help="运行自测")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    args = parser.parse_args(argv)

    warn_if_degraded()

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
    if args.events:
        try:
            events = load_entries(args.events)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print("错误: 无法读取事件导出: %s" % exc, file=sys.stderr)
            return 2
        errors = errors + verify_payload_digests(entries, events)
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
