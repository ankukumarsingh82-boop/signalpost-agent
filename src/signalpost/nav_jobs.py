"""NAV Arbeidsplassen public feed, matched by employer organisation number.

Terms: the public feed is free to use with agreement to NAV's terms. The public
token is experimental and rotates; this module fetches it at runtime and does
not hard-code it. Inactive ads are not stored. Contact details on ads are never
copied into claims. Consumers filter the feed themselves. Finn.no ads are not
in this feed.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from typing import Any

from .http_client import HttpClient

FEED_ORIGIN = "https://pam-stilling-feed.nav.no"
PUBLIC_TOKEN_URL = FEED_ORIGIN + "/api/publicToken"
FEED_URL = FEED_ORIGIN + "/api/v1/feed"


def normalize_name(value: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9æøå]+", str(value or "").casefold()))


def _token(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip().strip('"')
        if candidate.startswith("eyJ") and candidate.count(".") == 2:
            return candidate
    return None


def _absolute(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        url = "/" + url
    return FEED_ORIGIN + url


def build_nav_catalog(client: HttpClient, *, days: int = 30, max_pages: int = 220) -> dict[str, Any]:
    """Walk recent feed pages and index active ads by employer name.

    The list payload has no organisation number. Detail fetches happen later,
    and only for names that match a researched company. A posting is published
    only when the detail's employer.orgnr equals that company.
    """
    token_fetch = client.get_text(PUBLIC_TOKEN_URL, timeout=20, max_bytes=20_000, public_only=True)
    token = _token(token_fetch.text)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base: dict[str, Any] = {
        "by_name": {},
        "token": token,
        "since": since.date().isoformat(),
        "days": days,
        "pages": 0,
        "active_stubs": 0,
        "capped": False,
        "error": None,
        "feed_url": FEED_URL,
        "retrieved_at": token_fetch.retrieved_at,
    }
    if not token_fetch.ok or not token:
        base["error"] = token_fetch.error or "NAV public token was not in the response."
        return base
    headers = {
        "Authorization": f"Bearer {token}",
        "If-Modified-Since": formatdate(since.timestamp(), usegmt=True),
    }
    url = FEED_URL
    seen: set[str] = set()
    by_name: dict[str, list[dict[str, str]]] = {}
    while url and base["pages"] < max_pages:
        fetched = client.get_json(url, headers=headers, timeout=40, max_bytes=3_000_000, public_only=True)
        if not fetched.ok or not isinstance(fetched.json_body, dict):
            if base["pages"] == 0:
                base["error"] = fetched.error or f"NAV feed returned HTTP {fetched.status}."
            break
        items = fetched.json_body.get("items") or []
        if not isinstance(items, list):
            break
        base["pages"] += 1
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = item.get("_feed_entry") if isinstance(item.get("_feed_entry"), dict) else {}
            if entry.get("status") != "ACTIVE":
                continue
            uuid = str(item.get("id") or entry.get("uuid") or "")
            if not uuid or uuid in seen:
                continue
            seen.add(uuid)
            business = str(entry.get("businessName") or "")
            key = normalize_name(business)
            if not key:
                continue
            bucket = by_name.setdefault(key, [])
            if len(bucket) >= 25:
                continue
            bucket.append(
                {
                    "uuid": uuid,
                    "detail_url": _absolute(str(item.get("url") or f"/api/v1/feedentry/{uuid}")),
                    "title": str(entry.get("title") or item.get("title") or "")[:180],
                    "business_name": business[:180],
                    "municipal": str(entry.get("municipal") or ""),
                    "modified": str(entry.get("sistEndret") or item.get("date_modified") or ""),
                }
            )
            base["active_stubs"] += 1
        next_url = fetched.json_body.get("next_url")
        if not next_url or not isinstance(next_url, str):
            break
        nxt = _absolute(next_url)
        if nxt == url:
            break
        url = nxt
        headers = {"Authorization": f"Bearer {token}"}
    else:
        base["capped"] = True
    if base["pages"] >= max_pages:
        base["capped"] = True
    base["by_name"] = by_name
    base["note"] = (
        f"Public Arbeidsplassen feed modified since {base['since']} "
        f"({base['pages']} pages, {base['active_stubs']} active ads indexed by employer name"
        + (", page cap reached" if base["capped"] else "")
        + ")."
    )
    return base


def _digits(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _public_url(ad: dict[str, Any], uuid: str) -> str:
    link = ad.get("link")
    if isinstance(link, str) and link.startswith("https://arbeidsplassen.nav.no/"):
        return link
    return f"https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}"


def match_nav_jobs(
    client: HttpClient,
    track: Any,
    catalog: dict[str, Any] | None,
    org: str,
    parsed: dict[str, Any] | None,
) -> dict[str, Any]:
    if catalog is None:
        return {"availability": "not_available", "note": "NAV feed was not scanned in this run.", "errors": []}
    if catalog.get("error"):
        return {
            "availability": "failed",
            "note": catalog["error"],
            "errors": [{"url": catalog.get("feed_url") or FEED_URL, "status": None, "error": catalog["error"]}],
        }
    if not parsed or not parsed.get("name"):
        return {"availability": "not_available", "note": "No confirmed legal name, so job ads were not matched.", "errors": []}
    stubs = (catalog.get("by_name") or {}).get(normalize_name(parsed.get("name"))) or []
    note = catalog.get("note") or "NAV feed scanned."
    if not stubs:
        return {
            "availability": "not_available",
            "note": f"No active ad in the scanned feed used this legal name. {note}",
            "checked": True,
            "errors": [],
        }
    token = catalog.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    matches: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stub in stubs[:20]:
        fetched = track(client.get_json(stub["detail_url"], headers=headers, timeout=15, max_bytes=1_500_000, public_only=True))
        if not fetched.ok or not isinstance(fetched.json_body, dict):
            errors.append({"url": stub["detail_url"], "status": fetched.status, "error": fetched.error or "nav_detail_failed"})
            continue
        detail = fetched.json_body
        if detail.get("status") != "ACTIVE":
            continue
        ad = detail.get("ad_content") if isinstance(detail.get("ad_content"), dict) else {}
        employer = ad.get("employer") if isinstance(ad.get("employer"), dict) else {}
        if _digits(employer.get("orgnr")) != org:
            continue
        uuid = str(detail.get("uuid") or stub["uuid"])
        if uuid in seen:
            continue
        seen.add(uuid)
        locations = ad.get("workLocations") if isinstance(ad.get("workLocations"), list) else []
        municipal = None
        if locations and isinstance(locations[0], dict):
            municipal = locations[0].get("municipal") or locations[0].get("city")
        title = ad.get("title") or stub.get("title") or "Stilling"
        matches.append(
            {
                "title": str(title)[:200],
                "published_at": ad.get("published"),
                "expires_at": ad.get("expires"),
                "municipality": municipal,
                "url": _public_url(ad, uuid),
                "employer_orgnr": org,
            }
        )
        hits.append(
            {
                "url": stub["detail_url"],
                "final_url": fetched.final_url,
                "retrieved_at": fetched.retrieved_at,
                "content_sha256": fetched.content_sha256,
                "error": None,
                "span": f"{title} employer.orgnr {org}",
            }
        )
    if not matches:
        return {
            "availability": "not_available",
            "note": f"Feed name candidates did not carry organisation number {org}. {note}",
            "checked": True,
            "errors": errors,
        }
    published = matches[:15]
    return {
        "availability": "available",
        "postings": published,
        "matched_count": len(matches),
        "truncated": len(matches) > 15 or len(stubs) >= 25,
        "hits": hits[:15],
        "note": f"Active ads whose employer.orgnr equals this organisation number. {note} Contact details were not stored.",
        "errors": errors,
    }
