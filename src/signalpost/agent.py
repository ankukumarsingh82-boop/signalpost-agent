"""Research one organisation number into a terminal envelope."""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlsplit

from .envelope import build_envelope
from .http_client import Fetch, HttpClient, availability_for_http, normalize_website
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
    wiki = _research_wiki(client, track, wiki_row, entity_state)

    research = {
        "entity": {"availability": entity_state, "parsed": parsed, "hit": _hit(entity_fetch), "note": entity_note},
        "accounts": accounts,
        "roles": roles,
        "workplaces": workplaces,
        "group": group,
        "website": website,
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
                "wiki": {"availability": "failed", "note": "Skipped after an internal error."},
                "errors": errors + [{"error": str(exc)}],
                "terminal_status": "failed",
                "operations": {"requests": requests, "runtime_ms": int((time.monotonic() - started) * 1000)},
            },
            run,
        )


def _research_website(client: HttpClient, track: Any, parsed: dict[str, Any] | None, *, skip_website: bool) -> dict[str, Any]:
    """The register's hjemmeside is a registry fact. Page content is published only after an exact number match."""
    if parsed is None:
        return {"availability": "not_available", "page_state": "not_available", "note": "No confirmed entity, so no website was fetched."}
    listed = normalize_website(parsed.get("registry_website"))
    if not listed:
        return {"availability": "not_available", "page_state": "not_available", "note": "The entity register has no website for this organisation."}
    base = {
        "availability": "available",
        "registry_url": listed,
        "final_url": listed,
        "page_state": "not_available",
        "note": "Website string recorded by the entity register. The page was not fetched.",
    }
    if skip_website:
        base["note"] = "Website string recorded by the entity register. Page fetch was disabled for this run."
        return base
    try:
        from .http_client import assert_public_http_url

        assert_public_http_url(listed)
    except Exception as exc:
        base["page_state"] = "blocked"
        base["note"] = f"Registry website was not fetched: {exc}"
        return base
    allowed, robots = _homepage_allowed(client, listed)
    if robots is not None:
        track(robots)
    if not allowed:
        base["page_state"] = "blocked"
        base["hit"] = _hit(robots) if robots is not None else None
        base["note"] = "robots.txt disallows the homepage. The register's website string is kept; page content is not."
        base["claim_span"] = "User-agent: * Disallow: /"
        return base
    fetched = track(client.get_text(listed, timeout=8, max_bytes=700_000, public_only=True))
    state = availability_for_http(fetched.status)
    base["hit"] = _hit(fetched)
    base["final_url"] = fetched.final_url or listed
    if state != "available":
        base["page_state"] = state
        base["note"] = fetched.error or "Registered website could not be fetched. The register's website string is kept."
        return base
    extracted = extract_page(fetched.text, str(parsed.get("organisation_number") or ""), fetched.final_url)
    if not extracted["verified"]:
        base["page_state"] = "ambiguous"
        base["note"] = "The registered page did not contain this organisation number, so its content was not published."
        base["claim_span"] = fetched.final_url
        return base
    base["page_state"] = "available"
    base["description"] = extracted["description"]
    base["social_links"] = extracted["social_links"]
    base["hiring_pages"] = extracted["hiring_pages"]
    base["news_pages"] = extracted["news_pages"]
    base["claim_span"] = extracted["claim_span"] or f"organisation number {parsed.get('organisation_number')}"
    base["note"] = "Organisation number found on the page."
    return base


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
