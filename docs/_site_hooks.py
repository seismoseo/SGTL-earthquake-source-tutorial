"""Preserve repository notebook links when nbconvert embeds their HTML in MkDocs pages."""

import html
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from mkdocs.utils import get_relative_url


def on_page_content(content, page, config, files):
    """Resolve notebook links from the notebook's source folder, then use the built page URL."""
    if not page.file.src_uri.endswith(".ipynb"):
        return content
    docs = Path(config["docs_dir"]).resolve()
    repo = docs.parent
    source = Path(page.file.abs_src_path).parent

    def rewrite(match):
        raw = html.unescape(match.group(3))
        url = urlsplit(raw)
        if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
            return match.group(0)
        target = (source / unquote(url.path)).resolve()
        try:
            relative = target.relative_to(docs).as_posix()
        except ValueError:
            try:
                relative = target.relative_to(repo).as_posix()
            except ValueError:
                return match.group(0)
            # Criteria and other public repository files are outside the documentation website.
            path = config["repo_url"].rstrip("/") + "/blob/main/" + quote(relative, safe="/")
        else:
            file = files.get_file_from_path(relative)
            if file is None:
                return match.group(0)
            path = get_relative_url(file.url, page.url)
        resolved = urlunsplit(("", "", path, url.query, url.fragment))
        return match.group(1) + match.group(2) + html.escape(resolved, quote=True) + match.group(2)

    return re.sub(r"((?:href|src)=)([\"'])(.*?)\2", rewrite, content)
