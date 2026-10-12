"""DuckDuckGo-HTML-Provider (kein API-Key nötig)."""

from __future__ import annotations

import re
import urllib.parse

from .base import clean_html, fetch

ENDPOINT = "https://html.duckduckgo.com/html/"

_LINK_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)
_SNIPPET_RE = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL
)


def _decode_uddg(href: str) -> str:
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.endswith("/l/"):
        return urllib.parse.unquote(parsed.query.split("uddg=", 1)[1].split("&", 1)[0])
    if href.startswith("//"):
        return "https:" + href
    return href


def search(query: str, max_results: int = 8, timeout: int = 15,
           user_agent: str = "Mozilla/5.0") -> list[dict]:
    headers = {"User-Agent": user_agent}
    resp = fetch(ENDPOINT, params={"q": query}, headers=headers, timeout=timeout)
    text = resp.text

    snippets = [clean_html(s) for s in _SNIPPET_RE.findall(text)]
    results: list[dict] = []
    for i, m in enumerate(_LINK_RE.finditer(text)):
        url = _decode_uddg(m.group(1))
        title = clean_html(m.group(2))
        if not url or not title:
            continue
        # Werbe-Treffer (DuckDuckGo-/Bing-Ads) ausschliessen: keine echten Jobs.
        if "y.js" in url or "ad_domain" in url or "ad_provider" in url:
            continue
        results.append({
            "titel": title,
            "url": url,
            "snippet": snippets[i] if i < len(snippets) else "",
            "quelle": "DuckDuckGo",
        })
        if len(results) >= max_results:
            break
    return results
