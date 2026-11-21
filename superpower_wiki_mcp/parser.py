"""Wikitext cleaning and power-link extraction for Superpower Wiki (Fandom/MediaWiki)."""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List

_IGNORED_LINK_PREFIXES = (
    "wikipedia:",
    "w:",
    "file:",
    "image:",
    "category:",
    "special:",
    "template:",
    "user:",
    "user blog:",
    "talk:",
    "help:",
    "mediawiki:",
    "module:",
    "fanon:",
    "http://",
    "https://",
)

_DROP_TEMPLATE_NAMES = {
    "quote",
    "quote2",
    "gallery",
    "reflist",
    "references",
    "stub",
    "delete",
    "cleanup",
    "disambig",
    "disambiguation",
    "toc",
    "clr",
    "clear",
    "navbox",
    "youtube",
    "video",
    "fandom",
    "stub-section",
    "unfinished",
    "wip",
}

_UNWRAP_TEMPLATE_NAMES = {
    "scroll box",
    "scrollbox",
    "div col",
    "col-begin",
    "columns-list",
    "collapsible",
    "collapse",
    "hidden",
}


def _find_matching_braces(text: str, start: int) -> int:
    """Find the index right after the closing '}}' matching '{{' at start, or -1."""
    depth = 0
    i = start
    n = len(text)
    while i < n - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return -1


def _process_templates(text: str) -> str:
    """Unwrap container templates (like scroll box), resolve simple wiki templates, and drop decorative ones."""
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i : i + 2] == "{{":
            end = _find_matching_braces(text, i)
            if end == -1:
                out.append(text[i:])
                break
            inner = text[i + 2 : end - 2]
            parts = _split_top_level_pipes(inner)
            name = parts[0].strip().lower() if parts else ""
            if name in _UNWRAP_TEMPLATE_NAMES:
                body = _extract_template_body(parts[1:])
                out.append(_process_templates(body))
            elif name in {"w", "wp", "wikipedia"} and len(parts) >= 2:
                display = parts[2].strip() if len(parts) >= 3 and "=" not in parts[2] else parts[1].strip()
                out.append(display)
            elif name in {"main", "see also"} and len(parts) >= 2:
                refs = [p.strip() for p in parts[1:] if p.strip() and "=" not in p]
                if refs:
                    out.append("See also: " + ", ".join(refs))
            elif name in _DROP_TEMPLATE_NAMES or name.startswith("#"):
                pass
            else:
                # Preserve plain positional text if short, otherwise drop noisy layout templates
                positional = [p.strip() for p in parts[1:] if p.strip() and "=" not in p]
                if len(positional) == 1 and len(positional[0]) <= 80:
                    out.append(_process_templates(positional[0]))
            i = end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _split_top_level_pipes(text: str) -> List[str]:
    """Split template arguments on '|' ignoring pipes inside nested [[...]] or {{...}}."""
    parts: List[str] = []
    buf: List[str] = []
    brace_depth = 0
    bracket_depth = 0
    i = 0
    n = len(text)
    while i < n:
        pair = text[i : i + 2]
        if pair == "{{":
            brace_depth += 1
            buf.append(pair)
            i += 2
        elif pair == "}}":
            brace_depth = max(0, brace_depth - 1)
            buf.append(pair)
            i += 2
        elif pair == "[[":
            bracket_depth += 1
            buf.append(pair)
            i += 2
        elif pair == "]]":
            bracket_depth = max(0, bracket_depth - 1)
            buf.append(pair)
            i += 2
        elif text[i] == "|" and brace_depth == 0 and bracket_depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(text[i])
            i += 1
    parts.append("".join(buf))
    return parts


def _extract_template_body(args: List[str]) -> str:
    """Extract the main content argument from wrapper templates like {{scroll box|content=...}}."""
    named_keys = ("content", "text", "body", "1")
    for arg in args:
        if "=" in arg:
            k, v = arg.split("=", 1)
            if k.strip().lower() in named_keys:
                return v
    positional = [arg for arg in args if "=" not in arg]
    if positional:
        return "\n".join(positional)
    return ""


def _strip_file_and_category_links(text: str) -> str:
    """Remove [[File:...]], [[Image:...]], and [[Category:...]] links including nested brackets."""
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i : i + 2] == "[[":
            lower_ahead = text[i + 2 : i + 16].lower()
            if lower_ahead.startswith(("file:", "image:", "category:")):
                depth = 1
                j = i + 2
                while j < n - 1 and depth > 0:
                    pair = text[j : j + 2]
                    if pair == "[[":
                        depth += 1
                        j += 2
                    elif pair == "]]":
                        depth -= 1
                        j += 2
                    else:
                        j += 1
                i = j
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _replace_wikilink(match: re.Match[str]) -> str:
    target = match.group(1).strip()
    label = match.group(2)
    if label is not None and label.strip():
        return label.strip()
    if ":" in target:
        prefix, rest = target.split(":", 1)
        if prefix.strip().lower() in {"wikipedia", "w"}:
            return rest.strip()
    return target.split("#", 1)[0].strip()


