# Research and abstention

The organisation number is the only identity key. A name, domain, or brand is not enough to publish page content.

## Publish

- Entity, role, workplace, group, and account fields returned for that exact organisation number by Brønnøysund.
- The `hjemmeside` string stored on that entity, labelled as a register value.
- Text, social links, career links, and news links from that website only after the organisation number appears on the fetched page.
- A Wikidata description and Wikipedia extract only when the item's P2333 equals the organisation number.
- A template summary that quotes those claims and lists what was not found.

## Do not publish

- A page that does not contain the organisation number. The website claim stays the register URL and `website_page_verified` is false. Description, profiles, and hiring links stay `not_available` or `ambiguous`.
- Subsidiaries, siblings, or a parent brand's accounts as if they were this entity. Group accounts are labelled `KONSERN`. The group parser keeps only this node's parent and its direct children.
- Dates of birth from the roles payload.
- Search snippets, LinkedIn, Meta, Glassdoor, Indeed, or NAV result lists. Those are not used.
- A zero standing in for a missing employee count, revenue, or job list.
- Any fact invented to fill a gap. If a module fails, its claims are `failed` or `not_available` and the company still gets an envelope.

## Refresh

Stable claim fields are compared with `--previous`. Equal values emit no change. A failed fetch does not delete the previous file.
