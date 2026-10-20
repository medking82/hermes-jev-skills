# Jev For Codex

The maintained Codex layer of this fork installs one `$jev` skill (shown as `/jev`
where the host offers skill slash completion). Upstream Jev workflows become references
and retain their CLI commands. The main model remains responsible for execution.

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
Acknowledgements, explicit selections, sensitive requests and user opt-outs skip network
selection. Whole commands naming an exact design mode and a narrow grammar for ordinary
component polish also route locally. Extra prose, conflicting modes and unknown wording
retain the existing semantic selector; this is not a general ambiguity classifier.
For an ambiguous turn, the adapter reuses upstream two-stage skill selection;
an independent design-mode question shares stage one's request. It injects a short
advisory recommendation, never a tool call or a blocking decision.

The hook catalog covers both user scopes above (including `.system`), explicitly trusted
project scopes, and plugins in this session's host-supplied available-skills catalog.
It reads only the matching session's native rollout, verifies the active turn/cwd, and
accepts only complete developer `skills_instructions` records. User/tool text cannot
supply a catalog. Exact namespaced IDs and versioned paths are retained; unrelated plugin
caches are never inventoried. Current per-skill/plugin disables, missing versions, and
explicit-only metadata remove candidates even if an older host snapshot listed them.

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

Only duplicate delivery of the same turn may reuse a prompt-free fingerprint/result.
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

The upstream-sync workflow checks upstream daily, merges into a fixed integration
branch, runs offline toolkit/Codex tests and the release checks, then opens/updates a PR.
It does not execute downloaded installers, update local runtimes, approve its own PR,
change endpoints/models or enable new features. Review the diff and passing checks before
merging, then preview/apply the Codex installer from the accepted fork commit.
Conflicts or failed checks stop publication. Other public Jev implementations are research
inputs, never an automatic executable update source.

GitHub's repository setting that allows Actions to create PRs must be enabled; GitHub
groups that permission with review approval. This workflow only creates/updates the
integration PR and never approves or merges it. Default workflow permissions remain read.

## Validation

```text
python -B codex/check.py
# Full suite only on upstream-supported Linux/macOS:
python -B codex/check.py --full
```

Tests are offline and use synthetic state/fake transport. A separate small live smoke
run may verify the installed adapter, using existing credentials privately. Inspect its
returned model/usage; local mocks do not prove real API or Codex-host hook behavior.
