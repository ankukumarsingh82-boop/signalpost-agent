# Draft email — do not send

To: submit@builderr.ai
Subject: Signalpost entry — signalpost agent

Hello,

Please score this Signalpost entry.

- Agent name: signalpost
- Repository: https://github.com/ankukumarsingh82-boop/signalpost-agent
- Branch: cursor/signalpost-agent-65eb
- Commit: COMMIT_HASH
- Contact for results: the GitHub account that owns this repository

One run command, from a clean clone, with Python 3.11+ and no API key. Replace the input path with the official batch:

```bash
PYTHONPATH=src python3 -m signalpost run --input companies.jsonl --output outputs/envelopes.jsonl --report outputs/run-report.json
```

Install step: none. The standard library is enough. Tests, if wanted: `python3 -m pip install pytest==8.3.5` then `PYTHONPATH=src python3 -m pytest -q`.

Smoke test: `outputs/smoke-100.jsonl` and `outputs/smoke-100-report.json` (100 organisation numbers from `data/sample-100.txt`, one envelope each). A 1,000-company local run is in `outputs/envelopes.jsonl` with `outputs/run-report.json`. Those files are a local check. Please score the agent on the batch you supply.

Models: none. Summaries are a template over the published claims.

APIs and licences:

- Brønnøysundregistrene Enhetsregisteret and Regnskapsregisteret, NLOD 2.0 (https://data.brreg.no)
- Wikidata Query Service, CC0, property P2333 only
- Wikipedia REST page summary, CC BY-SA, only for the article linked from that Wikidata item
- The `hjemmeside` host recorded on the entity, fetched when robots.txt allows it. Page content is published only if the page contains the organisation number.

Expected cost per official run: USD 0. No paid model or data API. Under the USD 10 cap.

The agent returns one terminal envelope per input organisation number, with source URL, retrieval time, content hash, and an availability state. Missing values are null. `--previous earlier.jsonl` reports material changes and does not duplicate unchanged facts.

JBOX: not used. JBOX is a hosted Next.js product builder and is not available as a reproducible dependency for the official run.

Thank you.
