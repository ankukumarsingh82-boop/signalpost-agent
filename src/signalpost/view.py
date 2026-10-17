"""Local read-only browser for envelopes. Desktop and mobile."""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _claim(envelope: dict[str, Any], field: str) -> dict[str, Any] | None:
    for claim in envelope.get("claims") or []:
        if claim.get("field") == field:
            return claim
    return None


def _value(envelope: dict[str, Any], field: str) -> Any:
    claim = _claim(envelope, field)
    if not claim or claim.get("availability") != "available":
        return None
    return claim.get("value")


def _name(envelope: dict[str, Any]) -> str:
    return str(_value(envelope, "legal_name") or envelope.get("organisation_number"))


def _section(field: str) -> str:
    if field.startswith(("accounts.", "annual_", "latest_")):
        return "Accounts"
    if field.startswith("role.") or field == "leadership":
        return "Leadership"
    if field.startswith(("workplace.", "registered_workplace", "group_", "subsidiary.")):
        return "Workplaces and group"
    if field.startswith(("official_website", "website_", "company_", "hiring", "registry_listed")):
        return "Website and activity"
    if field.startswith(("wiki", "synthesis")):
        return "Public description"
    return "Legal identity"


def _render_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return f"<pre>{_esc(json.dumps(value, ensure_ascii=False, indent=2))}</pre>"
    return f"<p>{_esc(value)}</p>"


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
:root {{ color-scheme: light; --ink:#1c1915; --muted:#5c564c; --line:#e4dccb; --paper:#f6f1e7; --card:#fffdf8; --green:#0f6e56; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font:16px/1.45 "Iowan Old Style", Palatino, Georgia, serif; color:var(--ink); background:var(--paper); }}
header {{ padding:1rem 1.25rem; border-bottom:1px solid var(--line); background:var(--card); position:sticky; top:0; }}
header a {{ color:var(--green); font-weight:700; text-decoration:none; }}
main {{ padding:1rem 1.25rem 3rem; max-width:1100px; margin:0 auto; }}
form {{ display:flex; gap:.5rem; margin:.75rem 0 0; }}
input, select {{ font:inherit; padding:.55rem .7rem; border:1px solid var(--line); border-radius:8px; width:100%; background:white; }}
button, .button {{ font:inherit; background:var(--green); color:white; border:0; border-radius:8px; padding:.55rem .8rem; text-decoration:none; display:inline-block; }}
.grid {{ display:grid; gap:.75rem; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:.9rem 1rem; }}
.card h2 {{ font-size:1.05rem; margin:0 0 .4rem; }}
.meta {{ color:var(--muted); font-size:.92rem; }}
table {{ width:100%; border-collapse:collapse; }}
td, th {{ text-align:left; vertical-align:top; padding:.45rem .3rem; border-bottom:1px solid var(--line); }}
pre {{ white-space:pre-wrap; word-break:break-word; margin:.2rem 0; font:13px/1.4 ui-monospace, monospace; }}
a {{ color:var(--green); }}
ul {{ margin:.3rem 0 .3rem 1.1rem; padding:0; }}
@media (min-width: 800px) {{
  .split {{ display:grid; grid-template-columns:1fr 1fr; gap:1rem; }}
  .cards {{ display:grid; grid-template-columns:1fr 1fr; gap:.75rem; }}
}}
</style>
</head>
<body>
<header><a href="/">Signalpost</a> · <a href="/research">Research</a> · <a href="/refresh">Changes</a></header>
<main>{body}</main>
</body>
</html>"""
    return document.encode("utf-8")


def _company_card(envelope: dict[str, Any]) -> str:
    org = envelope["organisation_number"]
    industry = _value(envelope, "industry") or {}
    municipality = _value(envelope, "municipality") or {}
    label = industry.get("label") if isinstance(industry, dict) else ""
    place = municipality.get("name") if isinstance(municipality, dict) else ""
    synthesis = (envelope.get("synthesis") or {}).get("summary") or ""
    return f"""<article class="card">
      <h2><a href="/companies/{_esc(org)}">{_esc(_name(envelope))}</a></h2>
      <p class="meta">{_esc(org)} · {_esc(place)} · {_esc(label)}</p>
      <p>{_esc(synthesis[:280])}</p>
    </article>"""


def _company_body(envelope: dict[str, Any], other: dict[str, Any] | None) -> str:
    org = envelope["organisation_number"]
    synthesis = envelope.get("synthesis") or {}
    evidence = {item["id"]: item for item in envelope.get("evidence") or []}
    groups: dict[str, list[dict[str, Any]]] = {}
    for claim in envelope.get("claims") or []:
        if claim.get("field") == "synthesis":
            continue
        groups.setdefault(_section(claim["field"]), []).append(claim)
    sections = []
    for title, claims in groups.items():
        rows = []
        for claim in claims:
            refs = []
            for evidence_id in claim.get("evidence_ids") or []:
                item = evidence.get(evidence_id) or {}
                url = item.get("source_url")
                if url:
                    refs.append(f'<li><a href="{_esc(url)}">{_esc(url)}</a><br><span class="meta">{_esc(item.get("retrieved_at"))} · {_esc(item.get("source_class"))}</span></li>')
            rows.append(
                f"<tr><th>{_esc(claim['field'])}<br><span class='meta'>{_esc(claim.get('availability'))}</span></th>"
                f"<td>{_render_value(claim.get('value'))}{_esc(claim.get('note') or '')}<ul>{''.join(refs)}</ul></td></tr>"
            )
        sections.append(f"<section class='card'><h2>{_esc(title)}</h2><table>{''.join(rows)}</table></section>")
    unknowns = "".join(f"<li>{_esc(item)}</li>" for item in synthesis.get("unknowns") or [])
    changes = envelope.get("changes") or []
    change_html = "".join(
        f"<li>{_esc(change.get('field'))}: {_esc(change.get('change_type'))}</li>" for change in changes[:12]
    ) or "<li>No material change recorded.</li>"
    compare = ""
    if other:
        compare = f"<p><a class='button' href='/companies/{_esc(other['organisation_number'])}?compare={_esc(org)}'>Swap</a></p>" + _company_card(other)
    return f"""
      <h1>{_esc(_name(envelope))}</h1>
      <p class="meta">Organisation number {_esc(org)} · run {_esc((envelope.get('run') or {}).get('run_id'))} · cost USD 0</p>
      <div class="split">
        <section class="card">
          <h2>Summary</h2>
          <p>{_esc(synthesis.get('summary'))}</p>
          <p><strong>Changes.</strong> {_esc(synthesis.get('what_changed'))}</p>
          <h2>Unknown from this run</h2>
          <ul>{unknowns}</ul>
          <h2>Refresh</h2>
          <ul>{change_html}</ul>
        </section>
        <section>
          <form action="/companies/{_esc(org)}" method="get">
            <input name="compare" placeholder="Compare with organisation number" inputmode="numeric">
            <button type="submit">Compare</button>
          </form>
          {compare}
        </section>
      </div>
      <div class="grid" style="margin-top:1rem">{''.join(sections)}</div>
    """


class Viewer:
    def __init__(self, envelopes: list[dict[str, Any]]) -> None:
        self.by_org = {item["organisation_number"]: item for item in envelopes}
        self.ordered = envelopes

    def search(self, query: str) -> list[dict[str, Any]]:
        needle = query.casefold().strip()
        if not needle:
            return self.ordered[:50]
        hits = []
        for envelope in self.ordered:
            industry = _value(envelope, "industry") or {}
            municipality = _value(envelope, "municipality") or {}
            blob = " ".join(
                [
                    envelope["organisation_number"],
                    _name(envelope),
                    str(industry.get("label") if isinstance(industry, dict) else ""),
                    str(municipality.get("name") if isinstance(municipality, dict) else ""),
                ]
            ).casefold()
            if needle in blob:
                hits.append(envelope)
            if len(hits) >= 50:
                break
        return hits

    def handle(self, path: str, query: dict[str, list[str]]) -> tuple[int, bytes, str]:
        if path in {"", "/"}:
            cards = "".join(_company_card(item) for item in self.ordered[:24])
            body = f"<h1>Companies</h1><p class='meta'>{len(self.ordered)} profiles in this file. Search finds an organisation number, name, place, or industry.</p><div class='cards'>{cards}</div>"
            return 200, _page("Signalpost companies", body), "text/html; charset=utf-8"
        if path == "/research":
            q = (query.get("q") or [""])[0]
            hits = self.search(q)
            cards = "".join(_company_card(item) for item in hits) or "<p>No matching company in this file.</p>"
            body = f"<h1>Research</h1><form action='/research'><input name='q' value='{_esc(q)}' placeholder='Name, place, industry, or organisation number'><button>Search</button></form><div class='cards'>{cards}</div>"
            return 200, _page("Research", body), "text/html; charset=utf-8"
        if path == "/refresh":
            changed = [item for item in self.ordered if item.get("changes")]
            cards = "".join(_company_card(item) for item in changed[:50]) or "<p>No material changes in this file. Pass <span class='meta'>--previous</span> on the next run to compare snapshots.</p>"
            body = f"<h1>Changes</h1><p class='meta'>{len(changed)} profiles with at least one changed claim.</p><div class='cards'>{cards}</div>"
            return 200, _page("Changes", body), "text/html; charset=utf-8"
        if path.startswith("/companies/"):
            org = unquote(path.split("/", 2)[2])
            envelope = self.by_org.get(org)
            if not envelope:
                return 404, _page("Not found", f"<h1>No profile for {_esc(org)}</h1>"), "text/html; charset=utf-8"
            compare_org = (query.get("compare") or [""])[0]
            other = self.by_org.get(compare_org) if compare_org else None
            return 200, _page(_name(envelope), _company_body(envelope, other)), "text/html; charset=utf-8"
        if path.startswith("/api/companies/"):
            org = unquote(path.split("/", 3)[3])
            envelope = self.by_org.get(org)
            if not envelope:
                return 404, b'{"error":"not_found"}', "application/json"
            return 200, json.dumps(envelope, ensure_ascii=False).encode("utf-8"), "application/json"
        return 404, _page("Not found", "<h1>Not found</h1>"), "text/html; charset=utf-8"


def _static_card(envelope: dict[str, Any]) -> str:
    org = str(envelope.get("organisation_number") or "")
    name = _name(envelope)
    industry = _value(envelope, "industry") or {}
    municipality = _value(envelope, "municipality") or {}
    employees = _value(envelope, "employee_count")
    website = _value(envelope, "official_website")
    jobs = _value(envelope, "job_postings") or {}
    news = _value(envelope, "public_news") or {}
    summary = (envelope.get("synthesis") or {}).get("summary") or ""
    industry_label = industry.get("label") if isinstance(industry, dict) else ""
    place = municipality.get("name") if isinstance(municipality, dict) else ""
    employee_text = f"{employees} employees" if employees is not None else "employee count not published"
    site_text = "verified website" if website else "no verified website"
    job_count = len((jobs.get("postings") or [])) if isinstance(jobs, dict) else 0
    news_count = len((news.get("items") or [])) if isinstance(news, dict) else 0
    facts = " · ".join(part for part in (place, industry_label, employee_text, site_text, f"{job_count} NAV ads" if job_count else "", f"{news_count} news" if news_count else "") if part)
    return f"""<article class="card" data-text="{_esc(' '.join([org, name, facts]).casefold())}">
<h2>{_esc(name)}</h2>
<p class="meta">{_esc(org)} · {_esc(facts)}</p>
<p>{_esc(summary)}</p>
<p><a href="https://virksomhet.brreg.no/nb/oppslag/enheter/{_esc(org)}">Brønnøysund record</a></p>
</article>"""


def render_static(envelopes: list[dict[str, Any]]) -> str:
    cards = "\n".join(_static_card(item) for item in envelopes)
    verified = sum(1 for item in envelopes if _value(item, "official_website"))
    jobs = sum(1 for item in envelopes if _value(item, "job_postings"))
    news = sum(1 for item in envelopes if _value(item, "public_news"))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signalpost companies</title>
<style>
:root {{ color-scheme: light; --ink:#1c1915; --muted:#5c564c; --line:#e4dccb; --paper:#f6f1e7; --card:#fffdf8; --green:#0f6e56; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font:16px/1.45 Georgia, serif; color:var(--ink); background:var(--paper); }}
header {{ padding:1rem; border-bottom:1px solid var(--line); background:var(--card); position:sticky; top:0; }}
h1 {{ font-size:1.25rem; margin:0; }}
main {{ padding:1rem; max-width:720px; margin:0 auto; }}
input {{ font:inherit; width:100%; padding:.7rem; border:1px solid var(--line); border-radius:10px; margin-top:.7rem; }}
.stats {{ color:var(--muted); font-size:.92rem; margin:.4rem 0 0; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:.9rem 1rem; margin:.75rem 0; }}
.card h2 {{ font-size:1.05rem; margin:0 0 .25rem; }}
.meta {{ color:var(--muted); font-size:.92rem; margin:0 0 .5rem; }}
a {{ color:var(--green); }}
</style>
</head>
<body>
<header>
<h1>Signalpost</h1>
<p class="stats">{len(envelopes)} profiles · {verified} verified websites · {jobs} with NAV ads · {news} with dated news</p>
<input id="q" type="search" placeholder="Search name, place, industry, or organisation number" aria-label="Search companies">
</header>
<main id="list">
{cards}
</main>
<script>
const input = document.getElementById("q");
const cards = Array.from(document.querySelectorAll(".card"));
input.addEventListener("input", () => {{
  const needle = input.value.trim().toLowerCase();
  for (const card of cards) {{
    card.hidden = needle.length > 0 && !card.dataset.text.includes(needle);
  }}
}});
</script>
</body>
</html>
"""


def write_static(source: Path, destination: Path) -> int:
    envelopes = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_static(envelopes), encoding="utf-8")
    return len(envelopes)


def serve(path: Path, host: str, port: int) -> None:
    envelopes = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    viewer = Viewer(envelopes)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            split = urlsplit(self.path)
            status, body, content_type = viewer.handle(split.path, parse_qs(split.query))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Signalpost viewer at http://{host}:{port} ({len(envelopes)} profiles)")
    server.serve_forever()
