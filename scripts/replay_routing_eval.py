#!/usr/bin/env python3
"""Replay supplied classifier answers offline; no inference or network is permitted."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jevkit import route


def replay(dataset, config, catalog):
    results = []
    effective_config = {**route.DEFAULT_CONFIG, **config, "cache_repeat_asks": False}
    with patch.object(route.client, "ask", side_effect=AssertionError("offline replay forbids RPC")):
        for case in dataset:
            if not isinstance(case.get("answers"), dict):
                raise ValueError("each case needs recorded or synthetic classifier answers")
            decision = route.decide(
                case["prompt"], current=case["current"], only_provider=case["provider"],
                pinned=bool(case.get("pinned")), has_images=bool(case.get("has_images")),
                context_tokens=int(case.get("context_tokens", 0)),
                answers=case["answers"], config=effective_config, rows=catalog)
            results.append({"case_id": case["case_id"], "category": case["category"],
                            "routed": decision.get("routed"), "model": decision.get("model"),
                            "tier": decision.get("tier"), "reason": decision.get("reason"),
                            "evidence": "offline policy replay, not model execution"})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "config", "catalog"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(json.loads(args.dataset.read_text()),
                            json.loads(args.config.read_text()),
                            json.loads(args.catalog.read_text())), indent=2))
