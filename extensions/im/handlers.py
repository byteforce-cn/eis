# -*- coding: utf-8 -*-
"""im 扩展命令处理器（ADR-0023）。

处理器签名：(api, payload, actor, command_id) -> (events, created)。
纪律：
  - 先完成全部校验再写对象（内核不会为处理器回滚已写入的对象）；
  - 撤回/解散/移出群/改角色一律追加版本（version+1），不删除历史；
  - server_seq 是会话内扩展序列，只用于分页/已读，不与对象 version 混用。
"""
from __future__ import annotations

import re

COMMANDS = {}

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SETTINGS_FIELDS = ("pinned", "muted", "hidden")


# ---------------------------------------------------------------------------
# 通用校验
# ---------------------------------------------------------------------------
def register(api):
    return {
        "im.message.send": send_message,
        "im.message.edit": edit_message,
        "im.message.recall": recall_message,
        "im.conversation.settings.update": update_settings,
        "im.read.position.report": report_read_position,
        "im.group.create": create_group,
        "im.group.update": update_group,
        "im.group.dissolve": dissolve_group,
        "im.group.member.add": add_members,
        "im.group.member.remove": remove_member,
        "im.group.member.role.update": update_member_role,
        "im.friend.request": request_friend,
        "im.friend.request.decide": decide_friend_request,
        "im.friend.remove": remove_friend,
        "im.user.block": block_user,
        "im.user.unblock": unblock_user,
    }


def _str(api, payload: dict, field: str, *, optional: bool = False):
    value = payload.get(field)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise api.reject("EIS-400-001", f"{field} 必填且必须为非空字符串")
    return value


def _int(api, payload: dict, field: str, minimum: int = 0, *, optional: bool = False):
    value = payload.get(field)
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise api.reject("EIS-400-001", f"{field} 必须为 >= {minimum} 的整数")
    return value


def _bool(api, value, field: str) -> bool:
    if not isinstance(value, bool):
        raise api.reject("EIS-400-001", f"{field} 必须为布尔值")
    return value


def _timestamp(api, value, field: str):
    if value is None:
        return None
    if not isinstance(value, str):
        raise api.reject("EIS-400-001", f"{field} 必须为 ISO 8601 时间字符串")
    try:
        api.parse_ts(value)
    except (ValueError, TypeError):
        raise api.reject("EIS-400-001", f"{field} 不是合法时间：{value!r}")
    return value


