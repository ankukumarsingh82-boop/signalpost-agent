"""Template synthesis. It only restates claims that are already published."""

from __future__ import annotations

from typing import Any


def _by_field(claims: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {claim["field"]: claim for claim in claims}


def _available(claims_by_field: dict[str, dict[str, Any]], field: str) -> Any:
    claim = claims_by_field.get(field)
    if not claim or claim.get("availability") != "available":
        return None
    return claim.get("value")


def _money(figure: dict[str, Any] | None) -> str | None:
    if not isinstance(figure, dict) or figure.get("amount") is None:
        return None
    amount = figure["amount"]
    if isinstance(amount, float):
        rendered = f"{amount:,.0f}"
    else:
        rendered = f"{amount:,}"
    currency = figure.get("currency") or ""
    return f"{rendered} {currency}".strip()


def _address(value: dict[str, Any] | None) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = list(value.get("lines") or [])
    city = " ".join(part for part in (value.get("postal_code"), value.get("city")) if part)
    if city:
        parts.append(city)
    if value.get("municipality") and value.get("municipality") != value.get("city"):
        parts.append(str(value["municipality"]))
    return ", ".join(parts) if parts else None


def synthesize(org: str, claims: list[dict[str, Any]], changes: list[dict[str, Any]] | None, *, previous_supplied: bool) -> dict[str, Any]:
    by = _by_field(claims)
    name = _available(by, "legal_name") or "This entity"
    legal_form = _available(by, "legal_form")
    industry = _available(by, "industry")
    address = _address(_available(by, "business_address"))
    employees = _available(by, "employee_count")
    founded = _available(by, "founding_date")
    purpose = _available(by, "statutory_purpose")
    activity = _available(by, "registered_activity")
    latest = _available(by, "latest_entity_accounts")
    leader_claims = [
        claim
        for claim in claims
        if claim["field"].startswith("role.") and claim.get("availability") == "available" and not (claim.get("value") or {}).get("inactive")
    ]
    leaders = []
    for claim in leader_claims:
        value = claim.get("value") or {}
        if value.get("role_code") in {"DAGL", "LEDE", "INNH"} or value.get("group_code") in {"DAGL", "STYR"}:
            leaders.append(value)
        if len(leaders) >= 4:
            break
    if not leaders:
        leaders = [(claim.get("value") or {}) for claim in leader_claims[:3]]
    workplaces = _available(by, "registered_workplaces")
    website = _available(by, "official_website")
    page_verified = _available(by, "website_page_verified")
    listed_site = _available(by, "registry_listed_website")
    wiki = _available(by, "wikipedia_summary") or _available(by, "wikidata_description")
    hiring = _available(by, "hiring_pages")
    news = _available(by, "company_news_pages")
    status = _available(by, "organisation_status") or {}

    sentences: list[str] = []
    identity = f"{name} (organisation number {org})"
    if isinstance(legal_form, dict) and legal_form.get("label"):
        identity += f" is registered as {legal_form['label']}"
    elif isinstance(legal_form, str):
        identity += f" is registered as {legal_form}"
    else:
        identity += " was looked up in the Brønnøysund Register Centre"
    if address:
        identity += f", with registered business address {address}"
    sentences.append(identity + ".")

    if isinstance(industry, dict) and (industry.get("label") or industry.get("code")):
        sentences.append(
            f"The register classifies the industry as {industry.get('label') or 'unspecified'} (NACE {industry.get('code') or 'not stated'})."
        )
    if purpose:
        text = purpose[0] if isinstance(purpose, list) else str(purpose)
        text = text[:400].rstrip()
        if text and text[-1] not in ".!?":
            text += "."
        sentences.append(f"The registered statutory purpose says: {text}")
    elif activity:
        text = activity[0] if isinstance(activity, list) else str(activity)
        text = text[:400].rstrip()
        if text and text[-1] not in ".!?":
            text += "."
        sentences.append(f"The register describes the activity as: {text}")
    elif wiki:
        sentences.append(f"A Wikidata item carrying this organisation number describes it as: {str(wiki)[:400]}")

    if employees is not None:
        sentences.append(f"The register records {employees} employees.")
    if founded:
        sentences.append(f"Founding date recorded in the register: {founded}.")
    if status.get("bankrupt") is True:
        sentences.append("The register marks the entity as bankrupt.")
    elif status.get("liquidating") is True:
        sentences.append("The register marks the entity as under liquidation.")
    elif status.get("compulsory_liquidation") is True:
        sentences.append("The register marks the entity as under compulsory liquidation.")

    if isinstance(latest, dict) and latest.get("figures"):
        figures = latest["figures"]
        bits = []
        for label, key in (
            ("revenue", "revenue"),
            ("operating result", "operating_result"),
            ("annual result", "annual_result"),
            ("assets", "assets"),
            ("equity", "equity"),
            ("debt", "debt"),
        ):
            rendered = _money(figures.get(key))
            if rendered:
                bits.append(f"{label} {rendered}")
        if bits:
            period = latest.get("period_to") or "an undated period"
            account_type = latest.get("account_type") or "accounts"
            sentences.append(
                f"Latest {account_type} accounts for the period ending {period} report " + "; ".join(bits) + "."
            )

    if leaders:
        rendered = []
        for leader in leaders[:3]:
            who = leader.get("name") or leader.get("holder_organisation_number")
            role = leader.get("role") or leader.get("group") or "role"
            if who:
                rendered.append(f"{who} ({role})")
        if rendered:
            sentences.append("Registered roles include " + "; ".join(rendered) + ".")

    if isinstance(workplaces, dict):
        total = workplaces.get("total")
        if isinstance(total, int):
            sentences.append(f"The register lists {total} registered workplace{'s' if total != 1 else ''} (underenheter).")

    if website and page_verified is True:
        sentences.append(f"The official website {website} was accepted because the page contains organisation number {org}.")
    elif website:
        sentences.append(
            f"The register records the website as {website}. This run did not confirm organisation number {org} on that page, so page content was not published."
        )
    elif listed_site:
        sentences.append(
            f"The register lists {listed_site} as a website, but this run did not confirm organisation number {org} on that page, so site content was not published."
        )

    if hiring:
        sentences.append("The verified website links to a hiring or careers page.")
    if news:
        sentences.append("The verified website links to a news or press page.")

    unknowns: list[str] = []
    if employees is None:
        unknowns.append("No registered employee count was published by the entity register.")
    if not isinstance(latest, dict):
        unknowns.append("No normalized annual-account figures were returned. Missing figures are not treated as zero.")
    if not leaders:
        unknowns.append("No active public role holder was published.")
    if not isinstance(workplaces, dict):
        unknowns.append("Registered workplaces were not returned.")
    if not website:
        unknowns.append("No website was recorded or verified for this organisation number.")
    elif page_verified is not True:
        unknowns.append("The registered website was not confirmed by an organisation number on the page.")
    if not hiring:
        unknowns.append("No company-owned hiring page was verified in this run.")
    if not news and not wiki:
        unknowns.append("No dated public activity from a permitted source was verified in this run.")
    if not purpose and not activity and not wiki:
        unknowns.append("No registered purpose, activity description, or Wikipedia summary was found.")

    material = [change for change in (changes or []) if change.get("material")]
    if not previous_supplied:
        change_text = "No previous snapshot was supplied, so this run does not claim that anything changed."
    elif not material:
        change_text = "Compared with the previous snapshot, no material change was found."
    else:
        bits = []
        for change in material[:8]:
            bits.append(f"{change.get('field')} ({change.get('change_type')})")
        change_text = "Material changes since the previous snapshot: " + "; ".join(bits) + "."

    cited_ids: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        if claim.get("field") == "synthesis":
            continue
        for evidence_id in claim.get("evidence_ids") or []:
            if evidence_id not in seen:
                seen.add(evidence_id)
                cited_ids.append(evidence_id)

    summary = " ".join(sentences)
    return {
        "summary": summary,
        "what_changed": change_text,
        "unknowns": unknowns,
        "evidence_ids": cited_ids,
    }
