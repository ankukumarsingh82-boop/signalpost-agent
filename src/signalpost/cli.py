"""One command for an official batch: read organisation numbers, write one envelope each."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .agent import research_company
from .envelope import apply_refresh_metadata
from .http_client import HttpClient
from .inputs import read_organisations
from .refresh import diff_envelopes
from .validate import validate_envelopes
from .wikidata import fetch_wikidata


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _previous_map(path: str | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(Path(path)):
        org = row.get("organisation_number")
        if org:
            mapped[str(org)] = row
    return mapped


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _claim_available(envelope: dict[str, Any], field: str) -> bool:
    for claim in envelope.get("claims") or []:
        if claim.get("field") == field and claim.get("availability") == "available":
            return True
    return False


def _report(envelopes: list[dict[str, Any]], *, run_id: str, started_at: str, completed_at: str, elapsed_ms: int, validation: dict[str, Any], resumed: int) -> dict[str, Any]:
    runtimes = [int((item.get("operations") or {}).get("runtime_ms") or 0) for item in envelopes]
    requests = sum(int((item.get("operations") or {}).get("requests") or 0) for item in envelopes)
    families = {
        "legal_name": sum(_claim_available(item, "legal_name") for item in envelopes),
        "annual_accounts": sum(_claim_available(item, "annual_accounts") for item in envelopes),
        "leadership": sum(_claim_available(item, "leadership") for item in envelopes),
        "registered_workplaces": sum(_claim_available(item, "registered_workplaces") for item in envelopes),
        "official_website": sum(_claim_available(item, "official_website") for item in envelopes),
        "hiring_pages": sum(_claim_available(item, "hiring_pages") for item in envelopes),
        "wikipedia_summary": sum(_claim_available(item, "wikipedia_summary") for item in envelopes),
        "wikidata_description": sum(_claim_available(item, "wikidata_description") for item in envelopes),
        "company_profile": sum(
            any(claim.get("field", "").startswith("company_profile.") and claim.get("availability") == "available" for claim in item.get("claims") or [])
            for item in envelopes
        ),
    }
    terminal = {}
    for item in envelopes:
        status = (item.get("run") or {}).get("terminal_status")
        terminal[status] = terminal.get(status, 0) + 1
    return {
        "agent": "signalpost",
        "version": __version__,
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "elapsed_ms": elapsed_ms,
        "input_count": len(envelopes),
        "emitted_envelopes": len(envelopes),
        "resumed_profiles": resumed,
        "terminal_status": terminal,
        "field_coverage": families,
        "operations": {
            "requests": requests,
            "http_requests_including_shared_lookups": None,
            "runtime_ms": elapsed_ms,
            "third_party_cost_usd": 0,
            "p50_ms": _percentile(runtimes, 0.50),
            "p95_ms": _percentile(runtimes, 0.95),
            "mean_ms": int(statistics.fmean(runtimes)) if runtimes else None,
        },
        "models": [],
        "apis": [
            "https://data.brreg.no/enhetsregisteret/api (NLOD)",
            "https://data.brreg.no/regnskapsregisteret/regnskap (NLOD)",
            "https://query.wikidata.org/sparql (CC0)",
            "https://*.wikipedia.org/api/rest_v1/page/summary (CC BY-SA)",
            "company websites listed in the entity register, fetched only when robots.txt allows",
        ],
        "validation": validation,
    }


def run_batch(args: argparse.Namespace) -> int:
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    orgs = read_organisations(args.input)
    if args.limit:
        orgs = orgs[: args.limit]
    output = Path(args.output)
    done: dict[str, dict[str, Any]] = {}
    resumed = 0
    if args.resume and output.exists():
        for row in _read_jsonl(output):
            org = str(row.get("organisation_number") or "")
            if org:
                done[org] = row
        resumed = sum(1 for org in orgs if org in done)
    pending = [org for org in dict.fromkeys(orgs) if org not in done]
    client = HttpClient(timeout=args.timeout, retries=args.retries)
    wiki: dict[str, dict[str, Any]] = {}
    if pending and not args.skip_wikidata:
        print(f"Looking up Wikidata for {len(pending)} organisation numbers...", file=sys.stderr)
        wiki = fetch_wikidata(client, pending)
        print(f"Wikidata matched {len(wiki)} organisation numbers.", file=sys.stderr)
    run_id = args.run_id or _utc_stamp()
    run = {"run_id": run_id, "started_at": started_at, "completed_at": started_at}
    lock = threading.Lock()
    completed = 0

    def one(org: str) -> dict[str, Any]:
        try:
            return research_company(org, client, wiki.get(org), run, skip_website=args.skip_website)
        except Exception as exc:
            return research_company_failure(org, run, exc)

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(one, org): org for org in pending}
            for future in as_completed(futures):
                org = futures[future]
                try:
                    envelope = future.result()
                except Exception as exc:
                    envelope = research_company_failure(org, run, exc)
                with lock:
                    done[org] = envelope
                    completed += 1
                    if completed % args.checkpoint_every == 0 or completed == len(pending):
                        _write_jsonl(output, [done[item] for item in orgs if item in done])
                        print(f"checkpoint {completed}/{len(pending)}", file=sys.stderr)
    completed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run["completed_at"] = completed_at
    previous = _previous_map(args.previous)
    ordered: list[dict[str, Any]] = []
    for org in orgs:
        envelope = done[org]
        envelope = json.loads(json.dumps(envelope))
        envelope["run"]["run_id"] = run_id
        envelope["run"]["started_at"] = started_at
        envelope["run"]["completed_at"] = completed_at
        refresh = diff_envelopes(envelope, previous.get(org))
        apply_refresh_metadata(envelope, refresh)
        ordered.append(envelope)
    validation = validate_envelopes(ordered, orgs)
    _write_jsonl(output, ordered)
    report = _report(
        ordered,
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        validation=validation,
        resumed=resumed,
    )
    report["operations"]["http_requests_including_shared_lookups"] = client.request_count
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("run_id", "emitted_envelopes", "field_coverage", "operations", "validation")}, ensure_ascii=False, indent=2))
    return 0 if validation["passed"] else 1


def research_company_failure(org: str, run: dict[str, Any], exc: Exception) -> dict[str, Any]:
    from .envelope import build_envelope

    return build_envelope(
        org,
        {
            "entity": {"availability": "failed", "note": f"Unhandled error: {exc}"},
            "accounts": {"availability": "failed", "note": "Unhandled error."},
            "roles": {"availability": "failed", "note": "Unhandled error."},
            "workplaces": {"availability": "failed", "note": "Unhandled error."},
            "group": {"availability": "failed", "note": "Unhandled error."},
            "website": {"availability": "failed", "note": "Unhandled error."},
            "wiki": {"availability": "failed", "note": "Unhandled error."},
            "errors": [{"error": str(exc)}],
            "terminal_status": "failed",
            "operations": {"requests": 0, "runtime_ms": 0},
        },
        run,
    )


def check_batch(args: argparse.Namespace) -> int:
    envelopes = _read_jsonl(Path(args.input))
    expected = read_organisations(args.expected_input) if args.expected_input else None
    validation = validate_envelopes(envelopes, expected)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signalpost", description="Signalpost company research agent")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Research every organisation number in the supplied file")
    run.add_argument("--input", required=True, help="Text, JSON, or JSONL file of organisation numbers supplied for this run")
    run.add_argument("--output", required=True, help="JSONL path for one terminal envelope per input")
    run.add_argument("--report", required=True, help="JSON path for the machine-readable run report")
    run.add_argument("--previous", help="Earlier envelope JSONL. Used only to report material changes")
    run.add_argument("--run-id", help="Stable run identifier. Defaults to a UTC timestamp")
    run.add_argument("--workers", type=int, default=8)
    run.add_argument("--timeout", type=float, default=20.0)
    run.add_argument("--retries", type=int, default=2)
    run.add_argument("--checkpoint-every", type=int, default=25)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--skip-website", action="store_true")
    run.add_argument("--skip-wikidata", action="store_true")
    run.add_argument("--limit", type=int, help="Debug cap. Omit this on an official run")
    run.set_defaults(func=run_batch)

    check = sub.add_parser("check", help="Validate an envelope JSONL file")
    check.add_argument("--input", required=True)
    check.add_argument("--expected-input", help="Organisation file the envelopes must match in order")
    check.set_defaults(func=check_batch)

    view = sub.add_parser("view", help="Open a local browser for the envelopes")
    view.add_argument("--input", required=True)
    view.add_argument("--host", default="127.0.0.1")
    view.add_argument("--port", type=int, default=8765)
    view.set_defaults(func=_view)

    return parser


def _view(args: argparse.Namespace) -> int:
    from .view import serve

    serve(Path(args.input), args.host, args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