def _external_refs(api, value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise api.reject("EIS-400-001", "external_refs 必须为数组")
    refs = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise api.reject("EIS-400-001", f"external_refs[{index}] 必须为对象")
        system = item.get("system")
        ref_id = item.get("id")
        if not isinstance(system, str) or not system:
            raise api.reject("EIS-400-001", f"external_refs[{index}].system 必填")
        if not isinstance(ref_id, str) or not ref_id:
            raise api.reject("EIS-400-001", f"external_refs[{index}].id 必填")
        refs.append({"system": system, "id": ref_id})
    return refs


# ---------------------------------------------------------------------------
# 查询辅助
# ---------------------------------------------------------------------------
def _current(api, obj_type: str, pred):
    return api.find_current(obj_type, pred)


def _find_group(api, group_id: str):
    return api.as_of("im_group", group_id)


def _require_group(api, group_id: str):
    group = _find_group(api, group_id)
    if group is None:
        raise api.reject("IM-404-001", f"群组不存在：{group_id}")
    return group


def _require_active_group(api, group_id: str):
    group = _require_group(api, group_id)
    if group["status"] != "active":
        raise api.reject("IM-409-003", f"群组已解散：{group_id}")
    return group


def _active_member(api, group_id: str, user_id: str):
    return _current(api, "im_group_member",
                    lambda r: r["group_id"] == group_id
                    and r["user_id"] == user_id and r["left_at"] is None)


def _require_role(api, group_id: str, actor: str, allowed: set[str]):
    member = _active_member(api, group_id, actor)
    if member is None or member["role"] not in allowed:
        raise api.reject(
            "IM-403-001",
            f"操作者不是 {group_id} 的授权成员（需要 {sorted(allowed)}）")
    return member


def _find_message(api, message_id: str):
    return api.as_of("im_message", message_id)


def _max_server_seq(api, chat_id: str) -> int:
    sequences = [row["server_seq"] for row in api.current_objects("im_message")
                 if row["chat_id"] == chat_id]
    return max(sequences) if sequences else 0


def _content(api, payload: dict) -> dict:
    content = payload.get("content")
    if not isinstance(content, dict):
        raise api.reject("EIS-400-001", "content 必须为对象")
    return content


def _content_digest(api, payload: dict):
    digest = payload.get("content_sha256")
    if digest is None:
        return None
    if not isinstance(digest, str) or not SHA256_RE.match(digest):
        raise api.reject("EIS-400-001", "content_sha256 必须为 64 位小写十六进制")
    return digest


# ---------------------------------------------------------------------------
# 消息
# ---------------------------------------------------------------------------
def send_message(api, payload, actor, command_id):
    chat_id = _str(api, payload, "chat_id")
    client_msg_id = _str(api, payload, "client_msg_id")
    payload_type = _int(api, payload, "payload_type")
    content = _content(api, payload)
    content_sha256 = _content_digest(api, payload)
    content_ref = _str(api, payload, "content_ref", optional=True)
    external_refs = _external_refs(api, payload.get("external_refs"))
    if not content and not content_ref:
        raise api.reject("IM-400-001", "content 或 content_ref 至少提供一个")

    group = _find_group(api, chat_id)
    if group is not None:
        if group["status"] != "active":
            raise api.reject("IM-409-003", f"群组已解散：{chat_id}")
        if _active_member(api, chat_id, actor) is None:
            raise api.reject("IM-403-001", f"发送者不是群成员：{chat_id}")

    for row in api.current_objects("im_message"):
        if row["chat_id"] == chat_id and row["client_msg_id"] == client_msg_id:
            raise api.reject(
                "IM-409-001",
                f"客户端消息 ID 已用于另一条消息：{client_msg_id}（{row['id']}）")

    server_seq = _max_server_seq(api, chat_id) + 1
    message = api.create_object("im_message", {
        "chat_id": chat_id,
        "sender_user_id": actor,
        "client_msg_id": client_msg_id,
        "server_seq": server_seq,
        "status": "normal",
        "payload_type": payload_type,
        "content": content,
        "content_sha256": content_sha256,
        "content_ref": content_ref,
        "external_refs": external_refs,
        "recalled_at": None,
        "recalled_by": None,
    }, actor)
    event = api.event("im.message.sent", actor, [message["id"]], {
        "chat_id": chat_id,
        "message_id": message["id"],
        "server_seq": server_seq,
        "payload_type": payload_type,
        "external_refs": external_refs,
    })
    return [event], {"type": "im_message", "id": message["id"]}


def edit_message(api, payload, actor, command_id):
    message_id = _str(api, payload, "message_id")
    base_version = _int(api, payload, "base_version", 1)
    content = _content(api, payload)
    payload_type = _int(api, payload, "payload_type", optional=True)
    content_sha256 = _content_digest(api, payload)
    content_ref = _str(api, payload, "content_ref", optional=True)

    row = _find_message(api, message_id)
    if row is None:
        raise api.reject("IM-404-001", f"消息不存在：{message_id}")
    if row["status"] == "recalled":
        raise api.reject("IM-409-003", f"消息已撤回，不可编辑：{message_id}")
    if row["sender_user_id"] != actor:
        raise api.reject("IM-403-003", "仅发送者可编辑消息")
    if row["version"] != base_version:
        raise api.reject(
            "IM-409-002",
            f"版本冲突：当前 {row['version']}，提交 {base_version}（最新版本见读接口）")

    updates = {"content": content}
    if payload_type is not None:
        updates["payload_type"] = payload_type
    if content_sha256 is not None:
        updates["content_sha256"] = content_sha256
    if content_ref is not None:
        updates["content_ref"] = content_ref
    updated = api.update_object("im_message", message_id, updates, actor)
    event = api.event("im.message.edited", actor, [message_id], {
        "message_id": message_id,
        "base_version": base_version,
        "new_version": updated["version"],
    })
    return [event], {"type": "im_message", "id": message_id}


def recall_message(api, payload, actor, command_id):
    message_id = _str(api, payload, "message_id")
    row = _find_message(api, message_id)
    if row is None:
        raise api.reject("IM-404-001", f"消息不存在：{message_id}")
    if row["status"] == "recalled":
        raise api.reject("IM-409-003", f"消息已撤回：{message_id}")
    if row["sender_user_id"] != actor:
        group = _find_group(api, row["chat_id"])
        member = (_active_member(api, row["chat_id"], actor)
                  if group is not None and group["status"] == "active" else None)
        if member is None or member["role"] not in {"owner", "admin"}:
            raise api.reject("IM-403-003", "仅发送者或群主/管理员可撤回消息")
    updated = api.update_object("im_message", message_id, {
        "status": "recalled",
        "recalled_at": api.ts(api.now()),
        "recalled_by": actor,
    }, actor)
    event = api.event("im.message.recalled", actor, [message_id], {
        "chat_id": updated["chat_id"],
        "message_id": message_id,
        "recalled_by": actor,
        "recalled_at": updated["recalled_at"],
        "server_seq": updated["server_seq"],
    })
    return [event], {"type": "im_message", "id": message_id}


# ---------------------------------------------------------------------------
# 会话设置与已读位点
# ---------------------------------------------------------------------------
def update_settings(api, payload, actor, command_id):
    chat_id = _str(api, payload, "chat_id")
    changes = payload.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise api.reject("EIS-400-001", "changes 必须为非空对象")
    unknown = set(changes) - set(SETTINGS_FIELDS)
    if unknown:
        raise api.reject("EIS-400-001", f"changes 含未知字段：{sorted(unknown)}")
    normalized = {field: _bool(api, changes[field], f"changes.{field}")
                  for field in changes}
    expected_version = _int(api, payload, "expected_version", 1, optional=True)

    row = _current(api, "im_conversation",
                   lambda r: r["chat_id"] == chat_id and r["user_id"] == actor)
    if expected_version is not None:
        current_version = row["version"] if row is not None else 0
        if current_version != expected_version:
            raise api.reject(
                "IM-409-002",
                f"版本冲突：当前 {current_version}，提交 {expected_version}")
    if row is None:
        data = {"chat_id": chat_id, "user_id": actor,
                "pinned": False, "muted": False, "hidden": False}
        data.update(normalized)
        row = api.create_object("im_conversation", data, actor)
        before = {field: False for field in normalized}
        after = dict(normalized)
    else:
        before = {field: row[field] for field in normalized}
        after = {field: normalized[field] for field in normalized}
        api.update_object("im_conversation", row["id"], dict(normalized), actor)
    event = api.event("im.conversation.settings-changed", actor, [row["id"]], {
        "chat_id": chat_id,
        "user_id": actor,
        "changes": [{"field": field, "before": before[field], "after": after[field]}
                    for field in normalized],
    })
    return [event], {"type": "im_conversation", "id": row["id"]}


def report_read_position(api, payload, actor, command_id):
    chat_id = _str(api, payload, "chat_id")
    endpoint_id = _str(api, payload, "endpoint_id")
    last_seq = _int(api, payload, "last_seq")
    row = _current(api, "im_read_position",
                   lambda r: r["chat_id"] == chat_id
                   and r["user_id"] == actor and r["endpoint_id"] == endpoint_id)
    if row is not None and last_seq < row["last_seq"]:
        raise api.reject(
            "IM-409-004",
            f"已读位点不得回退：当前 {row['last_seq']}，提交 {last_seq}")
    advanced = row is None or last_seq > row["last_seq"]
    reported_at = api.ts(api.now())
    if row is None:
        row = api.create_object("im_read_position", {
            "chat_id": chat_id, "user_id": actor, "endpoint_id": endpoint_id,
            "last_seq": last_seq, "reported_at": reported_at,
        }, actor)
    elif advanced:
        row = api.update_object("im_read_position", row["id"], {
            "last_seq": last_seq, "reported_at": reported_at,
        }, actor)
    event = api.event("im.read.position.reported", actor, [row["id"]], {
        "chat_id": chat_id, "user_id": actor, "endpoint_id": endpoint_id,
        "last_seq": last_seq, "advanced": advanced,
    })
    return [event], {"type": "im_read_position", "id": row["id"]}


# ---------------------------------------------------------------------------
# 群组与成员
# ---------------------------------------------------------------------------
def create_group(api, payload, actor, command_id):
    name = _str(api, payload, "name")
    avatar = _str(api, payload, "avatar", optional=True)
    member_ids = payload.get("member_ids") or []
    if not isinstance(member_ids, list):
        raise api.reject("EIS-400-001", "member_ids 必须为数组")
    members: list[str] = []
    for value in member_ids:
        if not isinstance(value, str) or not value:
            raise api.reject("EIS-400-001", f"member_ids 含非法 ID：{value!r}")
        if value != actor and value not in members:
            members.append(value)

    now = api.ts(api.now())
    group = api.create_object("im_group", {
        "name": name,
        "avatar": avatar,
        "owner_user_id": actor,
        "status": "active",
        "dissolved_at": None,
        "dissolved_by": None,
    }, actor)
    api.create_object("im_group_member", {
        "group_id": group["id"], "user_id": actor, "role": "owner",
        "mute_until": None, "joined_at": now, "left_at": None,
    }, actor)
    for user_id in members:
        api.create_object("im_group_member", {
            "group_id": group["id"], "user_id": user_id, "role": "member",
            "mute_until": None, "joined_at": now, "left_at": None,
        }, actor)
    event = api.event("im.group.created", actor, [group["id"]], {
        "group_id": group["id"],
        "chat_id": group["id"],
        "owner_user_id": actor,
        "member_ids": members,
    })
    return [event], {"type": "im_group", "id": group["id"]}


def update_group(api, payload, actor, command_id):
    group_id = _str(api, payload, "group_id")
    group = _require_active_group(api, group_id)
    _require_role(api, group_id, actor, {"owner", "admin"})
    expected_version = _int(api, payload, "expected_version", 1, optional=True)
    if expected_version is not None and group["version"] != expected_version:
        raise api.reject(
            "IM-409-002",
            f"版本冲突：当前 {group['version']}，提交 {expected_version}")
    updates = {}
    if "name" in payload:
        updates["name"] = _str(api, payload, "name")
    if "avatar" in payload:
        updates["avatar"] = _str(api, payload, "avatar", optional=True)
    if not updates:
        raise api.reject("EIS-400-001", "至少提供 name 或 avatar")
    updated = api.update_object("im_group", group_id, updates, actor)
    event = api.event("im.group.updated", actor, [group_id], {
        "group_id": group_id,
        "changes": [{"field": field, "after": value}
                    for field, value in updates.items()],
        "version": updated["version"],
    })
    return [event], {"type": "im_group", "id": group_id}


def dissolve_group(api, payload, actor, command_id):
    group_id = _str(api, payload, "group_id")
    group = _require_active_group(api, group_id)
    if group["owner_user_id"] != actor:
        raise api.reject("IM-403-001", f"仅群主可解散：{group_id}")
    updated = api.update_object("im_group", group_id, {
        "status": "dissolved",
        "dissolved_at": api.ts(api.now()),
        "dissolved_by": actor,
    }, actor)
    event = api.event("im.group.dissolved", actor, [group_id], {
        "group_id": group_id,
        "operator_user_id": actor,
        "version": updated["version"],
    })
    return [event], {"type": "im_group", "id": group_id}


def add_members(api, payload, actor, command_id):
    group_id = _str(api, payload, "group_id")
    _require_active_group(api, group_id)
    _require_role(api, group_id, actor, {"owner", "admin"})
    user_ids = payload.get("user_ids")
    if not isinstance(user_ids, list) or not user_ids:
        raise api.reject("EIS-400-001", "user_ids 必须为非空数组")
    role = payload.get("role", "member")
    if role not in {"admin", "member"}:
        raise api.reject("EIS-400-001", "role 只能为 admin/member")
    normalized_ids = []
    for user_id in user_ids:
        if not isinstance(user_id, str) or not user_id:
            raise api.reject("EIS-400-001", f"user_ids 含非法 ID：{user_id!r}")
        if user_id not in normalized_ids:
            normalized_ids.append(user_id)
    now = api.ts(api.now())
    added, skipped = [], []
    for user_id in normalized_ids:
        existing = _current(api, "im_group_member",
                            lambda r: r["group_id"] == group_id
                            and r["user_id"] == user_id)
        if existing is not None and existing["left_at"] is None:
            skipped.append(user_id)
            continue
        if existing is not None:
            api.update_object("im_group_member", existing["id"], {
                "role": role, "joined_at": now, "left_at": None, "mute_until": None,
            }, actor)
        else:
            api.create_object("im_group_member", {
                "group_id": group_id, "user_id": user_id, "role": role,
                "mute_until": None, "joined_at": now, "left_at": None,
            }, actor)
        added.append(user_id)
    event = api.event("im.group.member.added", actor, [group_id], {
        "group_id": group_id,
        "user_ids": added,
        "skipped_user_ids": skipped,
        "operator_user_id": actor,
        "role": role,
    })
    return [event], {"type": "im_group", "id": group_id}


def remove_member(api, payload, actor, command_id):
    group_id = _str(api, payload, "group_id")
    user_id = _str(api, payload, "user_id")
    _require_active_group(api, group_id)
    actor_member = _require_role(api, group_id, actor, {"owner", "admin"})
    target = _active_member(api, group_id, user_id)
    if target is None:
        raise api.reject("IM-404-001", f"成员不存在或已离群：{group_id}/{user_id}")
    if target["role"] == "owner":
        raise api.reject("IM-409-006", "群主不可被移出，需先转让或解散")
    if actor_member["role"] == "admin" and target["role"] == "admin" \
            and actor != user_id:
        raise api.reject("IM-403-001", "管理员不可移出其他管理员")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise api.reject("EIS-400-001", "reason 必须为字符串")
    updated = api.update_object("im_group_member", target["id"], {
        "left_at": api.ts(api.now()),
        "mute_until": None,
    }, actor)
    event = api.event("im.group.member.removed", actor, [target["id"]], {
        "group_id": group_id,
        "user_id": user_id,
        "operator_user_id": actor,
        "reason": reason,
        "version": updated["version"],
    })
    return [event], {"type": "im_group_member", "id": target["id"]}


def update_member_role(api, payload, actor, command_id):
    group_id = _str(api, payload, "group_id")
    user_id = _str(api, payload, "user_id")
    role = payload.get("role")
    if role not in {"admin", "member"}:
        raise api.reject("EIS-400-001", "role 只能为 admin/member")
    _require_active_group(api, group_id)
    _require_role(api, group_id, actor, {"owner"})
    target = _active_member(api, group_id, user_id)
    if target is None:
        raise api.reject("IM-404-001", f"成员不存在或已离群：{group_id}/{user_id}")
    if target["role"] == "owner":
        raise api.reject("IM-409-006", "群主角色不可通过此命令修改")
    mute_until = _timestamp(api, payload.get("mute_until"), "mute_until")
    before = {"role": target["role"], "mute_until": target["mute_until"]}
    updated = api.update_object("im_group_member", target["id"], {
        "role": role,
        "mute_until": mute_until,
    }, actor)
    event = api.event("im.group.member.role-changed", actor, [target["id"]], {
        "group_id": group_id,
        "user_id": user_id,
        "changes": [
            {"field": "role", "before": before["role"], "after": role},
            {"field": "mute_until", "before": before["mute_until"], "after": mute_until},
        ],
        "version": updated["version"],
    })
    return [event], {"type": "im_group_member", "id": target["id"]}


# ---------------------------------------------------------------------------
# 好友与黑名单
# ---------------------------------------------------------------------------
def _friendship_between(api, user_a: str, user_b: str):
    return _current(api, "im_friendship",
                    lambda r: {r["from_user_id"], r["to_user_id"]} == {user_a, user_b})


def _active_block(api, user_id: str, blocked_user_id: str):
    return _current(api, "im_block",
                    lambda r: r["user_id"] == user_id
                    and r["blocked_user_id"] == blocked_user_id
                    and r["revoked_at"] is None)


def request_friend(api, payload, actor, command_id):
    to_user_id = _str(api, payload, "to_user_id")
    if to_user_id == actor:
        raise api.reject("IM-400-002", "不能向自己发起好友申请")
    if _active_block(api, actor, to_user_id) or _active_block(api, to_user_id, actor):
        raise api.reject("IM-409-007", "存在黑名单关系，无法发起好友申请")
    existing = _friendship_between(api, actor, to_user_id)
    if existing is not None and existing["status"] in {"pending", "accepted"}:
        raise api.reject(
            "IM-409-008",
            f"好友关系已存在：{existing['status']}（{existing['id']}）")
    now = api.ts(api.now())
    data = {
        "from_user_id": actor, "to_user_id": to_user_id,
        "status": "pending", "requested_at": now,
        "responded_at": None, "responded_by": None,
    }
    if existing is not None:
        friendship = api.update_object("im_friendship", existing["id"], data, actor)
    else:
        friendship = api.create_object("im_friendship", data, actor)
    event = api.event("im.friend.requested", actor, [friendship["id"]], {
        "friendship_id": friendship["id"],
        "from_user_id": actor,
        "to_user_id": to_user_id,
    })
    return [event], {"type": "im_friendship", "id": friendship["id"]}


def decide_friend_request(api, payload, actor, command_id):
    friendship_id = _str(api, payload, "friendship_id")
    decision = payload.get("decision")
    if decision not in {"accept", "reject"}:
        raise api.reject("EIS-400-001", "decision 只能为 accept/reject")
    row = api.as_of("im_friendship", friendship_id)
    if row is None:
        raise api.reject("IM-404-001", f"好友申请不存在：{friendship_id}")
    if row["status"] != "pending":
        raise api.reject("IM-409-009", f"好友申请已处理：{row['status']}")
    if row["to_user_id"] != actor:
        raise api.reject("IM-403-002", "仅被申请人可处理好友申请")
    status = "accepted" if decision == "accept" else "rejected"
    api.update_object("im_friendship", friendship_id, {
        "status": status,
        "responded_at": api.ts(api.now()),
        "responded_by": actor,
    }, actor)
    event_type = "im.friend.accepted" if decision == "accept" else "im.friend.rejected"
    event = api.event(event_type, actor, [friendship_id], {
        "friendship_id": friendship_id,
        "from_user_id": row["from_user_id"],
        "to_user_id": row["to_user_id"],
        "operator_user_id": actor,
    })
    return [event], {"type": "im_friendship", "id": friendship_id}


def remove_friend(api, payload, actor, command_id):
    peer_user_id = _str(api, payload, "peer_user_id")
    existing = _friendship_between(api, actor, peer_user_id)
    if existing is None or existing["status"] != "accepted":
        raise api.reject("IM-404-001", f"好友关系不存在：{peer_user_id}")
    updated = api.update_object("im_friendship", existing["id"], {
        "status": "removed",
        "responded_at": api.ts(api.now()),
        "responded_by": actor,
    }, actor)
    event = api.event("im.friend.removed", actor, [existing["id"]], {
        "friendship_id": existing["id"],
        "user_id": actor,
        "peer_user_id": peer_user_id,
        "operator_user_id": actor,
        "version": updated["version"],
    })
    return [event], {"type": "im_friendship", "id": existing["id"]}


def block_user(api, payload, actor, command_id):
    user_id = _str(api, payload, "user_id")
    if user_id == actor:
        raise api.reject("IM-400-002", "不能拉黑自己")
    if _active_block(api, actor, user_id) is not None:
        raise api.reject("IM-409-010", f"已在黑名单中：{user_id}")
    now = api.ts(api.now())
    existing = _current(api, "im_block",
                        lambda r: r["user_id"] == actor and r["blocked_user_id"] == user_id)
    data = {"user_id": actor, "blocked_user_id": user_id,
            "blocked_at": now, "revoked_at": None, "revoked_by": None}
    if existing is not None:
        block = api.update_object("im_block", existing["id"], data, actor)
    else:
        block = api.create_object("im_block", data, actor)
    # 拉黑同时解除已存在的好友关系（保留历史）
    friendship = _friendship_between(api, actor, user_id)
    if friendship is not None and friendship["status"] == "accepted":
        api.update_object("im_friendship", friendship["id"], {
            "status": "removed",
            "responded_at": now,
            "responded_by": actor,
        }, actor)
    event = api.event("im.user.blocked", actor, [block["id"]], {
        "block_id": block["id"],
        "user_id": actor,
        "blocked_user_id": user_id,
    })
    return [event], {"type": "im_block", "id": block["id"]}


def unblock_user(api, payload, actor, command_id):
    user_id = _str(api, payload, "user_id")
    block = _active_block(api, actor, user_id)
    if block is None:
        raise api.reject("IM-409-010", f"不在黑名单中：{user_id}")
    updated = api.update_object("im_block", block["id"], {
        "revoked_at": api.ts(api.now()),
        "revoked_by": actor,
    }, actor)
    event = api.event("im.user.unblocked", actor, [block["id"]], {
        "block_id": block["id"],
        "user_id": actor,
        "blocked_user_id": user_id,
        "version": updated["version"],
    })
    return [event], {"type": "im_block", "id": block["id"]}
