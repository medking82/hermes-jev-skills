"""Read-only cross-check of frozen labels, actual packets and retained CLI evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import benchmark as b


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit(run):
    manifest = load(run / "manifest.json")
    cases = {c["id"]: c for c in load(run / "cases.frozen.json")["cases"]}
    records = load(run / "records.json")
    assert len(records) == len(cases) == manifest["case_count"]
    assert {r["id"] for r in records} == cases.keys()
    assert manifest["sources_unchanged"]
    assert manifest["cases_sha256"] == b.digest(run / "cases.frozen.json")
    assert manifest["harness_sha256"] == b.digest(Path(b.__file__))
    assert manifest["sources_sha256"] == b.source_hashes()
    counts = {"pairs": len(records), "native_calls": 0, "jev_calls": 0,
              "model_packet_pairs_equal_except_advice": 0, "first_A": 0, "first_B": 0}
    for r in records:
        case = cases[r["id"]]
        assert r["expected"] == case["expected"] and r["suite"] == case["suite"]
        assert sorted(r["order"]) == ["A", "B"]
        counts["first_" + r["order"][0]] += 1
        ap = load(run / r["id"] / "A/prompt.json")
        bp = load(run / r["id"] / "B/prompt.json")
        assert bp.pop("jev_advice") == r["B"]["jev"]["advice"]
        assert ap == bp == b.contract(case)
        assert not {"expected", "rationale", "id"} & ap.keys()
        counts["model_packet_pairs_equal_except_advice"] += 1
        assert load(run / r["id"] / "A/schema.json") == load(run / r["id"] / "B/schema.json")
        for arm in ("A", "B"):
            directory = run / r["id"] / arm
            assert not list((directory / "isolated").rglob("*")), "Unexpected classifier file write"
            assert (directory / "instructions.txt").read_text(encoding="utf-8") == b.SYSTEM
            packet = load(directory / "command.json")
            argv = packet["arguments"]
            assert argv[argv.index("--model") + 1] == manifest["model"]
            assert 'model_reasoning_effort="' + manifest["effort"] + '"' in argv
            assert 'service_tier="' + manifest["service_tier"] + '"' in argv
            assert "features.hooks=false" in argv and 'model_provider="openai"' in argv
            assert "--ignore-user-config" in argv and "--ephemeral" in argv
            assert argv[argv.index("--sandbox") + 1] == "read-only"
            result = r[arm]["llm"]
            if result["status"] == "ok":
                stdout = (directory / "events.jsonl").read_text(encoding="utf-8")
                answer, evidence = b.NATIVE.parse_output(stdout, 0, manifest["model"])
                assert answer["choice"] == result["choice"]
                assert evidence["usage"] == result["usage"]
                assert hashlib.sha256(stdout.encode()).hexdigest() == result["output_sha256"]
            assert r[arm]["correct"] == (result.get("choice") in case["expected"])
            assert r[arm]["wall_ms"] >= result["wall_ms"]
            counts["native_calls"] += 1
        for call in r["B"]["jev"]["calls"]:
            assert call["retries"] == 0
            if call["outcome"] == "answered":
                assert call["reply"]["provider"] == "typesafe"
                assert call["reply"]["input_tokens"] == call["reply"]["usage"]["input_tokens"]
            counts["jev_calls"] += 1
    assert abs(counts["first_A"] - counts["first_B"]) <= 1
    return {"status": "passed", **counts, "source_hashes_match": True,
            "gold_excluded_from_packets": True, "native_tool_activity": 0,
            "unexpected_classifier_files": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = audit(args.run_dir.resolve())
    b.dump(args.run_dir / "audit.json", result)
    print(json.dumps(result))
