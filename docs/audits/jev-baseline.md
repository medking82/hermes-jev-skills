# JEV routing baseline and remediation, 2026-10-20

## Version scopes

| Scope | Version | Evidence and meaning |
|---|---|---|
| Installed plugin at audit snapshot | 0.20.0 | Installed manifest and entrypoint; historical runtime observations below |
| Initial audit source revision | 0.20.0 | `45ed9d43696c1f57a7d0768e3afc3740e018cdfe`, plus preserved local runtime changes |
| PR repository base after rebase | 0.24.0 | `7b56de6627557e8bebb22f1538d75b37555a5623`; upstream code and tests |
| Proposed PR package metadata | 0.24.1 | Paired library/manifest patch bump; no installation or live upgrade |

The audit is of the installed v0.20.0 snapshot, while the proposed code is based
on repository v0.24.0. The 1,340-test result belongs to the earlier v0.20-based
patch; 1,621 tests passed after rebasing. Subsequent focused-review validation is
recorded separately in `jev-validation.md`; these counts are not interchangeable.

## Scope and provenance

Read-only runtime investigation; implementation in a separate worktree on
`codex/jev-routing-isolation`, based on commit
`45ed9d43696c1f57a7d0768e3afc3740e018cdfe`. Local main was 53 commits behind its
recorded origin/main. No fetch, update, installation, restart, configuration edit,
paid inference, merge, or deployment was performed. The source checkout had two
modified plugin files and unrelated untracked skills; these were preserved and
excluded from this branch. Installed plugin version is 0.20.0. Its entrypoint
matches the dirty source entrypoint byte-for-byte, not necessarily the clean Git
baseline. The existing private telemetry extension is intentionally excluded.

Delivery update: a later fetch found 72 upstream commits beyond that baseline,
with library/plugin version 0.24.0. The patch was rebased onto that upstream,
preserving its newer pin and effort fixes; release metadata is now 0.24.1.
The runtime audit above remains a v0.20.0 observation. No live upgrade occurred.

Sources: `hermes/plugin/hermes-jev/__init__.py`, `jevkit/route.py`,
`jevkit/catalog.py`, `jevkit/effort.py`, `jevkit/ledger.py`, installed plugin
manifest, local routing settings and aggregate decision/ledger observations.
Only non-secret configuration fields were surfaced. No raw logs, customer
messages, live pools or credentials are included here.

## Verified baseline

Snapshot counts (logs can continue growing):

| Metric | Earlier observation | Current snapshot |
|---|---:|---:|
| Effective-request events | 8,145 | 8,150 |
| Applied flags | 40 | 40 |
| Missing custom alias | 4,880 | 4,885 |
| Pinned-model events | 2,851 | 2,851 |
| Ledger rows | 277 | 283 |
| Ledger recorded USD | about 0.011 | 0.01108204 |

There are 947 first requests and 7,203 follow-ups. Eight first requests have
`applied=true`: 0.845% of first requests, versus 0.491% of all requests. These
are middleware flags, not independently verified executions. Existing applied
flags can include assignments of an already-selected model; the patch corrects
that distinction going forward. Missing alias and pinned decisions repeat during
tool loops: 591 and 314 respectively at the route-decision level. Pins are
intentional restrictions, not routing defects.

947 route decisions: 905 active, 42 shadow. Tier/specialty are populated for only
eight decisions: hard 3, simple 3, medium 2; coding 6, general 2. Confidence is
numeric for eight; latency for three. Provider identity is not recorded reliably
enough for a named-provider or endpoint breakdown. No complete correlation IDs
exist in this decision stream; do not join events by row proximity or claim
unique user requests. `first_request` is the best available turn proxy; sampling,
rotation, retries, concurrent callbacks and missing hooks remain limitations.

Ledger statuses: 257 ok, 23 skipped, 3 code. Numeric latency exists on 260 rows:
median 801.5 ms, empirical p95 (floor index over n-1) 1,519 ms. This is mixed
decision telemetry, not end-to-end model latency or routing-only overhead.
`ledger.cost()` calculates tokens times a configured tariff; recorded cost is
not an invoice reconciliation. Avoided tokens are caller estimates.

## Reproduction

Run from the repository with RTK installed:

```sh
rtk git status --short --branch
rtk git log -1 --format='%H %s'
rtk proxy python3 scripts/audit_routing.py ~/.hermes/logs/jev-decisions.jsonl
rtk proxy python3 -m unittest discover -s tests
rtk proxy python3 scripts/check_release.py
```

Audit calculations stream JSONL and count effective flags separately from
first-request flags. For ledger reproduction, parse JSONL locally, sum numeric
`cost_usd`, count `status`, sort numeric `latency_ms`, use the median and index
`int((n-1)*.95)`. Never print raw rows. Do not publish live model pools.

## Root cause and identity path

