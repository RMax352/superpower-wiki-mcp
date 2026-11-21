#!/data/data/com.termux/files/usr/bin/python
"""Superpower Wiki MCP Server (dual transport: stdio + Streamable HTTP)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
from typing import Annotated, Any, Dict, List, Optional

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if os.environ.get("SUPERPOWER_MCP_FORCE_IPV4", "0") == "1":
    _orig_getaddrinfo = socket.getaddrinfo

    def _ipv4_getaddrinfo(host: Any, port: Any, family: int = 0, type: int = 0, proto: int = 0, flags: int = 0) -> Any:
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_getaddrinfo  # type: ignore[assignment]

from fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from superpower_wiki_mcp.client import PowerNotFoundError, SuperpowerWikiClient, SuperpowerWikiError
from superpower_wiki_mcp.models import (
    BrowseCategoryInput,
    ComparePowersInput,
    ExploreTreeInput,
    GetLimitationsInput,
    GetPowerInput,
    GetSectionInput,
    RandomPowersInput,
    ResponseFormat,
    SearchPowersInput,
)
from superpower_wiki_mcp.parser import clean_wikitext, extract_power_links, truncate_text

DEFAULT_POWER_SECTIONS = [
    "Also Called",
    "Capabilities",
    "Applications",
    "Techniques",
    "Variations",
    "Combinations",
    "Levels",
    "Associations",
    "Limitations",
]

NOISY_SECTIONS = {"known users", "gallery", "videos", "known objects", "known locations", "references"}

mcp = FastMCP(
    "superpower_wiki_mcp",
    instructions=(
        "Specialized MCP server for Superpower Wiki (powerlisting.fandom.com). "
        "Use it to research superpowers, capabilities, applications, techniques, variations, "
        "associations, and limitations for character creation and power system worldbuilding."
    ),
)

_client = SuperpowerWikiClient()

_READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

_RANDOM_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}


def _match_section(sections: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
    """Find a section by exact index, exact case-insensitive name, or substring match."""
    q = query.strip().lower()
    for sec in sections:
        if sec["index"] == query.strip() or sec["line"].strip().lower() == q:
            return sec
    for sec in sections:
        if q in sec["line"].strip().lower():
            return sec
    return None


async def _fetch_sections_clean(
    title: str,
    sections_meta: List[Dict[str, Any]],
    wanted_names: List[str],
) -> Dict[str, str]:
    """Fetch and clean multiple sections in parallel."""
    selected: List[Dict[str, Any]] = []
    seen_idx: set[str] = set()
    for name in wanted_names:
        match = _match_section(sections_meta, name)
        if match and match["index"] not in seen_idx:
            seen_idx.add(match["index"])
            selected.append(match)

    if not selected:
        return {}

    raw_texts = await asyncio.gather(
        *[_client.get_section_wikitext(title, sec["index"]) for sec in selected],
        return_exceptions=True,
    )
    result: Dict[str, str] = {}
    for sec, raw in zip(selected, raw_texts):
        if isinstance(raw, Exception):
            continue
        cleaned = clean_wikitext(raw, strip_leading_heading=True)
        if cleaned:
            result[sec["line"]] = cleaned
    return result


# ==============================================================================
# TOOLS (8 Specialized Worldbuilding & Power Research Tools)
# ==============================================================================


@mcp.tool(name="superpower_search", annotations=_READ_ONLY_ANNOTATIONS)
async def superpower_search(
    query: Annotated[str, Field(description="Search query (power name, concept, element, or keyword).")],
    limit: Annotated[int, Field(default=15, ge=1, le=50, description="Maximum results to return (1-50).")] = 15,
    offset: Annotated[int, Field(default=0, ge=0, le=500, description="Pagination offset.")] = 0,
    include_fanon: Annotated[bool, Field(default=False, description="Include Fanon (non-canon) namespace 116 pages.")] = False,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="'markdown' or 'json'.")] = ResponseFormat.MARKDOWN,
) -> str:
    """Search Superpower Wiki for powers by name, theme, or keyword with pagination."""
    params = SearchPowersInput(
        query=query,
        limit=limit,
        offset=offset,
        include_fanon=include_fanon,
        response_format=response_format,
    )
    try:
        data = await _client.search(
            query=params.query,
            limit=params.limit,
            offset=params.offset,
            include_fanon=params.include_fanon,
        )
    except SuperpowerWikiError as exc:
        return f"Error: {exc}"

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(data, ensure_ascii=False, indent=2)

    if not data["items"]:
        msg = f"No powers found for `{params.query}`."
        if data["suggestions"]:
            msg += "\n\nSuggestions:\n" + "\n".join(f"- {s}" for s in data["suggestions"])
        return msg

    lines = [
        f"# Search Results: {params.query}",
        f"Showing {data['count']} of {data['total']} hits (offset {data['offset']}).",
        "",
    ]
    for item in data["items"]:
        lines.append(f"- **{item['title']}** ({item['wordcount']} words) — {item['url']}")
    if data["has_more"]:
        lines.append(f"\n*More results available: call again with `offset={data['next_offset']}`.*")
    return "\n".join(lines)


@mcp.tool(name="superpower_get_power", annotations=_READ_ONLY_ANNOTATIONS)
async def superpower_get_power(
    title: Annotated[str, Field(description="Power title or alias (e.g., 'Fire Manipulation', 'Pyrokinesis').")],
    sections: Annotated[Optional[List[str]], Field(default=None, description="Specific section names to fetch. Defaults to core worldbuilding sections (omitting Known Users/Gallery).")] = None,
    include_known_users: Annotated[bool, Field(default=False, description="Include Known Users section when using default sections.")] = False,
    max_chars: Annotated[int, Field(default=12000, ge=500, le=40000, description="Character budget for rendered content.")] = 12000,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="'markdown' or 'json'.")] = ResponseFormat.MARKDOWN,
) -> str:
    """Retrieve a structured, context-optimized sheet for a superpower (resolves redirects automatically)."""
    params = GetPowerInput(
        title=title,
        sections=sections,
        include_known_users=include_known_users,
        max_chars=max_chars,
        response_format=response_format,
    )
    try:
        meta = await _client.get_page_metadata(params.title)
        wanted = list(params.sections) if params.sections else list(DEFAULT_POWER_SECTIONS)
        if not params.sections and params.include_known_users:
            wanted.append("Known Users")

        fetched = await _fetch_sections_clean(meta["title"], meta["sections"], wanted)
        if not fetched:
            lead = clean_wikitext(await _client.get_section_wikitext(meta["title"], 0), strip_leading_heading=False)
            if lead:
                fetched["Overview"] = lead
    except SuperpowerWikiError as exc:
        return f"Error: {exc}"

    available_sections = [s["line"] for s in meta["sections"] if s["level"] == 2]

    if params.response_format == ResponseFormat.JSON:
        truncated_any = False
        budget_left = max(400, params.max_chars - 1200)
        bounded_sections: Dict[str, str] = {}
        remaining_count = max(1, len(fetched))
        for sec_name, sec_body in fetched.items():
            share = max(250, budget_left // remaining_count)
            cut_body, was_cut = truncate_text(sec_body, share)
            if was_cut:
                truncated_any = True
            bounded_sections[sec_name] = cut_body
            budget_left = max(250, budget_left - len(cut_body))
            remaining_count = max(1, remaining_count - 1)
        payload = {
            "title": meta["title"],
            "pageid": meta["pageid"],
            "url": meta["url"],
            "redirected_from": meta["redirected_from"],
            "categories": meta["categories"],
            "available_sections": available_sections,
            "truncated": truncated_any,
            "sections": bounded_sections,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [f"# {meta['title']}", f"URL: {meta['url']}"]
    if meta["redirected_from"]:
        lines.append(f"*Redirected from: {meta['redirected_from']}*")
    if meta["categories"]:
        lines.append(f"**Categories:** {', '.join(meta['categories'][:15])}")
    lines.append(f"**Available Sections:** {', '.join(available_sections)}")
    lines.append("")

    for sec_name, sec_body in fetched.items():
        lines.append(f"## {sec_name}")
        lines.append(sec_body)
        lines.append("")

    rendered, _ = truncate_text("\n".join(lines).strip(), params.max_chars)
    return rendered


@mcp.tool(name="superpower_get_section", annotations=_READ_ONLY_ANNOTATIONS)
async def superpower_get_section(
    title: Annotated[str, Field(description="Power title or alias.")],
    section: Annotated[str, Field(description="Section name or index (e.g., 'Known Users', 'Levels', 'Trivia', 'Techniques').")],
    max_chars: Annotated[int, Field(default=8000, ge=500, le=40000, description="Character budget for output.")] = 8000,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="'markdown' or 'json'.")] = ResponseFormat.MARKDOWN,
) -> str:
    """Fetch a single specific section of a superpower page without downloading the entire article."""
    params = GetSectionInput(
        title=title,
        section=section,
        max_chars=max_chars,
        response_format=response_format,
    )
    try:
        meta = await _client.get_page_metadata(params.title)
        match = _match_section(meta["sections"], params.section)
        if not match:
            avail = ", ".join(s["line"] for s in meta["sections"] if s["level"] == 2)
            return f"Error: Section '{params.section}' not found on '{meta['title']}'. Available sections: {avail}"
        raw = await _client.get_section_wikitext(meta["title"], match["index"])
        cleaned = clean_wikitext(raw, strip_leading_heading=True)
    except SuperpowerWikiError as exc:
        return f"Error: {exc}"

    cleaned_cut, truncated = truncate_text(cleaned, params.max_chars)
    payload = {
        "title": meta["title"],
        "url": meta["url"],
        "section": match["line"],
        "section_index": match["index"],
        "truncated": truncated,
        "content": cleaned_cut,
    }
    if params.response_format == ResponseFormat.JSON:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    return f"# {meta['title']} — {match['line']}\nURL: {meta['url']}\n\n{cleaned_cut}"


@mcp.tool(name="superpower_explore_tree", annotations=_READ_ONLY_ANNOTATIONS)
async def superpower_explore_tree(
    title: Annotated[str, Field(description="Root power title or alias (e.g., 'Fire Manipulation').")],
    branches: Annotated[
        Optional[List[str]],
        Field(default=None, description="Branches to extract links from (defaults to Applications, Techniques, Variations, Combinations, Associations)."),
    ] = None,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="'markdown' or 'json'.")] = ResponseFormat.MARKDOWN,
) -> str:
    """Extract the navigable tree of sub-powers, techniques, variations, combinations, and associations for a power."""
    params = ExploreTreeInput(
        title=title,
        branches=branches or ["Applications", "Techniques", "Variations", "Combinations", "Associations"],
        response_format=response_format,
    )
    try:
        meta = await _client.get_page_metadata(params.title)
        matched_branches: List[Dict[str, Any]] = []
        for b in params.branches:
            sec = _match_section(meta["sections"], b)
            if sec:
                matched_branches.append(sec)

        raw_list = await asyncio.gather(
            *[_client.get_section_wikitext(meta["title"], sec["index"]) for sec in matched_branches],
            return_exceptions=True,
        )
    except SuperpowerWikiError as exc:
        return f"Error: {exc}"

    tree: Dict[str, List[Dict[str, Any]]] = {}
    for sec, raw in zip(matched_branches, raw_list):
        if isinstance(raw, Exception):
            continue
        links = extract_power_links(raw)
        if links:
            tree[sec["line"]] = links

    payload = {
        "title": meta["title"],
        "url": meta["url"],
        "redirected_from": meta["redirected_from"],
        "categories": meta["categories"],
        "tree": tree,
    }
    if params.response_format == ResponseFormat.JSON:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [f"# Power Tree: {meta['title']}", f"URL: {meta['url']}"]
    if meta["categories"]:
        lines.append(f"**Categories:** {', '.join(meta['categories'])}")
    lines.append("")

    if not tree:
        lines.append("No structured power-link branches found on this page.")
        return "\n".join(lines)

    for branch_name, items in tree.items():
        lines.append(f"## {branch_name} ({len(items)} linked powers)")
        for item in items:
            indent = "  " * max(0, item["depth"] - 1)
            label_suffix = f" (as '{item['label']}')" if "label" in item else ""
            lines.append(f"{indent}- {item['title']}{label_suffix}")
        lines.append("")

    return "\n".join(lines).strip()


@mcp.tool(name="superpower_get_limitations", annotations=_READ_ONLY_ANNOTATIONS)
async def superpower_get_limitations(
    titles: Annotated[List[str], Field(min_length=1, max_length=5, description="List of 1 to 5 power titles to inspect for limitations and weaknesses.")],
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="'markdown' or 'json'.")] = ResponseFormat.MARKDOWN,
) -> str:
    """Fetch limitations, weaknesses, and counters for 1 to 5 powers in parallel for character balancing."""
    params = GetLimitationsInput(titles=titles, response_format=response_format)

    async def _one(power_title: str) -> Dict[str, Any]:
        try:
            meta = await _client.get_page_metadata(power_title)
            sec = _match_section(meta["sections"], "Limitations")
            if not sec:
                return {"title": meta["title"], "url": meta["url"], "limitations": None, "error": "No Limitations section found."}
            raw = await _client.get_section_wikitext(meta["title"], sec["index"])
            return {
                "title": meta["title"],
                "url": meta["url"],
                "limitations": clean_wikitext(raw, strip_leading_heading=True),
                "error": None,
            }
        except SuperpowerWikiError as exc:
            return {"title": power_title, "url": None, "limitations": None, "error": str(exc)}

    results = await asyncio.gather(*[_one(t) for t in params.titles])
    if params.response_format == ResponseFormat.JSON:
        return json.dumps({"results": results}, ensure_ascii=False, indent=2)

    lines = ["# Power Limitations & Weaknesses", ""]
    for r in results:
        lines.append(f"## {r['title']}")
        if r["url"]:
            lines.append(f"URL: {r['url']}")
        if r["error"]:
            lines.append(f"*Note: {r['error']}*")
        else:
            lines.append(r["limitations"] or "*No limitations listed.*")
        lines.append("")
    return "\n".join(lines).strip()


@mcp.tool(name="superpower_browse_category", annotations=_READ_ONLY_ANNOTATIONS)
async def superpower_browse_category(
    category: Annotated[str, Field(description="Category name (e.g., 'Elemental Manipulation', 'Physiology', 'Mental Powers', 'Combat').")],
    limit: Annotated[int, Field(default=25, ge=1, le=100, description="Maximum items to return (1-100).")] = 25,
    continue_token: Annotated[Optional[str], Field(default=None, description="Pagination cursor from a previous call.")] = None,
    include_subcategories: Annotated[bool, Field(default=True, description="Include subcategories alongside powers.")] = True,
    include_fanon: Annotated[bool, Field(default=False, description="Include Fanon (namespace 116) pages.")] = False,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="'markdown' or 'json'.")] = ResponseFormat.MARKDOWN,
) -> str:
    """Browse powers and subcategories inside a Superpower Wiki category with cursor pagination."""
    params = BrowseCategoryInput(
        category=category,
        limit=limit,
        continue_token=continue_token,
        include_subcategories=include_subcategories,
        include_fanon=include_fanon,
        response_format=response_format,
    )
    try:
        data = await _client.get_category_members(
            category=params.category,
            limit=params.limit,
            continue_token=params.continue_token,
            include_subcategories=params.include_subcategories,
            include_fanon=params.include_fanon,
        )
    except SuperpowerWikiError as exc:
        return f"Error: {exc}"

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(data, ensure_ascii=False, indent=2)

    lines = [f"# Category: {data['category']}", f"URL: {data['url']}", ""]
    if data["subcategories"]:
        lines.append(f"## Subcategories ({len(data['subcategories'])})")
        for sub in data["subcategories"]:
            lines.append(f"- {sub}")
        lines.append("")

    if data["powers"]:
        lines.append(f"## Powers ({len(data['powers'])})")
        for p in data["powers"]:
            lines.append(f"- **{p['title']}** — {p['url']}")
        lines.append("")

    if data["fanon"]:
        lines.append(f"## Fanon ({len(data['fanon'])})")
        for f in data["fanon"]:
            lines.append(f"- {f['title']} — {f['url']}")
        lines.append("")

    if not data["powers"] and not data["subcategories"] and not data["fanon"]:
        lines.append("No entries found. Check the exact category name (e.g., `Elemental Manipulation`, `Powers`, `Physiology`).")

    if data["has_more"]:
        lines.append(f"*More items available: pass `continue_token=\"{data['next_continue']}\"`.*")
    return "\n".join(lines).strip()


@mcp.tool(name="superpower_random_powers", annotations=_RANDOM_ANNOTATIONS)
async def superpower_random_powers(
    count: Annotated[int, Field(default=3, ge=1, le=10, description="Number of random powers to draw (1-10).")] = 3,
    category: Annotated[Optional[str], Field(default=None, description="Optional category to restrict the random draw.")] = None,
    include_summary: Annotated[bool, Field(default=True, description="Include a short Capabilities summary for each drawn power.")] = True,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="'markdown' or 'json'.")] = ResponseFormat.MARKDOWN,
) -> str:
    """Draw random canonical superpowers (globally or within a category) for character brainstorming."""
    params = RandomPowersInput(
        count=count,
        category=category,
        include_summary=include_summary,
        response_format=response_format,
    )
    try:
        drawn = await _client.get_random_powers(count=params.count, category=params.category)
    except SuperpowerWikiError as exc:
        return f"Error: {exc}"

    async def _enrich(item: Dict[str, Any]) -> Dict[str, Any]:
        if not params.include_summary:
            return {**item, "summary": None}
        try:
            meta = await _client.get_page_metadata(item["title"])
            sec = _match_section(meta["sections"], "Capabilities")
            if sec:
                raw = await _client.get_section_wikitext(meta["title"], sec["index"])
                cleaned = clean_wikitext(raw, strip_leading_heading=True)
            else:
                raw = await _client.get_section_wikitext(meta["title"], 0)
                cleaned = clean_wikitext(raw, strip_leading_heading=False)
            summary, _ = truncate_text(cleaned, 500)
            return {**item, "categories": meta["categories"][:8], "summary": summary}
        except SuperpowerWikiError:
            return {**item, "categories": [], "summary": None}

    enriched = await asyncio.gather(*[_enrich(d) for d in drawn])
    payload = {"category": params.category, "count": len(enriched), "powers": enriched}
    if params.response_format == ResponseFormat.JSON:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    header = f"# Random Powers (Category: {params.category})" if params.category else "# Random Powers"
    lines = [header, ""]
    for idx, p in enumerate(enriched, 1):
        lines.append(f"## {idx}. {p['title']}")
        lines.append(f"URL: {p['url']}")
        if p.get("categories"):
            lines.append(f"**Categories:** {', '.join(p['categories'])}")
        if p.get("summary"):
            lines.append(f"\n{p['summary']}")
        lines.append("")
    return "\n".join(lines).strip()


@mcp.tool(name="superpower_compare_powers", annotations=_READ_ONLY_ANNOTATIONS)
async def superpower_compare_powers(
    titles: Annotated[List[str], Field(min_length=2, max_length=4, description="List of 2 to 4 power titles to compare for synergies, combos, or matchups.")],
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="'markdown' or 'json'.")] = ResponseFormat.MARKDOWN,
) -> str:
    """Compare 2 to 4 superpowers in parallel across Capabilities, Limitations, Associations, and shared Categories."""
    params = ComparePowersInput(titles=titles, response_format=response_format)

    async def _inspect(power_title: str) -> Dict[str, Any]:
        try:
            meta = await _client.get_page_metadata(power_title)
            fetched = await _fetch_sections_clean(meta["title"], meta["sections"], ["Capabilities", "Limitations"])
            assoc_sec = _match_section(meta["sections"], "Associations")
            associations: List[str] = []
            if assoc_sec:
                raw_assoc = await _client.get_section_wikitext(meta["title"], assoc_sec["index"])
                associations = [item["title"] for item in extract_power_links(raw_assoc)[:20]]

            cap_short, _ = truncate_text(fetched.get("Capabilities", ""), 1400)
            lim_short, _ = truncate_text(fetched.get("Limitations", ""), 1200)
            return {
                "title": meta["title"],
                "url": meta["url"],
                "categories": meta["categories"],
                "capabilities": cap_short,
                "limitations": lim_short,
                "associations": associations,
                "error": None,
            }
        except SuperpowerWikiError as exc:
            return {
                "title": power_title,
                "url": None,
                "categories": [],
                "capabilities": "",
                "limitations": "",
                "associations": [],
                "error": str(exc),
            }

    profiles = await asyncio.gather(*[_inspect(t) for t in params.titles])
    valid_cat_sets = [set(p["categories"]) for p in profiles if not p["error"] and p["categories"]]
    shared_categories = sorted(set.intersection(*valid_cat_sets)) if len(valid_cat_sets) >= 2 else []

    assoc_sets = [set(p["associations"]) for p in profiles if not p["error"] and p["associations"]]
    shared_associations = sorted(set.intersection(*assoc_sets)) if len(assoc_sets) >= 2 else []

    payload = {
        "shared_categories": shared_categories,
        "shared_associations": shared_associations,
        "powers": profiles,
    }
    if params.response_format == ResponseFormat.JSON:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [
        "# Power Comparison",
        f"**Shared Categories:** {', '.join(shared_categories) if shared_categories else 'None'}",
        f"**Shared Associations:** {', '.join(shared_associations) if shared_associations else 'None'}",
        "",
    ]
    for p in profiles:
        lines.append(f"## {p['title']}")
        if p["error"]:
            lines.append(f"*Error: {p['error']}*\n")
            continue
        lines.append(f"URL: {p['url']}")
        if p["categories"]:
            lines.append(f"**Categories:** {', '.join(p['categories'][:10])}")
        if p["capabilities"]:
            lines.append(f"\n### Capabilities\n{p['capabilities']}")
        if p["limitations"]:
            lines.append(f"\n### Limitations\n{p['limitations']}")
        if p["associations"]:
            lines.append(f"\n### Key Associations\n{', '.join(p['associations'][:12])}")
        lines.append("")
    return "\n".join(lines).strip()


# ==============================================================================
# PROMPTS (Reusable Worldbuilding Workflows)
# ==============================================================================


@mcp.prompt()
def design_character_power_kit(concept: str, power_tier: str = "street-to-city") -> str:
    """Structured workflow to build a coherent character power kit grounded in Superpower Wiki."""
    return (
        f"Design a coherent character power kit for the concept: '{concept}' (tier: {power_tier}).\n"
        "Follow these steps using the Superpower Wiki MCP tools:\n"
        "1. Call `superpower_search` to identify 1 core umbrella power and 1-2 complementary concepts.\n"
        "2. Call `superpower_get_power` on the chosen core power to ground its physical/conceptual Capabilities.\n"
        "3. Call `superpower_explore_tree` to pick 3-5 realistic Applications/Techniques appropriate for the target tier.\n"
        "4. Call `superpower_get_limitations` to derive strict costs, bottlenecks, and tactical counters.\n"
        "5. Present the final character power sheet with Core Mechanism, Signature Techniques, Synergies, and Hard Limits."
    )


@mcp.prompt()
def balance_power_system(powers: str) -> str:
    """Audit strengths, weaknesses, and counters across a set of character powers."""
    return (
        f"Audit and balance the following power set: {powers}.\n"
        "1. Call `superpower_compare_powers` on the listed powers.\n"
        "2. Identify overlapping categories, unintended overpowered synergies, and missing counters.\n"
        "3. Propose concrete physical/energy constraints and weaknesses grounded in each power's Limitations section."
    )


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_request: Request) -> JSONResponse:
    """Lightweight health endpoint for Render/Cloud Run/load balancers."""
    return JSONResponse({"status": "ok", "service": "superpower_wiki_mcp"})


# ASGI app exported for remote Streamable HTTP deployments (uvicorn / Render / Cloud Run / Fly.io)
app = mcp.http_app(
    path="/mcp",
    transport="streamable-http",
    stateless_http=True,
    json_response=True,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Superpower Wiki MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("SUPERPOWER_MCP_TRANSPORT", "stdio"),
        help="Transport mode: 'stdio' for local CLI or 'http' for remote Streamable HTTP.",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"), help="Bind host for HTTP mode.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")), help="Bind port for HTTP mode.")
    parser.add_argument("--path", default=os.environ.get("SUPERPOWER_MCP_PATH", "/mcp"), help="HTTP endpoint path.")
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            path=args.path,
            stateless_http=True,
            json_response=True,
            show_banner=False,
        )
    else:
        mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
