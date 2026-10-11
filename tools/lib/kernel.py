#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kernel — EIS 参考内核（v1.0.0，进程内、确定性）

定位：把 EIS 六份契约落成一个最小可执行语义体，用于
  1) e2e-runner 的场景执行（procure-to-pay 等）；
  2) 作为 seedj / server 移植的“可执行规格”（Java 端按本语义实现并对齐行为）。

覆盖的契约语义：
  - 数据契约：业务对象（元字段 + 双时间轴）、事件、命令、幂等键
  - 操作契约：命令受理（202/400/403/409 语义）、事件发布、错误码
  - 时间契约：半开区间 [from, to)、系统时间轴 append-only、时点/双时间点查询
  - 授权契约：主体 / 角色 / 绑定 / 代理、as_of 解析、SoD（prevent）
  - 审计契约：哈希链（复用 05 的 verify.tool 规范化与验证）
  - 演进契约：不涉及（工具域）

明确不做（参考实现的边界，生产实现需补齐）：
  - 持久化（内存）、并发控制、真实时钟、分区与索引优化
  - 规则引擎的通用化：仅实现本仓库扩展声明的规则（double-entry / period-lock /
    non-negative / no-self-approval）

使用：run_scenario(scenario_dict_or_path) → 场景报告；Kernel 类可直接嵌入测试。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

from eis_common import ROOT, load_yaml

VERIFY_TOOL = ROOT / "05-audit-contract" / "verify.tool"
GENESIS_PREV_HASH = "0" * 64

ISO = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def load_verify_module():
    loader = SourceFileLoader("eis_verify_tool_kernel", str(VERIFY_TOOL))
    module = module_from_spec(spec_from_loader("eis_verify_tool_kernel", loader))
    loader.exec_module(module)
    return module


_VT = load_verify_module()


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(ISO)


def parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dec(value) -> Decimal:
    return Decimal(str(value))


def dec_eq(a, b) -> bool:
    return dec(a) == dec(b)


class Rejected(Exception):
    """命令拒绝（携带错误码）。"""

    def __init__(self, code: str, reason: str, reason_code: str | None = None):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.reason_code = reason_code


# ---------------------------------------------------------------------------
# 授权（复用 authz-resolver 的语义实现）
# ---------------------------------------------------------------------------
def load_authz_module():
    loader = SourceFileLoader("eis_authz_kernel", str(ROOT / "tools" / "authz-resolver"))
    module = module_from_spec(spec_from_loader("eis_authz_kernel", loader))
    loader.exec_module(module)
    return module


