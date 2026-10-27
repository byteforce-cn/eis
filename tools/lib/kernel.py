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

扩展机制（新增领域无需修改内核源码）：
  - 命令处理器按扩展注册：`extensions/<id>/handlers.py`
  - 模块提供 `register(api) -> {command_type: handler}`（或 `COMMANDS` 映射）；
    handler 签名 `(api, payload, actor, command_id) -> (events, created)`；
  - 可选 `SENSITIVE_FIELDS = {command_type: (field, ...)}` 声明命令记录脱敏字段；
  - 可选 `WRITE_ONLY_FIELDS = {object_type: (field, ...)}` 声明读投影剔除字段（writeOnly）；
  - 可选 `derive_write_only(scope, raw)` / `write_only_variants(scope, raw)` 做服务端派生
    （HMAC-SHA256 密钥环：首密钥为主，余为轮换接受集；见 01 数据契约 DRV-*）；
  - 可选 `DEFERRED_AUTHZ = {command_type, ...}` 声明处理器内部做细粒度权限判定
    （如区块属主权限 `approval.section.confirm.<owner>`），内核跳过命令级预检；
  - 处理器只通过 `ExtensionAPI`（见下）访问内核能力。

明确不做（参考实现的边界，生产实现需补齐）：
  - 持久化（内存）、并发控制、真实时钟、分区与索引优化
  - 通用规则引擎：领域规则由各扩展处理器自行实现（参考 accounting / inventory /
    approval / iam 的 handlers.py）

使用：run_scenario(scenario_dict_or_path) → 场景报告；Kernel 类可直接嵌入测试。
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
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


# 写入专用派生字段（01-data-contract/write-only-fields.rules.yaml DRV-*）。
# 密钥环：首密钥为主（新写入），其余为轮换接受集（防重比对）；生产必须注入，
# 缺省值仅供参考内核/测试使用。
DEFAULT_FIELD_HASH_KEYS = ("eis-dev-field-hash-key",)


def field_hash_keys_from_env() -> tuple[str, ...]:
    raw = os.environ.get("EIS_FIELD_HASH_KEYS", "")
    keys = tuple(k.strip() for k in raw.split(",") if k.strip())
    return keys or DEFAULT_FIELD_HASH_KEYS


def derive_hmac(keys, scope: str, raw: str) -> str:
    """HMAC-SHA256(keys[0], scope + 0x00 + raw)，小写十六进制（域分离）。"""
    message = scope.encode("utf-8") + b"\x00" + raw.encode("utf-8")
    return hmac.new(keys[0].encode("utf-8"), message, hashlib.sha256).hexdigest()


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
def load_permission_callers() -> dict[str, tuple[str, ...]]:
    """载入扩展 manifest 的调用方约束（ADR-0013）：命令 → 允许的主体类型。

    权威只在 manifest.permissions[].callers；operations 契约的 x-eis-callers 是
    可校验投影（contract-checker 双向校验），内核不解析 OpenAPI。
    """
    callers: dict[str, tuple[str, ...]] = {}
    ext_root = ROOT / "extensions"
    if not ext_root.is_dir():
        return callers
    for manifest_path in sorted(ext_root.glob("*/manifest.yaml")):
        ext = load_yaml(manifest_path).get("extension", {}) or {}
        for perm in ext.get("permissions", []) or []:
            if not isinstance(perm, dict):
                continue
            pid, allowed = perm.get("id"), perm.get("callers")
            if isinstance(pid, str) and isinstance(allowed, list) and allowed:
                callers[pid] = tuple(allowed)
    return callers


def load_authz_module():
    loader = SourceFileLoader("eis_authz_kernel", str(ROOT / "tools" / "authz-resolver"))
    module = module_from_spec(spec_from_loader("eis_authz_kernel", loader))
    loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 扩展 API 与处理器注册
