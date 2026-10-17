"""Read a supplied organisation-number batch. The agent never chooses the companies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def normalise_org(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) != 9:
        raise ValueError(f"Invalid Norwegian organisation number: {value!r}")
    return digits


def read_organisations(path: str | Path) -> list[str]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    suffix = source.suffix.lower()
    if suffix == ".json":
        body = json.loads(text)
        rows = body if isinstance(body, list) else body.get("organisation_numbers") or body.get("organisations") or []
    elif suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        rows = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            rows.append(stripped)
    orgs: list[str] = []
    for row in rows:
        raw = row.get("organisation_number") if isinstance(row, dict) else row
        orgs.append(normalise_org(raw))
    if not orgs:
        raise ValueError(f"No organisation numbers in {source}")
    return orgs
