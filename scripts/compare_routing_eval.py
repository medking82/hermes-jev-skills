#!/usr/bin/env python3
"""Compare measured paired runs offline. This script never invokes a model."""
import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


MEASURED_COST_SOURCES = {"provider_invoice", "provider_billing", "gateway_billing"}


def _reference(value):
    return isinstance(value, str) and bool(value.strip())


def _human_review(row):
    reviewers = row.get("reviewer_ids")
    return (row.get("review_kind") == "human" and _reference(row.get("review_evidence_id"))
            and isinstance(reviewers, list) and bool(reviewers)
            and all(_reference(reviewer) for reviewer in reviewers)
            and len({reviewer.strip() for reviewer in reviewers}) == len(reviewers))


def compare(rows):
    pairs = defaultdict(dict)
    for row in rows:
        key = (row["case_id"], row["run_id"])
        arm = row["arm"]
        if arm not in ("baseline", "routed") or arm in pairs[key]:
            raise ValueError("invalid or duplicate arm")
        pairs[key][arm] = row
    deltas = defaultdict(list)
    excluded = Counter()
    reviewed = verified = paired = 0
    for arms in pairs.values():
        if set(arms) != {"baseline", "routed"}:
            continue
        paired += 1
        baseline, routed = arms["baseline"], arms["routed"]
        if baseline.get("category") != routed.get("category"):
            raise ValueError("paired category mismatch")
        kinds = [r.get("data_kind") for r in (baseline, routed)]
        if kinds != ["measured", "measured"]:
            reason = "synthetic" if kinds == ["synthetic", "synthetic"] else "missing_or_mixed_provenance"
            excluded[reason] += 1
            continue
        # Missing evidence must not silently turn into a zero-cost success.
        if not all(r.get("execution_verified") is True for r in (baseline, routed)):
            excluded["unverified_execution"] += 1
            continue
        if not all(_reference(r.get("execution_evidence_id")) for r in (baseline, routed)):
            excluded["missing_execution_evidence"] += 1
            continue
        verified += 1
        for metric in ("latency_ms", "actual_cost_usd", "input_tokens", "output_tokens"):
            values = [r.get(metric) for r in (baseline, routed)]
            if all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values):
                if metric == "actual_cost_usd":
                    if not all(isinstance(r.get("cost_source"), str)
                               and r["cost_source"] in MEASURED_COST_SOURCES
                               and _reference(r.get("cost_evidence_id")) for r in (baseline, routed)):
                        continue
                deltas[metric].append(values[1] - values[0])
        scores = [r.get("quality_score") for r in (baseline, routed)]
        if all(_human_review(r) for r in (baseline, routed)) and all(
                type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 4 for v in scores):
            reviewed += 1
            deltas["quality_score"].append(scores[1] - scores[0])
    return {"paired": paired, "unpaired": len(pairs) - paired,
            "excluded_pairs": dict(excluded), "provenance": "caller_attested_measurements",
            "execution_verified_pairs": verified, "human_reviewed_pairs": reviewed,
            "routed_minus_baseline": {k: {"n": len(v), "mean": mean(v)} for k, v in deltas.items()},
            "limitations": "Synthetic and unclassified pairs are excluded. Evidence references and declarations are validated structurally, not independently authenticated. Descriptive differences only; cost excludes JEV overhead unless included in input. No causal quality or savings claim."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path)
    args = parser.parse_args()
    with args.records.open(encoding="utf-8") as handle:
        result = compare([json.loads(line) for line in handle if line.strip()])
    print(json.dumps(result, indent=2))
