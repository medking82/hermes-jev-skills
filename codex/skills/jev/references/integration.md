# Codex Integration

Source: `medking82/hermes-jev-skills`, `codex/README.md`.
Use `python codex/install.py --check` then `python codex/install.py --apply` from the
canonical checkout. The Codex installer does not run the upstream multi-agent installer.
It installs the toolkit and one `jev` skill, dynamically archives all prior `jev-*` skills
from both `<codex-home>/skills` and `~/.agents/skills`, and disables their original discovery
paths in Codex config. Backups stay under Codex home; shared-scope copies use a separate
`retired/agents/` directory so matching names do not overwrite each other.

`UserPromptSubmit` runs the selector before the main model. The hook recommends one
skill and can include a design mode from the same stage-one request. Upstream two-stage
skill verification still decides whether any specialist is needed. Plugin candidates
come from this session's host-supplied available-skills record in its native rollout,
bound to the active session/turn/cwd. The hook never scans unrelated plugin caches.
Current skill/plugin disables and explicit-only policies are checked again. Missing,
foreign, unsupported or out-of-range session evidence leaves local routing available.
Receipts report `catalog_source`, snapshot timestamp/hash and admitted namespaced plugin
IDs, without raw prompts/transcript text. A session catalog is not evidence of external
service authorization; main-model/tool access checks still apply.

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
Duplicate turn delivery
can reuse a result; later turns are reevaluated. Disable network selection with
`JEV_CODEX_OFF=1`; the main model continues normally.

Upstream sync creates a reviewed integration branch/PR after offline checks. Publication,
installed copies and model aliases are separate. Run the Codex installer from an accepted
fork commit to update locally. Preview image/Box, new provider routes, local workers and
browser automation are not enabled by a source sync.
