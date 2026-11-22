# Scope Primitive v1

数据权限（data-scope）条件的**可组合 JSON 表达式树**契约。策略引擎（Rego/OPA 等）输出这棵树，
业务侧的方言翻译器把它翻译成 `WHERE` 条件；两侧只依赖这里冻结的原语集合，不共享 SQL 字符串。

- 权威定义：[`v1.json`](v1.json)（JSON Schema 2020-12）
- 契约版本：`v1`（已冻结，见 [CHANGELOG.md](CHANGELOG.md)）
- 引用方式：按 `$id` 引用 —— `https://byteforce-cn.github.io/eis/schemas/scope-primitive/v1.json`，
  **不要**按仓库路径硬编码（路径可能随仓库结构变化，`$id` 与版本绑定）。
- 治理：纳入 EIS 的决策与边界见 [ADR-0024](../../00-freeze/adr/0024-scope-primitive-schema-adoption.md)。

## 1. 用途与边界

| 属于本契约 | 不属于本契约 |
| --- | --- |
| 数据范围表达式（行级过滤意图） | 功能授权（permit/deny、角色判定）—— 属于授权策略，不在此 Schema |
| 21 个有限、可枚举原语 | 方言差异（SQL 生成规则由各实现的翻译器负责） |
| 布尔原语的常量折叠语义 | 具体 ORM / 数据库绑定 |

角色检查不在本 Schema 内：Rego 先按角色决定授予哪些 scope，再把 scope 交给翻译器。
布尔原语（`isMember` / `all` / `none`）折叠为 all/none，**不产生行级过滤**；行级原语产生
`WHERE` 条件。Java 侧必须先求值布尔原语并常量折叠，再翻译行级原语。

## 2. 常量折叠真值表（Rego 与 Java 两侧必须一致，且由两侧 CI 覆盖）

```text
and[all, x]        = x
and[none, x]       = none
and[all, all]      = all
or[none, x]        = x
or[all, x]         = all
or[none, none]     = none
not(all)           = none
not(none)          = all
not(not(x))        = x
isMember(r) == true  -> all
isMember(r) == false -> none
```

## 3. fail-closed 约定

- 未识别的 `op`、缺失/多余字段、越界字面量一律**拒绝**，不得退化为 `all`；
- `fieldRef` 只允许单表逻辑字段名（`^[a-z][a-z0-9_]{0,63}$`）；点路径 / 表别名 / 裸列名不支持，
  需要 JOIN 的场景由显式 mapper 处理；
- `attrRef` 的最终有效性（注册名、点分规则、provider 命名）由 `SubjectAttributesProvider`
  注册表校验，Schema 只做基本约束；
- 运行时反序列化必须用 `@JsonTypeInfo(use=NAME, property='op')` + `PrimitiveRegistry`，
  **不要**对每个请求跑 `oneOf` 校验（成本高且错误信息不可用）。

## 4. 版本策略

- `v1` 冻结：不修改结构、默认值、折叠规则、fail-closed 边界；
- 新增原语 / 调整默认语义 / 修改折叠规则 / 改变 fail-closed 边界 → 必须新增 `v2.json`，
  `v1.json` 保留；
- 勘误级修订（`description` / `examples` / 文档）可在 `v1` 内进行，但必须记录到
  [CHANGELOG.md](CHANGELOG.md)；
- `$id` 与版本绑定，不随仓库路径变化。

## 5. 与业务侧的关系

- EIS 是本契约的**权威来源**；
- 业务侧 Java 翻译器、Rego 策略包通过 `$id` 引用；构建期可保留镜像副本，但以 EIS 版本为准；
- 业务侧发现的问题走 EIS 评审：勘误进 `v1`，语义变更开 `v2`。
