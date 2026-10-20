# Measurement and installation provenance

The checker denies foreign symlinks by default. Operators with explicitly authorized shared Hermes homes may pass `shared_homes=[approved_home]` to verify installer-created links to copied root skills. Only exact managed mappings in those declared homes are accepted, never an inferred parent/root or an arbitrary foreign target.

## Four identities, not one "matches main" label

1. **Published main**: an exact remote-main SHA recorded as of the read. A stale local `origin/main` or successful push to a feature branch is not proof of it.
2. **Checkout**: the exact HEAD plus tracked-dirty state of the source actually being used.
3. **Installed managed files**: byte comparison of the expected tracked plugin, `jevkit` and Jev-skill files against both identities. Missing files and foreign file symlinks cannot count as matching. This is a declared managed-file scope, not a scan of arbitrary foreign files.
4. **Loaded runtime**: a running process's own version or a new isolated loader test. Installing bytes does not establish an existing gateway reloaded them.

`jevkit.provenance.check_install(repo, home, main_sha)` is read-only: no network, installs, mode changes or module execution. It checks an exact, literal SHA; the caller must retrieve the current remote identity. `matches_main` requires a clean checkout at that main SHA and matching installed managed bytes. `installed_matches_checkout` is intentionally a separate fact. Code and skills are both covered.

`jevkit.steward.install_state` is the portable adapter for a fleet's daily collector. It preserves the caller-owned execution callbacks and existing automation/test gates. A checkout away from published main, tracked edits, unavailable provenance or an active no-auto-refresh switch cannot trigger an automatic install. An approved candidate installed locally is **not** a reason to overwrite it with main. The renderer must use `provenance.describe(state.get('provenance'))`, not `in_sync` to manufacture a main label.

Do not rewrite historical reports with today's mode. Append a dated correction with the exact rechecked scope. Remote machines, foreign skills and already-running processes need separate evidence. Shared video/Blender skill dependencies should be inventoried locally by source revision, dirty state and content fingerprint; do not publish their private files merely to list the dependency.

## Shared usage, including standalone helpers

`jevkit.usage.ask(feature, state, questions, **kwargs)` adds hash-only write-ahead records to the normal shared ledger for the standalone video-QA helper/trial, image-action benchmark and Blender advice path. No state, pixels, paths, question text, labels or secrets are logged. A feature tag is a closed allowlist, not a free-form logging channel. It does not grant upload or spending permission; caller privacy checks must already have passed. It disables hidden client retries for these metered calls.

Unknown pending/error spend closes daily budget checks rather than being treated as free headroom. `spent_today` returns positive infinity as a budget-control sentinel, never as a billing amount. Strict ledger reads mark malformed or inaccessible logs unavailable.

Each invocation gets an attempt ID. Persist the attempt before entering the client. A returned result or error uses that same ID; `ledger.logical_calls` coalesces the event pair into **one call**, preserving old single-row records. A pending attempt, orphan result or contradictory event history remains unknown, never a fabricated successful/free call. This is append-only evidence; do not erase unresolved attempts to make a report tidy or automatically replay them.

Shared usage covers these default transports prospectively. Existing per-feature logs and older direct `client.ask` calls remain historical evidence with coverage gaps. Caller-injected test/custom transports are not automatically evidence of a real metered request. `JEV_LEDGER=off` is still an explicit opt-out; do not claim complete accounting when it is disabled. No past missing usage is reconstructed from guesses.

## Cost and savings labels

- The legacy `cost_usd`/`list_usd` fields are configured-rate estimates, not reconciled invoices. `estimated_cost_usd` is the explicit summary alias; `billed_cost_usd` stays null without billing evidence. Unknown usage makes `estimated_cost_complete` false. Known estimates are not a complete total when any amount is unknown.
- `actual_llm_avoided_tokens` is zero for an entirely shadow group, because the original path still ran. Other groups remain null without an actual downstream-outcome measurement. `counterfactual_llm_avoided_est_tokens` retains the modelled estimate, not a realized-saving claim.
- `calls` counts logical invocations, not the two write-ahead events. Legacy `sent` is a status-based indicator, not a verified HTTP-attempt count. An error can have unknown dispatch/spend. Count this explicitly rather than reading it as zero.

## End-to-end comparison

Measure observation/capture, inference (including fallback), execution, independent verification and human/frontier review. Include low coverage, clean referrals, unknown attempts and failed cases. Report the model, question/source hashes, privacy scope, confidence floor and per-workflow deadlines/probe budgets. Do not multiply a quick call by a guessed expensive-model baseline and present the result as measured ROI.

A paid experiment needs a scoped owner-approved cap and explicit request/token limits. Local estimates do not certify an external invoice ceiling. Preparing a fixture, installing code or writing an approval template does not authorize inference, mode activation, publication of private footage or a gateway restart.