def clean_wikitext(wikitext: str, strip_leading_heading: bool = True) -> str:
    """Convert Superpower Wiki MediaWiki wikitext into clean, compact Markdown."""
    if not wikitext:
        return ""

    text = html.unescape(wikitext)
    # Remove HTML comments, galleries, refs, and style/script blocks
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<gallery\b[^>]*>.*?</gallery>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<ref\b[^>]*>.*?</ref>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<ref\b[^>]*/>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<(?:tabber|style|script)\b[^>]*>.*?</(?:tabber|style|script)>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:div|span|center|small|big|font|p|sup|sub|blockquote)\b[^>]*>", "", text, flags=re.IGNORECASE)

    # Process templates (unwrap scroll boxes, drop quotes/navboxes)
    text = _process_templates(text)

    # Strip File/Image/Category links
    text = _strip_file_and_category_links(text)

    # Convert external links [https://... Label] -> Label
    text = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://[^\s\]]+\]", "", text)

    # Convert internal wikilinks [[Target|Label]] or [[Target]]
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]", _replace_wikilink, text)

    # Convert MediaWiki bold/italic
    text = re.sub(r"'''''(.*?)'''''", r"***\1***", text)
    text = re.sub(r"'''(.*?)'''", r"**\1**", text)
    text = re.sub(r"''(.*?)''", r"*\1*", text)

    lines = text.splitlines()
    cleaned_lines: List[str] = []
    skipped_first_heading = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        # MediaWiki headings (== Heading ==)
        heading_match = re.match(r"^(={2,6})\s*(.+?)\s*\1$", line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if strip_leading_heading and not skipped_first_heading and level == 2 and not cleaned_lines:
                skipped_first_heading = True
                continue
            md_level = min(6, level + 1)
            cleaned_lines.append(f"{'#' * md_level} {heading_text}")
            continue

        # Bullet lists (*, **, ***)
        bullet_match = re.match(r"^(\*+)\s*(.*)$", line)
        if bullet_match:
            depth = len(bullet_match.group(1)) - 1
            item = bullet_match.group(2).strip()
            if item:
                cleaned_lines.append(f"{'  ' * depth}- {item}")
            continue

        # Numbered lists (#, ##)
        num_match = re.match(r"^(#+)\s*(.*)$", line)
        if num_match:
            depth = len(num_match.group(1)) - 1
            item = num_match.group(2).strip()
            if item:
                cleaned_lines.append(f"{'  ' * depth}1. {item}")
            continue

        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def extract_power_links(wikitext: str, include_fanon: bool = False) -> List[Dict[str, Any]]:
    """Extract deduplicated internal Superpower Wiki power links with list depth metadata."""
    if not wikitext:
        return []

    unwrapped = _process_templates(html.unescape(wikitext))
    unwrapped = _strip_file_and_category_links(unwrapped)

    seen: set[str] = set()
    links: List[Dict[str, Any]] = []

    for raw_line in unwrapped.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        bullet_match = re.match(r"^(\*+)", line)
        depth = len(bullet_match.group(1)) if bullet_match else 0

        for match in re.finditer(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]", line):
            raw_target = match.group(1).strip()
            raw_label = match.group(2).strip() if match.group(2) else None
            if not raw_target or raw_target.startswith("#"):
                continue

            lower_target = raw_target.lower()
            if not include_fanon and lower_target.startswith("fanon:"):
                continue
            if any(lower_target.startswith(prefix) for prefix in _IGNORED_LINK_PREFIXES if prefix != "fanon:"):
                continue

            canonical = raw_target.split("#", 1)[0].replace("_", " ").strip()
            if not canonical:
                continue
            key = canonical.lower()
            if key in seen:
                continue
            seen.add(key)

            entry: Dict[str, Any] = {"title": canonical, "depth": depth}
            if raw_label and raw_label.lower() != key:
                entry["label"] = raw_label
            links.append(entry)

    return links


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text cleanly at a line/word boundary if it exceeds max_chars."""
    if len(text) <= max_chars:
        return text, False
    cut = text[: max_chars - 60]
    last_nl = cut.rfind("\n")
    if last_nl > max_chars // 2:
        cut = cut[:last_nl]
    return cut.rstrip() + "\n\n... [truncated due to max_chars limit]", True
