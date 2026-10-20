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
backs up changed runtime files, dynamically archives every standalone `jev-*` directory and disables
their former discovery paths. Existing keys and provider settings are neither read by
the agent nor changed by the installer. The generic upstream `install.py` installs
multiple agents/skills; use the Codex-specific installer for this consolidated setup.

Review/trust the new hook once in Codex `/hooks`. Do not bypass the trust review or
manufacture stored approval hashes. New or changed hook definitions require review.
Source publication and a manual hook replay do not establish host activation.

## Runtime

`UserPromptSubmit` runs before the model. Its worker gets a hard 3.5-second deadline.
Acknowledgements, explicit selections, sensitive requests and user opt-outs skip network
selection. For an ambiguous turn, the adapter reuses upstream two-stage skill selection;
an independent design-mode question shares stage one's request. It injects a short
advisory recommendation, never a tool call or a blocking decision.

The hook catalog covers enabled user scopes (including `.system`) and explicitly trusted
project scopes. It honors exact disabled paths and explicit-only metadata. It deliberately
does not rank unrelated plugin caches. For plugin selection, pass the host's current
available-skills catalog to `select`; exact namespaced IDs and paths are retained.

Discovery stops at skill entrypoints instead of walking resources, dependencies or
embedded examples. Timeouts/catalog failures leave explicit, prompt-free reason codes.

Only duplicate delivery of the same turn may reuse a prompt-free fingerprint/result.
There is no cross-turn decision cache or added retry loop. `JEV_CODEX_OFF=1` disables the
automatic gate. Existing `JEV_PROVIDER` is respected; otherwise the adapter uses TypeSafe
without provider fallback. It preserves the existing Jev alias/version setting and logs
the version actually returned. Preview image/Box features are not enabled automatically.

The last observed hook receipt lives in `<codex-home>/jev/last-hook.json`; it contains
skill IDs, outcomes, request-attempt counts, model versions, tokens and timing, not prompt
text. The Windows launcher briefly spools stdin under the user's Codex runtime so the
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

## Validation

```text
python -B codex/check.py
# Full suite only on upstream-supported Linux/macOS:
python -B codex/check.py --full
```

Tests are offline and use synthetic state/fake transport. A separate small live smoke
run may verify the installed adapter, using existing credentials privately. Inspect its
returned model/usage; local mocks do not prove real API or Codex-host hook behavior.
