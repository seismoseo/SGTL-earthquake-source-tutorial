"""Glossary of technical terms (English, Korean, plain definition).

The table is ``glossary/glossary.csv`` with columns ``key,english,korean,definition,modules,review_flag``.
"""
from __future__ import annotations

import csv
import difflib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import _paths

__all__ = ["entries", "lookup", "term", "terms"]

_CACHE: Dict[Tuple[str, int], Dict[str, dict]] = {}


def _path() -> Path:
    return _paths.repo_root() / "glossary" / "glossary.csv"


def entries() -> Dict[str, dict]:
    """All glossary rows, keyed by ``key`` (rows without a key use the English term in snake_case)."""
    path = _path()
    sig = (str(path), path.stat().st_mtime_ns)
    if sig not in _CACHE:
        rows: Dict[str, dict] = {}
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
                key = row.get("key") or row.get("english", "").lower().replace(" ", "_")
                if key:
                    rows[key] = row
        _CACHE.clear()
        _CACHE[sig] = rows
    return _CACHE[sig]


def lookup(key: str) -> dict:
    """The glossary row for ``key`` (raises KeyError with suggestions when unknown)."""
    rows = entries()
    k = key.strip()
    if k not in rows:
        alt = {r.lower(): r for r in rows}
        if k.lower() in alt:
            return rows[alt[k.lower()]]
        close = difflib.get_close_matches(k, list(rows), n=3)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise KeyError(f"No glossary term {key!r}.{hint}")
    return rows[k]


def term(key: str) -> str:
    """``"english (korean): definition"`` for a glossary key, e.g. ``term("hypocenter")``."""
    row = lookup(key)
    head = row.get("english") or key
    if row.get("korean"):   # "memory (RAM)" becomes "memory (RAM; 메모리)": one pair of parentheses only
        head = f"{head[:-1]}; {row['korean']})" if head.endswith(")") else f"{head} ({row['korean']})"
    definition = row.get("definition", "")
    return f"{head}: {definition}" if definition else head


def terms(module: Optional[str] = None) -> List[str]:
    """Keys of all terms, or of the terms listed for ``module`` (e.g. ``"M01"``)."""
    rows = entries()
    if module is None:
        return sorted(rows)
    out = []
    for k, r in rows.items():
        mods = [m.strip() for m in r.get("modules", "").replace(";", ",").replace(" ", ",").split(",")]
        if module in mods:
            out.append(k)
    return sorted(out)