Hermes selects a named entry before resolving its runtime. In the inspected
Hermes source, `hermes_cli/runtime_provider_custom.py:_resolve_named_custom_runtime`
uses the name for lookup and creates a custom runtime; its documentation describes
bare custom as the shared billing class. `agent/turn_api_request.py` calls
`apply_llm_request_middleware` with `provider=agent.provider`, `base_url`, model,
session/turn/request IDs and API mode. It does not pass the durable named custom
identity. JEV accepts provider and discards other metadata on this baseline.
The middleware can replace request fields, not the configured provider client.

Both configured custom entries use the same localhost gateway URL. Their
configured inventories contain 1,852 and 11 identifiers with seven overlapping.
These are configured menus, not execution evidence or tenant entitlements. Do not
recover identity by first URL match or by overlapping model names. There is no
custom alias in the inspected routing configuration. Configured routing is active;
vision and lanes are shadow. No switches were changed.

JEV constructs provider:model references, restricts candidates via only_provider,
and returns a bare model_id to Hermes. A catalog provider guard establishes a
namespace constraint, not gateway support. The gateway's advertised identifiers,
canonical-name equivalence, prefix translation, upstream chosen model and actual
execution remain unverified. No authenticated discovery or model execution was
attempted. Slash prefixes and colons inside gateway IDs must be treated as opaque.

## Architecture decision

| Option | Correctness/security | Compatibility and maintenance | Failure mode |
|---|---|---|---|
| A: named aliases | Requires trusted selected name from host; unavailable here | Small schema but host integration and per-name tests required | Unknown identity must keep original |
| B: endpoint allowlist | URL alone cannot distinguish these entries or credentials | Inventory snapshots need identity, provenance, TTL and revocation; advertised models insufficient | Stale/missing inventory must keep original |
| C: gateway adapter | Could bind namespace and entitlements to actual selected route | Largest change; gateway contract and execution correlation required | Adapter outage/drift must keep original |

Decision: retain current custom safeguard. Do not introduce an unproven mapping
schema or claim endpoint compatibility. The smallest supported change is to bind
cached decisions to provider, exact endpoint, host model and outgoing model, and
accurately record whether an assignment changed the request. This prevents a
decision for one connection from being reused after a fallback or model switch.
After any observed context mismatch, invalidation is sticky for that turn: an
A -> B -> A callback sequence cannot revive A's decision. Repeated callbacks
retain their incoming model and effort, without stale routing or effort notices.
A fresh `pre_llm_call` creates independent state for the next turn.
Endpoint comparison is conservative and in-memory only; even a benign URL change
causes fallback. Existing string aliases remain operator assertions; nested named
maps remain rejected. They are not newly certified as safe endpoint routing.

## Patch and acceptance boundaries

Changes: middleware context binding, non-mutating fallback telemetry, provider
class and compatibility-basis telemetry, actual-change accounting, regression
tests, aggregate audit tool and this delivery package. Endpoint URLs are not logged.
Missing stable custom identity is recorded as null, never guessed.

Acceptance is partial: no increased custom-provider routing is enabled. Existing
pins, shadow behavior, namespace guards and effort capabilities are retained.
Absolute guarantees against unsupported endpoint models cannot be established
from an operator alias and a model catalog. Live inventory drift, credential
rotation at an unchanged URL, same-turn concurrent first callbacks and upstream
rewrites remain outside the patch's guarantee. Full provider-aware enablement is
blocked on trusted host identity plus execution validation.

## Quality evaluation framework

Runnable tools: `scripts/replay_routing_eval.py` for offline replay/rescoring and
`scripts/compare_routing_eval.py` for paired recorded measurements. Input schema,
seven-category task matrix and commands are in `evals/routing-reliability/README.md`.
Synthetic fixture tests verify denominator handling, missing evidence exclusion,
duplicate rejection, no RPC replay and telemetry sanitization. These are framework
checks, not measured answer quality.

Repository eval directories include representative tasks, lanes, plan quality,
gate, context filtering, compaction and tool selection. Their existence is not
evidence of comparative routed answer quality. No linked, reviewed dataset of
baseline and selected-model answers was established. Historical answer access was
not expanded into unrelated personal session databases.

Use a versioned, consented dataset with at least coding, debugging, reasoning,
tool selection, high-risk, long-context and supported multimodal cases. Each case
needs an opaque ID, category, input hash, expected outcome, checks and rubric;
store sensitive content separately with restricted access. Freeze policy, catalog,
provider identity, inventory version and model IDs for each run.

1. Offline routing replay: feed fixed classifier answers via mocked transport;
   record proposed/kept model, pin/shadow behavior and compatibility outcome.
2. Policy rescoring: change thresholds against the same answers; report changed
   decisions only. Neither stage executes models or establishes quality/savings.
3. Real execution, only after explicit authorization: run paired baseline and
   selected requests with identical tool permissions, context and task budget.
   Randomize order, record errors and retries, and retain request/response IDs
   linking middleware to gateway and upstream execution. Verify the returned
   model against gateway execution evidence, not just the response model string.
