# Signalpost

Agent that turns a Norwegian organisation number into a sourced company profile for the [builderr.ai Signalpost challenge](https://builderr.ai/challenges/signalpost).

It reads the organisation numbers it is given. It does not pick its own list. Every input gets one JSON envelope, including numbers that are missing, blocked, or ambiguous. Missing figures stay null. They are never written as zero.

## One run command

Python 3.11 or newer. No third-party packages and no API key.

```bash
PYTHONPATH=src python3 -m signalpost run \
  --input companies.jsonl \
  --output outputs/envelopes.jsonl \
  --report outputs/run-report.json
```

`companies.jsonl` is the batch supplied for that run (JSONL, JSON, or one organisation number per line). Official scoring uses the batch Builderr hands the agent. Replace `companies.jsonl` with that path.

Install step on a clean machine: none. The command above is enough. Optional, if you want a `signalpost` executable:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/signalpost run --input companies.jsonl --output outputs/envelopes.jsonl --report outputs/run-report.json
```

## What a run returns

- `outputs/envelopes.jsonl` — one terminal envelope per input, in the same order
- `outputs/run-report.json` — counts, latency, request count, cost, and contract check

Envelope shape (see `DATA_SCHEMA.md`): `organisation_number`, `run`, `claims`, `evidence`, `changes`, `errors`, `operations`, plus a `synthesis` block. Claim availability is one of `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`.

Compare a later run with an earlier file:

```bash
PYTHONPATH=src python3 -m signalpost run \
  --input companies.jsonl \
  --output outputs/envelopes.jsonl \
  --report outputs/run-report.json \
  --previous outputs/previous-envelopes.jsonl
```

The same source values produce an empty `changes` list. The previous file is left in place.

Check a file without fetching:

```bash
PYTHONPATH=src python3 -m signalpost check \
  --input outputs/envelopes.jsonl \
  --expected-input companies.jsonl
```

Browse profiles on desktop or a phone-width window:

```bash
PYTHONPATH=src python3 -m signalpost view --input outputs/envelopes.jsonl --port 8765
```

Open `http://127.0.0.1:8765`. Routes: `/`, `/companies/{organisation_number}`, `/research`, `/refresh`.

A standalone file needs no server. Open it directly on a phone or a laptop:

```bash
PYTHONPATH=src python3 -m signalpost view --input outputs/envelopes.jsonl --static outputs/viewer.html
```

## Models, APIs, licences, cost

No model is called. Summaries are filled from the published claims by a template. An external model key is not required and is not read.

| Source | Use | Licence / terms |
| --- | --- | --- |
| `data.brreg.no` Enhetsregisteret (entity, roles, subunits, group) | Identity, address, industry, employees, status, leadership, workplaces | [NLOD 2.0](https://data.norge.no/nlod/en/2.0). Data from Brønnøysundregistrene. |
| `data.brreg.no` Regnskapsregisteret | Filed annual accounts and recent history | NLOD 2.0. Brønnøysundregistrene. |
| Wikidata Query Service (`P2333`) | Off unless `--wikidata` is passed. Description only when P2333 equals this organisation number | CC0 |
| Wikipedia REST summary | Only with `--wikidata`, for the article linked from that item | CC BY-SA |
| NAV Arbeidsplassen public feed | Active ads whose employer number is this organisation or one of its sub-units. The feed stores the workplace organisation number. This agent reads `overordnetEnhet` from Brreg underenheter and also matches workplace names. The public token is fetched at runtime from `/api/publicToken` and is not stored in the repo | Free if you agree to the [feed terms](https://navikt.github.io/pam-stilling-feed/). The token is experimental and rotates. Inactive ads and contact details are not stored. Finn.no ads are not in the feed. The scan covers feed pages modified in the last 45 days, capped at 360 pages |
| Google News RSS | Dated items only. Accepted when the item contains the organisation number, or the exact legal name and the registered municipality outside that name. The evidence is the RSS item; article bodies are not fetched | The starter kit treats RSS as a rights-review experiment because the article is not re-fetched. This agent publishes only the stricter matches above, with that limit stated on the claim |
| Website stored as `hjemmeside` | Fetched when `robots.txt` allows it, plus contact, about, privacy, and terms pages, and matching sitemap URLs when the homepage is not yet identified. Published when a same-domain page shows the organisation number (including `NO … MVA`), JSON-LD with the legal name and postcode, the registered phone, or a distinctive name token that also appears in the register host. Shared registrable domains (3 or more organisations in the 2025 universe) and directory hosts are not fetched or published. A redirect to another registrable domain is rejected | The company's own site |

Measured cost for a run: **USD 0**. There is no paid API. Declared external cost is under the USD 10 cap.

Measured on 17 October 2026 for `data/sample-1000.txt` (1,000 companies, run id `sample-1000`, started 07:25:01Z): 1,000 envelopes, validation passed, 5,680 HTTP requests, 534 seconds wall time, p50 2.3 s and p95 13.1 s per company, third-party cost USD 0. Each company stops optional page, job, and news fetches after 22 seconds. Coverage in that file: legal name 1,000, annual accounts 998, leadership 997, registered workplaces 1,000, employee count 135 (the rest are unpublished; Brønnøysund hides the 0–4 band, so a missing count is not zero), verified official websites 45, website descriptions 34, company profile links 28, hiring pages 4, dated news items 2, companies with a matched NAV ad 4. The public feed from 2 September 2026 was 92 pages and 20,399 active ads. Profile links are company pages only, and hiring links are careers paths. Google News items use the publisher URL when the RSS source supplies one. 937 summaries state an amount in MNOK. Open `outputs/viewer.html` directly in a browser; each card has source links and a compare button.

The annual-account copy-year endpoint (`/regnskap/aarsregnskap/kopi/{org}/aar`) is not called. It is rate limited, and the accounts endpoint already returns the recent company and group filings.

## Reproduce the committed 1,000 profiles

`data/sample-1000.txt` is 1,000 organisation numbers taken from the public universe `https://builderr.ai/signalpost-company-universe-2025.jsonl.gz` (archive SHA-256 `1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384`, 411,160 rows), every 411th row.

```bash
PYTHONPATH=src python3 -m signalpost run \
  --input data/sample-1000.txt \
  --output outputs/envelopes.jsonl \
  --report outputs/run-report.json \
  --run-id sample-1000
```

`outputs/smoke-100.jsonl` is the first 100 envelopes from that run, one per line of `data/sample-100.txt`. Precomputed profiles are not the official score. Builderr supplies a fresh batch and runs the command above.

## Tests

```bash
python3 -m pip install pytest==8.3.5
PYTHONPATH=src python3 -m pytest -q
```

## Layout

- `src/signalpost/` — batch runner, Brønnøysund parsers, website gate, Wikidata lookup, refresh diff, viewer
- `AGENT.md` — what is published and what is refused
- `DATA_SCHEMA.md` — envelope fields
- `LIMITATIONS.md` — gaps, JBOX, source rights
- `SUBMISSION.md` — draft email, not sent
