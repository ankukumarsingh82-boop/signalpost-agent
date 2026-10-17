import json

from signalpost.parse_brreg import parse_accounts, parse_entity, parse_group, parse_roles, parse_subunit_page


def test_entity_keeps_missing_employees_absent():
    parsed = parse_entity(
        {
            "organisasjonsnummer": "810059672",
            "navn": "AASEN & FARSTAD AS",
            "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
            "harRegistrertAntallAnsatte": False,
            "konkurs": False,
            "underAvvikling": False,
            "forretningsadresse": {"adresse": ["Storgata 1"], "postnummer": "6413", "poststed": "MOLDE", "kommune": "MOLDE"},
            "naeringskode1": {"kode": "68.200", "beskrivelse": "Utleie av egen eller leid fast eiendom"},
            "hjemmeside": "",
        }
    )
    assert parsed["employees"] is None
    assert parsed["employees_registered"] is False
    assert parsed["registry_website"] is None
    assert parsed["industry"]["code"] == "68.200"
    assert parsed["business_address"]["city"] == "MOLDE"
    assert parsed["bankrupt"] is False


def test_entity_publishes_registered_zero_employees():
    parsed = parse_entity({"organisasjonsnummer": "123456785", "navn": "TOM AS", "harRegistrertAntallAnsatte": True, "antallAnsatte": 0})
    assert parsed["employees"] == 0


def test_accounts_do_not_invent_missing_figures_and_prefer_latest_company_accounts():
    body = [
        {
            "id": 1,
            "regnskapstype": "KONSERN",
            "valuta": "NOK",
            "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
            "resultatregnskapResultat": {"aarsresultat": 5, "driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 50}, "driftsresultat": 7}},
            "eiendeler": {"sumEiendeler": 80},
            "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": 30}, "gjeldOversikt": {"sumGjeld": 50}},
        },
        {
            "id": 2,
            "regnskapstype": "SELSKAP",
            "valuta": "NOK",
            "regnskapsperiode": {"fraDato": "2023-01-01", "tilDato": "2023-12-31"},
            "resultatregnskapResultat": {"aarsresultat": 1, "driftsresultat": {"driftsinntekter": {}}},
            "eiendeler": {},
            "egenkapitalGjeld": {"egenkapital": {}, "gjeldOversikt": {}},
        },
        {
            "id": 3,
            "regnskapstype": "SELSKAP",
            "valuta": "NOK",
            "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
            "resultatregnskapResultat": {"aarsresultat": 9, "driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 40}, "driftsresultat": 4}},
            "eiendeler": {"sumEiendeler": 70},
            "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": 20}, "gjeldOversikt": {"sumGjeld": 50}},
        },
    ]
    parsed = parse_accounts(body)
    latest = parsed["records"][0]
    assert latest["account_type"] == "SELSKAP"
    assert latest["period_to"] == "2024-12-31"
    assert latest["figures"]["revenue"]["amount"] == 40
    older = next(record for record in parsed["records"] if record["record_id"] == 2)
    assert "revenue" not in older["figures"]
    assert "assets" not in older["figures"]
    assert "debt" not in older["figures"]
    assert older["figures"] == {"annual_result": older["figures"]["annual_result"]}


def test_roles_drop_birth_dates():
    parsed = parse_roles(
        {
            "rollegrupper": [
                {
                    "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                    "sistEndret": "2020-11-02",
                    "roller": [
                        {
                            "avregistrert": False,
                            "person": {"fodselsdato": "1968-05-04", "navn": {"fornavn": "Ada", "etternavn": "Lund"}},
                            "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                        }
                    ],
                }
            ]
        }
    )
    rendered = json.dumps(parsed)
    assert "1968-05-04" not in rendered
    assert "fodselsdato" not in rendered
    assert parsed["roles"][0]["name"] == "Ada Lund"
    assert parsed["roles"][0]["role_code"] == "DAGL"


def test_subunits_keep_explicit_zero_total():
    parsed = parse_subunit_page({"_embedded": {"underenheter": []}, "page": {"totalElements": 0, "totalPages": 0}})
    assert parsed["total"] == 0
    assert parsed["workplaces"] == []


def test_group_parser_does_not_publish_siblings_as_subsidiaries():
    body = {
        "organisasjonsnummer": "100000000",
        "navn": "PARENT AS",
        "children": [
            {
                "organisasjonsnummer": "200000000",
                "navn": "CHILD AS",
                "children": [{"organisasjonsnummer": "300000000", "navn": "GRANDCHILD AS"}],
            },
            {"organisasjonsnummer": "400000000", "navn": "SIBLING AS"},
        ],
    }
    parsed = parse_group(body, "200000000")
    assert parsed["matched"] is True
    assert parsed["parent"]["organisation_number"] == "100000000"
    assert [item["organisation_number"] for item in parsed["direct_subsidiaries"]] == ["300000000"]
    assert parsed["direct_subsidiary_count"] == 1
