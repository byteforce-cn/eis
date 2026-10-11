# -*- coding: utf-8 -*-
"""iam 扩展命令处理器（内核注册机制，见 extensions/README.md §6）。"""
from __future__ import annotations

import copy
import json

# 处理器只依赖内核注入的 ExtensionAPI（不使用 kernel 模块内部）

COMMANDS = {}

# 命令记录脱敏：这些字段只在受理时参与校验，不得留在命令存储/展示中
SENSITIVE_FIELDS = {
    "iam.credential.rotate": ("secret_hash", "old_secret_hash", "new_secret_hash"),
    "iam.credential.reset": ("secret_hash", "old_secret_hash", "new_secret_hash"),
}


def register(api):
    return {
        "iam.user.create": create_user,
        "iam.user.update": update_user,
        "iam.user.disable": disable_user,
        "iam.user.enable": enable_user,
        "iam.credential.rotate": rotate_credential,
        "iam.credential.reset": reset_credential,
        "iam.role.define": define_role,
        "iam.binding.grant": grant_binding,
        "iam.binding.revoke": revoke_binding,
        "iam.session.issue": issue_session,
        "iam.session.revoke": revoke_session,
    }


# -- 帮助函数 ---------------------------------------------------------------
def active_credential(api, account_id):
    return api.find_current(
        "iam_credential",
        lambda r: r["account_id"] == account_id and r["type"] == "password" and r["status"] == "active",
    )


def revoke_sessions(api, account_id, actor, reason):
    events = []
    for session in list(api.objects("iam_auth_session")):
        if session["superseded_at"] is None and session["account_id"] == account_id and session["status"] == "active":
            api.update_object("iam_auth_session", session["id"], {"status": "revoked"}, actor)
            events.append(api.event("iam.session.revoked", actor, [session["id"]],
                                    {"session_id": session["id"], "reason": reason}))
    return events


# -- 处理器 -----------------------------------------------------------------
def create_user(api, payload, actor, command_id):
    username = payload.get("username")
    display_name = payload.get("display_name")
    if not isinstance(username, str) or not username.strip() or not isinstance(display_name, str) or not display_name.strip():
        raise api.reject("IAM-400-001", "username 与 display_name 均为必填")
    if api.find_current("iam_user_account", lambda r: r["username"] == username):
        raise api.reject("IAM-409-001", f"用户名已存在: {username}")
    account = api.create_object("iam_user_account", {
        "username": username, "display_name": display_name, "status": "active",
        "org_code": payload.get("org_code"), "contact": payload.get("contact"),
        "built_in": False,
    }, actor)
    event = api.event("iam.user.created", actor, [account["id"]],
                      {"account_id": account["id"], "username": username})
    return [event], {"type": "iam_user_account", "id": account["id"]}


def update_user(api, payload, actor, command_id):
    account_id = payload.get("account_id")
    account = api.as_of("iam_user_account", account_id) if account_id else None
    if account is None:
        raise api.reject("IAM-404-001", f"账户不存在: {account_id}")
    updates = {key: payload[key] for key in ("display_name", "org_code", "contact") if key in payload}
    if not updates:
        raise api.reject("IAM-400-001", "至少提供一个可更新字段")
    if "display_name" in updates and (not isinstance(updates["display_name"], str) or not updates["display_name"].strip()):
        raise api.reject("IAM-400-001", "display_name 不能为空")
    api.update_object("iam_user_account", account_id, updates, actor)
    event = api.event("iam.user.updated", actor, [account_id], {"account_id": account_id})
    return [event], {"type": "iam_user_account", "id": account_id}


def disable_user(api, payload, actor, command_id):
    account_id = payload.get("account_id")
    account = api.as_of("iam_user_account", account_id) if account_id else None
    if account is None:
        raise api.reject("IAM-404-001", f"账户不存在: {account_id}")
    if account.get("built_in") or account.get("username") == "root":
        raise api.reject("IAM-403-002", "内置 root 账户不可禁用")
    now = api.ts(api.now())
    events = []
    for session in list(api.objects("iam_auth_session")):
        if session["superseded_at"] is None and session["account_id"] == account_id and session["status"] == "active":
            api.update_object("iam_auth_session", session["id"], {"status": "revoked"}, actor)
            events.append(api.event("iam.session.revoked", actor, [session["id"]],
                                    {"session_id": session["id"], "reason": "account_disabled"}))
    api.update_object("iam_user_account", account_id, {"status": "disabled"}, actor)
    events.append(api.event("iam.user.disabled", actor, [account_id],
                            {"account_id": account_id, "disabled_at": now}))
    return events, {"type": "iam_user_account", "id": account_id}


