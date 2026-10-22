"""Analyze retained benchmark evidence without any model or network calls."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import statistics


def percentile(values, p):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    a, z = math.floor(pos), math.ceil(pos)
    return ordered[a] + (ordered[z] - ordered[a]) * (pos - a)


def wilson(correct, n):
    z = 1.959963984540054
    p = correct / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0, center - half), min(1, center + half)]


def paired_interval(deltas, fn=statistics.mean):
    rng = random.Random(20261022)
    values = [fn(rng.choices(deltas, k=len(deltas))) for _ in range(10000)]
    return [percentile(values, .025), percentile(values, .975)]


def mcnemar(a_only, b_only):
    n = a_only + b_only
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(a_only, b_only) + 1)) / (2 ** n)) if n else 1.0


def analyze(records):
    result = {"n": len(records), "arms": {}, "suites": {}, "usage_complete": True}
    for arm in ("A", "B"):
        rows = [r[arm] for r in records]
        correct = sum(r["correct"] for r in rows)
        native_tokens = {}
        for field in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
            vals = [r["llm"].get("usage", {}).get(field) for r in rows]
            native_tokens[field] = sum(vals) if all(type(v) is int for v in vals) else None
        result["arms"][arm] = {"correct": correct, "accuracy": correct / len(rows),
            "accuracy_wilson95": wilson(correct, len(rows)),
            "failures": sum(r["llm"]["status"] != "ok" for r in rows),
            "wall_mean_ms": statistics.mean(r["wall_ms"] for r in rows),
            "wall_median_ms": statistics.median(r["wall_ms"] for r in rows),
            "wall_p95_ms": percentile([r["wall_ms"] for r in rows], .95),
            "wall_total_ms": sum(r["wall_ms"] for r in rows), "tokens": native_tokens}
        result["usage_complete"] &= all(v is not None for v in native_tokens.values())
    a_only = sum(r["A"]["correct"] and not r["B"]["correct"] for r in records)
    b_only = sum(r["B"]["correct"] and not r["A"]["correct"] for r in records)
    result["accuracy_pairing"] = {"A_only_correct": a_only, "B_only_correct": b_only,
        "exact_mcnemar_p": mcnemar(a_only, b_only)}
    deltas = [r["B"]["wall_ms"] - r["A"]["wall_ms"] for r in records]
    result["latency_pairing"] = {"mean_delta_ms": statistics.mean(deltas),
        "median_delta_ms": statistics.median(deltas),
        "mean_delta_bootstrap95_ms": paired_interval(deltas),
        "median_delta_bootstrap95_ms": paired_interval(deltas, statistics.median),
        "B_faster_pairs": sum(d < 0 for d in deltas)}
    calls = [c for r in records for c in r["B"]["jev"]["calls"]]
    result["jev"] = {"calls": len(calls), "answered": sum(c["outcome"] == "answered" for c in calls),
        "failed": sum(c["outcome"] != "answered" for c in calls),
        "bypass_cases": sum(not r["B"]["jev"]["calls"] for r in records),
        "adapter_wall_mean_ms": statistics.mean(r["B"]["jev"]["wall_ms"] for r in records),
        "adapter_wall_median_ms": statistics.median(r["B"]["jev"]["wall_ms"] for r in records),
        "models": sorted({c.get("reply", {}).get("jev_model") for c in calls if c.get("reply", {}).get("jev_model")}),
        "provider": sorted({c.get("reply", {}).get("provider") for c in calls if c.get("reply", {}).get("provider")}),
        "call_failures": dict(Counter(c.get("reason_code", "unknown") for c in calls if c["outcome"] != "answered")),
        "tokens": {}}
    for field in ("input_tokens", "output_tokens"):
        vals = [c.get("reply", {}).get("usage", {}).get(field) for c in calls]
        result["jev"]["tokens"][field] = {"known_total": sum(v for v in vals if type(v) is int),
            "missing_calls": sum(type(v) is not int for v in vals)}
    for suite in sorted({r["suite"] for r in records}):
        subset = [r for r in records if r["suite"] == suite]
        def total(arm, field):
            vals = [r[arm]["llm"].get("usage", {}).get(field) for r in subset]
            return sum(vals) if all(type(v) is int for v in vals) else None
        result["suites"][suite] = {"n": len(subset), **{arm: {
            "correct": sum(r[arm]["correct"] for r in subset),
            "median_ms": statistics.median(r[arm]["wall_ms"] for r in subset),
            "input_tokens": total(arm, "input_tokens"),
            "output_tokens": total(arm, "output_tokens")
        } for arm in ("A", "B")}}
        suite_calls = [c for r in subset for c in r["B"]["jev"]["calls"]]
        result["suites"][suite]["jev"] = {"calls": len(suite_calls), "tokens": {}}
        for field in ("input_tokens", "output_tokens"):
            vals = [c.get("reply", {}).get("usage", {}).get(field) for c in suite_calls]
            result["suites"][suite]["jev"]["tokens"][field] = sum(vals) if all(type(v) is int for v in vals) else None
    result["errors"] = [{"id": r["id"], "suite": r["suite"], "expected": r["expected"],
                          "A": r["A"]["llm"].get("choice"), "B": r["B"]["llm"].get("choice"),
                          "advice": r["B"]["jev"]["advice"]}
                         for r in records if not (r["A"]["correct"] and r["B"]["correct"])]
    result["advisory_mismatches"] = [{"id": r["id"], "expected": r["expected"],
                                    "suggestions": r["B"]["jev"]["advice"]["suggested_choices"],
                                    "B": r["B"]["llm"].get("choice")}
                                   for r in records if r["B"]["jev"]["calls"] and not
                                   set(r["expected"]) & set(r["B"]["jev"]["advice"]["suggested_choices"])]
    result["advisory_multi_choice"] = [r["id"] for r in records if len(r["B"]["jev"]["advice"]["suggested_choices"]) > 1]
    result["workflow_gate"] = []
    for r in records:
        if r["suite"] != "jev" or not r["B"]["jev"]["calls"]:
            continue
        answers = r["B"]["jev"]["calls"][0].get("reply", {}).get("answers", {})
        result["workflow_gate"].append({"id": r["id"], "expected": r["expected"],
            "raw_workflow": answers.get("workflow", {}).get("choice"),
            "confidence": answers.get("workflow", {}).get("confidence"),
            "workflow_needed": answers.get("workflow_needed", {}).get("noul"),
            "surfaced": r["B"]["jev"]["advice"]["suggested_choices"]})
    return result


def markdown(value, manifest, run):
    a, b = (value["arms"][k] for k in ("A", "B"))
    j = value["jev"]
    delta = value["latency_pairing"]
    ci = delta["mean_delta_bootstrap95_ms"]
    sec = lambda x: f"{x / 1000:.3f} s"
    number = lambda x: f"{x:,}" if x is not None else "Unknown"
    n = value["n"]
    conclusion = (f"Observed accuracy change: {(b['accuracy']-a['accuracy'])*100:+.1f} percentage points. "
                  + ("The paired latency interval includes zero; this run does not establish a speed improvement. "
                     if ci[0] <= 0 <= ci[1] else "See the paired latency interval below. ")
                  + "The advisor adds separate Jev token usage while retaining the native LLM call.")
    lines = ["# Skills Routing A/B Benchmark", "", conclusion, "",
        f"Run: `{run.name}`; {n} paired cases / {2*n} native LLM calls.", "",
        f"Same configured model: `{manifest['model']}` / `{manifest['effort']}` / `{manifest['service_tier']}`. "
        f"Observed Jev: `{', '.join(j['models'])}`. Synthetic English/Chinese cases; gold frozen before prediction.", "",
        "A = LLM-only. B = installed Jev advisor followed by the same LLM, which owns final selection.", "",
        "| Metric | A: LLM-only | B: LLM + Jev |", "|---|---:|---:|",
        f"| Routing accuracy | {a['correct']}/{n} ({a['accuracy']:.1%}) | {b['correct']}/{n} ({b['accuracy']:.1%}) |",
        f"| Mean wall time / case | {sec(a['wall_mean_ms'])} | {sec(b['wall_mean_ms'])} |",
        f"| Median wall time / case | {sec(a['wall_median_ms'])} | {sec(b['wall_median_ms'])} |",
        f"| p95 wall time / case | {sec(a['wall_p95_ms'])} | {sec(b['wall_p95_ms'])} |",
        f"| Native LLM input tokens | {number(a['tokens']['input_tokens'])} | {number(b['tokens']['input_tokens'])} |",
        f"| Native LLM cached input tokens (subset) | {number(a['tokens']['cached_input_tokens'])} | {number(b['tokens']['cached_input_tokens'])} |",
        f"| Native LLM uncached input tokens | {number(a['tokens']['input_tokens']-a['tokens']['cached_input_tokens']) if value['usage_complete'] else 'Unknown'} | {number(b['tokens']['input_tokens']-b['tokens']['cached_input_tokens']) if value['usage_complete'] else 'Unknown'} |",
        f"| Native LLM output tokens | {number(a['tokens']['output_tokens'])} | {number(b['tokens']['output_tokens'])} |",
        f"| Native LLM reasoning tokens (subset of output) | {number(a['tokens']['reasoning_output_tokens'])} | {number(b['tokens']['reasoning_output_tokens'])} |",
        f"| Jev input tokens, known | 0 | {number(j['tokens']['input_tokens']['known_total'])} |",
        f"| Jev output tokens, known | 0 | {number(j['tokens']['output_tokens']['known_total'])} |",
        f"| Native failures | {a['failures']} | {b['failures']} |", "",
        f"Paired mean wall-time difference (B − A): **{sec(delta['mean_delta_ms'])}**. "
        f"95% paired bootstrap interval: [{sec(ci[0])}, {sec(ci[1])}], 10,000 resamples, seed 20261022. "
        f"B was faster on {delta['B_faster_pairs']}/{n} pairs. These intervals resample cases from one run; "
        "they do not measure repeated-run network or model variance.", "",
        f"Accuracy discordances: B-only correct {value['accuracy_pairing']['B_only_correct']}; "
        f"A-only correct {value['accuracy_pairing']['A_only_correct']}; "
        f"exact two-sided McNemar p={value['accuracy_pairing']['exact_mcnemar_p']:.4f}. "
        f"A Wilson 95% interval [{a['accuracy_wilson95'][0]:.1%}, {a['accuracy_wilson95'][1]:.1%}]; "
        f"B [{b['accuracy_wilson95'][0]:.1%}, {b['accuracy_wilson95'][1]:.1%}].", "",
        "## Per Suite", "", "| Suite | Cases | A correct | B correct | A median | B median |", "|---|---:|---:|---:|---:|---:|"]
    for suite, row in value["suites"].items():
        lines.append(f"| {suite} | {row['n']} | {row['A']['correct']} | {row['B']['correct']} | {sec(row['A']['median_ms'])} | {sec(row['B']['median_ms'])} |")
    lines += ["", "| Suite | A LLM input + output | B LLM input + output | Additional Jev input + output | Jev calls |", "|---|---:|---:|---:|---:|"]
    for suite, row in value["suites"].items():
        def add(x, y):
            return x + y if x is not None and y is not None else None
        lines.append(f"| {suite} | {number(add(row['A']['input_tokens'], row['A']['output_tokens']))} | "
                     f"{number(add(row['B']['input_tokens'], row['B']['output_tokens']))} | "
                     f"{number(add(row['jev']['tokens']['input_tokens'], row['jev']['tokens']['output_tokens']))} | {row['jev']['calls']} |")
    lines += ["", "## Jev And Usage Accounting", "",
        f"{j['calls']} actual API attempts, {j['answered']} answered, {j['failed']} failed; "
        f"{j['bypass_cases']} cases used adapter local bypasses. Mean adapter overhead across all cases "
        f"{sec(j['adapter_wall_mean_ms'])}, median {sec(j['adapter_wall_median_ms'])}.", "",
        f"Jev usage missing on {j['tokens']['input_tokens']['missing_calls']} input-token receipts and "
        f"{j['tokens']['output_tokens']['missing_calls']} output-token receipts. Unknown usage is not zero.", ""]
    if value["usage_complete"] and not any(row["missing_calls"] for row in j["tokens"].values()):
        at = a["tokens"]["input_tokens"] + a["tokens"]["output_tokens"]
        bt = b["tokens"]["input_tokens"] + b["tokens"]["output_tokens"]
        jt = sum(row["known_total"] for row in j["tokens"].values())
        lines += [f"Native input + output: A {at:,}; B {bt:,} ({(bt/at-1):+.2%}). "
                  f"B plus Jev: {bt+jt:,} ({((bt+jt)/at-1):+.2%}). The cross-provider sum is a "
                  "descriptive count across different tokenizers, not a money, credit or subscription quota estimate.", ""]
    lines += ["## Errors And Advisory Disagreements", ""]
    if value["errors"]:
        lines += ["| Case | Gold | A | B | Jev suggestions |", "|---|---|---|---|---|"]
        for r in value["errors"]:
            lines.append(f"| {r['id']} | {', '.join(r['expected'])} | {r['A']} | {r['B']} | {', '.join(r['advice']['suggested_choices']) or 'abstain'} |")
    else:
        lines += ["No final LLM routing errors on this set."]
    lines += ["", f"Called-adapter suggestions excluded every gold label on {len(value['advisory_mismatches'])} cases. "
              f"Multiple entrypoint suggestions occurred on {len(value['advisory_multi_choice'])} cases. "
              "These are advice diagnostics, not a third Jev-only classification arm.", ""]
    for r in value["advisory_mismatches"]:
        lines.append(f"- `{r['id']}`: gold `{', '.join(r['expected'])}`; advice `{', '.join(r['suggestions']) or 'abstain'}`; final B `{r['B']}`.")
    if value["workflow_gate"]:
        lines += ["", "The Jev workflow adapter separately gates whether assistance is materially needed. "
                  "An absent workflow becomes no recommendation (`none`) in this benchmark. A correct raw "
                  "workflow suppressed by this gate is not a wrong raw classification. The current 0.6 "
                  "necessity threshold was retained throughout; no post-hoc tuning occurred.", "",
                  "| Case | Raw workflow | Confidence | workflow_needed | Surfaced advice |", "|---|---|---:|---:|---|"]
        for r in value["workflow_gate"]:
            lines.append(f"| {r['id']} | {r['raw_workflow']} | {r['confidence']} | {r['workflow_needed']} | {', '.join(r['surfaced'])} |")
    lines += ["", "## Interpretation And Limits", "",
        "This tests the incremental effect of adding an advisor while retaining the main LLM and the same catalog. "
        "It does not test replacing the LLM, pruning its context, or total implementation/release/review performance.", "",
        "The B arm explicitly enters each installed adapter and honors its local bypasses. In normal use, the "
        "main agent can skip clear/settled choices before calling an adapter; that discretionary gate is not measured. "
        "Autotrigger appears only in entrypoint selection because it has no internal Jev router. Native-review "
        "cases select already admitted candidate subsets; no reviewer was dispatched. Two native cases contain "
        "fictional capability constraints and establish nothing about real provider capabilities.", "",
        "40 development cases, half Chinese and half English, one sample per arm. Labels were independently "
        "authored by a sub-agent from the contracts, not by human adjudicators; one Matt case accepts overlapping "
        "labels. The set covers only some available routes and can have a ceiling effect on a strong model. "
        "A/B order was balanced and case order seeded, but network, service load and inference randomness remain.", "",
        "Automatic prompt caching was not forced or disabled. The arms received different cached-token totals "
        "(shown above), so wall time should not be interpreted as isolated model compute time or a cache-controlled "
        "microbenchmark. Different input-token cache treatment also prevents inferring money or credits from raw totals.", "",
        "Wall time includes process startup and network. Native prompt context includes Codex scaffolding and "
        "automatically supplied skill context; the same context and catalog are retained per pair. No model "
        "switch, hook/config edit, actual workflow execution or purchased route occurred. Model identity is "
        "native CLI configuration evidence; Jev version comes from API responses.", "",
        "The harness prepends adapter advice before the LLM call. It does not verify automatic host-hook "
        "activation or measure additional LLM/tool round trips required by a manually invoked advisor. "
        "Setup, dataset authorship, the transport smoke and report generation are outside the scored totals.", "",
        "## Reproduction And Evidence", "",
        f"- Frozen cases SHA-256: `{manifest['cases_sha256']}`.",
        f"- Executed harness SHA-256: `{manifest['harness_sha256']}`.",
        f"- Adapter/skill sources unchanged during run: `{manifest.get('sources_unchanged')}`.",
        "- `manifest.json`: configured model, timestamps, source hashes and paired design.",
        "- `cases.frozen.json`: frozen requests, gold labels and rationales.",
        "- `records.json`: every paired result, actual usage and Jev call receipts.",
        "- Per-case `prompt.json`, `events.jsonl`, `command.json`: exact packets and native evidence.",
        "- `analysis.json`: machine-readable analysis, intervals and advisory diagnostics.",
        "- `audit.json`: all 40 packet comparisons, exact native model settings, gold isolation, raw usage, "
        "source hashes, 20/20 order balance and zero native tool activity verified.",
        "- Parent README documents commands and treatment definitions.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    records = json.loads((run / "records.json").read_text(encoding="utf-8"))
    if len(records) != manifest["case_count"] or not manifest.get("sources_unchanged"):
        raise ValueError("Incomplete run or changed installed sources; inspect before final analysis")
    if hashlib.sha256((run / "cases.frozen.json").read_bytes()).hexdigest() != manifest["cases_sha256"]:
        raise ValueError("Frozen dataset hash changed")
    value = analyze(records)
    (run / "analysis.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run / "REPORT.md").write_text(markdown(value, manifest, run), encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
