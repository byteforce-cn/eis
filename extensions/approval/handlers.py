# -*- coding: utf-8 -*-
"""approval 扩展命令处理器（内核注册机制，见 extensions/README.md §6）。

简单模式：submit → decide（v1.0.0 既有语义，不变）。
区块模式：submit(sections) → section.confirm/reject/complete → 全部就绪 ⟺ 单据完成；
        rejected 后 resubmit 重置全部确认；无人确认前可 withdraw。
"""
from __future__ import annotations

COMMANDS = {}

# 区块命令的授权在处理器内按属主判定（permission = approval.section.confirm.<owner>）
DEFERRED_AUTHZ = {"approval.section.confirm", "approval.section.reject"}

READY_STATES = ("confirmed", "not_applicable")


def register(api):
    return {
        "approval.request.submit": submit_request,
        "approval.request.decide": decide_request,
        "approval.section.confirm": confirm_section,
        "approval.section.reject": reject_section,
        "approval.section.complete": complete_section,
        "approval.request.resubmit": resubmit_request,
        "approval.request.withdraw": withdraw_request,
    }


# ---------------------------------------------------------------------------
# 查询帮助
# ---------------------------------------------------------------------------
def _now(api):
    return api.ts(api.now())


def _request(api, request_id):
    row = api.as_of("approval_request", request_id) if request_id else None
    if row is None:
        raise api.reject("EIS-404-001", f"审批申请不存在: {request_id}")
    return row


def _section(api, section_id):
    row = api.as_of("approval_section", section_id) if section_id else None
    if row is None:
        raise api.reject("EIS-404-001", f"审批区块不存在: {section_id}")
    return row


def _sections_of(api, request_id):
    return [r for r in api.current_objects("approval_section") if r["request_id"] == request_id]


def _all_ready(sections):
    return bool(sections) and all(s["state"] in READY_STATES for s in sections)


def _require_owner_permission(api, actor, owner):
    permission = f"approval.section.confirm.{owner}"
    decision = api.check_permission(actor, permission)
    if not decision.get("allowed"):
        raise api.reject("APR-403-002",
                         f"区块属主权限不匹配：需要 {permission}",
                         decision.get("reason_code"))


def _complete_if_ready(api, request, actor, events):
    if _all_ready(_sections_of(api, request["id"])):
        api.update_object("approval_request", request["id"], {"status": "approved"}, actor)
        events.append(api.event("approval.request.completed", actor, [request["id"]],
                                {"request_id": request["id"]}))


def _require_block_mode(request):
    if not request.get("section_ids"):
        raise api.reject("APR-409-002", "该申请是简单流程，请使用 approval.request.decide")


# ---------------------------------------------------------------------------
# 提交 / 简单决定
# ---------------------------------------------------------------------------
def submit_request(api, payload, actor, command_id):
    operation = payload.get("operation")
    target = payload.get("target") or {}
    if not operation or not target.get("type") or not target.get("id"):
        raise api.reject("EIS-400-001", "缺少 operation / target")
    raw_sections = payload.get("sections") or []
    if not isinstance(raw_sections, list):
        raise api.reject("EIS-400-001", "sections 必须为数组")
    keys: set[str] = set()
    for spec in raw_sections:
        key, title, owner = spec.get("key"), spec.get("title"), spec.get("owner")
        if not isinstance(key, str) or not key or not isinstance(title, str) or not title.strip() \
                or not isinstance(owner, str) or not owner:
            raise api.reject("EIS-400-001", "区块必须包含 key/title/owner")
        if key in keys:
            raise api.reject("APR-409-006", f"区块 key 重复: {key}")
        keys.add(key)

    request_id = api.new_id()
    created_sections = {}
    sections = []
    for spec in raw_sections:
        applicable = bool(spec.get("applicable", True))
        section = api.create_object("approval_section", {
            "request_id": request_id, "key": spec["key"], "title": spec["title"],
            "owner": spec["owner"], "applicable": applicable,
            "state": "pending" if applicable else "not_applicable",
            "confirmer": None, "decided_at": None, "comment": None,
        }, actor)
        created_sections[spec["key"]] = section["id"]
        sections.append(section)

    request = api.create_object("approval_request", {
        "id": request_id, "operation": operation, "target": target, "requester": actor,
        "status": "pending", "summary": payload.get("summary"),
        "section_ids": [s["id"] for s in sections], "withdrawn_reason": None,
    }, actor)
    events = [api.event("approval.request.submitted", actor, subjects=[request["id"]],
                        payload={"request_id": request["id"], "operation": operation, "target": target})]
    if sections:
        _complete_if_ready(api, request, actor, events)
    return events, {"type": "approval_request", "id": request["id"], "sections": created_sections}


def decide_request(api, payload, actor, command_id):
    request_id = payload.get("request_id")
    outcome = payload.get("outcome")
    if not request_id or outcome not in ("approve", "reject"):
        raise api.reject("EIS-400-001", "缺少 request_id 或 outcome 非法")
    row = _request(api, request_id)
    if row.get("section_ids"):
        raise api.reject("APR-409-002", "该申请是区块流程，请使用 approval.section.confirm/reject")
    if row["status"] != "pending":
        raise api.reject("EIS-409-001", f"申请已处理: {row['status']}")
    # 规则 no_self_approval
    if row["requester"] == actor:
        raise api.reject("APR-403-001", "禁止自审：申请人与决定人相同")
    status = "approved" if outcome == "approve" else "rejected"
    api.update_object("approval_request", request_id, {"status": status}, actor,
                      extra={"decided_by": actor, "decided_at": _now(api)})
    event = api.event(f"approval.request.{status}", actor, subjects=[request_id],
                      payload={"request_id": request_id, "outcome": outcome})
    return [event], {"type": "approval_request", "id": request_id}


