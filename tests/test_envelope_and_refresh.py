from signalpost.envelope import build_envelope
from signalpost.refresh import diff_envelopes
from signalpost.validate import validate_envelopes

RUN = {"run_id": "test", "started_at": "2026-10-17T00:00:00Z", "completed_at": "2026-10-17T00:00:02Z"}
HIT = {
    "url": "https://data.brreg.no/enhetsregisteret/api/enheter/810034882",
    "final_url": "https://data.brreg.no/enhetsregisteret/api/enheter/810034882",
    "retrieved_at": "2026-10-17T00:00:01Z",
    "content_sha256": "abc",
    "error": None,
}


def _research():
    return {
        "entity": {
            "availability": "available",
            "hit": HIT,
            "parsed": {
                "organisation_number": "810034882",
                "name": "SANDNES ELEKTRISKE AS",
                "legal_form_code": "AS",
                "legal_form": "Aksjeselskap",
                "business_address": {"lines": ["Gata 1"], "postal_code": "4301", "city": "SANDNES", "municipality": "SANDNES"},
                "postal_address": None,
                "industry": {"code": "43.210", "label": "Elektrisk installasjonsarbeid"},
                "additional_industries": [],
                "employees": 11,
                "employees_registered": True,
                "founding_date": "1981-01-02",
                "entity_register_date": "1995-03-01",
                "vat_registered": True,
                "foretaksregister_registered": True,
                "bankrupt": False,
                "liquidating": False,
                "compulsory_liquidation": False,
                "share_capital": None,
                "statutory_purpose": ["Utføre elektriske installasjoner."],
                "registered_activity": [],
                "historical_names": [],
                "telephone": None,
                "registry_website": None,
                "in_corporate_group": False,
                "latest_submitted_accounts_year": "2025",
                "institutional_sector": None,
            },
        },
        "accounts": {
            "availability": "available",
            "hit": {**HIT, "url": "https://data.brreg.no/regnskapsregisteret/regnskap/810034882"},
            "parsed": {
                "records": [
                    {
                        "account_type": "SELSKAP",
                        "period_from": "2024-01-01",
                        "period_to": "2024-12-31",
                        "currency": "NOK",
                        "record_id": 9,
                        "figures": {"revenue": {"amount": 1000, "currency": "NOK", "period_to": "2024-12-31"}, "annual_result": {"amount": 100, "currency": "NOK", "period_to": "2024-12-31"}},
                    }
                ],
                "truncated": False,
            },
        },
        "roles": {"availability": "not_available", "hit": HIT, "note": "No roles."},
        "workplaces": {"availability": "available", "hit": HIT, "parsed": {"total": 0, "workplaces": [], "truncated": False}},
        "group": {"availability": "not_applicable", "hit": HIT, "note": "Not in a group."},
        "website": {"availability": "not_available", "note": "No website."},
        "wiki": {"availability": "not_available", "note": "No Wikidata item."},
        "errors": [],
        "operations": {"requests": 4, "runtime_ms": 20},
    }


def test_envelope_contract_and_missing_fields_are_not_zero():
    envelope = build_envelope("810034882", _research(), RUN)
    validation = validate_envelopes([envelope], ["810034882"])
    assert validation["passed"], validation["issues"]
    by_field = {claim["field"]: claim for claim in envelope["claims"]}
    assert by_field["employee_count"]["value"] == 11
    assert by_field["telephone"]["availability"] == "not_available"
    assert by_field["telephone"]["value"] is None
    assert by_field["registered_workplaces"]["value"]["total"] == 0
    assert by_field["accounts.SELSKAP.2024.revenue"]["value"]["amount"] == 1000
    assert "debt" not in {claim["field"].rsplit(".", 1)[-1] for claim in envelope["claims"] if claim["field"].startswith("accounts.")}
    assert "11" in envelope["synthesis"]["summary"]
    assert "1,000 NOK" in envelope["synthesis"]["summary"]
    assert "debt 0" not in envelope["synthesis"]["summary"].lower()


def test_refresh_is_idempotent_until_a_value_changes():
    first = build_envelope("810034882", _research(), RUN)
    second = build_envelope("810034882", _research(), {**RUN, "run_id": "test-2"})
    same = diff_envelopes(second, first)
    assert same["idempotent_rerun"] is True
    assert same["changes"] == []
    changed = _research()
    changed["entity"]["parsed"]["employees"] = 12
    third = build_envelope("810034882", changed, {**RUN, "run_id": "test-3"})
    delta = diff_envelopes(third, first)
    assert delta["idempotent_rerun"] is False
    fields = [change["field"] for change in delta["changes"]]
    assert "employee_count" in fields
    employee = next(change for change in delta["changes"] if change["field"] == "employee_count")
    assert employee["previous_value"] == 11
    assert employee["current_value"] == 12
    assert "synthesis" not in fields


def test_not_found_entity_still_emits_one_envelope():
    research = _research()
    research["entity"] = {"availability": "not_available", "hit": HIT, "parsed": None, "note": "missing"}
    research["accounts"] = {"availability": "not_available", "hit": HIT, "note": "missing"}
    research["roles"] = {"availability": "not_available", "hit": HIT, "note": "missing"}
    research["workplaces"] = {"availability": "not_available", "hit": HIT, "note": "missing"}
    research["group"] = {"availability": "not_available", "hit": HIT, "note": "missing"}
    envelope = build_envelope("810034882", research, RUN)
    validation = validate_envelopes([envelope], ["810034882"])
    assert validation["passed"], validation["issues"]
    assert envelope["run"]["terminal_status"] == "completed"
    assert all(claim["value"] is None for claim in envelope["claims"] if claim["availability"] == "not_available")
