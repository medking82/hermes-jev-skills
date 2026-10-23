# Codex Integration

Source: `medking82/hermes-jev-skills`, `codex/README.md`.
Use `python codex/install.py --check` then `python codex/install.py --apply` from the
canonical checkout. The Codex installer does not run the upstream multi-agent installer.
It installs the toolkit and one `jev` skill, dynamically archives all prior `jev-*` skills
from both `<codex-home>/skills` and `~/.agents/skills`, and disables their original discovery
paths in Codex config. Backups stay under Codex home; shared-scope copies use a separate
`retired/agents/` directory so matching names do not overwrite each other.

`UserPromptSubmit` uses `routing-requests-v1`: model selection is limited to current
requests explicitly asking which skill, workflow or design mode to choose. Ordinary
execution and continuation skip before catalog discovery; fenced examples and
blockquotes do not trigger it. Exact skill/design choices remain local and zero-call.
`/jev` stays on demand, with `select`, `design` and `decision` available to the main
agent. This conservative syntax gate is not a general ambiguity classifier.

For eligible routing requests, the hook recommends one skill and can include a
design mode from the same stage-one request. The official
TypeSafe skill-suggestion recipe combines Choice with independent applicability Nouls,
then verifies the top three using full descriptions and 700-character body excerpts.
The 0.30 fit threshold follows the cookbook. The request-only 0.30 gate is recorded
but evaluation-only after it missed covered requests before body verification;
`codex/evaluate_skillpick.py --official-gate` retains the full recipe for comparison.
No-match is advisory; missing/unsafe evidence or an API failure returns control normally.
The upstream community selector remains unchanged. Plugin candidates
come from this session's host-supplied available-skills record in its native rollout,
bound to the active session/turn/cwd. The hook never scans unrelated plugin caches.
Current skill/plugin disables and explicit-only policies are checked again. Missing,
foreign, unsupported or out-of-range session evidence leaves local routing available.
Receipts report `catalog_source`, snapshot timestamp/hash and admitted namespaced plugin
IDs, without raw prompts/transcript text. A session catalog is not evidence of external
service authorization; main-model/tool access checks still apply.

The hook supplies a routing second opinion, not the final route. It runs before the
main LLM and cannot observe that model's later choice. Its additional context requires
one main-LLM evidence recheck on same-layer disagreement, without rerunning Jev for the
same decision. No Stop hook or automatic code-review dispatch is needed; `native-review`
continues to own admitted code review. Abstention and local fallback are not disagreement.

Review/trust the installed hook once using Codex `/hooks`; changed hook definitions
require review again. Do not fabricate trust hashes or bypass trust. Restart or resume
Codex when required by the host. `scripts/jev.py status` shows only actual recorded
hook work; a manual replay is not host-activation evidence.

For an already loaded Desktop chat, persisted trust alone is insufficient when it was
written by a different CLI/app-server process. Reload through the current Desktop's
Hooks settings, or send `config/batchWrite` with `{"edits":[],"reloadUserConfig":true}`
over that Desktop's own existing app-server connection. The request refreshes that
process's loaded threads; starting another app-server cannot refresh them. Do not change
the selected model, effort, service tier or permissions to activate a hook.

Verify a fresh receipt against the current chat's `CODEX_THREAD_ID`, turn ID and timestamp.
Keep a new-host test separate from an existing-Desktop test. An async reply/steer inside
an active turn does not establish a new `UserPromptSubmit` event.

Persistent hook receipts/caches keep only metadata and a per-turn fingerprint/result,
without raw prompts, credentials, transcripts or retrieved content. Windows briefly
spools non-sensitive stdin for the shared hidden runner and deletes it in `finally`.
Immutable metadata observations also live under `jev/observations/<UTC-date>/` for
evaluation. They retain recipe/gate/fit values and excerpt hashes, never skill bodies.
They prove suggestions, not actual skill loads or task success. Duplicate turn delivery
can reuse a result only while candidate evidence is unchanged and records zero new
attempts; later eligible turns are reevaluated. No task-context deduplication is added.
Receipts identify `automatic_trigger_policy`, `trigger_reason` and `trigger_eligible`.
Keep old/new policy cohorts separate; local `automatic_scope_skipped` receipts are
zero-call abstentions, not model no-matches. Observe subsequent native skill loads,
actual procedure use, adoption, validation and outcomes, including sampled skips.
Preserve unknown usage and distinguish API latency from recorded worker duration;
neither measures complete user-visible delay. Disable network selection with
`JEV_CODEX_OFF=1`; the main model continues normally.

Upstream sync tests an exact merged candidate in isolated Linux/macOS/Windows jobs, then
fast-forwards fork main only if all tests pass and main is unchanged. Protected Codex,
hook, authorization and automation changes require manual review. A conflict or failed
check opens a stop issue and blocks later integrations until explicitly resolved.

The enrolled Windows updater runs hourly/at logon, accepts only a proven workflow commit,
checks installed ownership, runs native checks and applies the approved installer without
changing config or hooks. Local edits, missing files, changed trust definitions, failed
tests and missing provenance stop it persistently. A chat heartbeat reports new stops or
updates; it never clears a stop or bypasses trust. See `codex/README.md` for enrollment,
receipts, recovery and runtime availability. Preview image/Box, new provider routes,
local workers and browser automation are not enabled by source sync.

The same pipeline pins the official `typesafe-ai/skills` reference, including its MIT
license, source commit and file hashes. An official-only documentation change also
requires the exact tested bundle and publication proof. Executables, new invocation
metadata, symlinks, license changes and rewritten history stop for review. Runtime packages
the source as `references/official/typesafe-ai/guide.md` under the existing `/jev`;
it adds no discovery entrypoint or authorization. Both sources honor the existing stop
issue and local blocked state. For TypeSafe application/API work, read
[Build With TypeSafe](typesafe.md) and the relevant live docs instead of treating the
snapshot as a permanent API contract.
