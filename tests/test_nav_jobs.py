from signalpost.http_client import Fetch
from signalpost.nav_jobs import candidate_stubs, employer_match, match_nav_jobs, related_catalog_names


def _fetch(url: str, body: dict, status: int = 200) -> Fetch:
    return Fetch(
        url=url,
        final_url=url,
        status=status,
        body=b"{}",
        text="{}",
        json_body=body,
        content_sha256="abc",
        retrieved_at="2026-10-17T00:00:00Z",
        elapsed_ms=1,
    )


class _Client:
    def __init__(self, responses: dict[str, Fetch]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get_json(self, url: str, **kwargs: object) -> Fetch:
        self.calls.append(url)
        return self.responses[url]


def test_employer_match_accepts_parent_known_subunit_and_overordnet():
    subunits = {"933984087"}
    lookups: list[str] = []

    def parent_of(org: str) -> str | None:
        lookups.append(org)
        return {"972156914": "992784202"}.get(org)

    assert employer_match("933796345", "933796345", subunits, parent_of) == "parent"
    assert employer_match("933984087", "933796345", subunits, parent_of) == "known_subunit"
    assert employer_match("972156914", "992784202", subunits, parent_of) == "overordnet_enhet"
    assert employer_match("111111111", "933796345", subunits, parent_of) is None
    assert lookups == ["972156914", "111111111"]


def test_subunit_name_matches_when_overordnet_enhet_is_the_company():
    detail = "https://pam-stilling-feed.nav.no/api/v1/feedentry/abc"
    subunit = "https://data.brreg.no/enhetsregisteret/api/underenheter/998499526"
    client = _Client(
        {
            detail: _fetch(
                detail,
                {
                    "status": "ACTIVE",
                    "uuid": "abc",
                    "ad_content": {
                        "title": "Tannlege",
                        "employer": {"orgnr": "998499526", "name": "Oslo Tannlegesenter Avd"},
                        "published": "2026-10-01T00:00:00Z",
                    },
                },
            ),
            subunit: _fetch(subunit, {"organisasjonsnummer": "998499526", "overordnetEnhet": "998477204"}),
        }
    )
    catalog = {
        "by_name": {
            "oslo tannlegesenter avd": [
                {"uuid": "abc", "detail_url": detail, "title": "Tannlege", "business_name": "Oslo Tannlegesenter Avd"}
            ]
        },
        "note": "feed",
        "token": None,
    }
    parsed = {"name": "OSLO TANNLEGESENTER AS", "organisation_number": "998477204"}
    workplaces = {
        "parsed": {
            "workplaces": [{"organisation_number": "900000001", "name": "Oslo Tannlegesenter Avd"}],
        }
    }
    result = match_nav_jobs(client, lambda fetch: fetch, catalog, "998477204", parsed, workplaces)
    assert result["availability"] == "available"
    assert result["postings"][0]["employer_orgnr"] == "998499526"
    assert result["postings"][0]["employer_match"] == "overordnet_enhet"
    assert subunit in client.calls


def test_different_parent_is_not_published():
    detail = "https://pam-stilling-feed.nav.no/api/v1/feedentry/nope"
    subunit = "https://data.brreg.no/enhetsregisteret/api/underenheter/972156914"
    client = _Client(
        {
            detail: _fetch(
                detail,
                {"status": "ACTIVE", "uuid": "nope", "ad_content": {"title": "Barnehage", "employer": {"orgnr": "972156914"}}},
            ),
            subunit: _fetch(subunit, {"organisasjonsnummer": "972156914", "overordnetEnhet": "999999999"}),
        }
    )
    catalog = {
        "by_name": {"hovslageren fus barnehage as": [{"uuid": "nope", "detail_url": detail, "title": "Barnehage"}]},
        "token": None,
    }
    result = match_nav_jobs(
        client,
        lambda fetch: fetch,
        catalog,
        "992784202",
        {"name": "HOVSLAGEREN FUS BARNEHAGE AS"},
    )
    assert result["availability"] == "not_available"
    assert "postings" not in result


def test_detail_fetches_stop_when_the_company_budget_is_spent():
    detail = "https://pam-stilling-feed.nav.no/api/v1/feedentry/abc"
    client = _Client({detail: _fetch(detail, {"status": "ACTIVE", "uuid": "abc", "ad_content": {"employer": {"orgnr": "1"}}})})
    catalog = {"by_name": {"parent as": [{"uuid": "abc", "detail_url": detail}]}, "token": None}
    result = match_nav_jobs(client, lambda fetch: fetch, catalog, "810034882", {"name": "Parent AS"}, deadline=0)
    assert result["availability"] == "not_available"
    assert client.calls == []


def test_related_catalog_names_keeps_a_longer_workplace_name():
    catalog = {
        "by_name": {
            "hovslageren fus barnehage as": [],
            "hovslageren fus barnehage avdeling": [],
            "oslo": [],
        }
    }
    found = related_catalog_names(catalog, ["HOVSLAGEREN FUS BARNEHAGE AS"])
    assert "hovslageren fus barnehage avdeling" in found
    assert "oslo" not in found


def test_candidate_stubs_prefers_the_legal_name_and_dedupes():
    catalog = {
        "by_name": {
            "parent as": [{"uuid": "1", "detail_url": "a"}],
            "subunit": [{"uuid": "1", "detail_url": "a"}, {"uuid": "2", "detail_url": "b"}],
        }
    }
    stubs = candidate_stubs(catalog, ["Parent AS", "Subunit"])
    assert [stub["uuid"] for stub in stubs] == ["1", "2"]
