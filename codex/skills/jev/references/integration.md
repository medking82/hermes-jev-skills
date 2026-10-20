# Codex Integration

Source: `medking82/hermes-jev-skills`, `codex/README.md`.
Use `python codex/install.py --check` then `python codex/install.py --apply` from the
canonical checkout. The Codex installer does not run the upstream multi-agent installer.
It installs the toolkit and one `jev` skill, archives prior standalone Jev skills and
disables their original discovery paths in Codex config. Backups stay under Codex home.

`UserPromptSubmit` runs the selector before the main model. The hook recommends one
local skill and can include a design mode from the same stage-one request. Upstream
two-stage skill verification still decides whether any specialist is needed.
Plugin metadata is supplied from the live session by `select` when needed; the hook
does not scan unrelated plugin caches or claim it saw the session's full catalog.

Review/trust the installed hook once using Codex `/hooks`; changed hook definitions
require review again. Do not fabricate trust hashes or bypass trust. Restart or resume
Codex when required by the host. `scripts/jev.py status` shows only actual recorded
hook work; a manual replay is not host-activation evidence.

The hook keeps prompt-free metadata and a per-turn fingerprint/result. It never stores
raw prompts, credentials, transcripts or retrieved content. Duplicate turn delivery
can reuse a result; later turns are reevaluated. Disable network selection with
`JEV_CODEX_OFF=1`; the main model continues normally.

Upstream sync creates a reviewed integration branch/PR after offline checks. Publication,
installed copies and model aliases are separate. Run the Codex installer from an accepted
fork commit to update locally. Preview image/Box, new provider routes, local workers and
browser automation are not enabled by a source sync.
