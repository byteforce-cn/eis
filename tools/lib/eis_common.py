#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eis_common — EIS 工具链公共模块（路径、IO、报告）。

不直接执行；由 tools/* 工具导入。仅依赖 Python 3.10+ 标准库与 PyYAML。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# 仓库根（eis/）：tools/lib/eis_common.py → 上三级
ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = ROOT / "tools"
BUILD_DIR = ROOT / "build"


def load_yaml(path):
    if yaml is None:
        raise RuntimeError("需要 PyYAML（pip install pyyaml）")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def rel(path) -> str:
    """相对仓库根的展示路径。"""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def snake(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    return s.strip("_").lower()


class Report:
    """工具统一的检查报告：ok/fail 条目 + 退出码。"""

    def __init__(self, title: str):
        self.title = title
        self.entries: list[tuple[bool, str, str | None]] = []

    def ok(self, message: str, detail: str | None = None) -> bool:
        self.entries.append((True, message, detail))
        return True

    def fail(self, message: str, detail: str | None = None) -> bool:
        self.entries.append((False, message, detail))
        return False

    @property
    def failures(self):
        return [e for e in self.entries if not e[0]]

    @property
    def success(self) -> bool:
        return not self.failures

    def print(self, verbose: bool = True) -> int:
        print(f"== {self.title} ==")
        for ok, msg, detail in self.entries:
            flag = "ok  " if ok else "FAIL"
            print(f"[{flag}] {msg}")
            if detail and (verbose or not ok):
                for line in str(detail).splitlines():
                    print(f"        {line}")
        n_ok = len(self.entries) - len(self.failures)
        print(f"-- {n_ok} 通过, {len(self.failures)} 失败")
        return 0 if self.success else 1

    def to_json(self) -> dict:
        return {
            "title": self.title,
            "success": self.success,
            "passed": len(self.entries) - len(self.failures),
            "failed": len(self.failures),
            "entries": [
                {"ok": ok, "message": msg, "detail": detail}
                for ok, msg, detail in self.entries
            ],
        }
