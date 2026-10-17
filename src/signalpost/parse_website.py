"""Extract identity proof and company-owned links from a fetched page.

A page is verified when it contains the organisation number, the legal name
together with the registered postcode, the registered telephone number, or a
distinctive token from the legal name. Links are returned only for a verified page.
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

HIRING_PATH = re.compile(
    r"(?:^|/)(?:karriere|karrierer|stillinger|stilling|jobber|jobb|jobs|careers|career|vacancies|vacancy|ledige-stillinger|join-us|joinus|recruitment|recruit|rekruttering)(?:/|$)",
    re.IGNORECASE,
)
HIRING_BLOCK = (
    "bestill",
    "blogg",
    "blog",
    "booking",
    "leie",
    "news",
    "nyhet",
    "personvern",
    "privacy",
    "rental",
    "terms",
    "utleie",
    "vilkar",
    "vilkår",
)
NEWS_HINTS = ("nyhet", "news", "press", "aktuelt")
_GITHUB_RESERVED = {
    "about",
    "account",
    "collections",
    "customer-stories",
    "enterprise",
    "events",
    "explore",
    "features",
    "issues",
    "join",
    "login",
    "marketplace",
    "new",
    "notifications",
    "org",
    "organizations",
    "pricing",
    "pulls",
    "readme",
    "search",
    "security",
    "settings",
    "signup",
    "sponsors",
    "team",
    "topics",
    "trending",
}
_X_RESERVED = {"explore", "hashtag", "home", "i", "intent", "search", "settings", "share", "tos"}


LEGAL_FORMS = {"as", "asa", "sa", "ba", "da", "ans", "enk", "nuf", "sti", "iks", "fkf", "sf", "hf", "rhf"}
# Short or generic tokens must not be enough to claim a register website.
GENERIC_NAME_TOKENS = LEGAL_FORMS | {
    "ab",
    "and",
    "av",
    "bergen",
    "bil",
    "bolig",
    "bygg",
    "co",
    "company",
    "consult",
    "consulting",
    "digital",
    "drift",
    "eiendom",
    "elektro",
    "first",
    "for",
    "glass",
    "group",
    "gruppen",
    "holding",
    "hus",
    "international",
    "invest",
    "ltd",
    "management",
    "media",
    "nordic",
    "norge",
    "norsk",
    "norske",
    "norway",
    "og",
    "online",
    "oslo",
    "partner",
    "partners",
    "sameie",
    "service",
    "services",
    "solutions",
    "stavanger",
    "stiftelse",
    "the",
    "trondheim",
}
_ORG_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)


def organisation_number_pattern(org: str) -> re.Pattern[str]:
    digits = "".join(character for character in org if character.isdigit())
    spaced = r"[\s.\-]*".join(digits)
    return re.compile(rf"(?<!\d){spaced}(?!\d)", re.IGNORECASE)


def valid_organisation_number(value: str) -> bool:
    if not re.fullmatch(r"\d{9}", value):
        return False
    total = sum(int(digit) * weight for digit, weight in zip(value[:8], _ORG_WEIGHTS))
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    if check == 10:
        return False
    return check == int(value[8])


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9æøå]+", (value or "").casefold())


def strip_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value or "").split())


def visible_html(html: str) -> str:
    """Drop scripts and styles. JSON-LD is kept because it is company-supplied identity."""
    without = re.sub(r"(?is)<script\b(?![^>]*ld\+json)[^>]*>.*?</script>", " ", html or "")
    without = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", without)
    without = re.sub(r"(?is)<noscript\b[^>]*>.*?</noscript>", " ", without)
    return without


def legal_name_in_text(legal_name: str, text: str) -> bool:
    name_tokens = _tokens(legal_name)
    text_tokens = _tokens(text)
    if not name_tokens or len(name_tokens) > len(text_tokens):
        return False
    distinctive = [token for token in name_tokens if token not in LEGAL_FORMS]
    if len("".join(distinctive)) < 4:
        return False
    width = len(name_tokens)
    for index in range(len(text_tokens) - width + 1):
        if text_tokens[index : index + width] == name_tokens:
            return True
    return False


def postcode_in_text(postcode: str | None, text: str) -> bool:
    code = "".join(character for character in str(postcode or "") if character.isdigit())
    if len(code) != 4:
        return False
    return re.search(rf"(?<!\d){code}(?!\d)", text) is not None


def _phone_pattern(phone: str | None) -> re.Pattern[str] | None:
    digits = "".join(character for character in str(phone or "") if character.isdigit())
    if len(digits) < 8:
        return None
    target = digits[-8:]
    spaced = r"[\s.\-\u00a0]*".join(target)
    return re.compile(rf"(?<!\d){spaced}(?!\d)")


def phone_in_text(phone: str | None, text: str) -> bool:
    pattern = _phone_pattern(phone)
    return pattern.search(text) is not None if pattern else False


def matched_phone(phone: str | None, text: str) -> str | None:
    pattern = _phone_pattern(phone)
    if pattern is None:
        return None
    found = pattern.search(text)
    return found.group(0) if found else None


def distinctive_name_token(legal_name: str | None, text: str) -> str | None:
    """A name token long enough, and uncommon enough, to tie a page to this company."""
    if not legal_name:
        return None
    page_tokens = set(_tokens(text))
    candidates = [
        token
        for token in _tokens(legal_name)
        if len(token) >= 5 and token not in GENERIC_NAME_TOKENS and not token.isdigit()
    ]
    candidates.sort(key=len, reverse=True)
    for token in candidates:
        if token in page_tokens:
            return token
    return None


def foreign_organisation_number(text: str, org: str) -> bool:
    """True when the page labels a different valid organisation number as its own."""
    for match in re.finditer(r"(?<!\d)(\d{9})(?!\d)", text):
        candidate = match.group(1)
        if candidate == org or not valid_organisation_number(candidate):
            continue
        start = max(0, match.start() - 48)
        window = text[start : match.end() + 12].casefold()
        if re.search(r"organisasjonsnummer|org\.?\s*nr|orgnr|foretaksnummer", window):
            return True
    return False


def _ld_json_nodes(html: str) -> list[dict]:
    nodes: list[dict] = []
    for raw in re.findall(r"(?is)<script\b[^>]*ld\+json[^>]*>(.*?)</script>", html or ""):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        pending = payload if isinstance(payload, list) else [payload]
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            if isinstance(graph, list):
                pending.extend(graph)
            nodes.append(node)
    return nodes


def json_ld_identity(html: str, org: str, *, legal_name: str | None, postal_code: str | None) -> tuple[str, str] | None:
    """Organisation number, or legal name plus postcode, from JSON-LD."""
    pattern = organisation_number_pattern(org)
    for node in _ld_json_nodes(html):
        for key in ("taxID", "vatID", "identifier", "lei"):
            value = node.get(key)
            if isinstance(value, dict):
                value = value.get("value") or value.get("@id") or value.get("name")
            if isinstance(value, str) and pattern.search(value):
                return "json_ld_organisation_number", " ".join(value.split())[:240]
        name = node.get("legalName") or node.get("name")
        address = node.get("address") if isinstance(node.get("address"), dict) else {}
        code = address.get("postalCode") or address.get("postalcode")
        if (
            isinstance(name, str)
            and legal_name
            and legal_name_in_text(legal_name, name)
            and postcode_in_text(postal_code, str(code or ""))
        ):
            return "json_ld_name_and_postcode", f"{name} {code}"[:240]
    return None


def labelled_organisation_span(html: str, org: str) -> str | None:
    """Quote an organisation number that is labelled or written as NO … MVA."""
    for match in organisation_number_pattern(org).finditer(html or ""):
        start = max(0, match.start() - 48)
        stop = min(len(html), match.end() + 12)
        window = html[start:stop]
        flat = strip_html(window)
        lowered = flat.casefold()
        prefix = html[max(0, match.start() - 4) : match.start()]
        suffix = html[match.end() : match.end() + 8]
        mva = "mva" in lowered or "mva" in suffix.casefold()
        labelled = bool(re.search(r"organisasjonsnummer|org\.?\s*nr|foretaksnummer|taxid|vatid", lowered))
        no_prefix = bool(re.search(r"no[\s.\-\u00a0]*$", prefix, re.IGNORECASE))
        if mva or labelled or (no_prefix and mva):
            return " ".join(flat.split())[:240]
    return None


def identity_match(html: str, org: str, *, legal_name: str | None, postal_code: str | None, telephone: str | None) -> tuple[str | None, str]:
    """Return (method, claim span). Method is None when the page must not be used."""
    page = visible_html(html)
    if organisation_number_pattern(org).search(page):
        match = organisation_number_pattern(org).search(page)
        span = ""
        if match:
            start = max(0, match.start() - 80)
            stop = min(len(page), match.end() + 80)
            span = " ".join(re.sub(r"<[^>]+>", " ", page[start:stop]).split())[:240]
        return "organisation_number", span
    embedded = labelled_organisation_span(html, org)
    if embedded:
        return "embedded_organisation_number", embedded
    structured = json_ld_identity(html, org, legal_name=legal_name, postal_code=postal_code)
    if structured:
        return structured
    text = strip_html(page)
    if foreign_organisation_number(text, org):
        return None, ""
    if legal_name and legal_name_in_text(legal_name, text) and postcode_in_text(postal_code, text):
        return "name_and_postcode", f"{legal_name} {postal_code}"[:240]
    quoted = matched_phone(telephone, text) if telephone else None
    if quoted:
        return "telephone", f"registered telephone {quoted}"
    token = distinctive_name_token(legal_name, text)
    if token:
        return "distinctive_name_token", f"{token} from {legal_name}"[:240]
    return None, ""


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


def _path_parts(url: str) -> list[str]:
    return [part for part in urlsplit(url).path.split("/") if part]


def company_profile_url(url: str) -> str | None:
    """Canonical company-profile URL, or None for posts, shares, and personal pages."""
    platform = social_platform(url)
    if not platform:
        return None
    parts = urlsplit(url)
    host = _host_key(parts.hostname or "")
    path = parts.path or "/"
    lowered = path.casefold()
    query = parts.query.casefold()
    segments = [part.casefold() for part in _path_parts(url)]
    if platform == "linkedin":
        if not segments or segments[0] not in {"company", "school"}:
            return None
        if any(part in {"posts", "share"} for part in segments):
            return None
    elif platform == "facebook":
        blocked = ("sharer", "share.php", "dialog", "story.php", "permalink.php", "profile.php", "photo.php", "watch")
        if any(token in lowered or token in query for token in blocked):
            return None
        if not segments or segments[0] in {"people", "posts", "share", "sharer", "dialog", "watch", "reel", "groups", "marketplace", "login", "help", "privacy"}:
            return None
        if "posts" in segments or "photos" in segments or "videos" in segments:
            return None
    elif platform == "instagram":
        if len(segments) != 1 or segments[0] in {"p", "reel", "reels", "stories", "explore", "about", "accounts", "developer"}:
            return None
    elif platform == "youtube":
        if host == "youtu.be":
            return None
        if not segments:
            return None
        if segments[0] in {"watch", "shorts", "embed", "playlist", "feed", "results"}:
            return None
        if segments[0] not in {"channel", "c", "user"} and not segments[0].startswith("@"):
            return None
    elif platform == "github":
        if len(segments) != 1 or segments[0] in _GITHUB_RESERVED or segments[0].startswith("."):
            return None
    elif platform == "x":
        if not segments or segments[0] in _X_RESERVED or "intent" in segments or "status" in segments:
            return None
        if len(segments) != 1:
            return None
    elif platform == "tiktok":
        if not segments or not segments[0].startswith("@") or "video" in segments:
            return None
    else:
        return None
    canonical_path = "/" + "/".join(_path_parts(url))
    return f"https://{host}{canonical_path}"


def is_hiring_page(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    if any(token in path for token in HIRING_BLOCK):
        return False
    return HIRING_PATH.search(path) is not None


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


def extract_dated_news(html: str, page_url: str, *, limit: int = 5) -> list[dict[str, str]]:
    """Headlines with a timestamp inside an article on an already verified page."""
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for article in re.findall(r"<article\b[^>]*>(.*?)</article>", html, flags=re.IGNORECASE | re.DOTALL):
        time_match = re.search(r"<time\b[^>]*datetime=[\"']([^\"']+)[\"']", article, flags=re.IGNORECASE)
        heading = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", article, flags=re.IGNORECASE | re.DOTALL)
        if not time_match or not heading:
            continue
        published = time_match.group(1).strip()
        if not re.match(r"20\d{2}-\d{2}-\d{2}", published):
            continue
        title = strip_html(heading.group(1))[:200]
        if len(title) < 20:
            continue
        lowered = title.casefold()
        if "cookie" in lowered or lowered in {"personvern", "privacy"}:
            continue
        link_match = re.search(r"<a\b[^>]*href=[\"']([^\"']+)[\"']", article, flags=re.IGNORECASE)
        url = page_url
        if link_match:
            url = urljoin(page_url, link_match.group(1))
            if not _same_site(page_url, url):
                url = page_url
        if title.casefold() in seen:
            continue
        seen.add(title.casefold())
        items.append({"title": title, "url": url, "published_at": published[:25]})
        if len(items) >= limit:
            break
    return items


def extract_page(
    html: str,
    org: str,
    page_url: str,
    *,
    legal_name: str | None = None,
    postal_code: str | None = None,
    telephone: str | None = None,
) -> dict[str, object]:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    method, span = identity_match(html, org, legal_name=legal_name, postal_code=postal_code, telephone=telephone)
    matched = method is not None
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
        profile = company_profile_url(absolute)
        if profile and profile not in seen_social:
            seen_social.add(profile)
            social.append({"platform": social_platform(profile) or "", "url": profile})
        if absolute in seen_links or not _same_site(page_url, absolute):
            continue
        seen_links.add(absolute)
        path = urlsplit(absolute).path.casefold()
        if is_hiring_page(absolute) and len(hiring) < 5:
            hiring.append(absolute)
        elif any(hint in path for hint in NEWS_HINTS) and len(news) < 5:
            news.append(absolute)
    title = " ".join(" ".join(parser.title_parts).split())[:180]
    return {
        "verified": matched,
        "method": method,
        "title": title or None,
        "dated_news": extract_dated_news(html, page_url) if matched else [],
        "description": description if matched else None,
        "candidate_description": description,
        "social_links": social if matched else [],
        "hiring_pages": hiring if matched else [],
        "news_pages": news if matched else [],
        "candidate_social_links": social,
        "candidate_hiring_pages": hiring,
        "candidate_news_pages": news,
        "claim_span": span,
        "rejected_social_links": social if not matched else [],
    }
