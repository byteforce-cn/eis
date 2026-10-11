# 库存域扩展（inventory v1.0.0，骨架）

演示“数量守恒 + 非负”类不变量。当前为骨架：对象与规则已定义，操作仅含收货（`receiveStock`），
发料（issue）/ 盘点（count）/ 调整（adjust）按同一模式补充。

## 对象

| 对象 | 说明 |
|------|------|
| `InventoryItem` 物品 | SKU、名称、计量单位 |
| `StockMovement` 出入库 | 物品 × 仓库 × 方向（receipt/issue/adjust）× 数量 |
| `StockBalance` 库存余额 | 物品 × 仓库 × 当前数量（由变动投射） |

## 规则

- `rules/non-negative.yaml`：任何变动后 `quantity >= 0`（错误码 INV-400-001，enforcement: prevent）

## 关联核心

- SoD：`04-authz-contract/sod.rules.yaml` 的 SOD-003（盘点与调整分离）引用 `inventory.count` / `inventory.adjust` 权限