4. Blind human review: score correctness, completion, safety, instruction adherence
   and tool choices on a fixed 0–4 rubric with written anchors. Require two reviewers
   for high-risk cases and adjudicate disagreements. Retain failed tasks.

Comparison record schema (one row per case and arm): `case_id`, `category`,
`arm` (baseline/routed), `run_id`, `policy_hash`, `inventory_hash`, `requested_model`,
`effective_model`, `executed_model`, `data_kind`, `execution_verified`,
`execution_evidence_id`, `request_id`,
`completion`, `rubric_scores`, `reviewer_ids`, `latency_ms`, `input_tokens`,
`output_tokens`, `cached_tokens`, `actual_cost_usd`, `cost_source`, `cost_evidence_id`,
`review_kind`, `review_evidence_id`, `error`, `retries`.
Missing measurements stay null. Compare only matched pairs; publish sample sizes,
category strata and uncertainty. No quality improvement has been measured here.

Both arms must explicitly declare `data_kind: measured`, boolean
`execution_verified: true` and a nonblank `execution_evidence_id` before contributing
any measured delta. Synthetic pairs (`data_kind: synthetic`), mixed provenance and
unclassified legacy records are counted as excluded. Billed cost additionally
requires `cost_source` in `provider_invoice`, `provider_billing`, `gateway_billing`
and a nonblank `cost_evidence_id`; arbitrary labels and tariff estimates are excluded.
Quality additionally requires `review_kind: human`, a nonempty list of distinct,
nonblank string `reviewer_ids`, and a nonblank `review_evidence_id`. The tool checks
structure and caller attestations; it does not authenticate receipts, reviewers
or upstream execution. Audit those references before publishing production results.

## Cost and latency methodology

Measure middleware entry-to-exit with a monotonic clock separately from classifier
RPC latency; collect p50/p95/p99 and warm/cold status. Measure request submission
through final tool/task completion separately. Use provider usage plus invoice or
gateway billing records including retries, cache discounts and decision overhead.
Paired net difference = baseline execution cost minus routed execution cost minus
incremental JEV cost. Estimate-only tariff costs must be labeled separately.
Report fallback/rejection rates by reason, exclude intentional pins from defect
rates, and report both turn and request denominators. There are no measured net
savings, execution-cost differences or end-to-end performance results in this work.

## Security review

| Finding | Severity | Evidence/status |
|---|---|---|
| Cached decision can follow a different endpoint/provider/model | High potential impact | Prior cache keyed by session/turn only; patched with exact context binding and regression tests |
| Shared custom class loses named identity | High enablement blocker | Host callback lacks named identity; retained fail-safe rejection |
| Alias is an assertion, not entitlement validation | Medium residual | String alias trusts configured catalog namespace; no live enablement |
| Gateway inventory and credential drift | Medium residual | Same URL cannot prove same entitlements; no gateway adapter introduced |
| Concurrent first callbacks can duplicate classification | Medium residual | Lookup lock does not encompass RPC and decision publication; not claimed fixed |
| Savings attribution exceeds evidence | Low reporting risk | Applied flags are middleware observations; patch distinguishes actual assignment changes |

Untrusted messages cannot supply the binding through request body fields; host
kwargs provide provider/endpoint. Configuration remains trusted operator input,
not a security boundary against an actor able to edit plugin code. Invalid nested
aliases fail closed. No new prefix rewriting or alias interpolation is introduced.
Endpoint credentials are retained only in process memory and never in new logs.
Existing model/reason fields are not a general redaction boundary; do not configure
secrets as model IDs. Shadow callbacks return no request mutation. Router exceptions
retain the original path; effort changes still require explicit capabilities.

## Validation and delivery gate

Baseline targeted middleware suite: 27 passed. Initial full patched suite: 1,335
tests, one failure in unrelated `test_lanes.Evidence.test_scope_sensitive_paths_and_check_tails`
(expected two out-of-scope files, got one). Release scan passed for 201 text files;
one existing PNG explicitly excluded from text scanning. Final validation and
independent review are recorded in `jev-validation.md`.

No remote PR until checks and review succeed. A PR description is prepared in
`jev-pr-description.md`; this is not a release approval.

## Deployment and rollback

Do not install or restart the live plugin from this branch. Before staging,
preserve the private telemetry extension while reconciling with current upstream;
review the resulting diff and rerun all checks. Obtain explicit staging approval.
Back up installed plugin, bundled jevkit and routing/state settings with hashes
and restrictive permissions. Test with synthetic requests and a local stub gateway,
then separately authorize any real inference. Require stable named host identity,
entitlement/inventory validation and correlated execution before custom enablement.

For rollback after an approved installation, restore the exact backed-up plugin
and bundled engine, verify hashes, and restart only with authorization. Restore
configuration only if that rollout changed it. This patch needs no config migration
and has not touched production. Keep logs for comparison; do not delete evidence.
