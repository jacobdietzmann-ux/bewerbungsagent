"""Bing-Provider (kein API-Key nötig)."""

from __future__ import annotations

import re

from .base import clean_html, fetch

ENDPOINT = "https://www.bing.com/search"

_BLOCK_RE = re.compile(r'<li class="b_algo".*?</li>', re.DOTALL)


def search(query: str, max_results: int = 8, timeout: int = 15,
           user_agent: str = "Mozilla/5.0") -> list[dict]:
    headers = {"User-Agent": user_agent, "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
    resp = fetch(ENDPOINT, params={"q": query, "count": 20}, headers=headers, timeout=timeout)
    text = resp.text

    results: list[dict] = []
    for block in _BLOCK_RE.findall(text):
        link = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not link:
            continue
        url = link.group(1)
        title = clean_html(link.group(2))
        snip = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        results.append({
            "titel": title,
            "url": url,
            "snippet": clean_html(snip.group(1)) if snip else "",
            "quelle": "Bing",
        })
        if len(results) >= max_results:
            break
    return results
