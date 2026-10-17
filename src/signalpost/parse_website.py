"""Extract identity proof and company-owned links from a fetched homepage.

Page facts are publishable only when the page contains the queried organisation number.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

SOCIAL_HOSTS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "x.com": "x",
    "twitter.com": "x",
    "github.com": "github",
    "tiktok.com": "tiktok",
}

HIRING_HINTS = ("karriere", "stilling", "jobb", "jobs", "career", "vacanc", "ledige", "join-us", "joinus", "recruit")
NEWS_HINTS = ("nyhet", "news", "press", "aktuelt", "blog")


def organisation_number_pattern(org: str) -> re.Pattern[str]:
    digits = "".join(character for character in org if character.isdigit())
    spaced = r"[\s.\-]*".join(digits)
    return re.compile(rf"(?<!\d){spaced}(?!\d)", re.IGNORECASE)


def robots_blocks_homepage(text: str) -> bool:
    """Return True when User-agent: * disallows the homepage and does not allow it back."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal agents, rules
        if agents:
            groups.append((agents, rules))
        agents, rules = [], []

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            flush()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if rules:
                flush()
            agents.append(value.lower())
        elif key in {"allow", "disallow"}:
            rules.append((key, value))
    flush()
    star_rules: list[tuple[str, str]] = []
    for group_agents, group_rules in groups:
        if "*" in group_agents:
            star_rules.extend(group_rules)
    if not star_rules:
        return False
    blocked = False
    allowed = False
    for kind, value in star_rules:
        if kind == "disallow" and value == "/":
            blocked = True
        if kind == "allow" and value in {"/", ""}:
            allowed = True
    return blocked and not allowed


def _host_key(hostname: str) -> str:
    host = hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def social_platform(url: str) -> str | None:
    host = _host_key(urlsplit(url).hostname or "")
    for domain, platform in SOCIAL_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return platform
    return None


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.skip = 0
        self.metas: list[tuple[str, str]] = []
        self.links: list[tuple[str, str]] = []
        self.scripts: list[tuple[str, str]] = []
        self._script: list[str] = []
        self._script_type = ""
        self.in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
            if tag == "script":
                self.in_script = True
                self._script = []
                self._script_type = attributes.get("type", "").lower()
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            content = attributes.get("content", "").strip()
            if key and content:
                self.metas.append((key, content))
        if tag == "a":
            href = attributes.get("href", "").strip()
            if href:
                self.links.append((href, ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.in_script:
            self.scripts.append((self._script_type, "".join(self._script)))
            self.in_script = False
            self._script = []
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self._script.append(data)
            return
        if self.in_title:
            self.title_parts.append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _json_ld_descriptions(scripts: list[tuple[str, str]]) -> list[str]:
    descriptions: list[str] = []
    same_as: list[str] = []
    for script_type, raw in scripts:
        if "ld+json" not in script_type:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        stack = list(nodes)
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            description = node.get("description")
            if isinstance(description, str) and description.strip():
                descriptions.append(description.strip())
            extra = node.get("sameAs")
            if isinstance(extra, str):
                same_as.append(extra)
            elif isinstance(extra, list):
                same_as.extend(item for item in extra if isinstance(item, str))
    return descriptions


def _json_ld_same_as(scripts: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for script_type, raw in scripts:
        if "ld+json" not in script_type:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        pending = list(stack)
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("@graph"), list):
                pending.extend(node["@graph"])
            extra = node.get("sameAs")
            if isinstance(extra, str):
                found.append(extra)
            elif isinstance(extra, list):
                found.extend(item for item in extra if isinstance(item, str))
    return found


def _clean_description(text: str) -> str | None:
    compact = " ".join(text.split())
    if len(compact) < 40:
        return None
    lowered = compact.casefold()
    if lowered.startswith("cookie") or "cookie consent" in lowered or "personvern" == lowered:
        return None
    return compact[:500]


def _same_site(page_url: str, link: str) -> bool:
    page_host = _host_key(urlsplit(page_url).hostname or "")
    link_host = _host_key(urlsplit(link).hostname or "")
    if not page_host or not link_host:
        return False
    return link_host == page_host or link_host.endswith("." + page_host) or page_host.endswith("." + link_host)


def extract_page(html: str, org: str, page_url: str) -> dict[str, object]:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    matched = organisation_number_pattern(org).search(html) is not None
    span = ""
    if matched:
        match = organisation_number_pattern(org).search(html)
        if match:
            start = max(0, match.start() - 80)
            stop = min(len(html), match.end() + 80)
            span = " ".join(re.sub(r"<[^>]+>", " ", html[start:stop]).split())[:240]
    descriptions = _json_ld_descriptions(parser.scripts)
    meta_description = ""
    for key, content in parser.metas:
        if key in {"description", "og:description"} and not meta_description:
            meta_description = content
    description = None
    for candidate in [*descriptions, meta_description]:
        cleaned = _clean_description(candidate) if candidate else None
        if cleaned:
            description = cleaned
            break
    social: list[dict[str, str]] = []
    seen_social: set[str] = set()
    hiring: list[str] = []
    news: list[str] = []
    seen_links: set[str] = set()
    for href in [*_json_ld_same_as(parser.scripts), *[item[0] for item in parser.links]]:
        absolute = urljoin(page_url, href)
        if urlsplit(absolute).scheme not in {"http", "https"}:
            continue
        platform = social_platform(absolute)
        if platform and absolute not in seen_social:
            seen_social.add(absolute)
            social.append({"platform": platform, "url": absolute})
        if absolute in seen_links or not _same_site(page_url, absolute):
            continue
        seen_links.add(absolute)
        haystack = absolute.casefold()
        if any(hint in haystack for hint in HIRING_HINTS) and len(hiring) < 5:
            hiring.append(absolute)
        elif any(hint in haystack for hint in NEWS_HINTS) and len(news) < 5:
            news.append(absolute)
    title = " ".join(" ".join(parser.title_parts).split())[:180]
    return {
        "verified": matched,
        "title": title or None,
        "description": description if matched else None,
        "social_links": social if matched else [],
        "hiring_pages": hiring if matched else [],
        "news_pages": news if matched else [],
        "claim_span": span,
        "rejected_social_links": social if not matched else [],
    }