# ---------------------------------------------------------------------------
class ExtensionAPI:
    """扩展处理器可用的内核能力面（受控接缝，不直接触碰 Kernel 内部实现）。"""

    def __init__(self, kernel: "Kernel"):
        self._kernel = kernel

    # -- 时钟 / 标识 / 值转换 -------------------------------------------
    def now(self) -> datetime:
        return self._kernel.now()

    def advance(self, seconds: int = 60) -> None:
        self._kernel.advance(seconds)

    def new_id(self) -> str:
        return self._kernel.new_id()

    def ts(self, dt: datetime) -> str:
        return ts(dt)

    def parse_ts(self, value) -> datetime:
        return parse_ts(value)

    def dec(self, value) -> Decimal:
        return dec(value)

    def dec_eq(self, a, b) -> bool:
        return dec_eq(a, b)

    # -- 写入专用派生字段（DRV-*） --------------------------------------
    def derive_write_only(self, scope: str, raw: str) -> str:
        """服务端派生写入专用字段（主密钥）。"""
        return derive_hmac(self._kernel.field_hash_keys, scope, raw)

    def write_only_variants(self, scope: str, raw: str) -> list[str]:
        """同一原始值在密钥环全部密钥下的散列（主密钥在前），供防重跨轮换比对。"""
        return [derive_hmac((key,), scope, raw) for key in self._kernel.field_hash_keys]

    # -- 拒绝 -----------------------------------------------------------
    def reject(self, code: str, reason: str, reason_code: str | None = None):
        """拒绝当前命令（抛出内核统一捕获的 Rejected）。"""
        raise Rejected(code, reason, reason_code)

    # -- 对象（双时间轴） -----------------------------------------------
    def create_object(self, obj_type: str, data: dict, actor: str) -> dict:
        return self._kernel._create_object(obj_type, data, actor)

    def update_object(self, obj_type: str, obj_id: str, updates: dict, actor: str,
                      extra=None) -> dict:
        return self._kernel._update_object(obj_type, obj_id, updates, actor, extra)

    def find_current(self, obj_type: str, pred) -> dict | None:
        return self._kernel._find_current(obj_type, pred)

    def objects(self, obj_type: str) -> list[dict]:
        """某类型的全部版本行（append-only，含已封口版本）。"""
        return self._kernel.objects.get(obj_type, [])

    def current_objects(self, obj_type: str) -> list[dict]:
        return [r for r in self._kernel.objects.get(obj_type, []) if r["superseded_at"] is None]

    def as_of(self, obj_type: str, obj_id: str, valid_at=None, recorded_at=None) -> dict | None:
        return self._kernel.as_of(obj_type, obj_id, valid_at, recorded_at)

    def history(self, obj_type: str, obj_id: str) -> list[dict]:
        return self._kernel.history(obj_type, obj_id)

    # -- 事件 -----------------------------------------------------------
    def event(self, event_type: str, actor: str, subjects, payload) -> dict:
        return self._kernel._event(event_type, actor, subjects, payload)

    # -- 读模型 / 领域状态 ----------------------------------------------
    def stock(self, item_id: str, warehouse: str) -> str:
        return self._kernel.stock(item_id, warehouse)

    @property
    def locked_periods(self) -> set:
        return self._kernel.locked_periods

    # -- 授权 -----------------------------------------------------------
    @property
    def authz(self):
        return self._kernel.authz

    def principal_of(self, actor: str) -> str:
        return self._kernel.principal_of(actor)

    def check_permission(self, actor: str, permission: str, as_of=None) -> dict:
        """处理器内细粒度权限检查（区块属主等动态权限用）。"""
        if self._kernel.authz is None:
            return {"allowed": True, "reason": "未装载授权夹具", "reason_code": "ALLOWED"}
        moment = ts(parse_ts(as_of)) if as_of else ts(self._kernel.now())
        return self._kernel.authz.check(self._kernel.principal_of(actor), permission, moment)


