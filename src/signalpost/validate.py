"""Contract checks for a batch of terminal envelopes."""

from __future__ import annotations

from typing import Any

from .envelope import ALLOWED_AVAILABILITY

REQUIRED_KEYS = ("organisation_number", "run", "claims", "evidence", "changes", "errors", "operations")
RUN_KEYS = ("run_id", "started_at", "completed_at", "terminal_status")


def validate_envelopes(envelopes: list[dict[str, Any]], expected_orgs: list[str] | None = None) -> dict[str, Any]:
    issues: list[str] = []
    orgs = [item.get("organisation_number") for item in envelopes]
    if expected_orgs is not None:
        if orgs != expected_orgs:
            issues.append(f"envelope order/count does not match input ({len(orgs)} envelopes, {len(expected_orgs)} inputs)")
    if len(orgs) != len(envelopes):
        issues.append("missing organisation numbers")
    seen_cost = True
    for envelope in envelopes:
        org = envelope.get("organisation_number")
        for key in REQUIRED_KEYS:
            if key not in envelope:
                issues.append(f"{org}: missing {key}")
        run = envelope.get("run") or {}
        for key in RUN_KEYS:
            if key not in run:
                issues.append(f"{org}: run missing {key}")
        if run.get("terminal_status") not in {"completed", "failed"}:
            issues.append(f"{org}: bad terminal_status")
        evidence_ids = {item.get("id") for item in envelope.get("evidence") or []}
        fields: set[str] = set()
        for claim in envelope.get("claims") or []:
            field = claim.get("field")
            if field in fields:
                issues.append(f"{org}: duplicate claim field {field}")
            fields.add(field)
            availability = claim.get("availability")
            if availability not in ALLOWED_AVAILABILITY:
                issues.append(f"{org}: bad availability on {field}")
            if availability != "available" and claim.get("value") not in (None,):
                issues.append(f"{org}: non-available claim {field} carries a value")
            if availability == "available":
                if not claim.get("evidence_ids") and not (field == "synthesis" and not evidence_ids):
                    issues.append(f"{org}: available claim {field} has no evidence")
                if claim.get("value") is None and field not in {"organisation_status"}:
                    issues.append(f"{org}: available claim {field} has a null value")
            for evidence_id in claim.get("evidence_ids") or []:
                if evidence_id not in evidence_ids:
                    issues.append(f"{org}: claim {field} references missing evidence {evidence_id}")
        operations = envelope.get("operations") or {}
        if operations.get("third_party_cost_usd") not in (0, 0.0):
            seen_cost = False
            issues.append(f"{org}: undeclared third-party cost")
        if "synthesis" not in envelope:
            issues.append(f"{org}: missing synthesis")
    return {
        "passed": not issues,
        "envelope_count": len(envelopes),
        "issue_count": len(issues),
        "issues": issues[:30],
        "third_party_cost_ok": seen_cost,
    }
