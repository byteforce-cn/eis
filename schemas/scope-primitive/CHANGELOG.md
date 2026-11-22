# Scope Primitive — Changelog

格式遵循 Keep a Changelog；版本策略见 [README.md](README.md) §4。

## [v1] — 2026-11-22

### Added

- 初始纳入（ADR-0024 / issue #59）：`v1.json` 从已冻结的业务侧 Schema 逐字迁入，25 个 `$defs`、
  21 个原语（`all` / `none` / `and` / `or` / `not` / `eq` / `ne` / `in` / `notIn` / `lt` / `lte` /
  `gt` / `gte` / `between` / `nullCheck` / `startsWith` / `memberOf` / `isMember` /
  `ownerIsSubject` / `deptScope` / `subjectAttrCmp`）。
- `$id` 固定为 `https://byteforce-cn.github.io/eis/schemas/scope-primitive/v1.json`。

### Changed

- `$comment` 由「PROPOSED for inclusion」更新为「ADOPTED by EIS (ADR-0024)」；**Schema 主体
  （结构、默认值、折叠规则、fail-closed 边界）与业务侧冻结版本逐字一致**，本次仅修订该说明字段。