def load_extension_handlers(kernel: "Kernel") -> dict[str, callable]:
    """加载 `extensions/*/handlers.py` 的命令处理器。

    新增扩展只需自带 handlers.py，无需修改内核源码即可执行契约用例。
    """
    handlers: dict[str, callable] = {}
    ext_root = ROOT / "extensions"
    if not ext_root.is_dir():
        return handlers
    for ext_dir in sorted(p for p in ext_root.iterdir() if p.is_dir()):
        path = ext_dir / "handlers.py"
        if not path.exists():
            continue
        loader = SourceFileLoader(f"eis_handlers_{ext_dir.name}", str(path))
        module = module_from_spec(spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        if hasattr(module, "register"):
            registry = module.register(kernel.api)
        else:
            registry = getattr(module, "COMMANDS", None)
        if not isinstance(registry, dict):
            raise RuntimeError(f"{path}: handlers.py 必须提供 register(api) 或 COMMANDS 映射")
        for cmd_type, handler in registry.items():
            if not callable(handler):
                raise RuntimeError(f"{path}: {cmd_type} 的处理器不可调用")
            if cmd_type in handlers:
                raise RuntimeError(f"命令处理器重复注册: {cmd_type}（{path}）")
            handlers[cmd_type] = handler
        for cmd_type, fields in (getattr(module, "SENSITIVE_FIELDS", None) or {}).items():
            kernel.register_sensitive(cmd_type, fields)
        for obj_type, fields in (getattr(module, "WRITE_ONLY_FIELDS", None) or {}).items():
            kernel.register_write_only(obj_type, fields)
        for cmd_type in (getattr(module, "DEFERRED_AUTHZ", None) or ()):
            kernel.deferred_authz.add(cmd_type)
    return handlers


class Kernel:
    """EIS 参考内核：命令受理 → 规则 → 事件 → 审计链 → 双时间轴对象。"""

    def __init__(self, clock_start="2026-10-08T09:00:00Z", authz_fixtures: dict | None = None,
                 field_hash_keys: list[str] | None = None):
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

        # 扩展机制：处理器注册、脱敏字段、延迟授权、写入专用字段
        self.sensitive_fields: dict[str, tuple[str, ...]] = {}
        self.deferred_authz: set[str] = set()
        self.field_hash_keys: tuple[str, ...] = (
            tuple(field_hash_keys) if field_hash_keys else field_hash_keys_from_env()
        )
        self.write_only_fields: dict[str, tuple[str, ...]] = {}
        # 命令调用方约束：命令 → 允许的主体类型（ADR-0013，缺省不限制）
        self.permission_callers: dict[str, tuple[str, ...]] = load_permission_callers()
        self.api = ExtensionAPI(self)
        self.command_handlers: dict[str, callable] = load_extension_handlers(self)

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

    def register_sensitive(self, command_type: str, fields) -> None:
        """登记命令记录的脱敏字段（处理器模块通过 SENSITIVE_FIELDS 声明）。"""
        merged = set(self.sensitive_fields.get(command_type, ()))
        merged.update(fields)
        self.sensitive_fields[command_type] = tuple(sorted(merged))

    def register_write_only(self, obj_type: str, fields) -> None:
        """登记读投影剔除字段（处理器模块通过 WRITE_ONLY_FIELDS 声明）。"""
        merged = set(self.write_only_fields.get(obj_type, ()))
        merged.update(fields)
        self.write_only_fields[obj_type] = tuple(sorted(merged))

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
        for field in self.sensitive_fields.get(cmd_type, ()):
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
            # 授权（若装载）：命令级预检；DEFERRED_AUTHZ 命令由处理器内部细粒度判定
            if self.authz is not None and cmd_type not in self.deferred_authz:
                decision = self.authz.check(principal, cmd_type, ts(self.now()))
                if not decision["allowed"]:
                    raise Rejected(decision.get("reason_code", "EIS-403-001"), decision["reason"])
            # 调用方主体类型约束（ADR-0013）：与判定结果无关，fail-closed
            allowed_callers = self.permission_callers.get(cmd_type)
            if allowed_callers is not None and self.authz is not None:
                try:
                    principal_type = self.authz.principal(principal).get("type")
                except KeyError:
                    principal_type = None
                if principal_type not in allowed_callers:
                    raise Rejected(
                        "EIS-403-002",
                        f"{cmd_type} 仅限调用方主体类型 {', '.join(allowed_callers)}，"
                        f"实际 {principal_type}",
                    )
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
    # 命令分发（处理器由 extensions/*/handlers.py 注册）
    # ------------------------------------------------------------------
    def _handle(self, cmd_type: str, payload: dict, actor: str, command_id: str):
        handler = self.command_handlers.get(cmd_type)
        if handler is None:
            raise Rejected("EIS-400-001", f"未知命令类型: {cmd_type}")
        return handler(self.api, payload, actor, command_id)

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

    def read_projection(self, obj_type: str, obj_id: str, valid_at=None, recorded_at=None) -> dict | None:
        """读投影：剔除写入专用字段（writeOnly）后的对象视图（DRV-004）。"""
        row = self.as_of(obj_type, obj_id, valid_at, recorded_at)
        if row is None:
            return None
        excluded = self.write_only_fields.get(obj_type, ())
        return {k: v for k, v in row.items() if k not in excluded}

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
            "payload_digest": _VT.compute_payload_digest(events),
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
                    authz_fixtures=spec.get("authz"),
                    field_hash_keys=spec.get("field_hash_keys"))
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
        if assertion.get("verify_payload_digest"):
            by_id = {e["id"]: e for e in kernel.events}
            for entry in kernel.audit:
                event_ids = (entry.get("payload") or {}).get("event_ids") or []
                missing = [eid for eid in event_ids if eid not in by_id]
                if missing:
                    return False, f"审计条目 seq={entry.get('sequence')} 引用的事件缺失: {missing[0]}"
                expected = _VT.compute_payload_digest([by_id[eid] for eid in event_ids])
                if entry.get("payload_digest") != expected:
                    return False, f"payload_digest 与事件不符: seq={entry.get('sequence')}"
        return True, "审计链验证通过"
    if kind == "object-field":
        obj_id = resolve_tokens(assertion["id"], context)
        if assertion.get("read_projection"):
            row = kernel.read_projection(assertion["type"], obj_id)
        else:
            row = kernel.as_of(assertion["type"], obj_id)
        if row is None:
            return False, f"对象不存在: {assertion['type']}/{obj_id}"
        actual = row.get(assertion["field"])
        expect = resolve_tokens(assertion["expect"], context)
        if actual != expect:
            return False, f"{assertion['type']}.{assertion['field']} 期望 {expect}，实际 {actual}"
        return True, f"{assertion['type']}.{assertion['field']} == {expect}"
    if kind == "object-absent":
        obj_id = resolve_tokens(assertion["id"], context)
        row = kernel.read_projection(assertion["type"], obj_id)
        if row is None:
            return False, f"对象不存在: {assertion['type']}/{obj_id}"
        fields = assertion.get("fields", [])
        leaked = [field for field in fields if field in row]
        if leaked:
            return False, f"读投影泄漏写入专用字段: {leaked}"
        return True, f"读投影不含字段 {fields}"
    if kind == "object-count":
        where = {key: resolve_tokens(value, context)
                 for key, value in (assertion.get("where") or {}).items()}
        rows = [r for r in kernel.objects.get(assertion["type"], [])
                if r["superseded_at"] is None
                and all(r.get(key) == value for key, value in where.items())]
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

    # payload_digest：审计条目绑定事件投影（id/type/payload），事件正文篡改可复算检出
    by_id = {e["id"]: e for e in kernel.events}
    report("审计条目携带 payload_digest 且可由事件复算",
           all(entry.get("payload_digest") == _VT.compute_payload_digest(
               [by_id[eid] for eid in entry["payload"]["event_ids"]])
               for entry in kernel.audit))
    tampered_events = copy.deepcopy(kernel.events)
    tampered_events[0]["payload"] = dict(tampered_events[0]["payload"], __tampered__=True)
    report("事件正文篡改被检出（payload_digest_mismatch）", any(
        x["type"] == "payload_digest_mismatch"
        for x in _VT.verify_payload_digests(kernel.audit, tampered_events)))
    return ok


if __name__ == "__main__":
    if not _self_test():
        raise SystemExit(1)
    print("kernel 自测通过")
