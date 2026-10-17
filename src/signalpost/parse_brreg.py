"""Pure parsers for Brønnøysund Enhetsregisteret and Regnskapsregisteret payloads.

Missing keys stay missing. This module never substitutes zero for an absent figure.
"""

from __future__ import annotations

from typing import Any


def dig(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def format_address(address: Any) -> dict[str, Any] | None:
    if not isinstance(address, dict):
        return None
    lines = address.get("adresse") or []
    if isinstance(lines, str):
        lines = [lines]
    formatted = {
        "lines": [str(line) for line in lines if line],
        "postal_code": address.get("postnummer") or None,
        "city": address.get("poststed") or None,
        "municipality": address.get("kommune") or None,
        "municipality_number": address.get("kommunenummer") or None,
        "country": address.get("land") or None,
        "country_code": address.get("landkode") or None,
    }
    if not any(formatted.values()):
        return None
    return formatted


def format_industry(industry: Any) -> dict[str, Any] | None:
    if not isinstance(industry, dict):
        return None
    code = industry.get("kode") or None
    label = industry.get("beskrivelse") or None
    if not code and not label:
        return None
    return {"code": code, "label": label}


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                texts.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("navn") or item.get("beskrivelse") or item.get("tekst")
                if isinstance(name, str) and name.strip():
                    texts.append(name.strip())
        return texts
    return []


def _present_bool(body: dict[str, Any], key: str) -> bool | None:
    if key not in body or body[key] is None:
        return None
    return bool(body[key])


def parse_entity(body: Any) -> dict[str, Any]:
    """Normalize one Enhetsregisteret entity document."""
    body = body if isinstance(body, dict) else {}
    employees = None
    employees_registered = _present_bool(body, "harRegistrertAntallAnsatte")
    if employees_registered is True and isinstance(body.get("antallAnsatte"), (int, float)) and not isinstance(body.get("antallAnsatte"), bool):
        employees = int(body["antallAnsatte"])
    capital = None
    raw_capital = body.get("kapital")
    if isinstance(raw_capital, dict) and raw_capital.get("belop") is not None:
        capital = {
            "amount": raw_capital.get("belop"),
            "currency": raw_capital.get("valuta"),
            "type": raw_capital.get("type"),
        }
        if raw_capital.get("antallAksjer") is not None:
            capital["shares"] = raw_capital.get("antallAksjer")
    additional = [
        industry
        for industry in (format_industry(body.get("naeringskode2")), format_industry(body.get("naeringskode3")))
        if industry
    ]
    return {
        "organisation_number": body.get("organisasjonsnummer"),
        "name": body.get("navn") or None,
        "legal_form_code": dig(body, "organisasjonsform", "kode"),
        "legal_form": dig(body, "organisasjonsform", "beskrivelse"),
        "business_address": format_address(body.get("forretningsadresse")),
        "postal_address": format_address(body.get("postadresse")),
        "industry": format_industry(body.get("naeringskode1")),
        "additional_industries": additional,
        "employees": employees,
        "employees_registered": employees_registered,
        "founding_date": body.get("stiftelsesdato") or None,
        "entity_register_date": body.get("registreringsdatoEnhetsregisteret") or None,
        "vat_registered": _present_bool(body, "registrertIMvaregisteret"),
        "foretaksregister_registered": _present_bool(body, "registrertIForetaksregisteret"),
        "bankrupt": _present_bool(body, "konkurs"),
        "liquidating": _present_bool(body, "underAvvikling"),
        "compulsory_liquidation": _present_bool(body, "underTvangsavviklingEllerTvangsopplosning"),
        "share_capital": capital,
        "statutory_purpose": _text_list(body.get("vedtektsfestetFormaal")),
        "registered_activity": _text_list(body.get("aktivitet")),
        "historical_names": _text_list(body.get("historiskeNavn")),
        "telephone": str(body["telefon"]).strip() if body.get("telefon") else None,
        "registry_website": str(body["hjemmeside"]).strip() if body.get("hjemmeside") else None,
        "in_corporate_group": _present_bool(body, "erIKonsern"),
        "latest_submitted_accounts_year": body.get("sisteInnsendteAarsregnskap") or None,
        "institutional_sector": format_industry(body.get("institusjonellSektorkode")),
        "articles_date": body.get("vedtektsdato") or None,
    }


def _figure(item: dict[str, Any], amount: Any) -> dict[str, Any] | None:
    if amount is None or isinstance(amount, bool):
        return None
    if not isinstance(amount, (int, float)):
        return None
    period = item.get("regnskapsperiode") if isinstance(item.get("regnskapsperiode"), dict) else {}
    return {
        "amount": amount,
        "currency": item.get("valuta") or None,
        "account_type": item.get("regnskapstype") or None,
        "period_from": period.get("fraDato"),
        "period_to": period.get("tilDato"),
        "record_id": item.get("id"),
    }


def parse_accounts(body: Any, *, limit: int = 12) -> dict[str, Any]:
    """Normalize Regnskapsregisteret records. Latest period first; company before group."""
    rows = body if isinstance(body, list) else []
    records: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        period = item.get("regnskapsperiode") if isinstance(item.get("regnskapsperiode"), dict) else {}
        paths = {
            "revenue": ("resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter"),
            "operating_result": ("resultatregnskapResultat", "driftsresultat", "driftsresultat"),
            "profit_before_tax": ("resultatregnskapResultat", "ordinaertResultatFoerSkattekostnad"),
            "annual_result": ("resultatregnskapResultat", "aarsresultat"),
            "assets": ("eiendeler", "sumEiendeler"),
            "equity": ("egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
            "debt": ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld"),
        }
        figures = {}
        for name, path in paths.items():
            figure = _figure(item, dig(item, *path))
            if figure is not None:
                figures[name] = figure
        records.append(
            {
                "account_type": item.get("regnskapstype") or None,
                "period_from": period.get("fraDato"),
                "period_to": period.get("tilDato"),
                "currency": item.get("valuta") or None,
                "record_id": item.get("id"),
                "figures": figures,
            }
        )
    records.sort(
        key=lambda record: (
            record.get("period_to") or "",
            1 if record.get("account_type") == "SELSKAP" else 0,
        )
    )
    records.reverse()
    truncated = len(records) > limit
    return {"records": records[:limit], "truncated": truncated, "returned_count": len(rows) if isinstance(body, list) else 0}


def _entity_display_name(entity: dict[str, Any]) -> str | None:
    """Role holder firms put the name in enhet.navn as a string or a list of strings."""
    navn = entity.get("navn")
    if isinstance(navn, str) and navn.strip():
        return navn.strip()
    if isinstance(navn, list):
        parts = [part.strip() for part in navn if isinstance(part, str) and part.strip()]
        if parts:
            return " ".join(parts)
    return None


def parse_roles(body: Any, *, limit: int = 50) -> dict[str, Any]:
    """Normalize public roles. Dates of birth are discarded and never returned."""
    groups = body.get("rollegrupper") if isinstance(body, dict) else None
    roles: list[dict[str, Any]] = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        group_type = group.get("type") if isinstance(group.get("type"), dict) else {}
        for item in group.get("roller") or []:
            if not isinstance(item, dict):
                continue
            person = item.get("person") if isinstance(item.get("person"), dict) else {}
            name = person.get("navn") if isinstance(person.get("navn"), dict) else {}
            entity = item.get("enhet") if isinstance(item.get("enhet"), dict) else {}
            display = " ".join(
                part
                for part in (name.get("fornavn"), name.get("mellomnavn"), name.get("etternavn"))
                if isinstance(part, str) and part.strip()
            ).strip()
            if not display:
                display = _entity_display_name(entity)
            role_type = item.get("type") if isinstance(item.get("type"), dict) else {}
            roles.append(
                {
                    "name": display or None,
                    "holder_organisation_number": entity.get("organisasjonsnummer"),
                    "role_code": role_type.get("kode"),
                    "role": role_type.get("beskrivelse"),
                    "group_code": group_type.get("kode"),
                    "group": group_type.get("beskrivelse"),
                    "last_changed": group.get("sistEndret"),
                    "inactive": bool(item.get("avregistrert")),
                }
            )
    roles.sort(key=lambda role: (str(role.get("role_code") or ""), str(role.get("name") or ""), str(role.get("holder_organisation_number") or "")))
    return {"roles": roles[:limit], "truncated": len(roles) > limit, "returned_count": len(roles)}


def parse_subunit_page(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"total": None, "workplaces": []}
    page = body.get("page") if isinstance(body.get("page"), dict) else {}
    rows = dig(body, "_embedded", "underenheter") or []
    workplaces: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        employees = None
        if item.get("harRegistrertAntallAnsatte") is True and isinstance(item.get("antallAnsatte"), (int, float)) and not isinstance(item.get("antallAnsatte"), bool):
            employees = int(item["antallAnsatte"])
        workplaces.append(
            {
                "organisation_number": item.get("organisasjonsnummer"),
                "name": item.get("navn"),
                "address": format_address(item.get("beliggenhetsadresse") or item.get("postadresse")),
                "industry": format_industry(item.get("naeringskode1")),
                "employees": employees,
            }
        )
    total = page.get("totalElements")
    if total is not None and not isinstance(total, int):
        total = None
    return {"total": total, "workplaces": workplaces, "total_pages": page.get("totalPages")}


def merge_workplaces(pages: list[dict[str, Any]], *, limit: int = 100) -> dict[str, Any]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = None
    for page in pages:
        if total is None and page.get("total") is not None:
            total = page["total"]
        for workplace in page.get("workplaces") or []:
            org = str(workplace.get("organisation_number") or "")
            if org and org in seen:
                continue
            if org:
                seen.add(org)
            merged.append(workplace)
    merged.sort(key=lambda item: str(item.get("organisation_number") or ""))
    truncated = len(merged) > limit or (isinstance(total, int) and total > len(merged))
    return {"total": total if total is not None else len(merged), "workplaces": merged[:limit], "truncated": truncated}


def _find_group_node(node: Any, org: str, parent: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    if not isinstance(node, dict):
        return None
    if str(node.get("organisasjonsnummer") or "") == org:
        return node, parent
    for child in node.get("children") or []:
        found = _find_group_node(child, org, node)
        if found:
            return found
    return None


def parse_group(body: Any, org: str, *, limit: int = 25) -> dict[str, Any]:
    """Publish only the queried entity's parent and direct subsidiaries."""
    if not isinstance(body, dict):
        return {"matched": False, "parent": None, "direct_subsidiaries": [], "direct_subsidiary_count": 0}
    found = _find_group_node(body, org)
    if not found:
        return {"matched": False, "parent": None, "direct_subsidiaries": [], "direct_subsidiary_count": 0}
    node, parent_node = found
    children: list[dict[str, Any]] = []
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        children.append(
            {
                "organisation_number": child.get("organisasjonsnummer"),
                "name": child.get("navn"),
                "legal_form": dig(child, "organisasjonsform", "kode"),
                "stake": child.get("grunnlag"),
                "link_type": dig(child, "knytningsform", "beskrivelse"),
                "as_of": child.get("dato"),
            }
        )
    children.sort(key=lambda item: str(item.get("organisation_number") or ""))
    parent = None
    if isinstance(parent_node, dict) and parent_node.get("organisasjonsnummer"):
        parent = {"organisation_number": parent_node.get("organisasjonsnummer"), "name": parent_node.get("navn")}
    elif node.get("parentOrganisasjonsnummer"):
        parent = {
            "organisation_number": node.get("parentOrganisasjonsnummer"),
            "name": node.get("parentNavn"),
        }
    return {
        "matched": True,
        "parent": parent,
        "direct_subsidiaries": children[:limit],
        "direct_subsidiary_count": len(children),
        "truncated": len(children) > limit,
    }
