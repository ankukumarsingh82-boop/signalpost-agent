"""Build one terminal envelope. Absent facts stay null; they are never written as zero."""

from __future__ import annotations

from typing import Any

from .domains import unpublishable_reason
from .http_client import normalize_website
from .synthesize import synthesize

ALLOWED_AVAILABILITY = {
    "available",
    "not_available",
    "blocked",
    "not_applicable",
    "ambiguous",
    "failed",
}

FIGURE_KEYS = (
    "revenue",
    "operating_result",
    "profit_before_tax",
    "annual_result",
    "assets",
    "equity",
    "debt",
)


class EnvelopeBuilder:
    def __init__(self, org: str) -> None:
        self.org = org
        self.evidence: list[dict[str, Any]] = []
        self.claims: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self._n = 0

    def add_evidence(
        self,
        *,
        source_url: str,
        source_class: str,
        retrieved_at: str,
        content_sha256: str,
        claim_span: str,
    ) -> str:
        self._n += 1
        evidence_id = f"ev-{self.org}-{self._n}"
        self.evidence.append(
            {
                "id": evidence_id,
                "source_url": source_url,
                "source_class": source_class,
                "retrieved_at": retrieved_at,
                "content_sha256": content_sha256,
                "claim_span": (claim_span or "")[:400],
            }
        )
        return evidence_id

    def add_claim(
        self,
        field: str,
        value: Any,
        availability: str,
        evidence_ids: list[str],
        *,
        confidence: float,
        note: str | None = None,
        as_of: str | None = None,
    ) -> None:
        if availability not in ALLOWED_AVAILABILITY:
            raise ValueError(f"invalid availability {availability}")
        original = field
        if field in self._seen:
            suffix = 2
            while f"{original}#{suffix}" in self._seen:
                suffix += 1
            field = f"{original}#{suffix}"
        self._seen.add(field)
        claim: dict[str, Any] = {
            "field": field,
            "value": value if availability == "available" else None,
            "availability": availability,
            "confidence": round(float(confidence), 2),
            "evidence_ids": evidence_ids,
        }
        if note:
            claim["note"] = note
        if as_of and availability == "available":
            claim["as_of"] = as_of
        self.claims.append(claim)


def _hit_evidence(builder: EnvelopeBuilder, hit: dict[str, Any] | None, source_class: str, span: str) -> list[str]:
    if not hit:
        return []
    return [
        builder.add_evidence(
            source_url=hit.get("final_url") or hit["url"],
            source_class=source_class,
            retrieved_at=hit["retrieved_at"],
            content_sha256=hit["content_sha256"],
            claim_span=span or hit.get("error") or "",
        )
    ]


def _maybe(builder: EnvelopeBuilder, field: str, value: Any, evidence_ids: list[str], *, confidence: float, as_of: str | None = None, note: str | None = None) -> None:
    if value is None or value == [] or value == {}:
        builder.add_claim(field, None, "not_available", evidence_ids, confidence=confidence, note=note or "The source response did not include this field.")
        return
    builder.add_claim(field, value, "available", evidence_ids, confidence=confidence, as_of=as_of, note=note)


def _account_claim_value(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_type": record.get("account_type"),
        "period_from": record.get("period_from"),
        "period_to": record.get("period_to"),
        "currency": record.get("currency"),
        "record_id": record.get("record_id"),
        "figures": record.get("figures") or {},
    }


