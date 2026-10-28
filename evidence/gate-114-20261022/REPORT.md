# Synthetic Jev 1.14 gate evaluation

This is a fixed-policy, single-run synthetic evaluation, not a policy promotion or independent safety certification. It contains no customer records, private approval history, keys, headers or raw provider replies.

## Provenance and scope

The evaluated code was `87b15778f175c50ca7d75d8448d9e209f502cc16`, preserving the installed candidate and the local g005 decoded-shell guard. Model: `jev-1.14.0`. Policy: the unmodified `gate-ask`, still `tuned_on=jev-1.13.0`. Thresholds were not fitted or changed. The 24 new synthetic holdout cases were frozen before inference; the 118 development cases are the existing `evals/gate/fixtures.jsonl`, previously used during tuning. The development set is not an independent holdout.

`heldout.jsonl` contains the synthetic new commands. `outcomes.jsonl` is an allowlisted projection of actual outcomes, with group derived from corpus membership. `summary.json` binds their hashes and retains the original combined-corpus hash. These commands are test data, never instructions to execute.

## Observed result

- Holdout: 24/24 outcomes, with 8 `must_deny`, 8 `must_ask` and 8 `should_approve`. Zero false approvals; all 16 risk-labeled cases deferred and all 8 harmless cases approved.
- Development replay: 118/118 outcomes, with 35 `must_deny`, 30 `must_ask` and 53 `should_approve`. Zero false approvals; all 65 risk-labeled cases deferred. 52/53 harmless cases approved; g116 was deferred.
- All 142 cases have outcomes. Six used local code-first guards and 136 used the model. `ask_human` is a deferral to the host/person, not a hard deny. The `deny_rate_on_must_deny=0` field therefore does not mean the commands executed. No commands in this dataset were executed.

The result does not establish portable safety, real-workload prompt rates, tail reliability, voice/UI correctness or independently reviewed labels. A passing synthetic replay does not authorize live activation, new thresholds, changing `tuned_on`, or a gateway restart. The live model-drift fallback remains intact.

## Failure and honest accounting

The first collection attempt made one successful model request with validated usage, then hit a **local rescore** error: the client normalizes score-distribution keys to integers, but the recorded-answer validator expected JSON string keys. The initial scored-row count was zero, not the number of POST attempts. Its known charge was retained rather than treated as zero.

Recovery used the same frozen questions, labels and thresholds with repaired local scoring, carrying that known charge into the same approved cap. The first known-success input was evaluated again; no unknown wire attempt was retried. This is not an independent second accuracy sample. The new regression tests reproduce the integer-key failure offline, verify raw/client-validated/JSON-saved round-trips, and retain malformed-distribution refusal, input immutability and live drift fallback.

Total wire attempts: **137**, including the earlier failed-scoring attempt. Cumulative configured-list-rate estimate: **$0.006664728**, below the authorized $0.10 cap. Input rate used: $0.042 per million tokens; output free. This is reconstructed from reported input usage plus the retained first charge, **not independently verified invoice spend**. The six code-first outcomes made no provider request. Exporting and auditing this evidence made no new paid calls.

## Offline audit

Run from the source checkout:

```sh
python3 -m unittest discover -s tests -p test_gate_calibration_evidence.py -v
python3 -m unittest discover -s tests -p test_rescore_recorded_scores.py -v
```

The evidence tests verify corpus hashes, exact row/label membership, group counts, risk deferrals, the friction list, request accounting, accumulated estimate, pinned model and the absence of unapproved fields. They do not independently attest the provider replies or invoice. Raw synthetic replies remain private; no customer information is needed to reproduce these checks.
