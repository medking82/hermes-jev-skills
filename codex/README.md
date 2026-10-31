# Jev For Codex

The maintained Codex layer of this fork installs one `$jev` skill (shown as `/jev`
where the host offers skill slash completion). Upstream Jev workflows become references
and retain their CLI commands. The main model remains responsible for execution.

The same entrypoint also covers building/evaluating TypeSafe API workflows. It routes
to a concise integration reference and the complete MIT-licensed official skill from
`typesafe-ai/skills`, pinned with source commit/file hashes. Only `/jev` is discoverable;
the official `SKILL.md` is packaged as a subordinate `guide.md`, never a second skill.
Use relevant live docs for current API/SDK contracts; routine hook routing keeps the
existing adapter instead of loading those references on every turn.

## Install And Retire Standalone Skills

Python 3.11+ is required for Codex TOML configuration. From this checkout:

```text
python -B codex/install.py --check
python -B codex/install.py --apply
```

Use the workstation's hidden runner on Windows. The preview names the retired
entrypoints and the hook warning. Apply preserves existing unrelated hooks/config,
backs up changed runtime files, dynamically archives every standalone `jev-*` directory
from both `<codex-home>/skills` and `~/.agents/skills`, and disables their former discovery
paths. Shared-scope copies have separate backup paths even when their names match;
unrelated skills are preserved. Existing keys and provider settings are neither read by
the agent nor changed by the installer. The generic upstream `install.py` installs
multiple agents/skills; use the Codex-specific installer for this consolidated setup.

Review/trust the new hook once in Codex `/hooks`. Do not bypass the trust review or
manufacture stored approval hashes. New or changed hook definitions require review.
Source publication and a manual hook replay do not establish host activation.

The reviewed Windows helper source is `codex/invoke-hidden.ps1`. It fixes the host
Console/PowerShell output encoding and child stdout/stderr decoding to strict UTF-8,
and pins Python UTF-8 mode and stream encoding. The `guidance` CLI also explicitly
sets its stdout to strict UTF-8. This preserves Unicode guide content and its hash
across a stale legacy-codepage host. Existing workstation helper updates are manual
maintenance with a backup; the Jev installer never overwrites shared helper ownership.

