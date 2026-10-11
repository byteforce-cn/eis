# -*- coding: utf-8 -*-
"""approval 扩展命令处理器（内核注册机制，见 extensions/README.md §6）。"""
from __future__ import annotations

# 处理器只依赖内核注入的 ExtensionAPI（不使用 kernel 模块内部）

COMMANDS = {}


def register(api):
    return {
        "approval.request.submit": submit_request,
        "approval.request.decide": decide_request,
    }


def submit_request(api, payload, actor, command_id):
    operation = payload.get("operation")
    target = payload.get("target") or {}
    if not operation or not target.get("type") or not target.get("id"):
        raise api.reject("EIS-400-001", "缺少 operation / target")
    request = api.create_object("approval_request", {
        "operation": operation, "target": target, "requester": actor,
        "status": "pending", "summary": payload.get("summary"),
    }, actor)
    event = api.event("approval.request.submitted", actor, subjects=[request["id"]],
                      payload={"request_id": request["id"], "operation": operation, "target": target})
    return [event], {"type": "approval_request", "id": request["id"]}


def decide_request(api, payload, actor, command_id):
    request_id = payload.get("request_id")
    outcome = payload.get("outcome")
    if not request_id or outcome not in ("approve", "reject"):
        raise api.reject("EIS-400-001", "缺少 request_id 或 outcome 非法")
    row = api.as_of("approval_request", request_id)
    if row is None:
        raise api.reject("EIS-404-001", f"审批申请不存在: {request_id}")
    if row["status"] != "pending":
        raise api.reject("EIS-409-001", f"申请已处理: {row['status']}")
    # 规则 no_self_approval
    if row["requester"] == actor:
        raise api.reject("APR-403-001", "禁止自审：申请人与决定人相同")
    status = "approved" if outcome == "approve" else "rejected"
    api.update_object("approval_request", request_id, {"status": status}, actor,
                      extra={"decided_by": actor, "decided_at": api.ts(api.now())})
    event = api.event(f"approval.request.{status}", actor, subjects=[request_id],
                      payload={"request_id": request_id, "outcome": outcome})
    return [event], {"type": "approval_request", "id": request_id}
