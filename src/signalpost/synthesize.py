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


def _account_series(claims: list[dict[str, Any]], figure: str) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    prefix = "accounts.SELSKAP."
    suffix = f".{figure}"
    for claim in claims:
        field = claim.get("field") or ""
        if not field.startswith(prefix) or not field.endswith(suffix) or claim.get("availability") != "available":
            continue
        year = field[len(prefix) : -len(suffix)]
        value = claim.get("value")
        if year.isdigit() and isinstance(value, dict) and value.get("amount") is not None:
            rows.append((year, value))
    rows.sort(key=lambda item: item[0])
    return rows


def _trend_sentence(claims: list[dict[str, Any]]) -> str | None:
    revenue = _account_series(claims, "revenue")
    result = _account_series(claims, "annual_result")
    if len(revenue) < 2 and len(result) < 2:
        return None
    parts: list[str] = []

    def direction(older: float, newer: float) -> str:
        if newer > older:
            return "up"
        if newer < older:
            return "down"
        return "flat"

    def one(label: str, series: list[tuple[str, dict[str, Any]]]) -> str | None:
        if len(series) < 2:
            return None
        older_year, older = series[-2]
        newer_year, newer = series[-1]
        if older.get("currency") != newer.get("currency"):
            return None
        older_amount = older.get("amount")
        newer_amount = newer.get("amount")
        if not isinstance(older_amount, (int, float)) or not isinstance(newer_amount, (int, float)):
            return None
        rendered_old = _money(older)
        rendered_new = _money(newer)
        if not rendered_old or not rendered_new:
            return None
        return f"{label} {rendered_old} in {older_year} and {rendered_new} in {newer_year} ({direction(float(older_amount), float(newer_amount))})"

    revenue_text = one("revenue", revenue)
    result_text = one("annual result", result)
    if revenue_text:
        parts.append(revenue_text)
    if result_text:
        parts.append(result_text)
    if not parts:
        return None
    return "Company accounts (not group accounts) show " + ", and ".join(parts) + "."


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
    description = _available(by, "website_description")
    listed_site = _available(by, "registry_listed_website")
    wiki = _available(by, "wikipedia_summary") or _available(by, "wikidata_description")
    hiring = _available(by, "hiring_pages")
    news = _available(by, "company_news_pages")
    jobs = _available(by, "job_postings")
    public_news = _available(by, "public_news")
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

    if page_verified is True and description:
        sentences.append(f"Its website describes the business as: {str(description)[:300]}")
    if employees is not None:
        sentences.append(f"The register records {employees} employees.")
    else:
        sentences.append("The entity register has not published an employee count.")
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
    trend = _trend_sentence(claims)
    if trend:
        sentences.append(trend)

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
        sentences.append(f"The official website {website} was accepted after the page identified organisation {org}.")
    elif listed_site:
        sentences.append(
            f"The register lists {listed_site}, but that site was not verified, so it is not the official website and its content was not published."
        )

    if isinstance(jobs, dict) and jobs.get("postings"):
        count = jobs.get("matched_count") or len(jobs.get("postings") or [])
        sentences.append(f"Arbeidsplassen lists {count} active ad{'s' if count != 1 else ''} whose employer organisation number is {org}.")
    if isinstance(public_news, dict) and public_news.get("items"):
        sentences.append(f"Google News RSS returned {len(public_news['items'])} dated item(s) that name this company with its municipality or organisation number. Article bodies were not fetched.")
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
        unknowns.append("No verified official website was published.")
    if not isinstance(jobs, dict):
        unknowns.append("No active Arbeidsplassen ad with this organisation number was found in the scanned feed.")
    if not isinstance(public_news, dict):
        unknowns.append("No dated news item matched the organisation number, or the exact legal name plus municipality.")
    if not hiring:
        unknowns.append("No company-owned hiring page was verified in this run.")
    if not news and not wiki and not isinstance(public_news, dict):
        unknowns.append("No company news page was verified in this run.")
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
