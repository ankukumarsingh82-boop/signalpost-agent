# Draft email — do not send

To: submit@builderr.ai
Subject: Signalpost entry — signalpost agent

Hello,

Please score this Signalpost entry.

- Agent name: signalpost
- Repository: https://github.com/ankukumarsingh82-boop/signalpost-agent
- Branch: cursor/signalpost-agent-65eb
- Commit: 03c5645649a985e8f1c2bdafc0e874821380fb3d
- Contact: ankukumarsingh82@gmail.com

One run command, from a clean clone, with Python 3.11+ and no API key. Replace the input path with the official batch:

```bash
PYTHONPATH=src python3 -m signalpost run --input companies.jsonl --output outputs/envelopes.jsonl --report outputs/run-report.json
```

Install step: none. The standard library is enough. Tests, if wanted: `python3 -m pip install pytest==8.3.5` then `PYTHONPATH=src python3 -m pytest -q`.

A local viewer that opens without a server: `outputs/viewer.html`. Or `PYTHONPATH=src python3 -m signalpost view --input outputs/envelopes.jsonl --static outputs/viewer.html`.

Smoke test: `outputs/smoke-100.jsonl` and `outputs/smoke-100-report.json` (the first 100 envelopes from the 1,000-company run). That run is in `outputs/envelopes.jsonl` with `outputs/run-report.json`, produced by commit 03c5645649a985e8f1c2bdafc0e874821380fb3d. Those files are a local check. Please score the agent on the batch you supply.

Models: none. Summaries are a template over the published claims.

APIs and licences:

- Brønnøysundregistrene Enhetsregisteret and Regnskapsregisteret, NLOD 2.0 (https://data.brreg.no)
- NAV Arbeidsplassen public feed (https://pam-stilling-feed.nav.no). Free under the feed terms. The public token is fetched at runtime and is not stored. Ads are published when the employer number is the company or a sub-unit whose parent is the company. Inactive ads and contact details are not stored.
- Google News RSS titles only, when the item contains the organisation number or the exact legal name plus the registered municipality. The stored URL is the publisher URL from the RSS source when one is present. Article bodies are not fetched. The starter kit marks RSS as a rights-review experiment for that reason.
- The hjemmeside host on the entity, fetched when robots.txt allows it. The official website is published only when a page on that same domain shows the organisation number (including NO … MVA or JSON-LD), the legal name and registered postcode, the registered phone, or a distinctive name token that also appears in the host. Shared and directory hosts are not published. A token on a different brand's host is not published.
- Wikidata and Wikipedia are off unless `--wikidata` is passed.

Expected cost per official run: USD 0. No paid model or data API. Under the USD 10 cap.

The agent returns one terminal envelope per input organisation number, with source URL, retrieval time, content hash, and an availability state. Missing values are null. `--previous earlier.jsonl` reports material changes and does not duplicate unchanged facts.

JBOX: not used. JBOX is a hosted Next.js product builder and is not available as a reproducible dependency for the official run.

Thank you.