An already loaded Desktop session also needs its own app-server to reload the runtime
configuration. Trust written through a separate CLI/app-server process is persisted but
does not notify that Desktop session. Use the current Desktop's Hooks settings to apply
the reviewed hook there. A protocol client attached to the owning app-server can issue
`config/batchWrite` with `{"edits":[],"reloadUserConfig":true}`; a separate app-server
cannot refresh another process's loaded threads. This refresh preserves session model,
provider, reasoning, service tier and permission selections while rebuilding hooks.
See the [version-matched reload implementation](https://github.com/openai/codex/blob/4ebc485ca321243727539187169425fcf972f2c4/codex-rs/app-server/src/request_processors/config_processor.rs#L367).

To verify an existing Desktop chat, match the receipt's `session_id` to that chat's
`CODEX_THREAD_ID`, plus a fresh turn ID and timestamp. Passing in a new ephemeral host
does not prove activation in an already loaded Desktop chat. An async reply or steering
input inside an active turn is not a substitute for an independent `UserPromptSubmit`.

## Runtime

`UserPromptSubmit` runs before the model. Its worker gets a hard 3.5-second deadline.
Adapter 0.3.2 retains the conservative `routing-requests-v1` automatic trigger: only a
current request explicitly asking which skill, workflow or design mode to choose
enters model selection. For example, "Which skill should handle this request?" and
"这个任务应该用哪个 skill？" are eligible. Ordinary implementation, review, research
and continuation requests skip selection before catalog discovery. This is a narrow
English/Chinese syntax gate, not a general ambiguity classifier; it may abstain on
other wording. XML metadata, fenced/inline code and blockquotes do not open the gate.

Acknowledgements, sensitive requests and user opt-outs also skip network selection.
Explicit skill selections, whole commands naming an exact design mode and a narrow
component-polish grammar still route locally. An unavailable explicit skill never
falls through to Jev. `/jev` or `$jev` requests go to the main agent without a duplicate
automatic call. The main agent retains the on-demand `select`, `design` and `decision`
commands for useful ambiguous choices; their eligibility and questions are unchanged.

Trigger detection and explicit lookup share the same command parser. `$skill` and
`[$skill](path)` match the complete catalog ID, including plugin namespaces. Slash
commands must lead a line, optionally after `Use`/`使用`; slash-containing paths,
Windows drive paths, XML tags and link destinations are not commands. A bare `/name`
in command position is inherently ambiguous: quote literal paths and use `$name`
for an unambiguous skill choice. Quoted examples never become local explicit choices
when a separate routing question reaches the selector.

For an eligible routing request, the adapter follows TypeSafe's official
[skill-suggestion recipe](https://docs.typesafe.ai/cookbooks/skill_suggestion):
stage one combines a catalog Choice with three independent applicability Nouls;
stage two reads the top three candidates' full descriptions and first 700 characters
of `SKILL.md` body, then asks a Choice plus one fit Noul per candidate. Choice selects
the winner; the maximum fit Noul decides whether to suggest anything, as in the
cookbook, with its initial 0.30 fit threshold. The request-only gate is recorded
but not enforced by the installed hook: the full cookbook's 0.30 early gate missed
covered requests in local evaluation before their instructions could be read. Use
`--official-gate` in the evaluator to reproduce that policy. This is the measured
adaptation described in [the scorecard](skillpick-evaluation.md), not threshold tuning
to individual skill names or a task-context deduplication rule.
An independent design-mode question still shares stage one's request. The community
selector is unchanged. At most one skill is suggested, and verified no-match has its
own advisory sentence; an outage remains silent fail-open. No hint overrides an
explicit selection or mandatory skill instruction, loads a skill, or executes a tool.

The design-mode candidates include `impeccable` for UI creative direction and
distinctive visual design alongside the existing 15 modes. It refers to the matching
`$design` guide; a missing guide falls back to the main model's judgment. It adds no
installer, hook, browser, audit or prototype authorization. The four explicit-only
modes still require an actual opt-in, and ordinary implementation does not trigger
automatic selection.

Only shortlisted, already-admitted entrypoints are opened; linked resources are not
followed. Reads are bounded to 16,000 characters, descriptions to 8,000 and body excerpts
to 700. Sensitive lines (including credential-setup examples) are withheld before the
normal redaction boundary. Missing, linked or malformed evidence, or filtering that
leaves no usable evidence, fails open rather than silently pretending that full
verification ran. No local file paths accompany the evidence sent to Jev.

The hook catalog covers both user scopes above (including `.system`), explicitly trusted
project scopes, and plugins in this session's host-supplied available-skills catalog.
It reads only the matching session's native rollout, verifies the active turn/cwd, and
accepts only complete developer `skills_instructions` records. User/tool text cannot
supply a catalog. Exact namespaced IDs and versioned paths are retained; unrelated plugin
caches are never inventoried. Current per-skill/plugin disables and missing versions
remove candidates even if an older host snapshot listed them. Following OpenAI's
[invocation policy](https://learn.chatgpt.com/docs/build-skills#optional-metadata),
`allow_implicit_invocation: false` removes a skill from implicit candidates while
allowing an exact user choice to resolve locally. This exception admits only the
explicitly named skills; it never bypasses disablement, project trust or host provenance.

Discovery supports Codex's UUIDv7/date-partitioned rollout layout, reads at most the last
32 MiB, and records the catalog timestamp/hash and admitted plugin IDs in the receipt.
If identity, format, or catalog evidence is unavailable, it falls back to local scopes.
This is the latest catalog supplied to that session, not a separate host's plugin scan
or a promise that an external service is connected. The main model still checks current
tool access and authorization before using a recommended skill. An explicit `select`
caller can also supply the current catalog directly.

Discovery stops at skill entrypoints instead of walking resources, dependencies or
embedded examples. Timeouts/catalog failures leave explicit, prompt-free reason codes.
Inactive configured paths are compared lexically without probing other filesystems.

Only duplicate delivery of the same turn may reuse a prompt-free fingerprint/result;
the shortlisted evidence hashes must still match, including body-only changes.
There is no cross-turn decision cache or added retry loop. `JEV_CODEX_OFF=1` disables the
automatic gate. Existing `JEV_PROVIDER` is respected; otherwise the adapter uses TypeSafe
without provider fallback. It preserves the existing Jev alias/version setting and logs
the version actually returned. Preview image/Box features are not enabled automatically.

The last observed hook receipt lives in `<codex-home>/jev/last-hook.json`; it contains
skill IDs, outcomes, request-attempt counts, model versions, tokens and timing, not prompt
text. UTC timestamps, session/turn IDs and the selected design mode allow correlation
with real host hook notifications. A local recommendation is labelled as local, not a
Jev model response. The Windows launcher briefly spools stdin under the user's Codex runtime so the
shared hidden runner can consume it, then removes the file in `finally`.

Each observation is also retained once under
`<codex-home>/jev/observations/<UTC-date>/<observation-id>.json`. Unique immutable files
avoid concurrent hooks rewriting a shared history. Receipts identify the adapter/recipe,
`automatic_trigger_policy`, `trigger_reason` and `trigger_eligible`,
gate values, candidates, excerpt hashes/lengths, fit values, outcome and actual attempts.
A reused same-turn result records zero new attempts; a killed worker leaves attempts
unknown, not zero. Manual smoke events are labelled separately. Receipt storage failure
does not block the task. These records establish suggestions, not actual skill loads or
task success; those require separately observed outcomes. No task-context deduplication,
cross-turn result reuse or automatic skill-suppression policy is added.

Compare each adapter/trigger-policy cohort separately. `automatic_scope_skipped` is a
local zero-call abstention, not a verified model no-match. Include skipped real turns
when measuring hook overhead, and sample their subsequent native skill loads and task
outcomes for missed useful routing. Retain unknown attempts/usage after worker failures;
known early skips record zero attempts. API latency and worker duration are distinct
from the unobserved full host/launcher delay. Offline regressions establish boundaries,
not adoption, task benefit or net savings against a comparable baseline.

### Evaluate The Selector

`python -B codex/evaluate_skillpick.py --check` validates the synthetic bilingual
fixtures offline. `--live` explicitly runs a bounded paired legacy/new-selector
comparison using the existing client, model and credentials, with no added retries.
Add `--official-gate` to compare the complete cookbook policy instead of the installed
body-verification policy. Use `--help` for the case limit and output path. Reports contain case IDs, labels,
selection outcomes, model versions, attempts, tokens and wall latency, without request
text, skill bodies or local paths. Fail-open is reported separately from correct
no-match. This is selector evaluation, not an agent baseline/oracle study, proof of
skill loading, task completion or realized cost savings. Keep generated reports local.

## Principles

- Keep the main model, effort, Fast, permissions, tool bans and explicit user choices.
- Code handles deterministic work and side effects; Jev handles bounded semantic choices.
- Batch independent questions over the same small, redacted state.
- Abstention and outages return to the main model without routine confirmation prompts.
- No new provider routes, purchased credits, local/GPU workers or browser permissions.
- Confidence is not correctness, permission, prompt-injection immunity or completion proof.
- Chinese requests need representative evaluation; a few passing cases establish smoke
  coverage, not general accuracy or a measured efficiency gain.

## Upstream Maintenance

`origin` is this fork; `upstream` is `kerpopule/hermes-jev-skills`. Keep upstream files
intact except the small `skillpick.ask_fn` injection seam; Codex-specific files live
under `codex/`, `jevkit/codex.py` and `tests/test_codex*.py`.

The same scheduled sync also checks `https://github.com/typesafe-ai/skills.git`.
Its `skills/typesafe-ai` Markdown/MIT-license files are pinned under
`vendor/typesafe-ai/`, with source provenance and byte-preserving Git attributes.
An official-only change creates a commit even when Hermes is unchanged.

New scripts, invocation metadata, symlinks/executable file modes, license/identity changes,
rewritten official history and oversized/unsupported files stop the update for manual
review. Only bounded reference data updates automatically; Codex adapter, hook, provider,
permission, threshold and updater controls retain their existing review boundary. The
official guide is subordinate to umbrella/user rules, including per-turn-only hook
caching and existing retry policy. Official cookbook examples grant no tool permissions.
When the main model enters a Jev workflow beyond unchanged skill/design dispatch, the
umbrella directs it to run `scripts/jev.py guidance` and read the returned content.
The command validates the installed manifest/source identity and guide hash, reads from
disk on every call, and returns the actual guide with its official commit/hash. It makes
no provider/network call and writes nothing; missing, linked or modified inputs fail open
without changing routing. Future accepted reference updates therefore change the returned
guidance, while protected adapter behavior remains reviewed code. Delivery of the content
is verifiable; semantic compliance by a future model still needs task-specific evidence.
The local blocked state applies to both sources; adding this source never clears an
earlier stop.

To verify the pinned package offline, run `python -B codex/official.py verify`; add
`--live` to compare it to the actual official Git commit. `refresh` updates only the
intact owned snapshot on an explicitly selected maintenance branch; it installs nothing.

`Sync fork with upstream` (`.github/workflows/fork-sync-upstream.yml`) runs every six
hours, or on manual dispatch. It is a plain fork sync (Owner decision, 2026-10-31): it
merges `kerpopule/hermes-jev-skills` main, refreshes the official TypeSafe reference,
pushes ordinary commits to main without force, and then dispatches `test.yml` for the new
main (pushes made with `GITHUB_TOKEN` start no push workflows). A merge conflict, an
official-reference refusal or a rejected push fails the run, and GitHub emails the Owner;
the GA401 schedule watchdog reports a schedule that stops firing. Confirm its actual state
with `gh api repos/medking82/hermes-jev-skills/actions/workflows/fork-sync-upstream.yml`.

Testing gates installation, not merging. Changes to `codex/`, `jevkit/codex*`,
`tests/test_codex*`, `.github/`, `AGENTS.md`, `.gitattributes`, `.gitmodules` or
`vendor/typesafe-ai/.gitattributes` can reach fork main, but the local updater refuses to
install them until they are reviewed and re-enrolled. These include the umbrella, hook,
authorization boundaries, installer and updater itself. Other public Jev implementations
remain research inputs, never automatic executable update sources.

### Local Windows Update

After previewing/applying an accepted clean `main` commit with `codex/install.py`, run
`codex/register-sync.ps1` in PowerShell 7. It enrolls the exact installed release and
copies a pinned updater under `<codex-home>/jev-sync`. The **Codex Jev Update** Windows
task runs at logon and hourly, under the current user's limited interactive token, with
hidden VBS/PowerShell launchers and the actual `python.exe`. No console window, model,
provider call, purchased credit or GPU worker is used by the updater. The computer must
be awake and that Windows user logged in; missed runs start when available.

The updater accepts only a descendant fork main whose exact commit passed `test.yml` on
GitHub. It then tests in a temporary clone and isolated profile before advancing clean
local main and applying the approved transactional installer. GitHub tests that are still
running or failed only defer the update; a later passing commit installs. Unknown/missing
owned files, local edits, an unclean/non-main checkout, rewritten history, changed controls
or config/hook/retirement changes stop it. Config and hooks must stay byte-identical; existing disables,
explicit-only policies and trust remain in force. The task never enrolls new controls
or trusts a hook automatically. Existing installer backups are retained.

`last-run.json` and `last-update.json` contain prompt-free receipts. A stop is persisted
in `state.json`; later scheduled runs return that same receipt without retrying tests
or writes. Resolve the cause, then explicitly run the pinned `sync.py resume --runtime
<codex-home>/jev-sync` before the next normal run. If installer application fails after
source advances, its transaction restores the runtime; source/runtime reconciliation is
then manual, so no user changes are reset. Manually approved fork changes to maintenance
controls require explicit re-enrollment after installing the new accepted main.
Temporary network outages only defer the local check until its next ordinary schedule;
they never install anything or add a retry loop. Authentication/permission failures and failed
local tests remain stops.

### Receipt Reporting And GitHub Alerts

The existing task reports after the updater exits, including a sticky stop. It also
checks its peer Native Review task and reports missing, disabled or unhealthy peer
state. There is no additional local service or model-based health monitor. Registration
requires a random 16-hex `-Device` pseudonym first approved in `receipt-policy.json`.
Only that pseudonym, UTC timestamps, task state/result, event identity, commit, an
allowlisted CI URL and closed reason codes leave the machine. No prompt, config, keys,
raw exception text, paths or test logs are uploaded. This fork is public, so this
allowlisted receipt metadata and its alert issues are public too.

`report.py` submits a `codex-updater-receipt` repository dispatch using existing `gh`
access without reading credentials. `submitted` in local `last-report.json` means
accepted for processing; the state on the `updater-receipts` branch and completed
receiver run establish delivery. Reporting denial is retained locally and uses no
alternate tool or credential fallback. A later ordinary schedule may submit again;
it never reruns a blocked update or failed tests. Source CI excludes the receipt branch.

The trusted default-branch receiver saves each device's latest report and deduplicates
event notifications against persistent issue markers, including closed issues. A new
stop, launcher error, missing/disabled task or completed run missing a fresh receipt
after five minutes creates one assigned alert. Running and matching sticky stops are
excluded from stale detection. An old `enrolled` receipt is never installation proof.
New `updated` events have one completion notice; unchanged reports stay quiet.

A cloud watchdog runs every six hours. After three hours without reporting it emits
one reporting-unavailable notice per outage (there can be up to nine hours' delay).
It cannot distinguish an offline PC from both tasks being disabled, and does not infer
tests failed, tests passed or an installation. Known deferred offline state stays quiet.
Canary devices are separate and excluded from scheduled liveness checks. No receiver
or alert resumes, installs, merges or repairs anything. The former
chat heartbeat is retired only after live production receipts and deduplication pass.

## Validation

```text
python -B codex/check.py
# Full suite only on upstream-supported Linux/macOS:
python -B codex/check.py --full
```

Tests are offline and use synthetic state/fake transport. A separate small live smoke
run may verify the installed adapter, using existing credentials privately. Inspect its
returned model/usage; local mocks do not prove real API or Codex-host hook behavior.
