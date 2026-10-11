# 会计域扩展（accounting v1.0.0）

会计域的完整示例扩展：演示对象、操作、规则、不变量的标准写法。

## 对象

| 对象 | 说明 | 核心元结构 |
|------|------|-----------|
| `Account` 科目 | 会计科目（资产/负债/权益/收入/费用），带余额方向 | `allOf` + `01-data-contract/object.schema.json` |
| `Voucher` 凭证 | 借贷分录集合；过账需借贷平衡 | 同上 |
| `Balance` 余额 | 科目在某期间的累计值（读模型） | 同上 |

## 操作

| 操作 | 命令类型 | 校验 |
|------|----------|------|
| 过账 `postVoucher` | `accounting.voucher.post` | 借贷平衡（ACC-400-001）、期间未锁定（ACC-409-001） |
| 关账 `closePeriod` | `accounting.period.close` | 期间无未过账凭证；重复关账拒绝（ACC-409-002） |

所有操作遵循核心命令 API 元结构（幂等键、202/400/409），见 `02-operation-contract/command.openapi.yaml`。

## 规则与不变量

- `rules/double-entry.yaml`：借贷平衡（enforcement: prevent）
- `rules/period-lock.yaml`：期间锁定（enforcement: prevent）
- 不变量：`sum(debit) == sum(credit)`、`posted_at not in locked_periods`

## 时间语义

- 凭证的 `voucher_date` 为业务时间（决定落入哪个会计期间）
- 过账事实以系统时间（`recorded_at`）追加；红冲/更正以新版本追加（时间契约 T-R006/T-R011）
