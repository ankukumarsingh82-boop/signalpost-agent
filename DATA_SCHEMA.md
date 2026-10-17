# Envelope schema

One JSON object per input organisation number. JSONL, input order.

```json
{
  "organisation_number": "923609016",
  "run": {
    "run_id": "sample-1000",
    "started_at": "2026-10-17T05:00:00Z",
    "completed_at": "2026-10-17T05:10:00Z",
    "terminal_status": "completed"
  },
  "claims": [
    {
      "field": "legal_name",
      "value": "EQUINOR ASA",
      "availability": "available",
      "confidence": 0.99,
      "evidence_ids": ["ev-923609016-1"],
      "as_of": null,
      "note": null
    }
  ],
  "evidence": [
    {
      "id": "ev-923609016-1",
      "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
      "source_class": "official_registry",
      "retrieved_at": "2026-10-17T05:00:01Z",
      "content_sha256": "<sha256 of the response body>",
      "claim_span": "EQUINOR ASA organisasjonsnummer 923609016"
    }
  ],
  "changes": [],
  "errors": [],
  "operations": {"requests": 6, "runtime_ms": 1200, "third_party_cost_usd": 0},
  "synthesis": {
    "summary": "...",
    "what_changed": "...",
    "unknowns": ["..."],
    "evidence_ids": ["ev-923609016-1"]
  },
  "refresh": {
    "previous_supplied": false,
    "previous_run_id": null,
    "material_change_count": 0,
    "idempotent_rerun": null
  }
}
```

`as_of`, `note`, `synthesis`, and `refresh` are included when they carry information. Availability on every claim is one of:

- `available` — a value was published
- `not_available` — the source was checked and did not have it
- `blocked` — the source refused (401, 403, 429, or robots)
- `not_applicable` — the question does not apply (for example the register says the entity is not in a group)
- `ambiguous` — a candidate could not be tied to this organisation number
- `failed` — the request or parser failed

A claim that is not `available` has `"value": null`. A checked workplace count of zero is `available` with `"total": 0`, because the register returned that total. An employee count is `not_available` when `harRegistrertAntallAnsatte` is false.

## Claim fields

| Field | Meaning |
| --- | --- |
| `legal_name`, `legal_form`, `organisation_status`, `business_address`, `postal_address`, `municipality`, `industry` | Entity register |
| `employee_count`, `founding_date`, `vat_registered`, `share_capital`, `statutory_purpose`, `registered_activity` | Entity register. Absent keys are not zero |
| `registry_listed_website` | Register `hjemmeside`, omitted when the host is shared or a directory |
| `official_website` | Final URL only after page verification. Otherwise null |
| `job_postings` | Active Arbeidsplassen ads with this `employer.orgnr` |
| `public_news` | Dated Google News RSS items that match the organisation number, or the exact legal name plus municipality |
| `company_news_items` | Dated headlines from article blocks on the verified site |
| `website_page_verified` | True when a fetched page shows the organisation number, the legal name plus registered postcode, or the registered phone. False when a page was fetched and did not match |
| `website_description`, `company_profile.{platform}`, `hiring_pages`, `company_news_pages` | Published only when `website_page_verified` is true |
| `annual_accounts`, `latest_entity_accounts`, `latest_group_accounts` | Regnskapsregisteret. Group accounts are labelled and not mixed into the entity |
| `accounts.{TYPE}.{YEAR}.{figure}` | One figure: revenue, operating result, profit before tax, annual result, assets, equity, debt |
| `leadership`, `role.{code}.{name}` | Public roles. Dates of birth are dropped |
| `registered_workplaces`, `workplace.{orgnr}` | Underenheter |
| `group_structure`, `group_parent`, `subsidiary.{orgnr}` | Direct parent and direct subsidiaries of this organisation number only |
| `wikidata_description`, `wikidata_label`, `wikipedia_summary`, `wikipedia_url` | Only from a Wikidata item whose P2333 is this number |
| `synthesis` | Template restatement of the claims above |

## Evidence

`source_class` is `official_registry`, `official_accounts`, `company_owned`, `nav_jobs`, `news_rss`, `wikidata`, or `wikipedia`. `content_sha256` is the response body. `retrieved_at` is when this run fetched it. `claim_span` is a short locator, not the whole document.

## Refresh

`--previous` diffs claim field, availability, and value. `synthesis` is not a source fact and is not itself a change. A second pass over the same values sets `idempotent_rerun` to true and `changes` to `[]`. Changed claims keep `previous_value`, `current_value`, and both evidence id lists. The previous JSONL file is the preserved snapshot.