def enable_user(api, payload, actor, command_id):
    account_id = payload.get("account_id")
    account = api.as_of("iam_user_account", account_id) if account_id else None
    if account is None:
        raise api.reject("IAM-404-001", f"账户不存在: {account_id}")
    if account.get("status") == "locked":
        raise api.reject("IAM-403-002", "锁定账户须经解锁流程处理")
    api.update_object("iam_user_account", account_id, {"status": "active"}, actor)
    event = api.event("iam.user.enabled", actor, [account_id], {"account_id": account_id})
    return [event], {"type": "iam_user_account", "id": account_id}


def rotate_credential(api, payload, actor, command_id):
    account_id = payload.get("account_id")
    if actor != account_id:
        raise api.reject("IAM-403-001", "本人凭证轮换只能操作自身账户")
    account = api.as_of("iam_user_account", account_id)
    credential = active_credential(api, account_id)
    if account is None or account.get("status") != "active" or credential is None:
        raise api.reject("IAM-403-002", "账户不可用或不存在有效凭证")
    if payload.get("old_secret_hash") != credential.get("secret_hash"):
        raise api.reject("IAM-400-002", "旧凭证校验失败")
    new_hash = payload.get("new_secret_hash")
    if not isinstance(new_hash, str) or not new_hash or new_hash == credential["secret_hash"]:
        raise api.reject("IAM-400-001", "新凭证无效")
    api.update_object("iam_credential", credential["id"], {
        "secret_hash": new_hash, "must_change": False, "rotated_at": api.ts(api.now()),
    }, actor)
    events = revoke_sessions(api, account_id, actor, "credential_rotated")
    events.append(api.event("iam.credential.rotated", actor, [credential["id"]],
                            {"account_id": account_id, "credential_id": credential["id"]}))
    return events, {"type": "iam_credential", "id": credential["id"]}


def reset_credential(api, payload, actor, command_id):
    account_id = payload.get("account_id")
    if actor == account_id:
        raise api.reject("IAM-403-001", "管理员不得通过重置命令自我提权")
    account = api.as_of("iam_user_account", account_id) if account_id else None
    new_hash = payload.get("new_secret_hash")
    if account is None or account.get("status") != "active":
        raise api.reject("IAM-403-002", "账户不可用或不存在")
    if not isinstance(new_hash, str) or not new_hash:
        raise api.reject("IAM-400-001", "新凭证无效")
    credential = active_credential(api, account_id)
    if credential is None:
        credential = api.create_object("iam_credential", {
            "account_id": account_id, "type": "password", "secret_hash": new_hash,
            "status": "active", "must_change": True, "rotated_at": api.ts(api.now()),
        }, actor)
    else:
        credential = api.update_object("iam_credential", credential["id"], {
            "secret_hash": new_hash, "must_change": True, "rotated_at": api.ts(api.now()),
        }, actor)
    events = revoke_sessions(api, account_id, actor, "credential_reset")
    events.append(api.event("iam.credential.reset", actor, [account_id],
                            {"account_id": account_id, "credential_id": credential["id"]}))
    return events, {"type": "iam_credential", "id": credential["id"]}


def define_role(api, payload, actor, command_id):
    key, name, permissions = payload.get("key"), payload.get("name"), payload.get("permissions")
    if not isinstance(key, str) or not key or not isinstance(name, str) or not name or not isinstance(permissions, list):
        raise api.reject("IAM-400-001", "key、name、permissions 格式非法")
    duplicate = api.find_current("iam_role", lambda r: r["key"] == key)
    role_id = payload.get("role_id")
    if duplicate is not None and duplicate["id"] != role_id:
        raise api.reject("IAM-409-002", f"角色 key 已存在: {key}")
    if role_id:
        current = api.as_of("iam_role", role_id)
        if current is None:
            raise api.reject("IAM-404-001", f"角色不存在: {role_id}")
        row = api.update_object("iam_role", role_id, {
            "key": key, "name": name, "permissions": sorted(set(permissions)),
        }, actor)
        event_type = "iam.role.updated"
    else:
        row = api.create_object("iam_role", {
            "key": key, "name": name, "permissions": sorted(set(permissions)), "built_in": False,
        }, actor)
        event_type = "iam.role.defined"
    event = api.event(event_type, actor, [row["id"]], {"role_id": row["id"], "key": key})
    return [event], {"type": "iam_role", "id": row["id"]}


