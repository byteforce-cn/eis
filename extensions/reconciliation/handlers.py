# -*- coding: utf-8 -*-
"""reconciliation 扩展命令处理器（ADR-0022）。

处理器签名：(api, payload, actor, command_id) -> (events, created)。
纪律：先完成全部校验，再写对象——内核不会为处理器回滚已写入的对象。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

COMMANDS = {}

PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
NEW_CATEGORIES = {"matched", "amount_mismatch", "missing_source", "missing_target"}
RESOLVABLE_CATEGORIES = {"amount_mismatch", "missing_source", "missing_target"}
RESOLUTION_CODES = {"adjust", "write_off", "manual_match", "accept"}


def register(api):
    """返回命令类型 → 处理器映射（加载时由内核调用）。"""
    return {
        "reconciliation.run.start": start_run,
        "reconciliation.run.finish": finish_run,
        "reconciliation.difference.resolve": resolve_difference,
    }


def _decimal(api, value, field: str, *, allow_none: bool = False):
    if value is None:
        if allow_none:
            return None
        raise api.reject("EIS-400-001", f"{field} 必填")
    try:
        number = api.dec(value)
    except (InvalidOperation, ValueError):
        raise api.reject("EIS-400-001", f"{field} 非法十进制：{value!r}")
    if number < 0:
        raise api.reject("REC-400-001", f"{field} 不得为负：{value!r}")
    return number


def _integer(value, field: str, minimum: int = 0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} 必须为 >= {minimum} 的整数：{value!r}")
    return value


def _prepare_differences(api, raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise api.reject("EIS-400-001", "differences 必须为数组")
    prepared = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise api.reject("REC-400-001", f"差异 #{index} 必须为对象")
        category = item.get("category")
        if category not in NEW_CATEGORIES:
            raise api.reject(
                "REC-400-001",
                f"差异 #{index} 分类非法：{category!r}（新建仅允许 "
                "matched/amount_mismatch/missing_source/missing_target）")
        source_ref = item.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref:
            raise api.reject("REC-400-001", f"差异 #{index} 缺少 source_ref")
        target_ref = item.get("target_ref")
        if target_ref is not None and (not isinstance(target_ref, str) or not target_ref):
            raise api.reject("REC-400-001", f"差异 #{index} 的 target_ref 非法")
        amount_delta = _decimal(api, item.get("amount_delta"),
                                f"differences[{index}].amount_delta", allow_none=True)
        quantity_delta = _decimal(api, item.get("quantity_delta"),
                                  f"differences[{index}].quantity_delta", allow_none=True)
        note = item.get("note")
        if note is not None and not isinstance(note, str):
            raise api.reject("REC-400-001", f"差异 #{index} 的 note 必须为字符串")
        prepared.append({
            "category": category,
            "source_ref": source_ref,
            "target_ref": target_ref,
            "amount_delta": str(amount_delta) if amount_delta is not None else None,
            "quantity_delta": str(quantity_delta) if quantity_delta is not None else None,
            "note": note,
        })
    return prepared


def start_run(api, payload, actor, command_id):
    domain = payload.get("domain")
    period = payload.get("period")
    if not isinstance(domain, str) or not domain:
        raise api.reject("EIS-400-001", "domain 必填")
    if not isinstance(period, str) or not PERIOD_RE.match(period):
        raise api.reject("EIS-400-001", "period 必须为 YYYY-MM")
    try:
        sequence = _integer(payload.get("sequence"), "sequence", 1)
        source_count = _integer(payload.get("source_count"), "source_count")
        target_count = _integer(payload.get("target_count"), "target_count")
    except ValueError as exc:
        raise api.reject("EIS-400-001", str(exc))
    tolerance_amount = _decimal(api, payload.get("tolerance_amount"), "tolerance_amount")
    tolerance_quantity = _decimal(api, payload.get("tolerance_quantity"), "tolerance_quantity")

    # 先校验全部差异，再写对象（避免半写入）
    differences = _prepare_differences(api, payload.get("differences"))

    run_key = f"{domain}:{period}:{sequence}"
    for row in api.current_objects("reconciliation_run"):
        if row.get("run_key") == run_key:
            raise api.reject(
                "REC-409-001",
                f"同一 run_key 已存在：{run_key}（run {row['id']}，状态 {row['status']}）")

    run = api.create_object("reconciliation_run", {
        "domain": domain,
        "period": period,
        "sequence": sequence,
        "run_key": run_key,
        "status": "running",
        "tolerance_amount": str(tolerance_amount),
        "tolerance_quantity": str(tolerance_quantity),
        "source_count": source_count,
        "target_count": target_count,
        "difference_count": len(differences),
        "started_at": api.ts(api.now()),
        "finished_at": None,
        "failure_reason": None,
    }, actor)

    created_differences = []
    for item in differences:
        difference = api.create_object("reconciliation_difference", {
            **item,
            "run_id": run["id"],
            "resolution_code": None,
            "resolved_by": None,
            "resolved_at": None,
        }, actor)
        created_differences.append(difference)

    subjects = [run["id"], *(d["id"] for d in created_differences)]
    event = api.event("reconciliation.run.started", actor, subjects, {
        "run_id": run["id"],
        "run_key": run_key,
        "domain": domain,
        "period": period,
        "sequence": sequence,
        "difference_count": len(created_differences),
    })
    return [event], {"type": "reconciliation_run", "id": run["id"]}


def finish_run(api, payload, actor, command_id):
    run_id = payload.get("run_id")
    status = payload.get("status")
    if not isinstance(run_id, str) or not run_id:
        raise api.reject("EIS-400-001", "run_id 必填")
    if status not in ("succeeded", "failed"):
        raise api.reject("EIS-400-001", "status 必须为 succeeded/failed")
    row = api.as_of("reconciliation_run", run_id)
    if row is None:
        raise api.reject("EIS-404-001", f"对账运行不存在：{run_id}")
    if row["status"] != "running":
        raise api.reject("REC-409-002", f"运行已终态：{row['status']}")
    failure_reason = payload.get("failure_reason")
    if status == "failed" and (not isinstance(failure_reason, str) or not failure_reason):
        raise api.reject("REC-400-002", "failed 必须给出 failure_reason")

    api.update_object("reconciliation_run", run_id, {
        "status": status,
        "finished_at": api.ts(api.now()),
        "failure_reason": failure_reason if status == "failed" else None,
    }, actor)
    event = api.event("reconciliation.run.finished", actor, [run_id], {
        "run_id": run_id,
        "run_key": row["run_key"],
        "status": status,
        "failure_reason": failure_reason if status == "failed" else None,
    })
    return [event], {"type": "reconciliation_run", "id": run_id}


def resolve_difference(api, payload, actor, command_id):
    difference_id = payload.get("difference_id")
    resolution_code = payload.get("resolution_code")
    if not isinstance(difference_id, str) or not difference_id:
        raise api.reject("EIS-400-001", "difference_id 必填")
    if resolution_code not in RESOLUTION_CODES:
        raise api.reject(
            "REC-400-001",
            f"resolution_code 非法：{resolution_code!r}（adjust/write_off/manual_match/accept）")
    row = api.as_of("reconciliation_difference", difference_id)
    if row is None:
        raise api.reject("EIS-404-001", f"差异记录不存在：{difference_id}")
    if row["category"] not in RESOLVABLE_CATEGORIES:
        raise api.reject(
            "REC-409-003",
            f"差异不可处理：{row['category']}（仅 amount_mismatch/missing_source/missing_target）")
    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        raise api.reject("EIS-400-001", "note 必须为字符串")

    category = "written_off" if resolution_code == "write_off" else "resolved"
    api.update_object("reconciliation_difference", difference_id, {
        "category": category,
        "resolution_code": resolution_code,
        "resolved_by": actor,
        "resolved_at": api.ts(api.now()),
        "note": note,
    }, actor)
    event = api.event("reconciliation.difference.resolved", actor, [difference_id], {
        "difference_id": difference_id,
        "run_id": row["run_id"],
        "category": category,
        "resolution_code": resolution_code,
    })
    return [event], {"type": "reconciliation_difference", "id": difference_id}
