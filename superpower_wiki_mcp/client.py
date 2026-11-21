"""Async MediaWiki API client for Superpower Wiki (powerlisting.fandom.com)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import random
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

API_URL = "https://powerlisting.fandom.com/api.php"
WIKI_BASE_URL = "https://powerlisting.fandom.com/wiki/"
USER_AGENT = "SuperpowerWikiMCP/1.0 (https://modelcontextprotocol.io; MediaWiki API Client)"


class SuperpowerWikiError(Exception):
    """Base error for Superpower Wiki API failures."""


class PowerNotFoundError(SuperpowerWikiError):
    """Raised when a requested power page does not exist."""

    def __init__(self, title: str, suggestions: Optional[List[str]] = None) -> None:
        self.title = title
        self.suggestions = suggestions or []
        hint = (
            f" Did you mean: {', '.join(self.suggestions)}?"
            if self.suggestions
            else " Try calling superpower_search to find the exact canonical title."
        )
        super().__init__(f"Power '{title}' was not found on Superpower Wiki.{hint}")


class _TTLCache:
    """Lightweight bounded LRU + TTL cache."""

    def __init__(self, max_size: int = 256, ttl_seconds: float = 900.0) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, Tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.monotonic() + self._ttl, value)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)


def wiki_url(title: str) -> str:
    """Build canonical Superpower Wiki URL for a page title."""
    return WIKI_BASE_URL + quote(title.replace(" ", "_"), safe="/:@")


class SuperpowerWikiClient:
    """Async client with TTL caching and exponential backoff for powerlisting.fandom.com."""

    def __init__(
        self,
        api_url: str = API_URL,
        timeout: float = 20.0,
        cache_ttl: float = 900.0,
        max_retries: int = 3,
    ) -> None:
        self.api_url = api_url
        self.timeout = timeout
        self.max_retries = max_retries
        self._cache = _TTLCache(max_size=256, ttl_seconds=cache_ttl)

    async def _request(self, params: Dict[str, Any], use_cache: bool = True) -> Dict[str, Any]:
        req_params = {**params, "format": "json"}
        cache_key = "&".join(f"{k}={req_params[k]}" for k in sorted(req_params))
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        last_err: Optional[Exception] = None
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    headers=headers,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(self.api_url, params=req_params)
                    if response.status_code in {429, 500, 502, 503, 504}:
                        raise httpx.HTTPStatusError(
                            f"Transient HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    data = response.json()
                    if use_cache and "error" not in data:
                        self._cache.set(cache_key, data)
                    return data
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = exc
                if attempt + 1 < self.max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                else:
                    break

        if isinstance(last_err, httpx.HTTPStatusError):
            code = last_err.response.status_code
            if code == 429:
                raise SuperpowerWikiError("Superpower Wiki rate limit exceeded (HTTP 429). Wait a few seconds and retry.") from last_err
            raise SuperpowerWikiError(f"Superpower Wiki API returned HTTP {code}.") from last_err
        if isinstance(last_err, httpx.TimeoutException):
            raise SuperpowerWikiError("Superpower Wiki API timed out. Try again or request fewer sections.") from last_err
        raise SuperpowerWikiError(f"Network error contacting Superpower Wiki: {type(last_err).__name__}") from last_err

    async def suggest(self, prefix: str, limit: int = 5) -> List[str]:
        """Return quick title suggestions via MediaWiki opensearch."""
        data = await self._request(
            {
                "action": "opensearch",
                "search": prefix,
                "limit": limit,
                "namespace": 0,
            }
        )
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [str(item) for item in data[1]]
        return []

    async def search(
        self,
        query: str,
        limit: int = 15,
        offset: int = 0,
        include_fanon: bool = False,
    ) -> Dict[str, Any]:
        """Full-text search across Superpower Wiki powers."""
        srnamespace = "0|116" if include_fanon else "0"
        data = await self._request(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "sroffset": offset,
                "srnamespace": srnamespace,
                "srprop": "snippet|wordcount|timestamp",
            }
        )
        query_obj = data.get("query", {})
        searchinfo = query_obj.get("searchinfo", {})
        total = int(searchinfo.get("totalhits", 0))
        raw_items = query_obj.get("search", [])

        items = [
            {
                "title": item["title"],
                "pageid": item["pageid"],
                "namespace": item.get("ns", 0),
                "wordcount": item.get("wordcount", 0),
                "url": wiki_url(item["title"]),
            }
            for item in raw_items
        ]

        suggestions: List[str] = []
        if not items:
            suggestions = await self.suggest(query, limit=5)

        next_offset = data.get("continue", {}).get("sroffset")
        return {
            "query": query,
            "total": total,
            "count": len(items),
            "offset": offset,
            "has_more": next_offset is not None,
            "next_offset": next_offset,
            "items": items,
            "suggestions": suggestions,
        }

    async def get_page_metadata(self, title: str) -> Dict[str, Any]:
        """Resolve redirects and fetch sections and categories for a power page."""
        data = await self._request(
            {
                "action": "parse",
                "page": title,
                "redirects": 1,
                "prop": "sections|categories|displaytitle",
            }
        )
        if "error" in data:
            err = data["error"]
            if err.get("code") in {"missingtitle", "invalidtitle"}:
                suggestions = await self.suggest(title, limit=5)
                raise PowerNotFoundError(title, suggestions)
            raise SuperpowerWikiError(f"MediaWiki error ({err.get('code')}): {err.get('info')}")

        parse_obj = data["parse"]
        canonical_title = parse_obj["title"]
        redirects = parse_obj.get("redirects", [])
        redirected_from = redirects[0]["from"] if redirects else None

        sections = [
            {
                "index": sec["index"],
                "line": sec["line"],
                "level": int(sec.get("level", 2)),
                "toclevel": int(sec.get("toclevel", 1)),
                "number": sec.get("number", ""),
            }
            for sec in parse_obj.get("sections", [])
        ]

        categories = [
            cat["*"].replace("_", " ")
            for cat in parse_obj.get("categories", [])
            if "*" in cat
        ]

        return {
            "title": canonical_title,
            "pageid": parse_obj["pageid"],
            "url": wiki_url(canonical_title),
            "redirected_from": redirected_from,
            "sections": sections,
            "categories": categories,
        }

    async def get_section_wikitext(self, title: str, section_index: str | int) -> str:
        """Fetch raw wikitext for a specific section index (0 for lead)."""
        data = await self._request(
            {
                "action": "parse",
                "page": title,
                "redirects": 1,
                "prop": "wikitext",
                "section": str(section_index),
            }
        )
        if "error" in data:
            err = data["error"]
            raise SuperpowerWikiError(f"Failed to read section {section_index} of '{title}': {err.get('info')}")
        return data.get("parse", {}).get("wikitext", {}).get("*", "")

    async def get_category_members(
        self,
        category: str,
        limit: int = 25,
        continue_token: Optional[str] = None,
        include_subcategories: bool = True,
        include_fanon: bool = False,
    ) -> Dict[str, Any]:
        """List powers and subcategories within a Superpower Wiki category."""
        cat_title = category if category.lower().startswith("category:") else f"Category:{category}"
        namespaces = ["0"]
        if include_subcategories:
            namespaces.append("14")
        if include_fanon:
            namespaces.append("116")

        params: Dict[str, Any] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": cat_title,
            "cmlimit": limit,
            "cmnamespace": "|".join(namespaces),
        }
        if continue_token:
            params["cmcontinue"] = continue_token

        data = await self._request(params)
        members = data.get("query", {}).get("categorymembers", [])

        powers: List[Dict[str, Any]] = []
        subcategories: List[str] = []
        fanon: List[Dict[str, Any]] = []

        for m in members:
            ns = m.get("ns", 0)
            title = m["title"]
            if ns == 14:
                subcategories.append(title.removeprefix("Category:"))
            elif ns == 116:
                fanon.append({"title": title, "pageid": m["pageid"], "url": wiki_url(title)})
            else:
                powers.append({"title": title, "pageid": m["pageid"], "url": wiki_url(title)})

        next_continue = data.get("continue", {}).get("cmcontinue")
        return {
            "category": cat_title.removeprefix("Category:"),
            "url": wiki_url(cat_title),
            "count": len(members),
            "has_more": next_continue is not None,
            "next_continue": next_continue,
            "powers": powers,
            "subcategories": subcategories,
            "fanon": fanon,
        }

    async def get_random_powers(self, count: int = 3, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Draw random canonical powers globally or from a specific category."""
        if category:
            cat_data = await self.get_category_members(
                category=category,
                limit=200,
                include_subcategories=False,
                include_fanon=False,
            )
            pool = cat_data["powers"]
            if not pool:
                raise SuperpowerWikiError(
                    f"No canonical powers found in category '{category}'. Verify the category name via superpower_browse_category."
                )
            sample_size = min(count, len(pool))
            return random.sample(pool, sample_size)

        data = await self._request(
            {
                "action": "query",
                "list": "random",
                "rnnamespace": 0,
                "rnlimit": count,
            },
            use_cache=False,
        )
        items = data.get("query", {}).get("random", [])
        return [
            {"title": item["title"], "pageid": item["id"], "url": wiki_url(item["title"])}
            for item in items
        ]
