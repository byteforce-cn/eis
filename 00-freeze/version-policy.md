# 版本政策（EIS Spec v1.0）

## 1. 三层独立版本化

| 层 | 版本示例 | 独立规则 |
|----|----------|----------|
| 核心契约 | `1.0.0` | 冻结；升版必须走 ADR |
| 领域扩展 | `accounting 1.0.0` | 只依赖 `core_version`，独立发布 |
| 应用案例 | `procurement 1.0.0` | 只组合扩展版本（`composition.yaml`） |

扩展声明对核心的依赖（`core_version`）；核心不得反向依赖扩展或案例。

## 2. 版本格式与语义

```
版本格式：MAJOR.MINOR.PATCH
```

### MAJOR — 破坏性变更

- 字段删除
- 字段类型变更
- 必填字段新增
- 语义变更（如时点查询语义、哈希链公式）

### MINOR — 向后兼容的新增

- 可选字段新增
- 新 API 新增
- 新事件类型新增
- 新错误码新增（仅新增，不改变既有含义）

### PATCH — 向后兼容的修复

- Bug 修复
- 文档更新
- 性能优化

## 3. 判定权威

兼容性判定表（字段级/操作级/事件级规则与所需配套动作）以
`06-evolution-contract/compatibility.rules.yaml` 为唯一权威。
工具 `tools/compatibility-checker` 按该文件对新旧版本工件进行判定。

## 4. 弃用窗口

标记为弃用的 API / 事件类型 / 字段，必须满足：

- 至少跨 **2 个 MINOR 版本**，且
- 不少于 **90 天**

弃用期内：双轨可用（旧工件保留、文档标注、监控调用量）；窗口结束后方可删除（走 MAJOR）。

## 5. 版本载体

每个工件必须显式携带版本信息：

- Schema：`$id` 中的 `/v{n}`
- OpenAPI / AsyncAPI：`info.version`
- 扩展：`manifest.yaml` 的 `version` 与 `core_version`
- 案例：`composition.yaml` 的扩展版本锁定

## 6. 冻结与解冻

- 冻结内容见 `core-freeze.md`。
- 解冻 = ADR + 可执行工件 + 验收通过 + 升版合并；流程见 `adr/README.md`。
