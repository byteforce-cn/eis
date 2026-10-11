# -*- coding: utf-8 -*-
"""inventory 扩展命令处理器（内核注册机制，见 extensions/README.md §6）。"""
from __future__ import annotations

# 处理器只依赖内核注入的 ExtensionAPI（不使用 kernel 模块内部）

COMMANDS = {}


def register(api):
    return {
        "inventory.stock.receive": receive_stock,
    }


def receive_stock(api, payload, actor, command_id):
    item_id = payload.get("item_id")
    warehouse = payload.get("warehouse")
    quantity = payload.get("quantity")
    if not (item_id and warehouse and quantity):
        raise api.reject("EIS-400-001", "缺少 item_id / warehouse / quantity")
    qty = api.dec(quantity)
    if qty <= 0:
        raise api.reject("INV-400-001", f"收货数量必须 > 0：{quantity}")
    # 规则 non_negative：应用后余额 >= 0（receipt 恒增，此处仍校验）
    balance = api.dec(api.stock(item_id, warehouse)) + qty
    if balance < 0:
        raise api.reject("INV-400-001", f"库存不足：余额 {balance}")
    # 更新库存余额对象 + 记录变动对象
    row = api.find_current("stock_balance",
                           lambda r: r["item_id"] == item_id and r["warehouse"] == warehouse)
    if row is None:
        api.create_object("stock_balance", {
            "item_id": item_id, "warehouse": warehouse,
            "quantity": str(qty), "unit": payload.get("unit", "EA"),
        }, actor)
    else:
        api.update_object("stock_balance", row["id"], {"quantity": str(balance)}, actor)
    movement = api.create_object("stock_movement", {
        "item_id": item_id, "warehouse": warehouse, "movement_type": "receipt",
        "quantity": str(qty), "reference": payload.get("reference"),
    }, actor)
    event = api.event("inventory.stock.received", actor, subjects=[item_id],
                      payload={"item_id": item_id, "warehouse": warehouse,
                               "quantity": str(qty), "reference": payload.get("reference")})
    return [event], {"type": "stock_movement", "id": movement["id"]}
