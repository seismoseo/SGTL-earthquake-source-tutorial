"""Keep repository links usable when a notebook is copied from the reading list into work/."""
from __future__ import annotations

import re


def relocate_links(notebook, link_root="../../"):
    """Rewrite Markdown links to the repository root in place, preserving every code cell and cell id."""
    meta = notebook.setdefault("metadata", {}).setdefault("sgtl", {})
    previous = meta.get("link_root", "../../")
    if previous != link_root:
        pattern = re.compile(r"(?<=\]\()" + re.escape(previous) + r"(?!\.\./)")
        for cell in notebook.get("cells", []):
            if cell.get("cell_type") != "markdown":
                continue
            source = cell.get("source", "")
            text = "".join(source) if isinstance(source, list) else str(source)
            updated = pattern.sub(lambda match: link_root, text)
            if updated != text:
                cell["source"] = updated
    meta["link_root"] = link_root
    return notebook
