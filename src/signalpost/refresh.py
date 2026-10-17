"""Idempotent refresh diffs. Same claim values produce no changes and no duplicate facts."""

from __future__ import annotations

import json
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def claim_map(envelope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for claim in envelope.get("claims") or []:
        field = claim.get("field")
        if not field or field == "synthesis":
            continue
        mapped[field] = claim
    return mapped


def diff_envelopes(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {
            "previous_supplied": False,
            "previous_run_id": None,
            "material_change_count": 0,
            "idempotent_rerun": None,
            "changes": [],
        }
    current_claims = claim_map(current)
    previous_claims = claim_map(previous)
    changes: list[dict[str, Any]] = []
    for field in sorted(set(current_claims) | set(previous_claims)):
        now = current_claims.get(field)
        then = previous_claims.get(field)
        now_key = None if now is None else (now.get("availability"), _canonical(now.get("value")))
        then_key = None if then is None else (then.get("availability"), _canonical(then.get("value")))
        if now_key == then_key:
            continue
        if then is None:
            change_type = "new_claim"
        elif now is None:
            change_type = "removed_claim"
        else:
            change_type = "changed_value"
        changes.append(
            {
                "field": field,
                "change_type": change_type,
                "material": True,
                "previous_value": None if then is None else then.get("value"),
                "previous_availability": None if then is None else then.get("availability"),
                "current_value": None if now is None else now.get("value"),
                "current_availability": None if now is None else now.get("availability"),
                "previous_evidence_ids": [] if then is None else list(then.get("evidence_ids") or []),
                "current_evidence_ids": [] if now is None else list(now.get("evidence_ids") or []),
                "previous_retrieved_from": (previous.get("run") or {}).get("completed_at"),
                "current_retrieved_from": (current.get("run") or {}).get("completed_at"),
            }
        )
    return {
        "previous_supplied": True,
        "previous_run_id": (previous.get("run") or {}).get("run_id"),
        "material_change_count": len(changes),
        "idempotent_rerun": len(changes) == 0,
        "changes": changes,
    }
