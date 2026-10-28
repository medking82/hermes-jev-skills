#!/usr/bin/env python3
"""Offline, aggregate-only routing audit. Never prints prompts or raw event rows."""
import argparse
from collections import Counter
import json
from pathlib import Path


def _summarize(lines):
    counts, reasons, modes = Counter(), Counter(), Counter()
    effective = applied = first = first_applied = malformed = 0
    kinds = {"merged", "skill", "route", "route_effective", "skill_accepted",
             "skill_repeat", "skill_unreachable", "screen", "skill_suppressed", "effort"}
    for line in lines:
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("not an event")
        except (ValueError, TypeError):
            malformed += 1
            continue
        kind = row.get("kind")
        counts[kind if isinstance(kind, str) and kind in kinds else "unknown"] += 1
        if kind != "route_effective":
            continue
        effective += 1
        changed = row.get("applied") is True
        applied += changed
        is_first = row.get("first_request") is True
        first += is_first
        first_applied += changed and is_first
        # Historical reason strings can contain arbitrary configuration text. Count
        # only known policy categories; never echo untrusted strings into reports.
        reason = str(row.get("reason", ""))
        category = ("custom_alias_required" if "provider_aliases.custom" in reason
                    else "pinned" if reason == "you pinned this model"
                    else "other")
        reasons[category] += 1
        modes[str(row.get("mode")) if row.get("mode") in ("on", "shadow", "off") else "unknown"] += 1
    return {"events": dict(counts), "effective_requests": effective, "applied_requests": applied,
            "first_requests": first, "applied_first_requests": first_applied,
            "request_application_rate": applied / effective if effective else None,
            "first_request_application_rate": first_applied / first if first else None,
            "reason_categories": dict(reasons), "modes": dict(modes), "malformed": malformed,
            "scope": "middleware boundary; no execution or savings claim"}


def summarize(path):
    with path.open(encoding="utf-8") as handle:
        return _summarize(handle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.decisions), indent=2, sort_keys=True))
