# -*- coding: utf-8 -*-
"""hr 扩展命令处理器（内核注册机制，见 extensions/README.md §6）。

处理器只通过内核注入的 ExtensionAPI 访问对象存储/事件/授权，不依赖内核源码。
"""
from __future__ import annotations

import re
from datetime import datetime

COMMANDS = {}

# 证件散列只在受理时参与校验/防重，命令记录中脱敏（幂等指纹仍基于原文）
SENSITIVE_FIELDS = {
    "hr.employee.create": ("id_number_hash",),
}

NON_TERMINAL = ("pending_onboarding", "active")
TERMINAL = ("terminated", "cancelled")

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,31}$")


def register(api):
    return {
        "hr.org.unit.define": define_org_unit,
        "hr.org.unit.update": update_org_unit,
        "hr.position.define": define_position,
        "hr.position.update": update_position,
        "hr.employee.create": create_employee,
        "hr.employee.update": update_employee,
        "hr.employee.activate": activate_employee,
        "hr.employee.cancel": cancel_employee,
        "hr.assignment.assign": assign_position,
        "hr.assignment.end": end_assignment,
        "hr.provisioning.run": run_provisioning,
    }


# ---------------------------------------------------------------------------
# 查询与校验帮助
# ---------------------------------------------------------------------------
def _valid_date(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _today(api) -> str:
    return api.ts(api.now())[:10]


def _require_code(api, code, label):
    if not isinstance(code, str) or not CODE_RE.match(code):
        raise api.reject("HR-400-001", f"{label} 格式非法（^[A-Z0-9][A-Z0-9_-]{{1,31}}$）")


def _org_unit(api, org_unit_id, *, must_be_active=True) -> dict:
    if not org_unit_id:
        raise api.reject("HR-404-001", "组织单元不存在: None")
    org = api.as_of("hr_organization_unit", org_unit_id)
    if org is None:
        raise api.reject("HR-404-001", f"组织单元不存在: {org_unit_id}")
    if must_be_active and org["status"] != "active":
        raise api.reject("HR-409-006", f"组织单元未启用: {org['code']}")
    return org


def _position(api, position_id, *, assignable=True) -> dict:
    pos = api.as_of("hr_position", position_id) if position_id else None
    if pos is None:
        raise api.reject("HR-404-001", f"岗位不存在: {position_id}")
    if assignable and pos["status"] != "active":
        raise api.reject("HR-409-006", f"岗位不可分配: {pos['code']}（{pos['status']}）")
    return pos


def _employee(api, employee_id) -> dict:
    emp = api.as_of("hr_employee", employee_id) if employee_id else None
    if emp is None:
        raise api.reject("HR-404-001", f"员工不存在: {employee_id}")
    return emp


def _primary_assignment(api, employee_id):
    return api.find_current(
        "hr_assignment",
        lambda r: r["employee_id"] == employee_id and r["is_primary"] and r["status"] == "active",
    )


def _assert_acyclic(api, obj_type, parent_field, new_parent_id, self_id) -> None:
    """沿上级链上溯：不得回到自身，也不得碰到既有环。"""
    seen = set()
    cursor = new_parent_id
    while cursor is not None:
        if cursor == self_id:
            raise api.reject("HR-409-005", f"关系成环：{self_id} 的上级链回到自身")
        if cursor in seen:
            raise api.reject("HR-409-005", f"既有关系链已存在环：{cursor}")
        seen.add(cursor)
        node = api.as_of(obj_type, cursor)
        if node is None:
            raise api.reject("HR-404-001", f"上级对象不存在: {cursor}")
        cursor = node.get(parent_field)


def _next_employee_no(api) -> str:
    """服务端生成工号（确定性：按已建档员工数递增并跳过已占用）。"""
    used = {r["employee_no"] for r in api.objects("hr_employee")}
    n = len({r["id"] for r in api.objects("hr_employee")}) + 1
    while f"EMP-{n:06d}" in used:
        n += 1
    return f"EMP-{n:06d}"


# ---------------------------------------------------------------------------
# 组织单元
# ---------------------------------------------------------------------------
def define_org_unit(api, payload, actor, command_id):
    code, name, unit_type = payload.get("code"), payload.get("name"), payload.get("unit_type")
    _require_code(api, code, "code")
    if not isinstance(name, str) or not name.strip():
        raise api.reject("HR-400-001", "name 必填")
    if unit_type not in ("company", "department", "team"):
        raise api.reject("HR-400-001", "unit_type 非法（company/department/team）")
    if api.find_current("hr_organization_unit", lambda r: r["code"] == code):
        raise api.reject("HR-409-001", f"组织编码已存在: {code}")
    parent_id = payload.get("parent_id")
    if parent_id is not None:
        _org_unit(api, parent_id)
    unit = api.create_object("hr_organization_unit", {
        "code": code, "name": name, "unit_type": unit_type,
        "parent_id": parent_id, "status": "active",
        "description": payload.get("description"),
    }, actor)
    event = api.event("hr.org.unit.defined", actor, [unit["id"]],
                      {"unit_id": unit["id"], "code": code, "unit_type": unit_type})
    return [event], {"type": "hr_organization_unit", "id": unit["id"]}


def update_org_unit(api, payload, actor, command_id):
    unit_id = payload.get("unit_id")
    unit = api.as_of("hr_organization_unit", unit_id) if unit_id else None
    if unit is None:
        raise api.reject("HR-404-001", f"组织单元不存在: {unit_id}")
    updates = {}
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip():
            raise api.reject("HR-400-001", "name 不能为空")
        updates["name"] = name
    if "parent_id" in payload:
        parent_id = payload["parent_id"]
        if parent_id is not None:
            _assert_acyclic(api, "hr_organization_unit", "parent_id", parent_id, unit_id)
            _org_unit(api, parent_id)  # 上级必须启用
        updates["parent_id"] = parent_id
    if "status" in payload:
        if payload["status"] not in ("active", "inactive"):
            raise api.reject("HR-400-001", "status 非法（active/inactive）")
        updates["status"] = payload["status"]
    if "description" in payload:
        updates["description"] = payload["description"]
    if not updates:
        raise api.reject("HR-400-001", "至少提供一个可更新字段")
    api.update_object("hr_organization_unit", unit_id, updates, actor)
    event = api.event("hr.org.unit.updated", actor, [unit_id], {"unit_id": unit_id})
    return [event], {"type": "hr_organization_unit", "id": unit_id}


# ---------------------------------------------------------------------------
# 岗位
# ---------------------------------------------------------------------------
def define_position(api, payload, actor, command_id):
    code, title = payload.get("code"), payload.get("title")
    org_unit_id = payload.get("org_unit_id")
    _require_code(api, code, "code")
    if not isinstance(title, str) or not title.strip():
        raise api.reject("HR-400-001", "title 必填")
    _org_unit(api, org_unit_id)  # 岗位必须挂在启用的组织单元下
    if api.find_current("hr_position", lambda r: r["code"] == code):
        raise api.reject("HR-409-001", f"岗位编码已存在: {code}")
    reports_to = payload.get("reports_to_position_id")
    if reports_to is not None:
        _position(api, reports_to)
    position = api.create_object("hr_position", {
        "code": code, "title": title, "org_unit_id": org_unit_id,
        "reports_to_position_id": reports_to, "grade": payload.get("grade"),
        "headcount": payload.get("headcount"), "status": "active",
    }, actor)
    event = api.event("hr.position.defined", actor, [position["id"]],
                      {"position_id": position["id"], "code": code, "org_unit_id": org_unit_id})
    return [event], {"type": "hr_position", "id": position["id"]}


def update_position(api, payload, actor, command_id):
    position_id = payload.get("position_id")
    position = api.as_of("hr_position", position_id) if position_id else None
    if position is None:
        raise api.reject("HR-404-001", f"岗位不存在: {position_id}")
    updates = {}
    if "title" in payload:
        if not isinstance(payload["title"], str) or not payload["title"].strip():
            raise api.reject("HR-400-001", "title 不能为空")
        updates["title"] = payload["title"]
    if "reports_to_position_id" in payload:
        reports_to = payload["reports_to_position_id"]
        if reports_to is not None:
            _assert_acyclic(api, "hr_position", "reports_to_position_id", reports_to, position_id)
            _position(api, reports_to)  # 上级岗位必须启用
        updates["reports_to_position_id"] = reports_to
    if "grade" in payload:
        updates["grade"] = payload["grade"]
    if "headcount" in payload:
        updates["headcount"] = payload["headcount"]
    if "status" in payload:
        if payload["status"] not in ("active", "frozen", "closed"):
            raise api.reject("HR-400-001", "status 非法（active/frozen/closed）")
        updates["status"] = payload["status"]
    if not updates:
        raise api.reject("HR-400-001", "至少提供一个可更新字段")
    api.update_object("hr_position", position_id, updates, actor)
    event = api.event("hr.position.updated", actor, [position_id], {"position_id": position_id})
    return [event], {"type": "hr_position", "id": position_id}


# ---------------------------------------------------------------------------
# 员工
# ---------------------------------------------------------------------------
def create_employee(api, payload, actor, command_id):
    name, hire_date = payload.get("name"), payload.get("hire_date")
    if not isinstance(name, str) or not name.strip():
        raise api.reject("HR-400-001", "name 必填")
    if not _valid_date(hire_date):
        raise api.reject("HR-400-001", "hire_date 必须为 YYYY-MM-DD")
    id_hash = payload.get("id_number_hash")
    if id_hash is not None:
        if not isinstance(id_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", id_hash):
            raise api.reject("HR-400-001", "id_number_hash 必须为小写十六进制 HMAC-SHA256（64 字符）")
        duplicate = api.find_current(
            "hr_employee",
            lambda r: r.get("id_number_hash") == id_hash and r["status"] in NON_TERMINAL,
        )
        if duplicate:
            raise api.reject("HR-409-002", f"证件散列与未终态员工重复: {duplicate['employee_no']}")
    org_unit_id = payload.get("org_unit_id")
    if org_unit_id is not None:
        _org_unit(api, org_unit_id)
    employee = api.create_object("hr_employee", {
        "employee_no": _next_employee_no(api), "name": name, "status": "pending_onboarding",
        "hire_date": hire_date, "org_unit_id": org_unit_id, "contact": payload.get("contact"),
        "id_type": payload.get("id_type"), "id_number_hash": id_hash,
        "terminated_at": None, "terminated_reason": None,
    }, actor)
    event = api.event("hr.employee.created", actor, [employee["id"]],
                      {"employee_id": employee["id"], "employee_no": employee["employee_no"]})
    return [event], {"type": "hr_employee", "id": employee["id"]}


def update_employee(api, payload, actor, command_id):
    employee = _employee(api, payload.get("employee_id"))
    if employee["status"] in TERMINAL:
        raise api.reject("HR-403-001", f"终态员工不可更新: {employee['status']}")
    updates = {}
    if "name" in payload:
        if not isinstance(payload["name"], str) or not payload["name"].strip():
            raise api.reject("HR-400-001", "name 不能为空")
        updates["name"] = payload["name"]
    if "contact" in payload:
        updates["contact"] = payload["contact"]
    if "org_unit_id" in payload:
        if payload["org_unit_id"] is not None:
            _org_unit(api, payload["org_unit_id"])
            primary = _primary_assignment(api, employee["id"])
            if primary is not None and primary["org_unit_id"] != payload["org_unit_id"]:
                raise api.reject("HR-409-006", "主组织由主岗派生：请通过任职调整，不得直接改写")
        updates["org_unit_id"] = payload["org_unit_id"]
    if not updates:
        raise api.reject("HR-400-001", "至少提供一个可更新字段")
    api.update_object("hr_employee", employee["id"], updates, actor)
    event = api.event("hr.employee.updated", actor, [employee["id"]],
                      {"employee_id": employee["id"]})
    return [event], {"type": "hr_employee", "id": employee["id"]}


def activate_employee(api, payload, actor, command_id):
    employee = _employee(api, payload.get("employee_id"))
    if employee["status"] != "pending_onboarding":
        raise api.reject("HR-403-001", f"员工状态不允许转在职: {employee['status']}")
    primary = _primary_assignment(api, employee["id"])
    if primary is None:
        raise api.reject("HR-409-004", "在职必有主岗：请先分配有效主岗")
    updates = {"status": "active", "org_unit_id": primary["org_unit_id"]}
    api.update_object("hr_employee", employee["id"], updates, actor)
    event = api.event("hr.employee.activated", actor, [employee["id"]],
                      {"employee_id": employee["id"], "employee_no": employee["employee_no"]})
    return [event], {"type": "hr_employee", "id": employee["id"]}


def cancel_employee(api, payload, actor, command_id):
    employee = _employee(api, payload.get("employee_id"))
    if employee["status"] != "pending_onboarding":
        raise api.reject("HR-403-001", f"仅待入职员工可取消: {employee['status']}")
    api.update_object("hr_employee", employee["id"], {
        "status": "cancelled", "terminated_at": api.ts(api.now()),
        "terminated_reason": payload.get("reason"),
    }, actor)
    event = api.event("hr.employee.cancelled", actor, [employee["id"]],
                      {"employee_id": employee["id"], "reason": payload.get("reason")})
    return [event], {"type": "hr_employee", "id": employee["id"]}


# ---------------------------------------------------------------------------
# 任职
# ---------------------------------------------------------------------------
def assign_position(api, payload, actor, command_id):
    employee = _employee(api, payload.get("employee_id"))
    if employee["status"] not in NON_TERMINAL:
        raise api.reject("HR-403-001", f"终态员工不可分配岗位: {employee['status']}")
    position = _position(api, payload.get("position_id"))
    _org_unit(api, position["org_unit_id"])  # 岗位所属组织必须启用
    is_primary = bool(payload.get("is_primary", False))
    if is_primary:
        existing = _primary_assignment(api, employee["id"])
        if existing is not None:
            raise api.reject("HR-409-003", f"员工已有有效主岗: {existing['id']}")
    start_date = payload.get("start_date") or _today(api)
    if not _valid_date(start_date):
        raise api.reject("HR-400-001", "start_date 必须为 YYYY-MM-DD")
    assignment = api.create_object("hr_assignment", {
        "employee_id": employee["id"], "position_id": position["id"],
        "org_unit_id": position["org_unit_id"], "is_primary": is_primary,
        "status": "active", "start_date": start_date, "end_date": None,
    }, actor)
    event = api.event("hr.assignment.assigned", actor, [assignment["id"]], {
        "assignment_id": assignment["id"], "employee_id": employee["id"],
        "position_id": position["id"], "is_primary": is_primary,
    })
    return [event], {"type": "hr_assignment", "id": assignment["id"]}


def end_assignment(api, payload, actor, command_id):
    assignment_id = payload.get("assignment_id")
    assignment = api.as_of("hr_assignment", assignment_id) if assignment_id else None
    if assignment is None:
        raise api.reject("HR-404-001", f"任职不存在: {assignment_id}")
    if assignment["status"] != "active":
        raise api.reject("HR-403-001", f"任职已结束: {assignment_id}")
    end_date = payload.get("end_date") or _today(api)
    if not _valid_date(end_date):
        raise api.reject("HR-400-001", "end_date 必须为 YYYY-MM-DD")
    api.update_object("hr_assignment", assignment_id,
                      {"status": "ended", "end_date": end_date}, actor)
    events = [api.event("hr.assignment.ended", actor, [assignment_id], {
        "assignment_id": assignment_id, "employee_id": assignment["employee_id"],
    })]
    # 结束主岗 → 在职员工进入终态（在职必有主岗不变量）
    employee = api.as_of("hr_employee", assignment["employee_id"])
    if assignment["is_primary"] and employee is not None and employee["status"] == "active":
        api.update_object("hr_employee", employee["id"], {
            "status": "terminated", "terminated_at": api.ts(api.now()),
            "terminated_reason": payload.get("reason") or "primary_assignment_ended",
        }, actor)
        events.append(api.event("hr.employee.terminated", actor, [employee["id"]],
                                {"employee_id": employee["id"],
                                 "reason": payload.get("reason") or "primary_assignment_ended"}))
    return events, {"type": "hr_assignment", "id": assignment_id}


# ---------------------------------------------------------------------------
# 账号供给
# ---------------------------------------------------------------------------
def run_provisioning(api, payload, actor, command_id):
    employee = _employee(api, payload.get("employee_id"))
    action = payload.get("action")
    if action not in ("create_account", "enable_account", "disable_account"):
        raise api.reject("HR-400-001", "action 非法（create_account/enable_account/disable_account）")
    if action in ("create_account", "enable_account") and employee["status"] not in NON_TERMINAL:
        raise api.reject("HR-409-006", f"{action} 不适用于员工状态 {employee['status']}")
    if action == "disable_account" and employee["status"] not in TERMINAL:
        raise api.reject("HR-409-006", f"{action} 仅适用于终态员工（当前 {employee['status']}）")
    task = api.create_object("hr_provisioning_task", {
        "employee_id": employee["id"], "action": action, "status": "succeeded",
        "attempts": "1", "last_error": None, "completed_at": api.ts(api.now()),
    }, actor)
    event = api.event("hr.provisioning.completed", actor, [employee["id"]],
                      {"task_id": task["id"], "employee_id": employee["id"], "action": action})
    return [event], {"type": "hr_provisioning_task", "id": task["id"]}
