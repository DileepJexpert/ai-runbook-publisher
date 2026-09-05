from __future__ import annotations
from urllib.parse import parse_qs, unquote, urlparse
import subprocess
def resolve_compare_url(url: str) -> tuple[str, str] | None:
    path = unquote(urlparse(url).path)
    if "/compare/" in path:
        value = path.split("/compare/", 1)[1]
        if "..." in value:
            base, head = value.split("...", 1); return base, head
    return None
def resolve_url(url: str, base_fallback: str | None = None) -> tuple[str, str] | None:
    parsed=urlparse(url); path=unquote(parsed.path); query=parse_qs(parsed.query)
    github=resolve_compare_url(url)
    if github: return github
    if path.endswith('/compare') and query.get('sourceBranch') and query.get('targetBranch'):
        return query['targetBranch'][0].removeprefix('refs/heads/'), query['sourceBranch'][0].removeprefix('refs/heads/')
    parts=path.strip('/').split('/')
    if 'pull-requests' in parts:
        try: pr=parts[parts.index('pull-requests')+1]
        except IndexError: return None
        if not pr.isdigit(): return None
        return (base_fallback or f"refs/pull-requests/{pr}/to", f"refs/pull-requests/{pr}/from")
    return None
