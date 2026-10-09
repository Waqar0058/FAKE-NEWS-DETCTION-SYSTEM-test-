"""
live_search.py - real-time web search used for live claim verification.

Uses DuckDuckGo through the `ddgs` package (no API key needed).
    pip install ddgs
"""


def web_snippets(query, max_results=8, timeout=10):
    """Return a list of {'title', 'body', 'url'} for the query, or [] if offline/blocked."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS      # older package name
        results = DDGS(timeout=timeout).text(query, max_results=max_results)
        return [
            {"title": r.get("title", ""), "body": r.get("body", ""), "url": r.get("href", "")}
            for r in (results or [])
            if r.get("body")
        ]
    except Exception:
        return []