class Kernel:
    """EIS 参考内核：命令受理 → 规则 → 事件 → 审计链 → 双时间轴对象。"""

    def __init__(self, clock_start="2026-10-08T09:00:00Z", authz_fixtures: dict | None = None):
        self.clock = parse_ts(clock_start)
        self._id_ns = 0x0190F2E3A12C
        self._id_counter = 0

        # 存储
        self.commands: dict[str, dict] = {}
        self.idem: dict[str, tuple[str, str]] = {}  # key → (payload_fingerprint, command_id)
        self.events: list[dict] = []
        self.objects: dict[str, list[dict]] = {}    # type → 版本行（append-only）
        self.audit: list[dict] = []
        self.locked_periods: set[str] = set()

        # 授权（可选）：actor → principal；为空则不做权限判定
        self.authz = None
        self.authz_by_key: dict[str, str] = {}
        if authz_fixtures:
            authz_mod = load_authz_module()
            self.authz = authz_mod.Authz({"fixtures": authz_fixtures})
            for p in authz_fixtures.get("principals", []):
                self.authz_by_key[p.get("key", p["id"])] = p["id"]

    # ------------------------------------------------------------------
    # 时钟与 ID
    # ------------------------------------------------------------------
    def now(self) -> datetime:
        return self.clock

    def advance(self, seconds: int = 60) -> None:
        self.clock += timedelta(seconds=seconds)

    def new_id(self) -> str:
        self._id_counter += 1
        value = (self._id_ns << 64) | self._id_counter
        # UUIDv7：版本位置位（bits 76-79 = 0111）与 variant（bits 62-63 = 10）
        value &= ~(0xF << 76)
        value |= 7 << 76
        value &= ~(0x3 << 62)
        value |= 0x2 << 62
        return str(uuid.UUID(int=value))

    def principal_of(self, actor: str) -> str:
        return self.authz_by_key.get(actor, actor)

    # ------------------------------------------------------------------
    # 命令受理
    # ------------------------------------------------------------------
    def submit(self, command: dict, actor: str) -> dict:
        """受理命令（幂等）。返回 {status, command_id, event_ids, code?, reason?, created?}。"""
        cmd_type = command.get("type", "")
        payload = command.get("payload", {})
        idem_key = command.get("idempotency_key", "")
        if not idem_key or not isinstance(payload, dict):
            raise Rejected("EIS-400-001", "命令缺少 idempotency_key 或 payload 非对象")

        fingerprint = json.dumps({"type": cmd_type, "payload": payload,
                                  "targets": command.get("targets", [])},
                                 sort_keys=True, ensure_ascii=False)
        if idem_key in self.idem:
            old_fp, old_cmd_id = self.idem[idem_key]
            if old_fp != fingerprint:
                return {"status": "conflict", "command_id": old_cmd_id, "event_ids": [],
                        "code": "EIS-409-001", "reason": "幂等键冲突：内容与首次提交不一致"}
            old = self.commands[old_cmd_id]
            return {"status": old["status"], "command_id": old_cmd_id,
                    "event_ids": old["event_ids"], "code": old.get("rejection_code"),
                    "reason": old.get("rejection_reason"), "replayed": True}

        principal = self.principal_of(actor)
        command_id = self.new_id()
        stored_payload = copy.deepcopy(payload)
        if cmd_type.startswith("iam.credential."):
            for field in ("secret_hash", "old_secret_hash", "new_secret_hash"):
                stored_payload.pop(field, None)
        record = {
            "id": command_id, "type": cmd_type, "issued_at": ts(self.now()),
            "issuer": principal, "payload": stored_payload, "idempotency_key": idem_key,
            "status": "pending", "event_ids": [],
            # 幂等指纹基于脱敏前的原始载荷；命令记录只存不可逆摘要（存储/展示仍为脱敏载荷）
            "payload_fingerprint": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
        }
        self.idem[idem_key] = (fingerprint, command_id)
        self.commands[command_id] = record

        try:
            # 授权（若装载）
            if self.authz is not None:
                decision = self.authz.check(principal, cmd_type, ts(self.now()))
                if not decision["allowed"]:
                    raise Rejected(decision.get("reason_code", "EIS-403-001"), decision["reason"])
            events, created = self._handle(cmd_type, payload, principal, command_id)
        except Rejected as exc:
            record["status"] = "rejected"
            record["rejection_reason"] = exc.reason
            record["rejection_code"] = exc.code
            self.advance()
            result = {"status": "rejected", "command_id": command_id, "event_ids": [],
                      "code": exc.code, "reason": exc.reason}
            if exc.reason_code:
                result["reason_code"] = exc.reason_code
            return result

        record["status"] = "accepted"
        record["event_ids"] = [e["id"] for e in events]
        self.events.extend(events)
        self._append_audit(cmd_type, principal, record, events, payload)
        self.advance()
        return {"status": "accepted", "command_id": command_id,
                "event_ids": [e["id"] for e in events], "created": created}

    # ------------------------------------------------------------------
    # 命令处理器
    # ------------------------------------------------------------------
    def _handle(self, cmd_type: str, payload: dict, actor: str, command_id: str):
        handler = {
            "accounting.voucher.post": self._post_voucher,
            "accounting.period.close": self._close_period,
            "inventory.stock.receive": self._receive_stock,
            "approval.request.submit": self._submit_request,
            "approval.request.decide": self._decide_request,
            "iam.user.create": self._iam_user_create,
            "iam.user.update": self._iam_user_update,
            "iam.user.disable": self._iam_user_disable,
            "iam.user.enable": self._iam_user_enable,
            "iam.credential.rotate": self._iam_credential_rotate,
            "iam.credential.reset": self._iam_credential_reset,
            "iam.role.define": self._iam_role_define,
            "iam.binding.grant": self._iam_binding_grant,
            "iam.binding.revoke": self._iam_binding_revoke,
            "iam.session.issue": self._iam_session_issue,
            "iam.session.revoke": self._iam_session_revoke,
        }.get(cmd_type)
        if handler is None:
            raise Rejected("EIS-400-001", f"未知命令类型: {cmd_type}")
        return handler(payload, actor, command_id)

    # -- accounting -----------------------------------------------------
    def _post_voucher(self, payload, actor, command_id):
        voucher_id = payload.get("voucher_id")
        post_date = payload.get("post_date")
        if not voucher_id or not post_date:
            raise Rejected("EIS-400-001", "缺少 voucher_id 或 post_date")
        row = self.as_of("voucher", voucher_id)
        if row is None:
            raise Rejected("EIS-404-001", f"凭证不存在: {voucher_id}")
        if row["status"] != "draft":
            raise Rejected("EIS-400-002", f"凭证状态不可过账: {row['status']}")
        period = str(post_date)[:7]
        # 规则 double_entry：按币种分组借贷平衡
        groups: dict[str, dict[str, Decimal]] = {}
        for line in row["lines"]:
            cur = line.get("currency", "CNY")
            g = groups.setdefault(cur, {"debit": Decimal(0), "credit": Decimal(0)})
            g["debit"] += dec(line.get("debit", "0"))
            g["credit"] += dec(line.get("credit", "0"))
        for cur, g in groups.items():
            if g["debit"] != g["credit"]:
                raise Rejected("ACC-400-001",
                               f"凭证借贷不平衡（{cur}）：借方 {g['debit']}，贷方 {g['credit']}")
        # 规则 period_lock
        if period in self.locked_periods:
            raise Rejected("ACC-409-001", f"会计期间 {period} 已锁定")
        # 接受：状态变更 + 事件
        self._update_object("voucher", voucher_id, {"status": "posted", "posted_at": ts(self.now())}, actor)
        event = self._event("accounting.voucher.posted", actor,
                            subjects=[voucher_id],
                            payload={"voucher_id": voucher_id, "number": row["number"],
                                     "period": period, "lines": row["lines"]})
        return [event], {"type": "voucher", "id": voucher_id}

    def _close_period(self, payload, actor, command_id):
        period = payload.get("period")
        if not period or not re.match(r"^\d{4}-\d{2}$", str(period)):
            raise Rejected("EIS-400-001", "缺少合法 period（YYYY-MM）")
        if period in self.locked_periods:
            raise Rejected("ACC-409-002", f"会计期间 {period} 已关闭")
        for row in self.objects.get("voucher", []):
            if row["superseded_at"] is not None:
                continue
            if row.get("status") == "draft" and str(row.get("voucher_date", ""))[:7] == period:
                raise Rejected("ACC-400-002", f"期间 {period} 存在未过账凭证: {row['number']}")
        self.locked_periods.add(period)
        event = self._event("accounting.period.closed", actor, subjects=[],
                            payload={"period": period})
        return [event], {"type": "period", "id": period}

    # -- inventory ------------------------------------------------------
    def _receive_stock(self, payload, actor, command_id):
        item_id = payload.get("item_id")
        warehouse = payload.get("warehouse")
        quantity = payload.get("quantity")
        if not (item_id and warehouse and quantity):
            raise Rejected("EIS-400-001", "缺少 item_id / warehouse / quantity")
        qty = dec(quantity)
        if qty <= 0:
            raise Rejected("INV-400-001", f"收货数量必须 > 0：{quantity}")
        # 规则 non_negative：应用后余额 >= 0（receipt 恒增，此处仍校验）
        balance = dec(self.stock(item_id, warehouse)) + qty
        if balance < 0:
            raise Rejected("INV-400-001", f"库存不足：余额 {balance}")
        # 更新库存余额对象 + 记录变动对象
        row = self._find_current("stock_balance", lambda r: r["item_id"] == item_id and r["warehouse"] == warehouse)
        if row is None:
            self._create_object("stock_balance", {
                "item_id": item_id, "warehouse": warehouse,
                "quantity": str(qty), "unit": payload.get("unit", "EA"),
            }, actor)
        else:
            self._update_object("stock_balance", row["id"], {"quantity": str(balance)}, actor)
        movement = self._create_object("stock_movement", {
            "item_id": item_id, "warehouse": warehouse, "movement_type": "receipt",
            "quantity": str(qty), "reference": payload.get("reference"),
        }, actor)
        event = self._event("inventory.stock.received", actor, subjects=[item_id],
                            payload={"item_id": item_id, "warehouse": warehouse,
                                     "quantity": str(qty), "reference": payload.get("reference")})
        return [event], {"type": "stock_movement", "id": movement["id"]}

    # -- approval -------------------------------------------------------
    def _submit_request(self, payload, actor, command_id):
        operation = payload.get("operation")
        target = payload.get("target") or {}
        if not operation or not target.get("type") or not target.get("id"):
            raise Rejected("EIS-400-001", "缺少 operation / target")
        request = self._create_object("approval_request", {
            "operation": operation, "target": target, "requester": actor,
            "status": "pending", "summary": payload.get("summary"),
        }, actor)
        event = self._event("approval.request.submitted", actor, subjects=[request["id"]],
                            payload={"request_id": request["id"], "operation": operation, "target": target})
        return [event], {"type": "approval_request", "id": request["id"]}

    def _decide_request(self, payload, actor, command_id):
        request_id = payload.get("request_id")
        outcome = payload.get("outcome")
        if not request_id or outcome not in ("approve", "reject"):
            raise Rejected("EIS-400-001", "缺少 request_id 或 outcome 非法")
        row = self.as_of("approval_request", request_id)
        if row is None:
            raise Rejected("EIS-404-001", f"审批申请不存在: {request_id}")
        if row["status"] != "pending":
            raise Rejected("EIS-409-001", f"申请已处理: {row['status']}")
        # 规则 no_self_approval
        if row["requester"] == actor:
            raise Rejected("APR-403-001", "禁止自审：申请人与决定人相同")
        status = "approved" if outcome == "approve" else "rejected"
        self._update_object("approval_request", request_id, {"status": status}, actor,
                            extra={"decided_by": actor, "decided_at": ts(self.now())})
        event = self._event(f"approval.request.{status}", actor, subjects=[request_id],
                            payload={"request_id": request_id, "outcome": outcome})
        return [event], {"type": "approval_request", "id": request_id}

    # -- iam ------------------------------------------------------------
    def _iam_user_create(self, payload, actor, command_id):
        username = payload.get("username")
        display_name = payload.get("display_name")
        if not isinstance(username, str) or not username.strip() or not isinstance(display_name, str) or not display_name.strip():
            raise Rejected("IAM-400-001", "username 与 display_name 均为必填")
        if self._find_current("iam_user_account", lambda r: r["username"] == username):
            raise Rejected("IAM-409-001", f"用户名已存在: {username}")
        account = self._create_object("iam_user_account", {
            "username": username, "display_name": display_name, "status": "active",
            "org_code": payload.get("org_code"), "contact": payload.get("contact"),
            "built_in": False,
        }, actor)
        event = self._event("iam.user.created", actor, [account["id"]],
                            {"account_id": account["id"], "username": username})
        return [event], {"type": "iam_user_account", "id": account["id"]}

    def _iam_user_update(self, payload, actor, command_id):
        account_id = payload.get("account_id")
        account = self.as_of("iam_user_account", account_id) if account_id else None
        if account is None:
            raise Rejected("IAM-404-001", f"账户不存在: {account_id}")
        updates = {key: payload[key] for key in ("display_name", "org_code", "contact") if key in payload}
        if not updates:
            raise Rejected("IAM-400-001", "至少提供一个可更新字段")
        if "display_name" in updates and (not isinstance(updates["display_name"], str) or not updates["display_name"].strip()):
            raise Rejected("IAM-400-001", "display_name 不能为空")
        self._update_object("iam_user_account", account_id, updates, actor)
        event = self._event("iam.user.updated", actor, [account_id], {"account_id": account_id})
        return [event], {"type": "iam_user_account", "id": account_id}

    def _iam_user_disable(self, payload, actor, command_id):
        account_id = payload.get("account_id")
        account = self.as_of("iam_user_account", account_id) if account_id else None
        if account is None:
            raise Rejected("IAM-404-001", f"账户不存在: {account_id}")
        if account.get("built_in") or account.get("username") == "root":
            raise Rejected("IAM-403-002", "内置 root 账户不可禁用")
        now = ts(self.now())
        events = []
        for session in list(self.objects.get("iam_auth_session", [])):
            if session["superseded_at"] is None and session["account_id"] == account_id and session["status"] == "active":
                self._update_object("iam_auth_session", session["id"], {"status": "revoked"}, actor)
                events.append(self._event("iam.session.revoked", actor, [session["id"]],
                                          {"session_id": session["id"], "reason": "account_disabled"}))
        self._update_object("iam_user_account", account_id, {"status": "disabled"}, actor)
        events.append(self._event("iam.user.disabled", actor, [account_id],
                                  {"account_id": account_id, "disabled_at": now}))
        return events, {"type": "iam_user_account", "id": account_id}

    def _iam_user_enable(self, payload, actor, command_id):
        account_id = payload.get("account_id")
        account = self.as_of("iam_user_account", account_id) if account_id else None
        if account is None:
            raise Rejected("IAM-404-001", f"账户不存在: {account_id}")
        if account.get("status") == "locked":
            raise Rejected("IAM-403-002", "锁定账户须经解锁流程处理")
        self._update_object("iam_user_account", account_id, {"status": "active"}, actor)
        event = self._event("iam.user.enabled", actor, [account_id], {"account_id": account_id})
        return [event], {"type": "iam_user_account", "id": account_id}

    def _iam_active_credential(self, account_id):
        return self._find_current(
            "iam_credential",
            lambda r: r["account_id"] == account_id and r["type"] == "password" and r["status"] == "active",
        )

    def _iam_revoke_sessions(self, account_id, actor, reason):
        events = []
        for session in list(self.objects.get("iam_auth_session", [])):
            if session["superseded_at"] is None and session["account_id"] == account_id and session["status"] == "active":
                self._update_object("iam_auth_session", session["id"], {"status": "revoked"}, actor)
                events.append(self._event("iam.session.revoked", actor, [session["id"]],
                                          {"session_id": session["id"], "reason": reason}))
        return events

    def _iam_credential_rotate(self, payload, actor, command_id):
        account_id = payload.get("account_id")
        if actor != account_id:
            raise Rejected("IAM-403-001", "本人凭证轮换只能操作自身账户")
        account = self.as_of("iam_user_account", account_id)
        credential = self._iam_active_credential(account_id)
        if account is None or account.get("status") != "active" or credential is None:
            raise Rejected("IAM-403-002", "账户不可用或不存在有效凭证")
        if payload.get("old_secret_hash") != credential.get("secret_hash"):
            raise Rejected("IAM-400-002", "旧凭证校验失败")
        new_hash = payload.get("new_secret_hash")
        if not isinstance(new_hash, str) or not new_hash or new_hash == credential["secret_hash"]:
            raise Rejected("IAM-400-001", "新凭证无效")
        self._update_object("iam_credential", credential["id"], {
            "secret_hash": new_hash, "must_change": False, "rotated_at": ts(self.now()),
        }, actor)
        events = self._iam_revoke_sessions(account_id, actor, "credential_rotated")
        events.append(self._event("iam.credential.rotated", actor, [credential["id"]],
                                  {"account_id": account_id, "credential_id": credential["id"]}))
        return events, {"type": "iam_credential", "id": credential["id"]}

    def _iam_credential_reset(self, payload, actor, command_id):
        account_id = payload.get("account_id")
        if actor == account_id:
            raise Rejected("IAM-403-001", "管理员不得通过重置命令自我提权")
        account = self.as_of("iam_user_account", account_id) if account_id else None
        new_hash = payload.get("new_secret_hash")
        if account is None or account.get("status") != "active":
            raise Rejected("IAM-403-002", "账户不可用或不存在")
        if not isinstance(new_hash, str) or not new_hash:
            raise Rejected("IAM-400-001", "新凭证无效")
        credential = self._iam_active_credential(account_id)
        if credential is None:
            credential = self._create_object("iam_credential", {
                "account_id": account_id, "type": "password", "secret_hash": new_hash,
                "status": "active", "must_change": True, "rotated_at": ts(self.now()),
            }, actor)
        else:
            credential = self._update_object("iam_credential", credential["id"], {
                "secret_hash": new_hash, "must_change": True, "rotated_at": ts(self.now()),
            }, actor)
        events = self._iam_revoke_sessions(account_id, actor, "credential_reset")
        events.append(self._event("iam.credential.reset", actor, [account_id],
                                  {"account_id": account_id, "credential_id": credential["id"]}))
        return events, {"type": "iam_credential", "id": credential["id"]}

    def _iam_role_define(self, payload, actor, command_id):
        key, name, permissions = payload.get("key"), payload.get("name"), payload.get("permissions")
        if not isinstance(key, str) or not key or not isinstance(name, str) or not name or not isinstance(permissions, list):
            raise Rejected("IAM-400-001", "key、name、permissions 格式非法")
        duplicate = self._find_current("iam_role", lambda r: r["key"] == key)
        role_id = payload.get("role_id")
        if duplicate is not None and duplicate["id"] != role_id:
            raise Rejected("IAM-409-002", f"角色 key 已存在: {key}")
        if role_id:
            current = self.as_of("iam_role", role_id)
            if current is None:
                raise Rejected("IAM-404-001", f"角色不存在: {role_id}")
            row = self._update_object("iam_role", role_id, {
                "key": key, "name": name, "permissions": sorted(set(permissions)),
            }, actor)
            event_type = "iam.role.updated"
        else:
            row = self._create_object("iam_role", {
                "key": key, "name": name, "permissions": sorted(set(permissions)), "built_in": False,
            }, actor)
            event_type = "iam.role.defined"
        event = self._event(event_type, actor, [row["id"]], {"role_id": row["id"], "key": key})
        return [event], {"type": "iam_role", "id": row["id"]}

    def _iam_binding_grant(self, payload, actor, command_id):
        principal, role_id, scope = payload.get("principal"), payload.get("role_id"), payload.get("scope")
        role = self.as_of("iam_role", role_id) if role_id else None
        if not principal or role is None or not isinstance(scope, dict):
            raise Rejected("IAM-400-001", "principal、有效 role_id 与 scope 为必填")
        if principal == actor or (self.authz is not None and any(
            p.get("agent") == actor and p.get("principal") == principal for p in self.authz.proxies
        )):
            raise Rejected("IAM-403-001", "不得向本人或本人代理授予角色")
        account = self.as_of("iam_user_account", principal)
        if account is None or account.get("status") != "active":
            raise Rejected("IAM-403-002", "授权主体不存在或不可用")
        canonical_scope = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        duplicate = self._find_current("iam_role_binding", lambda r:
            r["principal"] == principal and r["role"] == role_id and r["status"] == "active"
            and json.dumps(r.get("scope") or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False) == canonical_scope
        )
        if duplicate:
            raise Rejected("IAM-409-001", "相同主体、角色与作用域已有有效绑定")
        warning_rules = []
        if self.authz is not None:
            sod_rules = self.authz.sod_rules
            existing_roles = []
            for binding in self.objects.get("iam_role_binding", []):
                if binding["superseded_at"] is None and binding.get("status") == "active" and binding["principal"] == principal:
                    bound_role = self.as_of("iam_role", binding["role"])
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
                        raise Rejected("IAM-403-003", f"SoD 冲突: {rule['id']}", rule["id"])
                    warning_rules.append(rule["id"])
        binding = self._create_object("iam_role_binding", {
            "principal": principal, "role": role_id, "scope": copy.deepcopy(scope), "status": "active",
        }, actor)
        event = self._event("iam.binding.granted", actor, [binding["id"]], {
            "binding_id": binding["id"], "principal": principal, "role_id": role_id,
            "sod_warnings": warning_rules,
        })
        return [event], {"type": "iam_role_binding", "id": binding["id"]}

    def _iam_binding_revoke(self, payload, actor, command_id):
        binding_id = payload.get("binding_id")
        binding = self.as_of("iam_role_binding", binding_id) if binding_id else None
        if binding is None or binding.get("status") != "active":
            raise Rejected("IAM-404-001", f"有效角色绑定不存在: {binding_id}")
        self._update_object("iam_role_binding", binding_id, {"status": "revoked"}, actor)
        event = self._event("iam.binding.revoked", actor, [binding_id], {"binding_id": binding_id})
        return [event], {"type": "iam_role_binding", "id": binding_id}

    def _iam_session_issue(self, payload, actor, command_id):
        account_id = payload.get("account_id")
        account = self.as_of("iam_user_account", account_id) if account_id else None
        expires_at = payload.get("expires_at")
        try:
            expires = parse_ts(expires_at)
        except (TypeError, ValueError):
            raise Rejected("IAM-400-001", "expires_at 必须为合法时间")
        if account is None or account.get("status") != "active":
            raise Rejected("IAM-403-002", "账户不可用或不存在")
        if expires <= self.now() or not payload.get("client_id") or not payload.get("jti"):
            raise Rejected("IAM-400-001", "会话字段非法或已过期")
        session = self._create_object("iam_auth_session", {
            "account_id": account_id, "client_id": payload["client_id"],
            "auth_method": payload.get("auth_method", "password"), "jti": payload["jti"],
            "status": "active", "expires_at": ts(expires),
        }, actor)
        event = self._event("iam.session.issued", actor, [session["id"]], {
            "session_id": session["id"], "account_id": account_id, "jti": session["jti"],
            "expires_at": session["expires_at"],
        })
        return [event], {"type": "iam_auth_session", "id": session["id"]}

    def _iam_session_revoke(self, payload, actor, command_id):
        session_id = payload.get("session_id")
        session = self.as_of("iam_auth_session", session_id) if session_id else None
        if session is None:
            raise Rejected("IAM-404-001", f"会话不存在: {session_id}")
        if session.get("status") != "active":
            raise Rejected("IAM-409-003", f"会话状态不可吊销: {session.get('status')}")
        self._update_object("iam_auth_session", session_id, {"status": "revoked"}, actor)
        event = self._event("iam.session.revoked", actor, [session_id], {"session_id": session_id})
        return [event], {"type": "iam_auth_session", "id": session_id}

    # ------------------------------------------------------------------
    # 对象存储（双时间轴）
    # ------------------------------------------------------------------
    def _meta(self, obj_id: str, version: int, actor: str, now_dt, superseded_at=None):
        return {
            "id": obj_id, "version": version,
            "valid_from": ts(now_dt), "valid_to": None,
            "recorded_at": ts(now_dt), "superseded_at": superseded_at,
            "created_by": actor, "created_at": ts(now_dt),
            "updated_by": None, "updated_at": None,
        }

    def _create_object(self, obj_type: str, data: dict, actor: str) -> dict:
        now_dt = self.now()
        obj_id = data.get("id") or self.new_id()
        row = {**self._meta(obj_id, 1, actor, now_dt), **data, "id": obj_id}
        self.objects.setdefault(obj_type, []).append(row)
        return row

    def _update_object(self, obj_type: str, obj_id: str, updates: dict, actor: str, extra=None) -> dict:
        rows = self.objects.get(obj_type, [])
        current = next((r for r in rows if r["id"] == obj_id and r["superseded_at"] is None), None)
        if current is None:
            raise Rejected("EIS-404-001", f"对象不存在: {obj_type}/{obj_id}")
        now_dt = self.now()
        new_row = copy.deepcopy(current)
        # 旧行：封口（系统时间轴 append-only；业务区间相交处收口）
        current["superseded_at"] = ts(now_dt)
        current["valid_to"] = ts(now_dt)
        # 新行
        new_row.update(updates)
        if extra:
            new_row.update(extra)
        new_row["version"] = current["version"] + 1
        new_row["valid_from"] = ts(now_dt)
        new_row["valid_to"] = None
        new_row["recorded_at"] = ts(now_dt)
        new_row["superseded_at"] = None
        new_row["updated_by"] = actor
        new_row["updated_at"] = ts(now_dt)
        rows.append(new_row)
        return new_row

    def _find_current(self, obj_type: str, pred):
        for row in self.objects.get(obj_type, []):
            if row["superseded_at"] is None and pred(row):
                return row
        return None

    # ------------------------------------------------------------------
    # 时点查询
    # ------------------------------------------------------------------
    def as_of(self, obj_type: str, obj_id: str, valid_at=None, recorded_at=None) -> dict | None:
        """双时间轴时点查询（半开区间）。缺省 = 当前版本。"""
        candidates = []
        for row in self.objects.get(obj_type, []):
            if row["id"] != obj_id:
                continue
            if valid_at is not None or recorded_at is not None:
                if valid_at is not None:
                    vf, vt_ = parse_ts(row["valid_from"]), row["valid_to"]
                    if vf > parse_ts(valid_at):
                        continue
                    if vt_ is not None and parse_ts(vt_) <= parse_ts(valid_at):
                        continue
                if recorded_at is not None:
                    ra, sa = parse_ts(row["recorded_at"]), row["superseded_at"]
                    if ra > parse_ts(recorded_at):
                        continue
                    if sa is not None and parse_ts(sa) <= parse_ts(recorded_at):
                        continue
            else:
                if row["superseded_at"] is not None:
                    continue
            candidates.append(row)
        if not candidates:
            return None
        return max(candidates, key=lambda r: r["version"])

    def history(self, obj_type: str, obj_id: str) -> list[dict]:
        rows = [r for r in self.objects.get(obj_type, []) if r["id"] == obj_id]
        return sorted(rows, key=lambda r: r["version"])

    # ------------------------------------------------------------------
    # 读模型
    # ------------------------------------------------------------------
    def balance(self, account_code: str, period: str) -> dict:
        """由过账事件投射的科目余额（可重复构建）。"""
        debit = credit = Decimal(0)
        for event in self.events:
            if event["type"] != "accounting.voucher.posted":
                continue
            payload = event["payload"]
            if payload.get("period") != period:
                continue
            for line in payload.get("lines", []):
                if line.get("account_code") != account_code:
                    continue
                debit += dec(line.get("debit", "0"))
                credit += dec(line.get("credit", "0"))
        return {"account_code": account_code, "period": period,
                "debit": str(debit), "credit": str(credit),
                "balance": str(debit - credit)}

    def stock(self, item_id: str, warehouse: str) -> str:
        row = self._find_current("stock_balance",
                                 lambda r: r["item_id"] == item_id and r["warehouse"] == warehouse)
        return row["quantity"] if row else "0"

    # ------------------------------------------------------------------
    # 事件与审计链
    # ------------------------------------------------------------------
    def _event(self, event_type: str, actor: str, subjects, payload) -> dict:
        now = ts(self.now())
        return {
            "id": self.new_id(), "type": event_type,
            "occurred_at": now, "recorded_at": now, "actor": actor,
            "subjects": subjects, "payload": payload,
            "idempotency_key": f"{self.new_id()}:rule:0", "version": 1,
        }

    def _append_audit(self, action: str, actor: str, record: dict, events: list, payload: dict) -> None:
        resource = {"type": "command", "id": record["id"]}
        if events and events[0].get("subjects"):
            resource = {"type": events[0]["type"].split(".")[0], "id": events[0]["subjects"][0]}
        entry = {
            "id": self.new_id(),
            "sequence": len(self.audit) + 1,
            "timestamp": ts(self.now()),
            "actor": actor,
            "action": action,
            "resource": resource,
            "payload": {"command_id": record["id"], "event_ids": [e["id"] for e in events]},
            "prev_hash": self.audit[-1]["hash"] if self.audit else GENESIS_PREV_HASH,
        }
        entry["hash"] = _VT.compute_hash(entry)
        self.audit.append(entry)

    def verify_chain(self) -> list:
        return _VT.verify_chain(self.audit)

    # ------------------------------------------------------------------
    # 场景执行
    # ------------------------------------------------------------------
    def seed(self, obj_type: str, obj_id: str, data: dict, actor: str, at: str | None = None) -> dict:
        """装载夹具对象（非命令路径，不产生事件/审计；用于场景前置数据）。"""
        saved = self.clock
        if at:
            self.clock = parse_ts(at)
        row = self._create_object(obj_type, {**data, "id": obj_id}, actor)
        self.clock = saved
        return row


