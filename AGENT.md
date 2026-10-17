# Research and abstention

The organisation number is the only identity key. A name, domain, or brand is not enough to publish page content.

## Publish

- Entity, role, workplace, group, and account fields returned for that exact organisation number by Brønnøysund.
- The `hjemmeside` string stored on that entity, and only when its registrable domain is not shared by three or more organisations and is not a directory. It is labelled as a register value, not as a verified official site.
- The official website, its description, social links, career links, and news links only after a fetched page on that same domain shows the organisation number, or the legal name together with the registered postcode, or the registered telephone number.
- Active NAV Arbeidsplassen ads whose employer organisation number equals this number.
- Google News RSS items that contain the organisation number, or the exact legal name and the registered municipality. The RSS item is the evidence; the article body is not fetched.
- A Wikidata description and Wikipedia extract only when `--wikidata` is used and the item's P2333 equals the organisation number.
- A template summary that quotes those claims and lists what was not found.

## Do not publish

- An unverified page. `official_website` is `ambiguous` with a null value. Description, profiles, and hiring links are not published.
- A shared or directory host, and any redirect whose registrable domain changes.
- Subsidiaries, siblings, or a parent brand's accounts as if they were this entity. Group accounts are labelled `KONSERN`. The group parser keeps only this node's parent and its direct children.
- Dates of birth from the roles payload.
- Search snippets, LinkedIn, Meta, Glassdoor, Indeed, or NAV result lists. Those are not used.
- A zero standing in for a missing employee count, revenue, or job list.
- Any fact invented to fill a gap. If a module fails, its claims are `failed` or `not_available` and the company still gets an envelope.

## Refresh

Stable claim fields are compared with `--previous`. Equal values emit no change. A failed fetch does not delete the previous file.
