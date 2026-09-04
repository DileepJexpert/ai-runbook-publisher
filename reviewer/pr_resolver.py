from __future__ import annotations
from urllib.parse import unquote, urlparse
def resolve_compare_url(url: str) -> tuple[str, str] | None:
    path = unquote(urlparse(url).path)
    if "/compare/" in path:
        value = path.split("/compare/", 1)[1]
        if "..." in value:
            base, head = value.split("...", 1); return base, head
    return None
