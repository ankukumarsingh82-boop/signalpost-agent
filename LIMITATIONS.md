# Limitations

## Coverage gaps

- Most entities in the public universe have no `hjemmeside` (about 11% do). Hosts shared by three or more organisations are not published, which removes housing-manager and group sites that the register repeats. A page is an official website only after it shows the organisation number (including an `NO … MVA` line or JSON-LD), the legal name with the registered postcode, or the registered phone. A distinctive name token is accepted only when that same token appears in the register host, so a different brand on the page is not published.
- JavaScript-only sites often omit those identifiers from the first HTML response. Those pages stay unverified. No browser renderer is bundled, so the run stays installable with the standard library.
- NAV ads are taken from the public feed pages modified in the last 45 days (at most 360 pages). The feed often ends before that cap. Older active ads and Finn.no ads are not included. A name on the feed is only a candidate. The ad is published when `employer.orgnr` is the company, a workplace already listed for it, or a sub-unit whose `overordnetEnhet` is the company.
- Google News items that mention the company without the municipality, and without the organisation number, are not published.
- Wikidata is off by default. P2333 covers a few thousand Norwegian entities, not the full 411,160.
- Reviews, ratings, and social sentiment are not collected. The October 2026 score note said that family was excluded from the round; it is still a gap if a later round counts it.
- The accounts history-year endpoint is intentionally unused because of its low rate limit. Recent filings still come from `/regnskapsregisteret/regnskap/{org}`.
- Banks and some insurers can 500 on the accounts API. Those claims are `failed`, not guessed.

## Source rights and URL safety

- Brønnøysund data is used under NLOD 2.0 and attributed to Brønnøysundregistrene.
- Wikidata is CC0. Wikipedia extracts are CC BY-SA.
- Company pages are fetched only for the host the entity register recorded, after a public-address check (no localhost, link-local, or private targets) and a `robots.txt` homepage disallow check.
- LinkedIn, Meta, Glassdoor, and Indeed are not crawled. A link to them is stored only when a verified company page publishes it. The destination is not fetched.
- No API keys, cookies, or account-tied credentials are required. None are hardcoded.

## JBOX

JBOX (https://jboxai.com) is a hosted product builder that generates Next.js applications. The separate USD 500 prize is for qualifying agents built with it. This entry does not use JBOX. There is no JBOX project or API in this environment, the evaluator has to rerun the agent from a clean checkout with one command, and a JBOX-hosted app would add a paid account the official run cannot reproduce. The local viewer is plain Python so it runs next to the batch command.

## Cost

External API spend is USD 0. The only network calls are the public sources listed in the README.