# ---------------------------------------------------------------------------
# 区块流转
# ---------------------------------------------------------------------------
def confirm_section(api, payload, actor, command_id):
    section = _section(api, payload.get("section_id"))
    request = _request(api, section["request_id"])
    _require_block_mode(request)
    if request["status"] != "pending":
        raise api.reject("APR-409-003", f"单据状态不允许确认: {request['status']}")
    if section["state"] != "pending":
        raise api.reject("APR-409-003", f"区块状态不允许确认: {section['state']}")
    _require_owner_permission(api, actor, section["owner"])
    api.update_object("approval_section", section["id"], {
        "state": "confirmed", "confirmer": actor, "decided_at": _now(api),
        "comment": payload.get("comment"),
    }, actor)
    events = [api.event("approval.section.confirmed", actor, [section["id"]],
                        {"section_id": section["id"], "request_id": request["id"],
                         "key": section["key"], "owner": section["owner"]})]
    _complete_if_ready(api, request, actor, events)
    return events, {"type": "approval_section", "id": section["id"]}


def reject_section(api, payload, actor, command_id):
    section = _section(api, payload.get("section_id"))
    request = _request(api, section["request_id"])
    _require_block_mode(request)
    if request["status"] != "pending":
        raise api.reject("APR-409-003", f"单据状态不允许打回: {request['status']}")
    if section["state"] != "pending":
        raise api.reject("APR-409-003", f"区块状态不允许打回: {section['state']}")
    _require_owner_permission(api, actor, section["owner"])
    api.update_object("approval_section", section["id"], {
        "state": "rejected", "confirmer": actor, "decided_at": _now(api),
        "comment": payload.get("comment"),
    }, actor)
    api.update_object("approval_request", request["id"], {"status": "rejected"}, actor)
    events = [
        api.event("approval.section.rejected", actor, [section["id"]],
                  {"section_id": section["id"], "request_id": request["id"], "key": section["key"]}),
        api.event("approval.request.rejected", actor, [request["id"]], {"request_id": request["id"]}),
    ]
    return events, {"type": "approval_section", "id": section["id"]}


def complete_section(api, payload, actor, command_id):
    section = _section(api, payload.get("section_id"))
    request = _request(api, section["request_id"])
    _require_block_mode(request)
    if section["owner"] != "system":
        raise api.reject("APR-403-002", "仅 system 属主区块可回写（approval.section.complete）")
    if request["status"] != "pending":
        raise api.reject("APR-409-003", f"单据状态不允许回写: {request['status']}")
    if section["state"] != "pending":
        raise api.reject("APR-409-003", f"区块状态不允许回写: {section['state']}")
    api.update_object("approval_section", section["id"], {
        "state": "confirmed", "confirmer": actor, "decided_at": _now(api),
        "comment": payload.get("comment"),
    }, actor)
    events = [api.event("approval.section.completed", actor, [section["id"]],
                        {"section_id": section["id"], "request_id": request["id"]})]
    _complete_if_ready(api, request, actor, events)
    return events, {"type": "approval_section", "id": section["id"]}


def resubmit_request(api, payload, actor, command_id):
    request = _request(api, payload.get("request_id"))
    _require_block_mode(request)
    if request["requester"] != actor:
        raise api.reject("APR-403-003", "仅发起方可重提")
    if request["status"] != "rejected":
        raise api.reject("APR-409-004", f"仅已驳回单据可重提: {request['status']}")
    reset = 0
    for section in _sections_of(api, request["id"]):
        if section["state"] in ("confirmed", "rejected"):
            api.update_object("approval_section", section["id"], {
                "state": "pending", "confirmer": None, "decided_at": None, "comment": None,
            }, actor)
            reset += 1
    api.update_object("approval_request", request["id"], {"status": "pending"}, actor)
    event = api.event("approval.request.resubmitted", actor, [request["id"]],
                      {"request_id": request["id"], "reset_sections": reset})
    return [event], {"type": "approval_request", "id": request["id"]}


def withdraw_request(api, payload, actor, command_id):
    request = _request(api, payload.get("request_id"))
    _require_block_mode(request)
    if request["requester"] != actor:
        raise api.reject("APR-403-003", "仅发起方可撤回")
    if request["status"] != "pending":
        raise api.reject("APR-409-003", f"单据状态不允许撤回: {request['status']}")
    confirmed = [s for s in _sections_of(api, request["id"]) if s["state"] == "confirmed"]
    if confirmed:
        raise api.reject("APR-409-005", f"已有 {len(confirmed)} 个区块确认，不可撤回")
    api.update_object("approval_request", request["id"], {
        "status": "withdrawn", "withdrawn_reason": payload.get("reason"),
    }, actor)
    event = api.event("approval.request.withdrawn", actor, [request["id"]],
                      {"request_id": request["id"], "reason": payload.get("reason")})
    return [event], {"type": "approval_request", "id": request["id"]}
