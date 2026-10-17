"""Batch Wikidata lookup by Norwegian organisation number (P2333)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from .http_client import HttpClient

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
LANGUAGE_RANK = {"nb": 0, "nn": 1, "en": 2, "no": 3}


def _query(orgs: list[str]) -> str:
    values = " ".join(f'"{org}"' for org in orgs)
    return f"""
SELECT ?org ?item ?itemLabel ?desc ?article ?articleLang WHERE {{
  VALUES ?org {{ {values} }}
  ?item wdt:P2333 ?org .
  OPTIONAL {{
    ?item schema:description ?desc .
    FILTER(LANG(?desc) IN ("nb", "nn", "en", "no"))
  }}
  OPTIONAL {{
    ?article schema:about ?item ;
             schema:isPartOf ?wiki .
    ?wiki wikibase:wikiGroup "wikipedia" .
    BIND(STRBEFORE(STRAFTER(STR(?wiki), "https://"), ".wikipedia.org/") AS ?articleLang)
    FILTER(?articleLang IN ("nb", "nn", "en", "no"))
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nb,nn,en". }}
}}
""".strip()


def _prefer(current: str | None, candidate: str | None, current_lang: str | None, candidate_lang: str | None) -> tuple[str | None, str | None]:
    if not candidate:
        return current, current_lang
    if not current:
        return candidate, candidate_lang
    current_rank = LANGUAGE_RANK.get(current_lang or "", 9)
    candidate_rank = LANGUAGE_RANK.get(candidate_lang or "", 9)
    if candidate_rank < current_rank:
        return candidate, candidate_lang
    return current, current_lang


def parse_sparql(payload: Any, requested: set[str]) -> dict[str, dict[str, Any]]:
    bindings = []
    if isinstance(payload, dict):
        bindings = ((payload.get("results") or {}).get("bindings")) or []
    found: dict[str, dict[str, Any]] = {}
    for row in bindings:
        if not isinstance(row, dict):
            continue
        org = ((row.get("org") or {}).get("value") or "").strip()
        if org not in requested:
            continue
        item = (row.get("item") or {}).get("value")
        label = (row.get("itemLabel") or {}).get("value")
        desc = (row.get("desc") or {}).get("value")
        desc_lang = (row.get("desc") or {}).get("xml:lang")
        article = (row.get("article") or {}).get("value")
        article_lang = (row.get("articleLang") or {}).get("value")
        slot = found.setdefault(
            org,
            {"item": item, "label": label, "description": None, "description_lang": None, "article_url": None, "article_lang": None},
        )
        if item and not slot.get("item"):
            slot["item"] = item
        if label and label != org and not slot.get("label"):
            slot["label"] = label
        description, description_lang = _prefer(slot.get("description"), desc, slot.get("description_lang"), desc_lang)
        slot["description"] = description
        slot["description_lang"] = description_lang
        article_url, chosen_lang = _prefer(slot.get("article_url"), article, slot.get("article_lang"), article_lang)
        slot["article_url"] = article_url
        slot["article_lang"] = chosen_lang
    for slot in found.values():
        slot.pop("description_lang", None)
        slot.pop("article_lang", None)
    return found


def fetch_wikidata(client: HttpClient, orgs: list[str], *, batch_size: int = 25) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    unique = list(dict.fromkeys(orgs))
    for start in range(0, len(unique), batch_size):
        batch = unique[start : start + batch_size]
        query = _query(batch)
        url = SPARQL_ENDPOINT + "?query=" + quote(query)
        fetched = client.get_json(url, timeout=60)
        if not fetched.ok or not isinstance(fetched.json_body, dict):
            continue
        parsed = parse_sparql(fetched.json_body, set(batch))
        for row in parsed.values():
            row["source_url"] = row.get("item") or url
            row["retrieved_at"] = fetched.retrieved_at
            row["content_sha256"] = fetched.content_sha256
            row["query_url"] = url
        found.update(parsed)
    return found


def wikipedia_title(article_url: str) -> tuple[str, str] | None:
    if "wikipedia.org/wiki/" not in article_url:
        return None
    head, title = article_url.split("/wiki/", 1)
    if "://" not in head:
        return None
    host = head.split("://", 1)[1]
    if not host.endswith("wikipedia.org"):
        return None
    return host, title