def grant_binding(api, payload, actor, command_id):
    principal, role_id, scope = payload.get("principal"), payload.get("role_id"), payload.get("scope")
    role = api.as_of("iam_role", role_id) if role_id else None
    if not principal or role is None or not isinstance(scope, dict):
        raise api.reject("IAM-400-001", "principal、有效 role_id 与 scope 为必填")
    if principal == actor or (api.authz is not None and any(
        p.get("agent") == actor and p.get("principal") == principal for p in api.authz.proxies
    )):
        raise api.reject("IAM-403-001", "不得向本人或本人代理授予角色")
    account = api.as_of("iam_user_account", principal)
    if account is None or account.get("status") != "active":
        raise api.reject("IAM-403-002", "授权主体不存在或不可用")
    canonical_scope = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    duplicate = api.find_current("iam_role_binding", lambda r:
        r["principal"] == principal and r["role"] == role_id and r["status"] == "active"
        and json.dumps(r.get("scope") or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False) == canonical_scope
    )
    if duplicate:
        raise api.reject("IAM-409-001", "相同主体、角色与作用域已有有效绑定")
    warning_rules = []
    if api.authz is not None:
        sod_rules = api.authz.sod_rules
        existing_roles = []
        for binding in api.objects("iam_role_binding"):
            if binding["superseded_at"] is None and binding.get("status") == "active" and binding["principal"] == principal:
                bound_role = api.as_of("iam_role", binding["role"])
                if bound_role:
                    existing_roles.append((bound_role, binding.get("scope") or {}))
        proposed_roles = [*existing_roles, (role, scope)]
        for rule in sod_rules:
            scope_key = {"same_department": "department", "same_organization": "organization",
                         "same_warehouse": "warehouse"}.get(rule.get("scope"))
            perms_in_scope = set()
            for held_role, held_scope in proposed_roles:
                if scope_key and held_scope.get(scope_key) != scope.get(scope_key):
                    continue
                perms_in_scope.update(held_role.get("permissions", []))
            conflicts = set(rule.get("conflicting_permissions", []))
            if len(conflicts.intersection(perms_in_scope)) > 1:
                if rule.get("enforcement") == "prevent":
                    raise api.reject("IAM-403-003", f"SoD 冲突: {rule['id']}", rule["id"])
                warning_rules.append(rule["id"])
    binding = api.create_object("iam_role_binding", {
        "principal": principal, "role": role_id, "scope": copy.deepcopy(scope), "status": "active",
    }, actor)
    event = api.event("iam.binding.granted", actor, [binding["id"]], {
        "binding_id": binding["id"], "principal": principal, "role_id": role_id,
        "sod_warnings": warning_rules,
    })
    return [event], {"type": "iam_role_binding", "id": binding["id"]}


def revoke_binding(api, payload, actor, command_id):
    binding_id = payload.get("binding_id")
    binding = api.as_of("iam_role_binding", binding_id) if binding_id else None
    if binding is None or binding.get("status") != "active":
        raise api.reject("IAM-404-001", f"有效角色绑定不存在: {binding_id}")
    api.update_object("iam_role_binding", binding_id, {"status": "revoked"}, actor)
    event = api.event("iam.binding.revoked", actor, [binding_id], {"binding_id": binding_id})
    return [event], {"type": "iam_role_binding", "id": binding_id}


def issue_session(api, payload, actor, command_id):
    account_id = payload.get("account_id")
    account = api.as_of("iam_user_account", account_id) if account_id else None
    expires_at = payload.get("expires_at")
    try:
        expires = api.parse_ts(expires_at)
    except (TypeError, ValueError):
        raise api.reject("IAM-400-001", "expires_at 必须为合法时间")
    if account is None or account.get("status") != "active":
        raise api.reject("IAM-403-002", "账户不可用或不存在")
    if expires <= api.now() or not payload.get("client_id") or not payload.get("jti"):
        raise api.reject("IAM-400-001", "会话字段非法或已过期")
    session = api.create_object("iam_auth_session", {
        "account_id": account_id, "client_id": payload["client_id"],
        "auth_method": payload.get("auth_method", "password"), "jti": payload["jti"],
        "status": "active", "expires_at": api.ts(expires),
    }, actor)
    event = api.event("iam.session.issued", actor, [session["id"]], {
        "session_id": session["id"], "account_id": account_id, "jti": session["jti"],
        "expires_at": session["expires_at"],
    })
    return [event], {"type": "iam_auth_session", "id": session["id"]}


def revoke_session(api, payload, actor, command_id):
    session_id = payload.get("session_id")
    session = api.as_of("iam_auth_session", session_id) if session_id else None
    if session is None:
        raise api.reject("IAM-404-001", f"会话不存在: {session_id}")
    if session.get("status") != "active":
        raise api.reject("IAM-409-003", f"会话状态不可吊销: {session.get('status')}")
    api.update_object("iam_auth_session", session_id, {"status": "revoked"}, actor)
    event = api.event("iam.session.revoked", actor, [session_id], {"session_id": session_id})
    return [event], {"type": "iam_auth_session", "id": session_id}
