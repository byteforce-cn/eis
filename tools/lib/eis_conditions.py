#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eis_conditions — 授权条件声明（受限 DSL）的校验与求值（ADR-0015）。

依据：
  - 00-freeze/adr/0015-authz-condition-declaration.md
  - 04-authz-contract/attribute.rules.yaml（ATR-003/006/007/009）
  - 04-authz-contract/attributes.api.yaml（属性快照形状 AttributeSet）

DSL（单一权威：`extensions/*/manifest.yaml` 的 `permissions[].condition`）：

    condition:
      all:                                   # 或 any；二选一、单层、不递归
        - {attribute: "primary_position.grade", op: "in", values: ["M2", "P1"]}

  - 子句字段固定为 attribute / op / values（不得有其它键）；
  - op ∈ {eq, neq, in, not_in, exists}；
  - attribute 为属性快照内的点分路径，段可带 [*]（"任一"语义）；
  - values 为非空标量数组；exists 只接受 [true] / [false]；
  - 求值 fail-closed（ATR-006/007）：快照 missing/stale/source_unavailable、
    路径缺失 → 对应 ATTRIBUTE_* 原因码；不匹配 → ATTRIBUTE_MISMATCH。

不做：调用方传入条件（`/check` 只接收 permission）、任意表达式/Rego、
运行期编辑、嵌套 all/any、deny 规则、通配值。
"""
from __future__ import annotations

import re
from pathlib import Path

from eis_common import ROOT, load_yaml

OPS = ("eq", "neq", "in", "not_in", "exists")
LOGIC_KEYS = ("all", "any")

# 段：name 或 name[*]；[*] 只能出现在数组节点上（由 schema 校验）
PATH_RE = re.compile(r"^[a-z][a-z0-9_]*(\[\*\])?(\.[a-z][a-z0-9_]*(\[\*\])?)*$")
SEGMENT_RE = re.compile(r"[a-z][a-z0-9_]*(?:\[\*\])?")
ATTRIBUTES_API = ROOT / "04-authz-contract" / "attributes.api.yaml"

REASON_MISSING = "ATTRIBUTE_MISSING"
REASON_STALE = "ATTRIBUTE_STALE"
REASON_SOURCE = "ATTRIBUTE_SOURCE_UNAVAILABLE"
REASON_MISMATCH = "ATTRIBUTE_MISMATCH"


# ---------------------------------------------------------------------------
# 属性快照 Schema（04）→ 可声明路径集合
# ---------------------------------------------------------------------------
class _Schema:
    """本地 $ref 解析（只接受 attributes.api.yaml 内的 #/components/...）。"""

    def __init__(self, doc: dict):
        self.doc = doc

    def deref(self, node, depth: int = 0):
        if depth > 12:
            raise ValueError("$ref 解引用过深")
        while isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                raise ValueError(f"仅支持本地 $ref: {ref!r}")
            cursor = self.doc
            for part in ref[2:].split("/"):
                cursor = cursor[part]
            node = cursor
            depth += 1
        return node


def load_attribute_schema(path=None) -> dict:
    """载入 AttributeSet（解析一层 $ref 后返回的 schema 图）。"""
    doc = load_yaml(Path(path) if path else ATTRIBUTES_API)
    schema = _Schema(doc)
    return schema.deref(doc["components"]["schemas"]["AttributeSet"])


