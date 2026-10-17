"""Dated news from Google News RSS. Publish only on a strict identity match.

The RSS item is the evidence. Article bodies are not fetched.
"""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

from .http_client import HttpClient, utc_now
from .parse_website import organisation_number_pattern

LEGAL_FORMS = {"as", "asa", "sa", "ba", "da", "ans", "enk", "nuf", "sti", "iks", "fkf", "sf", "hf", "rhf"}
_PREDECESSORS = {"av", "for", "fra", "hos", "i", "med", "om", "på", "til", "og", "kjøper", "velger"}


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9æøå]+", (value or "").casefold())


def strip_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value or "").split())


def exact_legal_name_match(company_name: str, text: str) -> bool:
    """Full legal name as its own token sequence, including the legal form."""
    company_tokens = _tokens(company_name)
    text_tokens = _tokens(text.rsplit(" - ", 1)[0] if " - " in text else text)
    if not company_tokens or not text_tokens or len(company_tokens) > len(text_tokens):
        return False
    distinctive = [token for token in company_tokens if token not in LEGAL_FORMS]
    if len("".join(distinctive)) < 4:
        return False
    for index in range(len(text_tokens) - len(company_tokens) + 1):
        if text_tokens[index : index + len(company_tokens)] != company_tokens:
            continue
        if index == 0 or text_tokens[index - 1] in _PREDECESSORS:
            return True
    return False


def municipality_in_text(municipality: str, text: str) -> bool:
    wanted = _tokens(municipality)
    found = _tokens(text)
    if not wanted or not found:
        return False
    for index in range(len(found) - len(wanted) + 1):
        if found[index : index + len(wanted)] == wanted:
            return True
    return False


def _without_legal_name(legal_name: str, text: str) -> str:
    name_tokens = _tokens(legal_name)
    text_tokens = _tokens(text)
    if not name_tokens:
        return text
    kept: list[str] = []
    index = 0
    width = len(name_tokens)
    while index < len(text_tokens):
        if text_tokens[index : index + width] == name_tokens:
            index += width
            continue
        kept.append(text_tokens[index])
        index += 1
    return " ".join(kept)


def news_match(org: str, legal_name: str, municipality: str | None, title: str, description: str) -> str | None:
    """Return the match method, or None when the item must not be published."""
    blob = f"{title}\n{description}"
    if organisation_number_pattern(org).search(blob):
        return "organisation_number"
    if not municipality or not str(municipality).strip():
        return None
    if not (exact_legal_name_match(legal_name, title) or exact_legal_name_match(legal_name, description)):
        return None
    # The municipality has to appear apart from the legal name itself.
    # "SANDNES ELEKTRISKE AS" must not count as the place Sandnes.
    outside = _without_legal_name(legal_name, title) + " " + _without_legal_name(legal_name, description)
    if municipality_in_text(municipality, outside):
        return "name_and_municipality"
    return None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone().isoformat().replace("+00:00", "Z")


def google_news_url(legal_name: str) -> str:
    query = quote(f'"{legal_name}"')
    return f"https://news.google.com/rss/search?q={query}&hl=no&gl=NO&ceid=NO:no"


def parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = strip_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        description = strip_html(item.findtext("description") or "")
        published = (item.findtext("pubDate") or "").strip()
        source = item.find("source")
        publisher = strip_html(source.text or "") if source is not None and source.text else ""
        if title and link:
            items.append(
                {
                    "title": title,
                    "link": link,
                    "description": description,
                    "published_raw": published,
                    "publisher": publisher,
                }
            )
    return items


def select_news_items(
    xml_text: str,
    *,
    org: str,
    legal_name: str,
    municipality: str | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parse_rss_items(xml_text):
        method = news_match(org, legal_name, municipality, item["title"], item["description"])
        if not method:
            continue
        published_at = _parse_date(item["published_raw"])
        if not published_at:
            continue
        key = item["title"].casefold()
        if key in seen:
            continue
        seen.add(key)
        accepted.append(
            {
                "title": item["title"][:240],
                "url": item["link"],
                "published_at": published_at,
                "publisher": item["publisher"] or None,
                "match": method,
            }
        )
        if len(accepted) >= limit:
            break
    return accepted


def research_news(client: HttpClient, track: Any, parsed: dict[str, Any] | None, *, skip: bool) -> dict[str, Any]:
    if skip:
        return {"availability": "not_available", "note": "News lookup was disabled for this run.", "errors": []}
    if not parsed or not parsed.get("name"):
        return {"availability": "not_available", "note": "No confirmed legal name, so news was not searched.", "errors": []}
    address = parsed.get("business_address") if isinstance(parsed.get("business_address"), dict) else {}
    municipality = address.get("municipality") if isinstance(address, dict) else None
    url = google_news_url(str(parsed["name"]))
    fetched = track(client.get_text(url, accept="application/rss+xml, application/xml, text/xml", timeout=12, max_bytes=1_500_000, public_only=True, retries=1))
    errors: list[dict[str, Any]] = []
    if not fetched.ok:
        errors.append({"url": url, "status": fetched.status, "error": fetched.error or "news_rss_failed"})
        state = "blocked" if fetched.status in {401, 403, 429} else "failed"
        return {
            "availability": state,
            "note": fetched.error or "Google News RSS could not be fetched.",
            "hit": {
                "url": fetched.url,
                "final_url": fetched.final_url,
                "status": fetched.status,
                "retrieved_at": fetched.retrieved_at,
                "content_sha256": fetched.content_sha256,
                "error": fetched.error,
            },
            "errors": errors,
        }
    items = select_news_items(
        fetched.text,
        org=str(parsed.get("organisation_number") or ""),
        legal_name=str(parsed.get("name") or ""),
        municipality=str(municipality) if municipality else None,
    )
    hit = {
        "url": fetched.url,
        "final_url": fetched.final_url,
        "status": fetched.status,
        "retrieved_at": fetched.retrieved_at or utc_now(),
        "content_sha256": fetched.content_sha256,
        "error": None,
    }
    if not items:
        return {
            "availability": "not_available",
            "note": "The RSS feed was fetched. No item contained this organisation number, or the exact legal name together with the registered municipality.",
            "hit": hit,
            "items": [],
            "errors": [],
        }
    return {
        "availability": "available",
        "note": "Google News RSS item. The article body was not fetched. Accepted only on an organisation number, or the exact legal name plus the registered municipality.",
        "hit": hit,
        "items": items,
        "errors": [],
    }
