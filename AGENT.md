# Research and abstention

The organisation number is the only identity key. A name, domain, or brand is not enough to publish page content.

## Publish

- Entity, role, workplace, group, and account fields returned for that exact organisation number by Brønnøysund.
- The `hjemmeside` string stored on that entity only when a page on that host identified the organisation. Shared, directory, and unverified hosts are not published.
- The official website, its description, company-profile links, and careers links only after a fetched page on that same domain shows the organisation number (including an NO … MVA line or JSON-LD), the legal name together with the registered postcode, the registered telephone number, or a distinctive name token that also appears in the register host. Share buttons, personal profiles, posts, and non-career paths are dropped.
- Active NAV Arbeidsplassen ads whose employer organisation number is this company or a sub-unit of it.
- Google News RSS items that contain the organisation number, or the exact legal name and the registered municipality. The stored link is the publisher URL when the RSS source has one. The article body is not fetched.
- A Wikidata description and Wikipedia extract only when `--wikidata` is used and the item's P2333 equals the organisation number.
- A template summary that quotes those claims and lists what was not found.

## Do not publish

- An unverified page. `official_website` is `ambiguous` with a null value. Description, profiles, and hiring links are not published.
- A shared or directory host, and any redirect whose registrable domain changes.
- Subsidiaries, siblings, or a parent brand's accounts as if they were this entity. Group accounts are labelled `KONSERN`. The group parser keeps only this node's parent and its direct children.
- Dates of birth from the roles payload.
- Search snippets, LinkedIn, Meta, Glassdoor, Indeed, or NAV result lists. Those are not used.
- A zero standing in for a missing employee count, revenue, or job list. An unpublished employee count includes the hidden 0–4 band and is not reported as zero.
- Any fact invented to fill a gap. If a module fails, its claims are `failed` or `not_available` and the company still gets an envelope.

## Refresh

Stable claim fields are compared with `--previous`. Equal values emit no change. A failed fetch does not delete the previous file.
