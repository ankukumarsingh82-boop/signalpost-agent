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

## Models, APIs, licences, cost

No model is called. Summaries are filled from the published claims by a template. An external model key is not required and is not read.

| Source | Use | Licence / terms |
| --- | --- | --- |
| `data.brreg.no` Enhetsregisteret (entity, roles, subunits, group) | Identity, address, industry, employees, status, leadership, workplaces | [NLOD 2.0](https://data.norge.no/nlod/en/2.0). Data from Brønnøysundregistrene. |
| `data.brreg.no` Regnskapsregisteret | Filed annual accounts and recent history | NLOD 2.0. Brønnøysundregistrene. |
| Wikidata Query Service (`P2333`) | Description only when the item carries this exact organisation number | CC0 |
| Wikipedia REST summary | Extract for the article linked from that Wikidata item | CC BY-SA |
| Website stored as `hjemmeside` on the entity | The URL is a registry fact. Page text, profiles, and career links are published only if the page contains the organisation number and `robots.txt` does not disallow the homepage | The company's own site |

Measured cost for a run: **USD 0**. There is no paid API. Declared external cost is under the USD 10 cap.

Measured on 17 October 2026 for `data/sample-1000.txt` (1,000 companies, run id `sample-1000`): 1,000 envelopes, validation passed, 4,415 HTTP requests, 457 seconds wall time, p50 2.1 s and p95 13.3 s per company, third-party cost USD 0. Coverage in that file: legal name 1,000, annual accounts 998, leadership 997, registered workplaces 1,000, register-listed website 112, page-verified hiring links 2, Wikipedia summaries 8. A repeat fetch of organisation `810034882` against that file reported zero material changes.

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
