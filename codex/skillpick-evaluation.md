# Official Skill Suggestion Evaluation

The Codex adapter follows the [TypeSafe cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion):
Choice plus three applicability Nouls, a top-three shortlist, full descriptions and
700-character instruction excerpts, then Choice plus independent fit Nouls. The initial
maximum-fit threshold is 0.30. The request-only 0.30 gate is recorded but evaluation-only
after it missed covered requests; the installed hook always reaches body verification
after its existing local gates. A singleton uses a deterministic winner after its fit
check. Existing Codex local gates, speculative design/workflow questions,
timeouts, redaction, explicit choices and advisory-only output remain in place.

The installed official skill reference is `typesafe-ai/skills` at
`65a39f393687675ce170e6094757de20370365b9`. The recipe is implemented in protected Codex
adapter code; an official documentation update does not silently change executable
questions or thresholds. Re-read current guidance and the cookbook when revising it.

## Paired Evaluation And Promotion Decision

- Final paired run UTC: 2026-10-22 01:15:53.810 through 01:16:10.935.
- Returned model: `jev-1.13.0` in both arms, all 16 completed pairs.
- Fixture: 16 synthetic English/Chinese requests, eight synthetic skill definitions;
  12 covered requests and four no-match cases. These are not private task replays.
- Alternating arm order: legacy/new, then new/legacy. One observation per case/arm,
  existing client/provider/model, 1.4-second per-request timeout, no extra retries.
- Legacy arm reproduces the former Codex description-only selection and first-request
  auxiliary questions. The new arm exercises the actual new `codex.select` function.

| Measured Selector Result | Legacy | Installed Body Verification |
| --- | ---: | ---: |
| Correct selections or no-match | 16 / 16 | 16 / 16 |
| Wrong / needless / missed selections | 0 / 0 / 0 | 0 / 0 / 0 |
| Fail-open | 0 | 0 |
| API attempts | 30 | 32 |
| Input tokens | 27,853 | 40,813 |
| Selector wall-time p50 | 538.658 ms | 542.322 ms |
| Selector wall-time p95 | 642.235 ms | 620.009 ms |

The installed policy used 46.5% more input tokens in this small run. The timing differences
are single-run observations, not evidence of a reliable speedup; timings exclude host
hook startup and catalog discovery. Both arms reached the fixture's ceiling, so the
run demonstrates basic behavior without establishing improved accuracy, saved tokens,
agent skill loads or task outcomes. Several recipe components changed together; this
is not an isolated causal test of body excerpts. These development fixtures informed the
promotion decision and are not a held-out benchmark. No per-skill exceptions or numerical
threshold adjustments were fitted to them.

The full cookbook policy remains available with `--official-gate`. Its paired run at
01:13:37.530 through 01:13:53.931 UTC selected correctly on 15/16 cases versus legacy's
16/16; `skill-author-en` was missed before any candidate body was read. It used 37,187
input tokens versus 27,432, with 29 attempts each. A separate two-case installed-catalog
smoke likewise scored 1/2 versus legacy's 2/2: skill authoring was missed, while interface
design was selected correctly. This is why the unvalidated early gate was not promoted.

An earlier exploratory implementation with paraphrased question wording scored 16/16
in both arms (27,432 versus 37,095 input tokens), but also missed the installed-catalog
skill-authoring request. The final implementation uses the cookbook's question wording
and request state. The earlier reports are retained locally; their numbers are not
substituted for the final policy's results.

The installed-catalog smoke also exposed harmless credential-setup prose being treated
as an entirely unsafe candidate. The final evidence reader withholds sensitive lines,
retains other useful procedure text, and records the redaction count. If no usable
evidence remains it still fails open. Regression tests cover both paths.

Keep task-context deduplication deferred. Immutable hook observations can establish
real suggestion frequency and failure causes; actual skill-load/task-outcome evidence
is still required before deciding whether a broader change is useful.

## Reproduce And Inspect

```text
python -B codex/evaluate_skillpick.py --check
python -B codex/evaluate_skillpick.py --live --limit 16 --output .cache/selector-evaluation.json
python -B codex/evaluate_skillpick.py --live --official-gate --limit 16 --output .cache/official-gate-evaluation.json
```

Create the output directory first and choose a new filename. `--check` makes zero API
calls. The live runner creates temporary fixture entrypoints beneath `tests/`, cleans
them up, and writes a report only to an explicit new output path. Reports omit request
text, instruction bodies, credentials and local paths. Failures remain separate from
correct no-match, and unknown usage is not reported as zero.

Initial dataset hash: `d8cdfcebd19a467d00c84a82000e265005c1970624dd3c7c093c00e0d699efaa`.
Initial roster hash: `868e282199ac23ce8d47fde01ab378d5593b455117208548b189d3da0a470e2b`.
Initial case hash: `4628e8863a161394489088f4b6f53e25715dcbce73cd7b51a8ec01d7cd7573a1`.
The local report also records implementation hashes and individual case/attempt outcomes.
Do not publish private hook observations or describe these synthetic cases as task success.
