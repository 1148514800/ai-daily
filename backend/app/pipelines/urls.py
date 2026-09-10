from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id"}


def canonicalize_url(url: str) -> str:
    raw = url.strip()
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if not host:
        return raw.split("#", 1)[0]

    netloc = host
    if parts.port:
        netloc = f"{host}:{parts.port}"

    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_KEYS or lowered.startswith(TRACKING_PREFIXES):
            continue
        query_pairs.append((key, value))

    path = parts.path or ""
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query_pairs, doseq=True), ""))
