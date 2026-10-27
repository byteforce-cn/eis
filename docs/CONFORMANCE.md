# 合规等级（Conformance）

> 一个实现满足 EIS 的程度分为四级（累进）。等级越高，可替代性越强、
> 跨系统互操作性越好。**每一级都必须可验证**，验证工具随本仓库发布。

## 等级定义

| 等级 | 名称 | 要求 | 验证方式 |
|------|------|------|----------|
| **L1** | 数据契约合规 | 对象/事件/命令/视图元结构 + 双时间轴 + 审计表结构可生成并可在 PostgreSQL 16 执行 | `tools/schema-compiler check`；`tools/ci/ddl-smoke.sql` 全过 |
| **L2** | 操作契约合规 | 命令/查询/事件 API 符合元结构（幂等键、`as_of`、错误码、202/400/409、`GET /commands/{id}`） | `tools/contract-checker` 对实现工件全过；边界行为与参考内核一致 |
| **L3** | 授权与审计合规 | as_of 授权解析（含代理）、SoD prevent/warn；哈希链通过**冻结测试向量**与篡改检测 | `tools/authz-resolver --self-test`；`tools/audit-verifier --vector` + 链夹具用例 |
| **L4** | 演进合规 | 兼容性门禁（`compatibility.rules.yaml`）、迁移+回滚+对账路径、弃用窗口（≥2 MINOR 且 ≥90 天） | `tools/compatibility-checker --fail-on MAJOR`；`06` 契约用例 |

## 扩展级合规

领域扩展可单独声明合规（“在 L2 核心之上，`accounting 1.0.0` 合规”），条件：

1. 扩展自身用例（`extensions/{id}/tests/*.test.yaml`）全部通过；
2. 引用完整性通过（`contract-checker` 的清单/组合检查）；
3. 不修改核心语义（仅 `allOf` 扩展）；
4. 读取面权限已在 `manifest.permissions` 声明（ADR-0006），实现按声明接入 `/check`，不自造权限标识。

## 声明模板

在实现项目 README 中声明（示例）：

```markdown
## EIS 合规

- 合规等级：**L3**（数据 / 操作 / 授权 / 审计），核心契约版本 `1.0.0`
- 验证记录：e2e-runner 汇总 `用例 135/135`（填入运行日期，`<实现提交 SHA>`）
- 扩展：accounting 1.0.0、approval 1.0.1、hr 1.1.0（扩展级合规；授权属性按 ATR-001..008，
  读取面按 ADR-0006 使用扩展声明的 `manifest.permissions`）
```

## 自验命令

```bash
# 规范侧全量（任何实现都可以跑，用来对照）
python3 tools/e2e-runner --all

# 单点验证
python3 tools/schema-compiler check
python3 tools/contract-checker
python3 tools/audit-verifier --vector
python3 tools/authz-resolver --self-test
python3 tools/compatibility-checker --self-test
```