def build_envelope(org: str, research: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    builder = EnvelopeBuilder(org)
    entity = research.get("entity") or {}
    entity_hit = entity.get("hit")
    entity_state = entity.get("availability") or "failed"
    parsed = entity.get("parsed") if entity_state == "available" else None
    entity_span = ""
    if parsed and parsed.get("name"):
        entity_span = f"{parsed['name']} organisasjonsnummer {org}"
    elif entity_hit:
        entity_span = entity_hit.get("error") or f"enhetsregisteret {org}"
    entity_ids = _hit_evidence(builder, entity_hit, "official_registry", entity_span)

    if entity_state != "available" or not parsed:
        note = "Brønnøysund returned no entity for this organisation number." if entity_state == "not_available" else (entity.get("note") or "Entity register request did not succeed.")
        for field in (
            "legal_name",
            "legal_form",
            "organisation_status",
            "business_address",
            "industry",
            "employee_count",
            "founding_date",
            "registry_listed_website",
        ):
            builder.add_claim(field, None, entity_state if entity_state in ALLOWED_AVAILABILITY else "failed", entity_ids, confidence=0.0, note=note)
    else:
        legal_form = None
        if parsed.get("legal_form") or parsed.get("legal_form_code"):
            legal_form = {"code": parsed.get("legal_form_code"), "label": parsed.get("legal_form")}
        status = {
            key: parsed[key]
            for key in ("bankrupt", "liquidating", "compulsory_liquidation")
            if parsed.get(key) is not None
        }
        _maybe(builder, "legal_name", parsed.get("name"), entity_ids, confidence=0.99)
        _maybe(builder, "legal_form", legal_form, entity_ids, confidence=0.99)
        _maybe(builder, "organisation_status", status or None, entity_ids, confidence=0.99)
        _maybe(builder, "business_address", parsed.get("business_address"), entity_ids, confidence=0.99)
        _maybe(builder, "postal_address", parsed.get("postal_address"), entity_ids, confidence=0.99)
        municipality = None
        if parsed.get("business_address") and parsed["business_address"].get("municipality"):
            municipality = {
                "name": parsed["business_address"].get("municipality"),
                "number": parsed["business_address"].get("municipality_number"),
            }
        _maybe(builder, "municipality", municipality, entity_ids, confidence=0.99)
        _maybe(builder, "industry", parsed.get("industry"), entity_ids, confidence=0.99)
        _maybe(builder, "additional_industries", parsed.get("additional_industries") or None, entity_ids, confidence=0.99)
        if parsed.get("employees_registered") is False:
            builder.add_claim(
                "employee_count",
                None,
                "not_available",
                entity_ids,
                confidence=0.99,
                note="The entity register has not published an employee count. Brønnøysund hides the 0–4 employee band, so this is not zero.",
            )
        else:
            _maybe(builder, "employee_count", parsed.get("employees"), entity_ids, confidence=0.99)
        _maybe(builder, "founding_date", parsed.get("founding_date"), entity_ids, confidence=0.99, as_of=parsed.get("founding_date"))
        _maybe(builder, "entity_register_date", parsed.get("entity_register_date"), entity_ids, confidence=0.99, as_of=parsed.get("entity_register_date"))
        _maybe(builder, "vat_registered", parsed.get("vat_registered"), entity_ids, confidence=0.99)
        _maybe(builder, "foretaksregister_registered", parsed.get("foretaksregister_registered"), entity_ids, confidence=0.99)
        _maybe(builder, "share_capital", parsed.get("share_capital"), entity_ids, confidence=0.99)
        _maybe(builder, "statutory_purpose", parsed.get("statutory_purpose") or None, entity_ids, confidence=0.99)
        _maybe(builder, "registered_activity", parsed.get("registered_activity") or None, entity_ids, confidence=0.99)
        _maybe(builder, "historical_names", parsed.get("historical_names") or None, entity_ids, confidence=0.99)
        _maybe(builder, "telephone", parsed.get("telephone"), entity_ids, confidence=0.99)
        _maybe(builder, "in_corporate_group", parsed.get("in_corporate_group"), entity_ids, confidence=0.99)
        _maybe(
            builder,
            "latest_submitted_accounts_year",
            parsed.get("latest_submitted_accounts_year"),
            entity_ids,
            confidence=0.99,
            as_of=str(parsed.get("latest_submitted_accounts_year")) if parsed.get("latest_submitted_accounts_year") else None,
        )
        _maybe(builder, "institutional_sector", parsed.get("institutional_sector"), entity_ids, confidence=0.99)

    _add_accounts(builder, research.get("accounts") or {}, entity_state)
    _add_roles(builder, research.get("roles") or {}, entity_state)
    _add_workplaces(builder, research.get("workplaces") or {}, entity_state)
    _add_group(builder, research.get("group") or {}, entity_state)
    website_module = research.get("website") or {}
    if parsed:
        _add_registry_website(builder, website_module, entity_ids)
    _add_website(builder, website_module)
    _add_jobs(builder, research.get("jobs") or {})
    _add_news(builder, research.get("news") or {})
    _add_wiki(builder, research.get("wiki") or {})

    operations = research.get("operations") or {}
    envelope: dict[str, Any] = {
        "organisation_number": org,
        "run": {
            "run_id": run["run_id"],
            "started_at": run["started_at"],
            "completed_at": run["completed_at"],
            "terminal_status": "completed" if research.get("terminal_status") != "failed" else "failed",
        },
        "claims": builder.claims,
        "evidence": builder.evidence,
        "changes": [],
        "errors": list(research.get("errors") or []),
        "operations": {
            "requests": int(operations.get("requests") or 0),
            "runtime_ms": int(operations.get("runtime_ms") or 0),
            "third_party_cost_usd": 0,
        },
    }
    _attach_synthesis(envelope, previous_supplied=False)
    return envelope


def _skip_module(builder: EnvelopeBuilder, fields: list[str], state: str, note: str, hit: dict[str, Any] | None, source_class: str) -> None:
    evidence_ids = _hit_evidence(builder, hit, source_class, note) if hit else []
    for field in fields:
        builder.add_claim(field, None, state, evidence_ids, confidence=0.0, note=note)


def _add_accounts(builder: EnvelopeBuilder, module: dict[str, Any], entity_state: str) -> None:
    state = module.get("availability")
    if entity_state == "not_available":
        state = "not_available"
    if state != "available":
        _skip_module(
            builder,
            ["annual_accounts", "latest_entity_accounts"],
            state or "not_available",
            module.get("note") or "Annual accounts were not available.",
            module.get("hit"),
            "official_accounts",
        )
        return
    parsed = module.get("parsed") or {}
    records = parsed.get("records") or []
    hit = module.get("hit")
    span = f"regnskap {builder.org} records {len(records)}"
    evidence_ids = _hit_evidence(builder, hit, "official_accounts", span)
    if not records:
        builder.add_claim("annual_accounts", None, "not_available", evidence_ids, confidence=0.99, note="The accounts endpoint returned no records. Missing figures are not zero.")
        builder.add_claim("latest_entity_accounts", None, "not_available", evidence_ids, confidence=0.99, note="No entity accounts record was returned.")
        return
    builder.add_claim(
        "annual_accounts",
        {"record_count": len(records), "truncated": bool(parsed.get("truncated"))},
        "available",
        evidence_ids,
        confidence=0.99,
    )
    entity_records = [record for record in records if record.get("account_type") == "SELSKAP"] or records
    latest = entity_records[0]
    builder.add_claim(
        "latest_entity_accounts",
        _account_claim_value(latest),
        "available",
        evidence_ids,
        confidence=0.99,
        as_of=latest.get("period_to"),
    )
    group_records = [record for record in records if record.get("account_type") == "KONSERN"]
    if group_records:
        builder.add_claim(
            "latest_group_accounts",
            _account_claim_value(group_records[0]),
            "available",
            evidence_ids,
            confidence=0.99,
            as_of=group_records[0].get("period_to"),
            note="Group accounts are not the legal entity's own accounts.",
        )
    for record in records:
        period = (record.get("period_to") or "undated")[:4]
        account_type = record.get("account_type") or "UNKNOWN"
        for key in FIGURE_KEYS:
            figure = (record.get("figures") or {}).get(key)
            if figure is None:
                continue
            builder.add_claim(
                f"accounts.{account_type}.{period}.{key}",
                figure,
                "available",
                evidence_ids,
                confidence=0.99,
                as_of=record.get("period_to"),
            )


def _add_roles(builder: EnvelopeBuilder, module: dict[str, Any], entity_state: str) -> None:
    state = "not_available" if entity_state == "not_available" else module.get("availability")
    if state != "available":
        _skip_module(builder, ["leadership"], state or "not_available", module.get("note") or "Roles were not available.", module.get("hit"), "official_registry")
        return
    parsed = module.get("parsed") or {}
    roles = parsed.get("roles") or []
    evidence_ids = _hit_evidence(builder, module.get("hit"), "official_registry", f"roller {builder.org}")
    if not roles:
        builder.add_claim("leadership", None, "not_available", evidence_ids, confidence=0.99, note="The roles endpoint returned no role holders.")
        return
    active = [role for role in roles if not role.get("inactive")]
    builder.add_claim(
        "leadership",
        {"active_count": len(active), "returned_count": parsed.get("returned_count"), "truncated": bool(parsed.get("truncated"))},
        "available",
        evidence_ids,
        confidence=0.99,
    )
    used: set[str] = set()
    for role in roles:
        code = role.get("role_code") or role.get("group_code") or "role"
        name = role.get("name") or role.get("holder_organisation_number") or "unknown"
        slug = "".join(character.lower() if character.isalnum() else "-" for character in str(name)).strip("-")
        slug = "-".join(part for part in slug.split("-") if part)[:48] or "unknown"
        field = f"role.{code}.{slug}"
        if field in used:
            suffix = 2
            while f"{field}-{suffix}" in used:
                suffix += 1
            field = f"{field}-{suffix}"
        used.add(field)
        builder.add_claim(field, role, "available", evidence_ids, confidence=0.99, as_of=role.get("last_changed"))


def _add_workplaces(builder: EnvelopeBuilder, module: dict[str, Any], entity_state: str) -> None:
    state = "not_available" if entity_state == "not_available" else module.get("availability")
    if state != "available":
        _skip_module(
            builder,
            ["registered_workplaces"],
            state or "not_available",
            module.get("note") or "Registered workplaces were not available.",
            module.get("hit"),
            "official_registry",
        )
        return
    parsed = module.get("parsed") or {}
    evidence_ids = _hit_evidence(builder, module.get("hit"), "official_registry", f"underenheter {builder.org}")
    total = parsed.get("total")
    workplaces = parsed.get("workplaces") or []
    builder.add_claim(
        "registered_workplaces",
        {"total": total, "truncated": bool(parsed.get("truncated")), "workplaces": workplaces},
        "available",
        evidence_ids,
        confidence=0.99,
        note="Count comes from the register page total, including when that total is zero.",
    )
    for workplace in workplaces:
        sub = workplace.get("organisation_number")
        if not sub:
            continue
        builder.add_claim(f"workplace.{sub}", workplace, "available", evidence_ids, confidence=0.99)


def _add_group(builder: EnvelopeBuilder, module: dict[str, Any], entity_state: str) -> None:
    state = module.get("availability")
    if entity_state == "not_available":
        state = "not_available"
    if state == "not_applicable":
        builder.add_claim(
            "group_structure",
            None,
            "not_applicable",
            _hit_evidence(builder, module.get("hit"), "official_registry", "erIKonsern false"),
            confidence=0.99,
            note="The entity register says this organisation is not part of a corporate group.",
        )
        return
    if state != "available":
        _skip_module(builder, ["group_structure"], state or "not_available", module.get("note") or "Group structure was not available.", module.get("hit"), "official_registry")
        return
    parsed = module.get("parsed") or {}
    evidence_ids = _hit_evidence(builder, module.get("hit"), "official_registry", f"konsernstruktur {builder.org}")
    if not parsed.get("matched"):
        builder.add_claim("group_structure", None, "not_available", evidence_ids, confidence=0.8, note="The group payload did not contain this organisation number.")
        return
    builder.add_claim(
        "group_structure",
        {
            "parent": parsed.get("parent"),
            "direct_subsidiary_count": parsed.get("direct_subsidiary_count"),
            "truncated": bool(parsed.get("truncated")),
        },
        "available",
        evidence_ids,
        confidence=0.99,
    )
    if parsed.get("parent"):
        builder.add_claim("group_parent", parsed["parent"], "available", evidence_ids, confidence=0.99, note="Parent in the official group tree. Not merged into this company's own accounts.")
    for subsidiary in parsed.get("direct_subsidiaries") or []:
        sub = subsidiary.get("organisation_number")
        if not sub:
            continue
        builder.add_claim(f"subsidiary.{sub}", subsidiary, "available", evidence_ids, confidence=0.99, as_of=subsidiary.get("as_of"))


def _add_registry_website(builder: EnvelopeBuilder, module: dict[str, Any], entity_ids: list[str]) -> None:
    """Publish the register URL only when the same site was verified.

    An unverified register host is a common wrong-company fact, so the URL stays null.
    """
    raw = module.get("registry_url")
    normalized = normalize_website(str(raw).strip()) if raw else None
    verified = bool(module.get("verified")) and module.get("availability") == "available"
    if not normalized:
        builder.add_claim(
            "registry_listed_website",
            None,
            "not_available",
            entity_ids,
            confidence=0.9,
            note="The entity register has no website for this organisation.",
        )
        return
    if unpublishable_reason(normalized):
        builder.add_claim(
            "registry_listed_website",
            None,
            "ambiguous",
            entity_ids,
            confidence=0.9,
            note="The entity register stores a website on a shared or directory domain. The URL is not published.",
        )
        return
    if not verified:
        builder.add_claim(
            "registry_listed_website",
            None,
            "ambiguous",
            entity_ids,
            confidence=0.9,
            note="The entity register stores a website that this run did not verify. The URL is not published.",
        )
        return
    builder.add_claim(
        "registry_listed_website",
        normalized,
        "available",
        entity_ids,
        confidence=0.9,
        note="Register website, published because a page on that host identified this organisation.",
    )


def _add_website(builder: EnvelopeBuilder, module: dict[str, Any]) -> None:
    state = module.get("availability") or "not_available"
    page_state = module.get("page_state") or "not_available"
    hit = module.get("hit")
    note = module.get("note")
    page_ids = _hit_evidence(builder, hit, "company_owned", module.get("claim_span") or note or "website") if hit else []
    if state != "available":
        builder.add_claim("official_website", None, state, page_ids, confidence=0.0, note=note or "Website was not available.")
        checked = state == "ambiguous" and bool(hit)
        if checked:
            verified_state = "available"
            verified_value: bool | None = False
            verified_note = note
        elif state in {"blocked", "failed"}:
            verified_state = state
            verified_value = None
            verified_note = note
        else:
            verified_state = "not_available"
            verified_value = None
            verified_note = note if state == "ambiguous" else "No registered website to check."
        builder.add_claim(
            "website_page_verified",
            verified_value,
            verified_state,
            page_ids,
            confidence=0.8 if checked else 0.0,
            note=verified_note,
        )
        for field in ("website_description", "company_profiles", "hiring_pages", "company_news_pages", "company_news_items"):
            builder.add_claim(field, None, "not_available" if state in {"not_available", "ambiguous", "blocked"} else state, page_ids, confidence=0.0, note="Not published without a verified company page.")
        return
    verified = bool(module.get("verified")) and page_state == "available" and state == "available"
    hits = module.get("hits") or ([hit] if hit else [])
    if hits:
        page_ids = []
        for item in hits[:5]:
            page_ids.extend(_hit_evidence(builder, item, "company_owned", module.get("claim_span") or note or "website"))
    if not verified:
        follow = state if state in ALLOWED_AVAILABILITY else "ambiguous"
        if follow == "available":
            follow = "ambiguous"
        builder.add_claim(
            "official_website",
            None,
            follow,
            page_ids,
            confidence=0.0,
            note=note or "The registered website was not verified, so it is not published as the official site.",
        )
        checked = page_state == "ambiguous"
        builder.add_claim(
            "website_page_verified",
            False if checked else None,
            "available" if checked else (page_state if page_state in ALLOWED_AVAILABILITY and page_state != "available" else "not_available"),
            page_ids,
            confidence=0.8 if checked else 0.0,
            note=note,
        )
        for field in ("website_description", "company_profiles", "hiring_pages", "company_news_pages", "company_news_items"):
            builder.add_claim(field, None, "not_available" if follow in {"ambiguous", "blocked", "not_available"} else follow, page_ids, confidence=0.0, note="Not published without a verified company page.")
        return
    method = module.get("verification_method") or "organisation_number"
    confidence = {
        "organisation_number": 0.95,
        "embedded_organisation_number": 0.9,
        "json_ld_organisation_number": 0.93,
        "json_ld_name_and_postcode": 0.88,
        "name_and_postcode": 0.86,
        "telephone": 0.8,
        "distinctive_name_token": 0.74,
    }.get(method, 0.74)
    builder.add_claim(
        "official_website",
        module.get("final_url"),
        "available",
        page_ids,
        confidence=confidence,
        note=note or "Verified company website.",
    )
    builder.add_claim(
        "website_page_verified",
        True,
        "available",
        page_ids,
        confidence=confidence,
        note=f"Verification method: {method}.",
    )
    if module.get("description"):
        builder.add_claim("website_description", module["description"], "available", page_ids, confidence=0.8, note="Company-owned description. Not an independent review.")
    else:
        builder.add_claim("website_description", None, "not_available", page_ids, confidence=0.8, note="No usable description on the verified page.")
    socials = module.get("social_links") or []
    if socials:
        for item in socials:
            builder.add_claim(
                f"company_profile.{item['platform']}",
                item["url"],
                "available",
                page_ids,
                confidence=0.85,
                note="Link published on the verified company site. The destination platform was not scraped.",
            )
    else:
        builder.add_claim("company_profiles", None, "not_available", page_ids, confidence=0.85, note="No social or video profile link was found on the verified page.")
    if module.get("hiring_pages"):
        builder.add_claim("hiring_pages", module["hiring_pages"], "available", page_ids, confidence=0.7, note="Links on the verified site. Individual vacancies were not asserted.")
    else:
        builder.add_claim("hiring_pages", None, "not_available", page_ids, confidence=0.7, note="The verified homepage did not link to a careers path. This is not zero open jobs.")
    if module.get("news_pages"):
        builder.add_claim("company_news_pages", module["news_pages"], "available", page_ids, confidence=0.7, note="Company-owned news or press links.")
    else:
        builder.add_claim("company_news_pages", None, "not_available", page_ids, confidence=0.7, note="No company news link was found on the verified pages.")
    dated = module.get("dated_news") or []
    if dated:
        builder.add_claim(
            "company_news_items",
            dated,
            "available",
            page_ids,
            confidence=0.7,
            note="Dated headlines from article blocks on the verified site. Not an independent news search.",
        )
    else:
        builder.add_claim("company_news_items", None, "not_available", page_ids, confidence=0.7, note="The verified pages had no dated article headlines.")


def _add_jobs(builder: EnvelopeBuilder, module: dict[str, Any]) -> None:
    state = module.get("availability") or "not_available"
    hits = module.get("hits") or []
    evidence_ids: list[str] = []
    for hit in hits:
        evidence_ids.extend(_hit_evidence(builder, hit, "nav_jobs", hit.get("span") or "arbeidsplassen"))
    if state != "available":
        builder.add_claim("job_postings", None, state, evidence_ids, confidence=0.0, note=module.get("note") or "No job ads were matched.")
        return
    builder.add_claim(
        "job_postings",
        {
            "source": "nav_arbeidsplassen",
            "matched_count": module.get("matched_count"),
            "truncated": bool(module.get("truncated")),
            "postings": module.get("postings") or [],
        },
        "available",
        evidence_ids,
        confidence=0.95,
        note=module.get("note") or "employer.orgnr is this organisation or one of its sub-units.",
    )


def _add_news(builder: EnvelopeBuilder, module: dict[str, Any]) -> None:
    state = module.get("availability") or "not_available"
    hit = module.get("hit")
    items = module.get("items") or []
    span = "; ".join(item.get("title", "") for item in items[:5])[:400] or module.get("note") or "google news rss"
    evidence_ids = _hit_evidence(builder, hit, "news_rss", span) if hit else []
    if state != "available":
        builder.add_claim("public_news", None, state, evidence_ids, confidence=0.0, note=module.get("note") or "No dated news item was accepted.")
        return
    builder.add_claim(
        "public_news",
        {"source": "google_news_rss", "items": items},
        "available",
        evidence_ids,
        confidence=0.72,
        note=module.get("note"),
    )


def _add_wiki(builder: EnvelopeBuilder, module: dict[str, Any]) -> None:
    state = module.get("availability") or "not_available"
    hit = module.get("hit")
    evidence_ids = _hit_evidence(builder, hit, "wikidata", module.get("claim_span") or "wikidata P2333") if hit else []
    if state != "available":
        builder.add_claim("wikidata_description", None, state, evidence_ids, confidence=0.0, note=module.get("note") or "No Wikidata item with this organisation number.")
        builder.add_claim("wikipedia_summary", None, "not_available", evidence_ids, confidence=0.0, note="No Wikipedia summary tied to this organisation number.")
        return
    if module.get("description"):
        builder.add_claim("wikidata_description", module["description"], "available", evidence_ids, confidence=0.9, note="Description of the Wikidata item whose P2333 equals this organisation number.")
    else:
        builder.add_claim("wikidata_description", None, "not_available", evidence_ids, confidence=0.9, note="The Wikidata item has no preferred description.")
    if module.get("label"):
        builder.add_claim("wikidata_label", module["label"], "available", evidence_ids, confidence=0.9)
    summary_hit = module.get("summary_hit")
    if module.get("summary") and summary_hit:
        summary_ids = _hit_evidence(builder, summary_hit, "wikipedia", module["summary"][:180])
        builder.add_claim(
            "wikipedia_summary",
            module["summary"],
            "available",
            summary_ids,
            confidence=0.85,
            as_of=module.get("summary_as_of"),
            note="Wikipedia extract for the article linked from the P2333 Wikidata item.",
        )
        if module.get("article_url"):
            builder.add_claim("wikipedia_url", module["article_url"], "available", summary_ids, confidence=0.9)
    else:
        builder.add_claim("wikipedia_summary", None, "not_available", evidence_ids, confidence=0.85, note="No Wikipedia extract was retrieved for the linked article.")


def _attach_synthesis(envelope: dict[str, Any], *, previous_supplied: bool) -> None:
    produced = synthesize(
        envelope["organisation_number"],
        envelope["claims"],
        envelope.get("changes") or [],
        previous_supplied=previous_supplied,
    )
    evidence_ids = produced["evidence_ids"]
    claims = [claim for claim in envelope["claims"] if claim.get("field") != "synthesis"]
    claims.append(
        {
            "field": "synthesis",
            "value": {
                "summary": produced["summary"],
                "what_changed": produced["what_changed"],
                "unknowns": produced["unknowns"],
            },
            "availability": "available",
            "confidence": 1.0,
            "evidence_ids": evidence_ids,
            "note": "Template summary of published claims only.",
        }
    )
    envelope["claims"] = claims
    envelope["synthesis"] = {
        "summary": produced["summary"],
        "what_changed": produced["what_changed"],
        "unknowns": produced["unknowns"],
        "evidence_ids": evidence_ids,
    }


def apply_refresh_metadata(envelope: dict[str, Any], refresh: dict[str, Any]) -> dict[str, Any]:
    envelope["changes"] = refresh["changes"]
    envelope["refresh"] = {
        "previous_supplied": refresh["previous_supplied"],
        "previous_run_id": refresh["previous_run_id"],
        "material_change_count": refresh["material_change_count"],
        "idempotent_rerun": refresh["idempotent_rerun"],
    }
    _attach_synthesis(envelope, previous_supplied=bool(refresh["previous_supplied"]))
    return envelope