def scalar_paths() -> dict[str, dict]:
    """枚举 AttributeSet 中所有可作条件左值的路径（含 [*]），路径 → 节点 schema。"""
    doc = load_yaml(ATTRIBUTES_API)
    resolver = _Schema(doc)

    def _resolve_inline(node):
        return resolver.deref(node) if isinstance(node, dict) else node

    def walk(node: dict, prefix: str, out: dict) -> None:
        node = _resolve_inline(node)
        if node is None or not isinstance(node, dict):
            return
        for branch in node.get("allOf", []) or []:
            walk(branch, prefix, out)
        if "oneOf" in node:
            for branch in node["oneOf"]:
                walk(_resolve_inline(branch), prefix, out)
            return
        types = node.get("type")
        typs = set(types) if isinstance(types, list) else ({types} if types else set())
        if typs == {"null"}:
            return  # 可空分支不构成可声明路径
        if "object" in typs and isinstance(node.get("properties"), dict):
            for name, child in node["properties"].items():
                walk(_resolve_inline(child), f"{prefix}.{name}" if prefix else name, out)
        elif "array" in typs:
            wildcard = f"{prefix}[*]"
            items = _resolve_inline(node.get("items"))
            if isinstance(items, dict) and (
                    items.get("type") == "object" or "properties" in items or "oneOf" in items):
                walk(items, wildcard, out)
            else:
                out[wildcard] = items if isinstance(items, dict) else {}
        elif prefix and (typs & {"string", "number", "integer", "boolean", "null"}):
            out[prefix] = node

    out: dict[str, dict] = {}
    walk(resolver.deref(doc["components"]["schemas"]["AttributeSet"]), "", out)
    return out


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def validate_condition(condition, allowed_paths: dict[str, dict] | None = None) -> list[str]:
    """校验 condition 结构；返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    if not isinstance(condition, dict) or not condition:
        return ["condition 必须为非空对象"]
    keys = [k for k in condition if k in LOGIC_KEYS]
    extra = [k for k in condition if k not in LOGIC_KEYS]
    if extra:
        problems.append(f"condition 只允许 all / any，出现未知键: {sorted(extra)}")
    if len(keys) != 1:
        problems.append("condition 必须且只能包含 all / any 之一（嵌套或混合即拒绝）")
        return problems
    logic = keys[0]
    clauses = condition[logic]
    if not isinstance(clauses, list) or not clauses:
        problems.append(f"condition.{logic} 必须为非空数组")
        return problems
    if allowed_paths is None:
        allowed_paths = scalar_paths(load_attribute_schema())
    for index, clause in enumerate(clauses):
        where = f"condition.{logic}[{index}]"
        if not isinstance(clause, dict):
            problems.append(f"{where} 必须为对象")
            continue
        extra = sorted(set(clause) - {"attribute", "op", "values"})
        missing = sorted({"attribute", "op", "values"} - set(clause))
        if extra:
            problems.append(f"{where} 含未知字段: {extra}")
        if missing:
            problems.append(f"{where} 缺字段: {missing}")
        if extra or missing:
            continue
        attribute, op, values = clause["attribute"], clause["op"], clause["values"]
        if not isinstance(attribute, str) or not PATH_RE.match(attribute):
            problems.append(f"{where}.attribute 路径语法不合规: {attribute!r}")
        elif attribute not in allowed_paths:
            problems.append(
                f"{where}.attribute 不在 04 属性快照（attributes.api.yaml AttributeSet）: {attribute}")
        if op not in OPS:
            problems.append(f"{where}.op 不在白名单 {list(OPS)}: {op!r}")
        if not isinstance(values, list) or not values:
            problems.append(f"{where}.values 必须为非空数组")
            continue
        for value in values:
            if isinstance(value, (dict, list)):
                problems.append(f"{where}.values 只允许标量（字符串/数字/布尔/null）")
                break
        if op == "exists" and not (len(values) == 1 and isinstance(values[0], bool)):
            problems.append(f"{where}.values 对 exists 必须为 [true] 或 [false]")
    return problems


# ---------------------------------------------------------------------------
# 求值
# ---------------------------------------------------------------------------
def _same(left, right) -> bool:
    """类型敏感相等（避免布尔与数字混同：True == 1）。"""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    return left == right


def _walk(node, segments: list[str]):
    """返回 (found, candidates)。found=False 表示路径在快照中不存在。"""
    if not segments:
        return True, [node]
    head, rest = segments[0], segments[1:]
    wildcard = head.endswith("[*]")
    name = head[:-3] if wildcard else head
    if not isinstance(node, dict) or name not in node:
        return False, []
    value = node[name]
    if not wildcard:
        return _walk(value, rest)
    if not isinstance(value, list):
        return False, []
    if not value:
        return True, []  # 空数组本身存在：零候选
    candidates = []
    for item in value:
        found, values = _walk(item, rest)
        if found:
            candidates.extend(values)
    if not candidates:
        return False, []  # 非空数组但所有元素都缺该路径 → 视为路径缺失（fail-closed）
    return True, candidates


def _resolve(snapshot: dict, attribute: str):
    segments = SEGMENT_RE.findall(attribute)
    return _walk(snapshot, segments)


def _clause(clause: dict, snapshot: dict):
    found, values = _resolve(snapshot, clause["attribute"])
    op, wanted = clause["op"], clause["values"]
    if op == "exists":
        want = bool(wanted[0])
        present = found and bool(values)
        return present == want, None
    if not found:
        return False, REASON_MISSING
    if op in ("eq", "in"):
        return any(_same(v, w) for v in values for w in wanted), None
    # neq / not_in：全体候选都必须不命中（空数组 → 真空成立）
    return all(not _same(v, w) for v in values for w in wanted), None


def evaluate_condition(condition: dict, snapshot: dict):
    """对属性快照求值条件。

    返回 (satisfied, reason_code, attribute_path)：
      - (True, None, None)：条件满足；
      - (False, REASON_MISMATCH, path)：条件不满足；
      - (False, REASON_MISSING, path)：路径缺失，无法求值（fail-closed）。
    快照自身的 missing/stale/source_unavailable 由调用方（判定方）先行处理。
    """
    logic = "all" if "all" in condition else "any"
    clauses = condition.get(logic) or []
    first_problem = None
    for clause in clauses:
        ok, reason = _clause(clause, snapshot)
        if reason == REASON_MISSING:
            # 无论 all/any，路径缺失都必须 fail-closed（ATR-006）
            return False, REASON_MISSING, clause["attribute"]
        if logic == "all" and not ok:
            return False, REASON_MISMATCH, clause["attribute"]
        if logic == "any" and ok:
            return True, None, None
        if not ok and first_problem is None:
            first_problem = clause["attribute"]
    if logic == "any":
        return False, REASON_MISMATCH, first_problem
    return True, None, None


# ---------------------------------------------------------------------------
# 声明加载
# ---------------------------------------------------------------------------
def load_conditions_file(path) -> dict[str, dict]:
    """加载条件声明文件：{conditions: {permission: condition}} 或裸映射。"""
    doc = load_yaml(Path(path))
    if isinstance(doc, dict) and isinstance(doc.get("conditions"), dict):
        return dict(doc["conditions"])
    if isinstance(doc, dict) and isinstance(doc.get("extension"), dict):
        return _from_manifest(doc["extension"])
    return dict(doc or {})


def _from_manifest(extension: dict) -> dict[str, dict]:
    out = {}
    for perm in extension.get("permissions", []) or []:
        if isinstance(perm, dict) and isinstance(perm.get("condition"), dict):
            out[perm["id"]] = perm["condition"]
    return out


def load_declared_conditions(root=None) -> dict[str, dict]:
    """从扩展 manifest 加载条件声明（权威位置）：{permission: condition}。"""
    base = Path(root) if root else ROOT
    ext_root = base / "extensions"
    out: dict[str, dict] = {}
    if not ext_root.is_dir():
        return out
    for manifest_path in sorted(ext_root.glob("*/manifest.yaml")):
        extension = (load_yaml(manifest_path) or {}).get("extension", {}) or {}
        out.update(_from_manifest(extension))
    return out
