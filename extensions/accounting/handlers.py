# -*- coding: utf-8 -*-
"""accounting 扩展命令处理器（内核注册机制，见 extensions/README.md §6）。

处理器签名：(api, payload, actor, command_id) -> (events, created)。
"""
from __future__ import annotations

import re
from decimal import Decimal

# 处理器只依赖内核注入的 ExtensionAPI（不使用 kernel 模块内部）

COMMANDS = {}


def register(api):
    """返回命令类型 → 处理器映射（加载时由内核调用）。"""
    return {
        "accounting.voucher.post": post_voucher,
        "accounting.period.close": close_period,
    }


def post_voucher(api, payload, actor, command_id):
    voucher_id = payload.get("voucher_id")
    post_date = payload.get("post_date")
    if not voucher_id or not post_date:
        raise api.reject("EIS-400-001", "缺少 voucher_id 或 post_date")
    row = api.as_of("voucher", voucher_id)
    if row is None:
        raise api.reject("EIS-404-001", f"凭证不存在: {voucher_id}")
    if row["status"] != "draft":
        raise api.reject("EIS-400-002", f"凭证状态不可过账: {row['status']}")
    period = str(post_date)[:7]
    # 规则 double_entry：按币种分组借贷平衡
    groups: dict[str, dict[str, Decimal]] = {}
    for line in row["lines"]:
        cur = line.get("currency", "CNY")
        g = groups.setdefault(cur, {"debit": Decimal(0), "credit": Decimal(0)})
        g["debit"] += api.dec(line.get("debit", "0"))
        g["credit"] += api.dec(line.get("credit", "0"))
    for cur, g in groups.items():
        if g["debit"] != g["credit"]:
            raise api.reject("ACC-400-001",
                           f"凭证借贷不平衡（{cur}）：借方 {g['debit']}，贷方 {g['credit']}")
    # 规则 period_lock
    if period in api.locked_periods:
        raise api.reject("ACC-409-001", f"会计期间 {period} 已锁定")
    # 接受：状态变更 + 事件
    api.update_object("voucher", voucher_id,
                      {"status": "posted", "posted_at": api.ts(api.now())}, actor)
    event = api.event("accounting.voucher.posted", actor,
                      subjects=[voucher_id],
                      payload={"voucher_id": voucher_id, "number": row["number"],
                               "period": period, "lines": row["lines"]})
    return [event], {"type": "voucher", "id": voucher_id}


def close_period(api, payload, actor, command_id):
    period = payload.get("period")
    if not period or not re.match(r"^\d{4}-\d{2}$", str(period)):
        raise api.reject("EIS-400-001", "缺少合法 period（YYYY-MM）")
    if period in api.locked_periods:
        raise api.reject("ACC-409-002", f"会计期间 {period} 已关闭")
    for row in api.current_objects("voucher"):
        if row.get("status") == "draft" and str(row.get("voucher_date", ""))[:7] == period:
            raise api.reject("ACC-400-002", f"期间 {period} 存在未过账凭证: {row['number']}")
    api.locked_periods.add(period)
    event = api.event("accounting.period.closed", actor, subjects=[],
                      payload={"period": period})
    return [event], {"type": "period", "id": period}