TOKEN_RE = re.compile(r"^\$\{(.+)\}$")


def resolve_tokens(value, context: dict):
    """解析 ${ids.x} / ${steps.S1.created.id} 等占位符（字符串整体或内嵌）。"""
    if isinstance(value, str):
        m = TOKEN_RE.match(value)
        if m:
            return resolve_path(m.group(1), context)
        return re.sub(r"\$\{([^}]+)\}", lambda mm: str(resolve_path(mm.group(1), context)), value)
    if isinstance(value, dict):
        return {k: resolve_tokens(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_tokens(v, context) for v in value]
    return value


def resolve_path(path: str, context: dict):
    node = context
    for part in path.split("."):
        if isinstance(node, dict):
            node = node[part]
        else:
            node = getattr(node, part)
    return node


def run_scenario(scenario, report_lines: list[str] | None = None) -> dict:
    """执行场景（dict 或 YAML 路径）。

    返回 {ok, steps: [...], asserts: [...], errors: [...]}；report 供 CLI 打印。
    """
    if isinstance(scenario, (str, Path)):
        scenario = load_yaml(Path(scenario))
    spec = scenario.get("scenario", scenario)
    errors: list[str] = []
    step_results: list[dict] = []
    assert_results: list[dict] = []

    kernel = Kernel(clock_start=spec.get("clock_start", "2026-10-08T09:00:00Z"),
                    authz_fixtures=spec.get("authz"))
    context: dict = {"ids": {}, "steps": {}}

    # setup
    setup = spec.get("setup", {})
    for name, value in (setup.get("ids") or {}).items():
        context["ids"][name] = value
    seed_actor = None
    if spec.get("authz"):
        principals = spec["authz"].get("principals", [])
        seed_actor = principals[0]["id"] if principals else None
    for obj in setup.get("objects", []):
        obj_id = resolve_tokens(obj["id"], context)
        context["ids"].setdefault(f"{obj['type']}.{obj_id[:8]}", obj_id)
        kernel.seed(obj["type"], obj_id, resolve_tokens(obj.get("data", {}), context),
                    obj.get("actor") or seed_actor or obj_id, at=obj.get("at"))
        kernel.advance(1)  # 装载消耗一个最小时间片，避免区间坍缩

    # steps
    for step in spec.get("steps", []):
        sid = step.get("id", f"step{len(step_results) + 1}")
        at_start = ts(kernel.now())
        kernel.advance(1)  # 命令记录时刻晚于步骤起点（时点查询可区分）
        command = {
            "type": step["command"],
            "payload": resolve_tokens(step.get("payload", {}), context),
            "idempotency_key": resolve_tokens(
                step.get("idempotency_key", f"{sid}-{spec.get('id', 'scenario')}"), context),
        }
        result = kernel.submit(command, step["actor"])
        record = {"id": sid, "command": step["command"], "actor": step["actor"],
                  "at": at_start, "result": result}
        context["steps"][sid] = {
            "created": result.get("created") or {},
            "result": result,
            "at": at_start,
            # 保留首次提交的原始（未脱敏）载荷，供幂等重放以同原文重提
            "payload": command["payload"],
        }
        expect_status = step.get("expect_status", "accepted")
        if result["status"] != expect_status:
            errors.append(f"[{sid}] 期望 {expect_status}，实际 {result['status']}"
                          f"（code={result.get('code')}）")
        if step.get("expect_code") and result.get("code") != step["expect_code"]:
            errors.append(f"[{sid}] 期望错误码 {step['expect_code']}，实际 {result.get('code')}")
        if step.get("expect_reason_code") and result.get("reason_code") != step["expect_reason_code"]:
            errors.append(f"[{sid}] 期望 reason_code {step['expect_reason_code']}，实际 {result.get('reason_code')}")
        expected_events = step.get("events", [])
        produced = [e["type"] for e in kernel.events if e["id"] in result.get("event_ids", [])]
        for wanted in expected_events:
            if wanted not in produced:
                errors.append(f"[{sid}] 缺少期望事件 {wanted}（实际 {produced}）")
        step_results.append(record)

    # asserts
    for assertion in spec.get("assert", []):
        ok, message = _run_assertion(kernel, assertion, context)
        assert_results.append({"assert": assertion, "ok": ok, "message": message})
        if not ok:
            errors.append(f"[assert] {message}")

    result = {"ok": not errors, "scenario": spec.get("id", "scenario"),
              "steps": step_results, "asserts": assert_results, "errors": errors,
              "audit_entries": len(kernel.audit)}
    if report_lines is not None:
        report_lines.append(f"场景 {result['scenario']}: {'通过' if result['ok'] else '失败'}"
                            f"（{len(step_results)} 步 / {len(assert_results)} 断言 / "
                            f"审计 {result['audit_entries']} 条）")
        for err in errors:
            report_lines.append(f"  - {err}")
    return result


def _collect_keys(node, keys: set) -> set:
    """递归收集节点内所有 dict 键（用于整条记录扫描敏感字段）。"""
    if isinstance(node, dict):
        keys.update(node.keys())
        for value in node.values():
            _collect_keys(value, keys)
    elif isinstance(node, list):
        for item in node:
            _collect_keys(item, keys)
    return keys


def _run_assertion(kernel: Kernel, assertion: dict, context: dict):
    kind = assertion.get("kind")
    if kind == "audit-chain":
        minimum = assertion.get("min_entries", 0)
        if not kernel.audit:
            if minimum > 0:
                return False, f"审计链条数 0 < {minimum}"
            return True, "空链（无受理命令）"
        errors = kernel.verify_chain()
        if minimum and len(kernel.audit) < minimum:
            return False, f"审计链条数 {len(kernel.audit)} < {minimum}"
        if errors:
            return False, f"审计链验证失败: {errors[0]['type']}@seq{errors[0].get('sequence')}"
        return True, "审计链验证通过"
    if kind == "object-field":
        obj_id = resolve_tokens(assertion["id"], context)
        row = kernel.as_of(assertion["type"], obj_id)
        if row is None:
            return False, f"对象不存在: {assertion['type']}/{obj_id}"
        actual = row.get(assertion["field"])
        expect = assertion["expect"]
        if actual != expect:
            return False, f"{assertion['type']}.{assertion['field']} 期望 {expect}，实际 {actual}"
        return True, f"{assertion['type']}.{assertion['field']} == {expect}"
    if kind == "object-count":
        rows = [r for r in kernel.objects.get(assertion["type"], [])
                if r["superseded_at"] is None
                and all(r.get(key) == value for key, value in assertion.get("where", {}).items())]
        expected = assertion["expect"]
        if len(rows) != expected:
            return False, f"{assertion['type']} 当前对象数期望 {expected}，实际 {len(rows)}"
        return True, f"{assertion['type']} 当前对象数 == {expected}"
    if kind == "command-redacted":
        step = context["steps"][assertion["step"]]
        record = kernel.commands[step["result"]["command_id"]]
        # 扫描整条命令记录（含 payload 外的字段），而非仅 payload
        present = _collect_keys(record, set())
        leaked = set(assertion.get("fields", [])).intersection(present)
        if leaked:
            return False, f"命令记录泄漏敏感字段: {sorted(leaked)}"
        return True, "命令记录不包含敏感字段"
    if kind == "balance":
        actual = kernel.balance(assertion["account_code"], assertion["period"])
        for field in ("debit", "credit", "balance"):
            if field in assertion and not dec_eq(actual[field], assertion[field]):
                return False, (f"{assertion['account_code']}@{assertion['period']} {field} "
                               f"期望 {assertion[field]}，实际 {actual[field]}")
        return True, f"{assertion['account_code']}@{assertion['period']} 余额一致"
    if kind == "stock":
        actual = kernel.stock(resolve_tokens(assertion["item_id"], context), assertion["warehouse"])
        if not dec_eq(actual, assertion["expect"]):
            return False, f"库存期望 {assertion['expect']}，实际 {actual}"
        return True, f"库存 == {assertion['expect']}"
    if kind == "time-travel":
        obj_id = resolve_tokens(assertion["id"], context)
        valid_at = context["steps"][assertion["as_of_step"]]["at"] if assertion.get("as_of_step") else None
        recorded_at = context["steps"][assertion["recorded_as_of_step"]]["at"] if assertion.get("recorded_as_of_step") else None
        valid_at = assertion.get("valid_at", valid_at)
        recorded_at = assertion.get("recorded_at", recorded_at)
        row = kernel.as_of(assertion["type"], obj_id, valid_at=valid_at, recorded_at=recorded_at)
        if row is None:
            if assertion.get("expect_absent"):
                return True, "指定时点对象不存在"
            return False, f"时点查询无版本: {assertion['type']}/{obj_id}"
        if assertion.get("expect_absent"):
            return False, f"指定时点对象意外存在: {assertion['type']}/{obj_id}"
        if row["version"] != assertion["expect_version"]:
            return False, f"时点版本期望 {assertion['expect_version']}，实际 {row['version']}"
        return True, f"时点版本 == {assertion['expect_version']}"
    if kind == "events":
        types = [e["type"] for e in kernel.events]
        for wanted in assertion.get("types", []):
            if wanted not in types:
                return False, f"缺少事件 {wanted}"
        for unwanted in assertion.get("absent", []):
            if unwanted in types:
                return False, f"不应出现事件 {unwanted}（实际出现）"
        return True, "事件集合符合预期"
    if kind == "temporal-history":
        obj_id = resolve_tokens(assertion["id"], context)
        rows = kernel.history(assertion["type"], obj_id)
        expect_n = assertion.get("expect_versions")
        if expect_n is not None and len(rows) != expect_n:
            return False, f"版本数期望 {expect_n}，实际 {len(rows)}"
        if assertion.get("expect_adjacent", True):
            for prev_row, next_row in zip(rows, rows[1:]):
                if prev_row["valid_to"] != next_row["valid_from"]:
                    return False, (f"v{prev_row['version']}→v{next_row['version']} 业务区间不相接："
                                   f"{prev_row['valid_to']} != {next_row['valid_from']}")
                if prev_row["superseded_at"] != next_row["recorded_at"]:
                    return False, (f"v{prev_row['version']}→v{next_row['version']} 系统区间不相接："
                                   f"{prev_row['superseded_at']} != {next_row['recorded_at']}")
        return True, f"版本历史（{len(rows)} 版）区间相接、无重叠"
    if kind == "idempotency":
        step = context["steps"][assertion["step"]]
        original = kernel.commands[step["result"]["command_id"]]
        # 幂等指纹基于原始载荷：重放必须提交首次的原文，而非脱敏后的存储载荷
        # （脱敏存储的载荷会被重算出不同指纹，导致凭证类命令被误判 conflict）
        replay = kernel.submit({"type": original["type"], "payload": step["payload"],
                                "idempotency_key": original["idempotency_key"]}, original["issuer"])
        if replay["command_id"] != original["id"] or replay.get("replayed") is not True:
            return False, "幂等重放未返回原结果"
        return True, "幂等重放返回原结果"
    return False, f"未知断言类型: {kind}"


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _self_test() -> bool:
    ok = True

    def report(name, cond):
        nonlocal ok
        print(f"[{'ok  ' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    fixture = {
        "scenario": {
            "id": "kernel.selftest",
            "authz": {
                "principals": [
                    {"id": "01900000-0000-7000-8000-000000000101", "type": "person", "key": "b",
                     "valid_from": "2026-01-01T00:00:00Z", "recorded_at": "2026-01-01T00:00:00Z"},
                    {"id": "01900000-0000-7000-8000-000000000102", "type": "person", "key": "m",
                     "valid_from": "2026-01-01T00:00:00Z", "recorded_at": "2026-01-01T00:00:00Z"},
                ],
                "roles": [
                    {"id": "01900000-0000-7000-8000-0000000001a1", "key": "r1",
                     "permissions": ["approval.request.submit", "approval.request.decide",
                                     "accounting.voucher.post", "accounting.period.close"],
                     "valid_from": "2026-01-01T00:00:00Z", "recorded_at": "2026-01-01T00:00:00Z"},
                ],
                "bindings": [
                    {"id": "01900000-0000-7000-8000-0000000001b1",
                     "principal": "01900000-0000-7000-8000-000000000101", "role": "r1",
                     "scope": {"department": "D1"},
                     "valid_from": "2026-01-01T00:00:00Z", "recorded_at": "2026-01-01T00:00:00Z"},
                    {"id": "01900000-0000-7000-8000-0000000001b2",
                     "principal": "01900000-0000-7000-8000-000000000102", "role": "r1",
                     "scope": {"department": "D1"},
                     "valid_from": "2026-01-01T00:00:00Z", "recorded_at": "2026-01-01T00:00:00Z"},
                ],
            },
            "setup": {
                "ids": {"voucher": "01900000-0000-7000-8000-0000000002f1"},
                "objects": [
                    {"type": "voucher", "id": "${ids.voucher}", "actor": "01900000-0000-7000-8000-000000000101",
                     "data": {"number": "记-1", "voucher_date": "2026-10-05", "status": "draft",
                              "lines": [{"account_code": "1405", "debit": "10.00", "currency": "CNY"},
                                        {"account_code": "2202", "credit": "10.00", "currency": "CNY"}]}},
                ],
            },
            "steps": [
                {"id": "T1", "actor": "01900000-0000-7000-8000-000000000101",
                 "command": "accounting.voucher.post",
                 "payload": {"voucher_id": "${ids.voucher}", "post_date": "2026-10-05"},
                 "events": ["accounting.voucher.posted"]},
            ],
            "assert": [
                {"kind": "audit-chain", "expect": "valid", "min_entries": 1},
                {"kind": "object-field", "type": "voucher", "id": "${ids.voucher}",
                 "field": "status", "expect": "posted"},
                {"kind": "balance", "account_code": "1405", "period": "2026-10", "debit": "10.00"},
                {"kind": "time-travel", "type": "voucher", "id": "${ids.voucher}",
                 "as_of_step": "T1", "expect_version": 1},
                {"kind": "idempotency", "step": "T1"},
            ],
        }
    }
    result = run_scenario(copy.deepcopy(fixture))
    report("selftest 场景全部通过", result["ok"])
    for err in result["errors"]:
        print(f"      {err}")

    # 凭证类命令：脱敏存储不得影响幂等重放（场景断言 idempotency）
    account_id = "01900000-0000-7000-8000-000000000902"
    cred_payload = {"account_id": account_id,
                    "old_secret_hash": "$2a$old-hash", "new_secret_hash": "$2a$new-hash"}
    cred_fixture = {
        "scenario": {
            "id": "kernel.credential-idempotency",
            "setup": {"objects": [
                {"type": "iam_user_account", "id": account_id,
                 "data": {"username": "member", "status": "active"}},
                {"type": "iam_credential", "id": "01900000-0000-7000-8000-000000000914",
                 "data": {"account_id": account_id, "type": "password",
                          "secret_hash": "$2a$old-hash", "status": "active", "must_change": True}},
            ]},
            "steps": [
                {"id": "T1", "actor": account_id, "command": "iam.credential.rotate",
                 "payload": cred_payload, "events": ["iam.credential.rotated"]},
            ],
            "assert": [
                {"kind": "command-redacted", "step": "T1",
                 "fields": ["old_secret_hash", "new_secret_hash", "secret_hash"]},
                {"kind": "idempotency", "step": "T1"},
            ],
        }
    }
    cred_result = run_scenario(copy.deepcopy(cred_fixture))
    report("凭证命令幂等重放（脱敏不误判冲突）", cred_result["ok"])
    for err in cred_result["errors"]:
        print(f"      {err}")

    # 同键同原文 → replay；同键异原文 → conflict（指纹基于原始载荷）
    k2 = Kernel()
    k2.seed("iam_user_account", account_id, {"username": "member", "status": "active"}, account_id)
    k2.seed("iam_credential", "01900000-0000-7000-8000-000000000914",
            {"account_id": account_id, "type": "password", "secret_hash": "$2a$old-hash",
             "status": "active", "must_change": True}, account_id)
    r1 = k2.submit({"type": "iam.credential.rotate", "payload": dict(cred_payload),
                    "idempotency_key": "cred-1"}, account_id)
    report("凭证命令首次受理", r1["status"] == "accepted")
    r2 = k2.submit({"type": "iam.credential.rotate", "payload": dict(cred_payload),
                    "idempotency_key": "cred-1"}, account_id)
    report("同键同原文重放", r2.get("replayed") is True and r2["command_id"] == r1["command_id"])
    different = dict(cred_payload, new_secret_hash="$2a$other-hash")
    r3 = k2.submit({"type": "iam.credential.rotate", "payload": different,
                    "idempotency_key": "cred-1"}, account_id)
    report("同键不同原文冲突", r3["status"] == "conflict" and r3.get("code") == "EIS-409-001")

    # 记录级脱敏：原始凭证不得出现在任何字段，指纹只存不可逆摘要
    record1 = k2.commands[r1["command_id"]]
    serialized = json.dumps(record1, ensure_ascii=False, sort_keys=True)
    report("命令记录不泄漏原始凭证", "$2a$old-hash" not in serialized
           and "$2a$new-hash" not in serialized)
    report("payload_fingerprint 为不可逆摘要",
           bool(re.fullmatch(r"[0-9a-f]{64}", record1.get("payload_fingerprint", ""))))

    # 篡改检出
    kernel = Kernel()
    kernel.submit({"type": "approval.request.submit",
                   "payload": {"operation": "inventory.stock.receive",
                               "target": {"type": "po", "id": "01900000-0000-7000-8000-000000000301"}},
                   "idempotency_key": "k1"},
                  "01900000-0000-7000-8000-000000000101")
    chain = copy.deepcopy(kernel.audit)
    chain[0]["payload"]["command_id"] = "01900000-0000-7000-8000-000000000302"
    report("篡改检出（invalid_hash）", any(e["type"] == "invalid_hash" for e in _VT.verify_chain(chain)))
    return ok


if __name__ == "__main__":
    if not _self_test():
        raise SystemExit(1)
    print("kernel 自测通过")
