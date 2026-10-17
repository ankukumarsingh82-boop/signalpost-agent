"""Research one organisation number into a terminal envelope."""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlsplit

from .domains import same_registrable_domain, unpublishable_reason
from .envelope import build_envelope
from .http_client import Fetch, HttpClient, UnsafeUrl, assert_public_http_url, availability_for_http, normalize_website
from .nav_jobs import match_nav_jobs
from .news import research_news
from .parse_brreg import merge_workplaces, parse_accounts, parse_entity, parse_group, parse_roles, parse_subunit_page
from .parse_website import extract_page, robots_blocks_homepage
from .wikidata import wikipedia_title

ENTITY_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
ROLES_URL = ENTITY_URL + "/roller"
ACCOUNTS_URL = "https://data.brreg.no/regnskapsregisteret/regnskap/{org}"
GROUP_URL = "https://data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}"
SUBUNIT_URL = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=100&page={page}"

_robots_lock = threading.Lock()
_robots_cache: dict[str, bool] = {}


def clear_robots_cache() -> None:
    with _robots_lock:
        _robots_cache.clear()


def _hit(fetch: Fetch) -> dict[str, Any]:
    return {
        "url": fetch.url,
        "final_url": fetch.final_url,
        "status": fetch.status,
        "retrieved_at": fetch.retrieved_at,
        "content_sha256": fetch.content_sha256,
        "error": fetch.error,
        "attempts": fetch.attempts,
    }


def _json_state(fetch: Fetch) -> str:
    if fetch.status == 200 and fetch.json_body is None:
        return "failed"
    return availability_for_http(fetch.status)


def _homepage_allowed(client: HttpClient, url: str) -> tuple[bool, Fetch | None]:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.hostname}"
    with _robots_lock:
        cached = _robots_cache.get(origin)
    if cached is not None:
        return cached, None
    fetched = client.get_text(origin + "/robots.txt", timeout=5, max_bytes=100_000, public_only=True)
    blocked = bool(fetched.ok and robots_blocks_homepage(fetched.text))
    allowed = not blocked
    with _robots_lock:
        _robots_cache[origin] = allowed
    return allowed, fetched


