#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eis_compat — EIS 兼容性判定核心（纯 stdlib，零 EIS 运行时依赖）。

用途：新旧 JSON Schema diff → MAJOR/MINOR/PATCH + 配套动作（requires）。
本模块不读取仓库文件、不依赖 PyYAML/jsonschema：规则映射由调用方注入
（`build_rule_index`），`rule_index=None` 时使用内置缺省 `DEFAULT_REQUIRES`
（与 `06-evolution-contract/compatibility.rules.yaml` 的四条数据规则一致）。

规范权威：`06-evolution-contract/compatibility.rules.yaml`、
`00-freeze/version-policy.md`；CLI 封装见 `tools/compatibility-checker`
（支持 `--standalone` 脱离本仓库运行）。
"""
from __future__ import annotations

LEVEL_ORDER = {"PATCH": 0, "MINOR": 1, "MAJOR": 2}

# kind → (规则表 scope, 规则名)——命中 rules 文件时取 requires
KIND_TO_RULE = {
    "字段删除": ("data", "字段删除"),
    "字段类型变更": ("data", "字段类型变更"),
    "可选字段新增": ("data", "可选字段新增"),
    "必填字段新增": ("data", "必填字段新增"),
}
# 内置缺省配套动作（standalone / 规则文件缺失时使用；与规则文件逐项一致）
DEFAULT_REQUIRES = {
    "字段删除": ["migration", "dual_write", "rollback"],
    "字段类型变更": ["migration", "dual_write", "rollback"],
    "可选字段新增": [],
    "必填字段新增": ["migration", "backfill", "dual_write"],
    "枚举取值收缩": ["migration"],
    "枚举取值扩展": [],
    "必填放宽": [],
    "约束收紧": ["migration"],
    "约束放宽": [],
    "$ref 无法解析": [],
    "递归过深": [],
}

MAX_DIFF_DEPTH = 64
COMBINERS = ("allOf", "anyOf", "oneOf")

# 下界类：数值增大为收紧；上界类：数值减小为收紧
LOWER_BOUNDS = ("minLength", "minimum", "exclusiveMinimum", "minItems")
UPPER_BOUNDS = ("maxLength", "maximum", "exclusiveMaximum", "maxItems")
# 逐节点比较的约束关键词（type/format 归入“类型变更”，enum/required 单独处理）
CONSTRAINT_KEYWORDS = LOWER_BOUNDS + UPPER_BOUNDS + (
    "pattern", "const", "multipleOf", "additionalProperties",
)


def build_rule_index(rules: dict) -> dict:
    """将 compatibility.rules.yaml 文档转为 {(scope, rule): entry} 索引。"""
    idx = {}
    for scope in ("data", "operation", "event"):
        for r in (rules.get("compatibility", {}) or {}).get(scope, []) or []:
            idx[(scope, r["rule"])] = r
    return idx


def norm_type(prop: dict):
    t = prop.get("type")
    if isinstance(t, list):
        t = tuple(sorted(map(str, t)))
    return (t, prop.get("format"))


def type_desc(node: dict) -> str:
    t = node.get("type")
    fmt = node.get("format")
    return f"{t}:{fmt}" if fmt else str(t)


def resolve_local_ref(node, root, seen=None):
    """解析本地 $ref（#/$defs/... 或 #/definitions/...）。

    返回 (resolved_node, ref, error)：无 $ref 时 ref/error 为 None；
    无法解析或循环时 node 原样返回并给出 error（调用方保守判 MAJOR）。
    """
    if not isinstance(node, dict) or "$ref" not in node:
        return node, None, None
    ref = node["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#"):
        return node, ref, f"仅支持本地 $ref，无法解析 {ref!r}"
    if seen is None:
        seen = set()
    if ref in seen:
        return node, ref, f"$ref 循环引用 {ref}"
    seen.add(ref)
    target = root
    for part in [p for p in ref.lstrip("#/").split("/") if p != ""]:
        part = part.replace("~1", "/").replace("~0", "~")
        try:
            target = target[part]
        except (KeyError, TypeError):
            return node, ref, f"$ref 无法解析 {ref}"
    return resolve_local_ref(target, root, seen)


def _constraint_direction(keyword: str, old_val, new_val) -> str | None:
    """返回 'tighten'（收紧）/ 'loosen'（放宽）/ 'change'（不可比，保守收紧）/ None。"""
    if old_val == new_val:
        return None
    if keyword in LOWER_BOUNDS:
        if old_val is None:
            return "tighten"
        if new_val is None:
            return "loosen"
        return "tighten" if new_val > old_val else "loosen"
    if keyword in UPPER_BOUNDS:
        if old_val is None:
            return "tighten"
        if new_val is None:
            return "loosen"
        return "tighten" if new_val < old_val else "loosen"
    if keyword == "pattern":
        if new_val is None:
            return "loosen"
        return "tighten"
    if keyword == "const":
        if new_val is None:
            return "loosen"
        return "tighten"
    if keyword == "multipleOf":
        if new_val is None:
            return "loosen"
        return "tighten"
    if keyword == "additionalProperties":
        # 缺省等价于 true（允许额外属性）
        old_allowed = old_val is not False
        new_allowed = new_val is not False
        if old_allowed == new_allowed:
            return None
        return "tighten" if not new_allowed else "loosen"
    return None


def _compare_enum(old_node: dict, new_node: dict, path: str, changes: list) -> None:
    oenum = {str(v) for v in old_node.get("enum", [])}
    nenum = {str(v) for v in new_node.get("enum", [])}
    if oenum and nenum and (oenum - nenum):
        changes.append({"kind": "枚举取值收缩", "prop": path, "level": "MAJOR",
                        "detail": f"移除取值 {sorted(oenum - nenum)}"})
    elif nenum - oenum:
        changes.append({"kind": "枚举取值扩展", "prop": path, "level": "MINOR",
                        "detail": f"新增取值 {sorted(nenum - oenum)}"})


def diff_node(old_node, new_node, path: str, old_root, new_root, changes: list,
              depth: int = 0) -> None:
    """递归比较两个 Schema 节点（解析本地 $ref 后逐层下钻，含 allOf/anyOf/oneOf）。"""
    if depth > MAX_DIFF_DEPTH:
        changes.append({"kind": "递归过深", "prop": path, "level": "MAJOR",
                        "detail": f"递归深度超过 {MAX_DIFF_DEPTH} 层，保守判 MAJOR"
                                  f"（可能是 $ref 自引用图）"})
        return
    # 相同的外部（非本地）$ref：视为未变，不做跨文件解析
    o_ref_raw = old_node.get("$ref") if isinstance(old_node, dict) else None
    n_ref_raw = new_node.get("$ref") if isinstance(new_node, dict) else None
    if o_ref_raw is not None and o_ref_raw == n_ref_raw and not str(o_ref_raw).startswith("#"):
        return
    old_res, o_ref, o_err = resolve_local_ref(old_node, old_root)
    new_res, n_ref, n_err = resolve_local_ref(new_node, new_root)
    if o_err or n_err:
        changes.append({"kind": "$ref 无法解析", "prop": path, "level": "MAJOR",
                        "detail": o_err or n_err})
        return
    if not isinstance(old_res, dict) or not isinstance(new_res, dict):
        return

    if norm_type(old_res) != norm_type(new_res):
        changes.append({"kind": "字段类型变更", "prop": path, "level": "MAJOR",
                        "detail": f"{type_desc(old_res)} → {type_desc(new_res)}"})

    _compare_enum(old_res, new_res, path, changes)

    for keyword in CONSTRAINT_KEYWORDS:
        direction = _constraint_direction(keyword, old_res.get(keyword), new_res.get(keyword))
        if direction is None:
            continue
        if direction == "tighten":
            changes.append({"kind": "约束收紧", "prop": path, "level": "MAJOR",
                            "detail": f"{keyword}: {old_res.get(keyword)} → {new_res.get(keyword)}"})
        else:
            changes.append({"kind": "约束放宽", "prop": path, "level": "MINOR",
                            "detail": f"{keyword}: {old_res.get(keyword)} → {new_res.get(keyword)}"})

    op = old_res.get("properties", {}) or {}
    np_ = new_res.get("properties", {}) or {}
    oreq = set(old_res.get("required", []) or [])
    nreq = set(new_res.get("required", []) or [])
    common = set(op) & set(np_)

    for name in op:
        child_path = name if path == "$" else f"{path}.{name}"
        if name not in np_:
            changes.append({"kind": "字段删除", "prop": child_path, "level": "MAJOR"})
            continue
        diff_node(op[name], np_[name], child_path, old_root, new_root, changes, depth + 1)

    for name in np_:
        if name in op:
            continue
        child_path = name if path == "$" else f"{path}.{name}"
        if name in nreq:
            changes.append({"kind": "必填字段新增", "prop": child_path, "level": "MAJOR"})
        else:
            changes.append({"kind": "可选字段新增", "prop": child_path, "level": "MINOR"})

    # required 变化（仅针对两侧共有的属性，避免与增删属性重复计数）
    for name in sorted((oreq - nreq) & common):
        child_path = name if path == "$" else f"{path}.{name}"
        changes.append({"kind": "必填放宽", "prop": child_path, "level": "MINOR"})
    for name in sorted((nreq - oreq) & common):
        child_path = name if path == "$" else f"{path}.{name}"
        changes.append({"kind": "必填字段新增", "prop": child_path, "level": "MAJOR"})

    if "items" in old_res or "items" in new_res:
        diff_node(old_res.get("items", {}) or {}, new_res.get("items", {}) or {},
                  f"{path}[]", old_root, new_root, changes, depth + 1)

    # allOf / anyOf / oneOf：逐项递归（本仓扩展对象 schema 的领域字段在 allOf[1]）
    for combiner in COMBINERS:
        old_list, new_list = old_res.get(combiner), new_res.get(combiner)
        if not isinstance(old_list, list) and not isinstance(new_list, list):
            continue
        old_list = old_list if isinstance(old_list, list) else []
        new_list = new_list if isinstance(new_list, list) else []
        for i in range(max(len(old_list), len(new_list))):
            o_item = old_list[i] if i < len(old_list) else {}
            n_item = new_list[i] if i < len(new_list) else {}
            diff_node(o_item, n_item, f"{path}/{combiner}[{i}]", old_root, new_root,
                      changes, depth + 1)


def diff_schemas(old: dict, new: dict) -> list[dict]:
    changes: list[dict] = []
    diff_node(old, new, "$", old, new, changes)
    return changes


def classify(changes: list[dict], rule_index: dict | None = None) -> dict:
    """汇总变更级别并补齐配套动作；rule_index 为空时使用内置缺省 DEFAULT_REQUIRES。"""
    idx = rule_index or {}
    for ch in changes:
        key = KIND_TO_RULE.get(ch["kind"])
        rule = idx.get(key) if key else None
        if rule is not None:
            ch["requires"] = list(rule.get("requires", []))
        else:
            ch["requires"] = list(DEFAULT_REQUIRES.get(ch["kind"], []))
    overall = "PATCH"
    if changes:
        overall = max((ch["level"] for ch in changes), key=lambda x: LEVEL_ORDER[x])
    return {"overall": overall, "changes": changes}
