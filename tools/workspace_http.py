from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def strip_route_prefix(raw_path: str, prefix: str) -> str:
    """Return a request target with an optional workspace route prefix removed."""
    parts = urlsplit(raw_path)
    path = parts.path
    normalized_prefix = "/" + prefix.strip("/")
    if path == normalized_prefix:
        path = "/"
    elif path.startswith(normalized_prefix + "/"):
        path = path[len(normalized_prefix):]
    return urlunsplit(("", "", path, parts.query, ""))