def research_company(
    org: str,
    client: HttpClient,
    wiki_row: dict[str, Any] | None,
    run: dict[str, Any],
    *,
    skip_website: bool = False,
    skip_news: bool = False,
    nav_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    requests = 0
    errors: list[dict[str, Any]] = []

    def track(fetch: Fetch) -> Fetch:
        nonlocal requests
        requests += fetch.attempts or 1
        if fetch.error and fetch.status not in {200, 404, 410}:
            errors.append({"url": fetch.url, "status": fetch.status, "error": fetch.error})
        return fetch

    entity_fetch = track(client.get_json(ENTITY_URL.format(org=org)))
    entity_state = _json_state(entity_fetch)
    parsed = parse_entity(entity_fetch.json_body) if entity_state == "available" else None
    entity_note = None
    if parsed and str(parsed.get("organisation_number") or "") != org:
        entity_note = f"Register document organisation number {parsed.get('organisation_number')} did not match the requested number."
        entity_state = "ambiguous"
        parsed = None
    elif entity_state == "failed":
        entity_note = entity_fetch.error or "Entity register request failed."
    elif entity_state == "blocked":
        entity_note = "Entity register refused the request."
    elif entity_state == "not_available":
        entity_note = "No entity is published for this organisation number."

    accounts: dict[str, Any] = {"availability": "not_available", "note": "Not requested."}
    roles: dict[str, Any] = {"availability": "not_available", "note": "Not requested."}
    workplaces: dict[str, Any] = {"availability": "not_available", "note": "Not requested."}
    group: dict[str, Any] = {"availability": "not_applicable", "note": "Not requested."}
    if entity_state in {"available", "failed"} and entity_state != "ambiguous":
        accounts_fetch = track(client.get_json(ACCOUNTS_URL.format(org=org)))
        accounts = {
            "availability": _json_state(accounts_fetch),
            "parsed": parse_accounts(accounts_fetch.json_body) if accounts_fetch.status == 200 else None,
            "hit": _hit(accounts_fetch),
            "note": accounts_fetch.error,
        }
        roles_fetch = track(client.get_json(ROLES_URL.format(org=org)))
        roles = {
            "availability": _json_state(roles_fetch),
            "parsed": parse_roles(roles_fetch.json_body) if roles_fetch.status == 200 else None,
            "hit": _hit(roles_fetch),
            "note": roles_fetch.error,
        }
        pages: list[dict[str, Any]] = []
        first_hit = None
        subunit_state = "failed"
        for page in range(3):
            subunit_fetch = track(client.get_json(SUBUNIT_URL.format(org=org, page=page)))
            if page == 0:
                first_hit = _hit(subunit_fetch)
                subunit_state = _json_state(subunit_fetch)
                if subunit_state != "available":
                    break
            if subunit_fetch.status != 200 or not isinstance(subunit_fetch.json_body, dict):
                break
            parsed_page = parse_subunit_page(subunit_fetch.json_body)
            pages.append(parsed_page)
            total_pages = parsed_page.get("total_pages") or 1
            if page + 1 >= int(total_pages):
                break
        workplaces = {
            "availability": subunit_state,
            "parsed": merge_workplaces(pages) if pages else None,
            "hit": first_hit,
            "note": None if pages else "Subunit request did not succeed.",
        }
        if parsed is not None and parsed.get("in_corporate_group") is False:
            group = {
                "availability": "not_applicable",
                "hit": _hit(entity_fetch),
                "note": "erIKonsern is false.",
            }
        else:
            group_fetch = track(client.get_json(GROUP_URL.format(org=org)))
            group_state = _json_state(group_fetch)
            group = {
                "availability": group_state,
                "parsed": parse_group(group_fetch.json_body, org) if group_state == "available" else None,
                "hit": _hit(group_fetch),
                "note": group_fetch.error,
            }
    elif entity_state == "not_available":
        accounts = {"availability": "not_available", "hit": _hit(entity_fetch), "note": "Entity was not found, so accounts were not requested."}
        roles = {"availability": "not_available", "hit": _hit(entity_fetch), "note": "Entity was not found, so roles were not requested."}
        workplaces = {"availability": "not_available", "hit": _hit(entity_fetch), "note": "Entity was not found, so workplaces were not requested."}
        group = {"availability": "not_available", "hit": _hit(entity_fetch), "note": "Entity was not found, so group structure was not requested."}

    website = _research_website(client, track, parsed, skip_website=skip_website)
    errors.extend(item for item in (website.get("errors") or []) if item.get("error") in {"shared_domain", "directory_host", "invalid_host", "cross_domain_or_directory_redirect"} or str(item.get("error") or "").startswith("blocked_url"))
    jobs = match_nav_jobs(client, track, nav_catalog, org, parsed, workplaces)
    news = research_news(client, track, parsed, skip=skip_news)
    wiki = _research_wiki(client, track, wiki_row, entity_state)

    research = {
        "entity": {"availability": entity_state, "parsed": parsed, "hit": _hit(entity_fetch), "note": entity_note},
        "accounts": accounts,
        "roles": roles,
        "workplaces": workplaces,
        "group": group,
        "website": website,
        "jobs": jobs,
        "news": news,
        "wiki": wiki,
        "errors": errors,
        "terminal_status": "completed",
        "operations": {"requests": requests, "runtime_ms": int((time.monotonic() - started) * 1000)},
    }
    try:
        return build_envelope(org, research, run)
    except Exception as exc:  # last-resort envelope so a batch never drops a row
        return build_envelope(
            org,
            {
                "entity": {"availability": "failed", "hit": _hit(entity_fetch), "note": f"Envelope assembly failed: {exc}"},
                "accounts": {"availability": "failed", "note": "Skipped after an internal error."},
                "roles": {"availability": "failed", "note": "Skipped after an internal error."},
                "workplaces": {"availability": "failed", "note": "Skipped after an internal error."},
                "group": {"availability": "failed", "note": "Skipped after an internal error."},
                "website": {"availability": "failed", "note": "Skipped after an internal error."},
                "jobs": {"availability": "failed", "note": "Skipped after an internal error."},
                "news": {"availability": "failed", "note": "Skipped after an internal error."},
                "wiki": {"availability": "failed", "note": "Skipped after an internal error."},
                "errors": errors + [{"error": str(exc)}],
                "terminal_status": "failed",
                "operations": {"requests": requests, "runtime_ms": int((time.monotonic() - started) * 1000)},
            },
            run,
        )


_PAGE_HINTS = (
    "kontakt",
    "contact",
    "om-oss",
    "omoss",
    "about",
    "personvern",
    "privacy",
    "vilkar",
    "vilkår",
    "terms",
    "salgsbetingelser",
    "personvernerklaering",
)
_FALLBACK_PATHS = (
    "/kontakt",
    "/kontakt-oss",
    "/contact",
    "/om-oss",
    "/about",
    "/about-us",
    "/personvern",
    "/vilkar",
    "/terms",
    "/privacy",
)


def _empty_website(availability: str, note: str, **extra: Any) -> dict[str, Any]:
    module = {
        "availability": availability,
        "page_state": extra.pop("page_state", availability),
        "verified": False,
        "note": note,
        "errors": extra.pop("errors", []),
        "hits": [],
        "social_links": [],
        "hiring_pages": [],
        "news_pages": [],
        "dated_news": [],
    }
    module.update(extra)
    return module


def _candidate_pages(html: str, page_url: str) -> list[str]:
    from urllib.parse import urljoin, urlsplit

    found: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        absolute = urljoin(page_url, url)
        parts = urlsplit(absolute)
        if parts.scheme not in {"http", "https"}:
            return
        if not same_registrable_domain(page_url, absolute):
            return
        key = parts._replace(fragment="", query="").geturl()
        if key in seen:
            return
        seen.add(key)
        found.append(key)

    for href in re_hrefs(html):
        lowered = href.casefold()
        if any(hint in lowered for hint in _PAGE_HINTS):
            add(href)
    for path in _FALLBACK_PATHS:
        add(path)
    return found[:6]


def sitemap_identity_urls(xml_text: str, page_url: str, *, limit: int = 3) -> list[str]:
    """Same-site sitemap locations that look like contact, about, privacy, or terms pages."""
    import re
    from urllib.parse import urljoin

    found: list[str] = []
    seen: set[str] = set()
    for loc in re.findall(r"(?i)<loc>\s*([^<\s]+)\s*</loc>", xml_text or ""):
        absolute = urljoin(page_url, loc.strip())
        if not same_registrable_domain(page_url, absolute):
            continue
        lowered = absolute.casefold()
        if not any(hint in lowered for hint in _PAGE_HINTS):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append(absolute)
        if len(found) >= limit:
            break
    return found


def re_hrefs(html: str) -> list[str]:
    import re

    return re.findall(r"""href=["']([^"'#]+)""", html, flags=re.IGNORECASE)


def _research_website(client: HttpClient, track: Any, parsed: dict[str, Any] | None, *, skip_website: bool) -> dict[str, Any]:
    """Publish official_website only after the page proves it is this company."""
    if parsed is None:
        return _empty_website("not_available", "No confirmed entity, so no website was fetched.")
    listed = normalize_website(parsed.get("registry_website"))
    if not listed:
        return _empty_website("not_available", "The entity register has no website for this organisation.")
    reason = unpublishable_reason(listed)
    if reason:
        return _empty_website(
            "ambiguous",
            "The registered website host is shared by several organisations or is a directory. It was not fetched and is not published.",
            registry_url=listed,
            errors=[{"url": listed, "status": None, "error": reason}],
        )
    if skip_website:
        return _empty_website(
            "ambiguous",
            "A website is recorded in the register. Page fetch was disabled, so it was not verified and is not published as the official site.",
            registry_url=listed,
        )
    try:
        assert_public_http_url(listed)
    except UnsafeUrl as exc:
        return _empty_website(
            "blocked",
            "The registered website was not fetched because the URL failed the public-address check.",
            registry_url=listed,
            errors=[{"url": listed, "status": None, "error": f"blocked_url: {exc}"}],
        )
    allowed, robots = _homepage_allowed(client, listed)
    if robots is not None:
        track(robots)
    if not allowed:
        return _empty_website(
            "blocked",
            "robots.txt disallows the homepage, so the page was not fetched and is not published as the official site.",
            registry_url=listed,
            hit=_hit(robots) if robots is not None else None,
            claim_span="User-agent: * Disallow: /",
        )
    org = str(parsed.get("organisation_number") or "")
    address = parsed.get("business_address") if isinstance(parsed.get("business_address"), dict) else {}
    postal = None
    if isinstance(address, dict):
        postal = address.get("postal_code")
    if not postal and isinstance(parsed.get("postal_address"), dict):
        postal = parsed["postal_address"].get("postal_code")
    identity = {
        "legal_name": parsed.get("name"),
        "postal_code": postal,
        "telephone": parsed.get("telephone"),
    }
    fetched = track(client.get_text(listed, timeout=8, max_bytes=700_000, public_only=True, retries=1))
    if fetched.error and fetched.status not in {200, 404, 410}:
        pass
    final_url = fetched.final_url or listed
    if availability_for_http(fetched.status) != "available":
        state = availability_for_http(fetched.status)
        return _empty_website(
            state if state in {"blocked", "failed", "not_available"} else "failed",
            fetched.error or "The registered website could not be fetched, so it is not published.",
            registry_url=listed,
            hit=_hit(fetched),
            errors=[{"url": listed, "status": fetched.status, "error": fetched.error or state}],
        )
    if unpublishable_reason(final_url) or not same_registrable_domain(listed, final_url):
        return _empty_website(
            "ambiguous",
            "The fetch redirected to a different registrable domain or a directory host, so the page was rejected.",
            registry_url=listed,
            hit=_hit(fetched),
            errors=[{"url": listed, "status": fetched.status, "error": "cross_domain_or_directory_redirect", "final_url": final_url}],
        )
    pages: list[tuple[Fetch, dict[str, object]]] = []
    home = extract_page(fetched.text, org, final_url, **identity)
    pages.append((fetched, home))
    candidates = _candidate_pages(fetched.text, final_url)
    if not home.get("verified"):
        origin = urlsplit(final_url)
        sitemap_url = f"{origin.scheme}://{origin.netloc}/sitemap.xml"
        sitemap = track(client.get_text(sitemap_url, timeout=6, max_bytes=400_000, public_only=True, retries=0))
        if sitemap.status == 200 and sitemap.text:
            for loc in sitemap_identity_urls(sitemap.text, final_url):
                if loc not in candidates:
                    candidates.insert(0, loc)
    for candidate in candidates[:6]:
        extra = track(client.get_text(candidate, timeout=6, max_bytes=500_000, public_only=True, retries=0))
        if extra.status != 200 or not extra.text:
            continue
        if unpublishable_reason(extra.final_url) or not same_registrable_domain(listed, extra.final_url):
            continue
        pages.append((extra, extract_page(extra.text, org, extra.final_url, **identity)))
    verified_pages = [(page, extracted) for page, extracted in pages if extracted.get("verified")]
    if not verified_pages:
        return _empty_website(
            "ambiguous",
            "The registered site did not show this organisation number, the legal name with the postcode, the registered phone, or a distinctive part of the company name. It is not published.",
            registry_url=listed,
            page_state="ambiguous",
            hit=_hit(fetched),
            claim_span=final_url,
        )
    method = str(verified_pages[0][1].get("method") or "organisation_number")
    span = str(verified_pages[0][1].get("claim_span") or f"organisation number {org}")
    description = None
    social: list[dict[str, str]] = []
    hiring: list[str] = []
    news_pages: list[str] = []
    dated: list[dict[str, str]] = []
    seen_social: set[str] = set()
    hits = []
    for page, extracted in pages:
        hits.append(_hit(page))
        if description is None and (extracted.get("description") or extracted.get("candidate_description")):
            description = extracted.get("description") or extracted.get("candidate_description")
        for item in extracted.get("candidate_social_links") or extracted.get("social_links") or []:
            if item["url"] not in seen_social:
                seen_social.add(item["url"])
                social.append(item)
        for link in extracted.get("candidate_hiring_pages") or extracted.get("hiring_pages") or []:
            if link not in hiring and len(hiring) < 5:
                hiring.append(link)
        for link in extracted.get("candidate_news_pages") or extracted.get("news_pages") or []:
            if link not in news_pages and len(news_pages) < 5:
                news_pages.append(link)
        for item in extracted.get("dated_news") or []:
            if len(dated) < 5 and item.get("title") not in {row["title"] for row in dated}:
                dated.append(item)
    notes = {
        "organisation_number": "The page contains this organisation number.",
        "name_and_postcode": "The page contains the legal name and the registered postcode.",
        "telephone": "The page contains the telephone number recorded in the entity register.",
        "distinctive_name_token": "The register host loaded on the same domain and the page contains a distinctive part of the company name.",
        "embedded_organisation_number": "The page labels this organisation number, including an NO … MVA form.",
        "json_ld_organisation_number": "JSON-LD on the page carries this organisation number.",
        "json_ld_name_and_postcode": "JSON-LD on the page carries the legal name and the registered postcode.",
    }
    return {
        "availability": "available",
        "page_state": "available",
        "verified": True,
        "verification_method": method,
        "registry_url": listed,
        "final_url": final_url,
        "description": description,
        "social_links": social[:8],
        "hiring_pages": hiring,
        "news_pages": news_pages,
        "dated_news": dated,
        "hits": hits[:5],
        "hit": hits[0],
        "claim_span": span,
        "note": notes.get(method, "The page matched this organisation."),
        "errors": [],
    }


def _research_wiki(client: HttpClient, track: Any, wiki_row: dict[str, Any] | None, entity_state: str) -> dict[str, Any]:
    if entity_state != "available":
        return {"availability": "not_available", "note": "Wikidata facts are published only after the entity register confirms the organisation number."}
    if not wiki_row:
        return {"availability": "not_available", "note": "No Wikidata item has P2333 equal to this organisation number."}
    module: dict[str, Any] = {
        "availability": "available",
        "hit": {
            "url": wiki_row.get("query_url") or wiki_row.get("source_url"),
            "final_url": wiki_row.get("source_url"),
            "retrieved_at": wiki_row.get("retrieved_at"),
            "content_sha256": wiki_row.get("content_sha256"),
            "error": None,
        },
        "description": wiki_row.get("description"),
        "label": wiki_row.get("label"),
        "article_url": wiki_row.get("article_url"),
        "claim_span": wiki_row.get("description") or wiki_row.get("label") or "P2333",
    }
    article = wiki_row.get("article_url")
    if article and wikipedia_title(article):
        host, title = wikipedia_title(article)  # type: ignore[misc]
        summary_url = f"https://{host}/api/rest_v1/page/summary/{title}"
        fetched = track(client.get_json(summary_url, timeout=12, public_only=True))
        if fetched.ok and isinstance(fetched.json_body, dict):
            extract = fetched.json_body.get("extract")
            if isinstance(extract, str) and extract.strip():
                module["summary"] = " ".join(extract.split())[:700]
                module["summary_as_of"] = fetched.json_body.get("timestamp")
                module["summary_hit"] = _hit(fetched)
    return module
