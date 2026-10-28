# PR #51 current-main integration review

## Artifact and ownership

Contributor: @fatalmonk, PR #51, exact reviewed head `9ee6de083a9419efdf929dfa3ab92163b7be9ce4`. The contribution is retained as an ancestor, not copied without attribution. Integration base: published main `e66a915bc12c691234a91128edbc05861d4cea0e`, including the recorded-score and decoded-shell updates. This is Donna's self-review and executable qualification, not an independent reviewer certification.

The contributor's audit/validation documents record historical snapshots and reviewer claims. They do not establish our current installed version or current live compatibility. This integration retains package metadata 0.25.1, not the contributor's obsolete proposed 0.24.1. Current validation is in `pr51-current-main-receipt.json`.

## Findings and repairs

1. **Integration conflicts:** original #51 conflicts with current changelog, library version and plugin manifest. Preserve both sets of notes, retain 0.25.1 and label the earlier 0.24.1 proposal as historical/unreleased. The newer rescorer, manual-effort and decoded-shell changes remain intact.
2. **First-request model disagreement:** #51 binds a cached route to host/request context but can still buy and apply the first route using host metadata when the outgoing request already names another model. A new regression first failed in active mode by replacing the outgoing user-choice model; shadow mode unnecessarily classified and could revive routing when the request returned to the default. The repair retains the outgoing request, performs no classifier call and invalidates that turn. Equivalent provider prefixes still match; next-turn reset remains available. See `tests/test_routing_initial_context.py`.
3. **Positive contribution retained:** subsequent provider, endpoint or model changes disable cached routing for the rest of the turn, including A → B → A. Stale effort/notices are suppressed. Applied telemetry requires an actual request-model change. Offline audit tools aggregate safe categories; paired comparisons exclude synthetic/unclassified records, require structured execution/cost/human-review provenance and explicitly do not authenticate those attestations.

## Verification

- 1,642 package tests passed on Python 3.9 and Python 3.11, in separate processes.
- 71 dashboard tests passed. Existing warnings are retained in local logs, not claimed fixed.
- Release text/privacy scan and `git diff --check` passed. No binary assets changed.
- Root-only installer preview and actual installation passed in a disposable synthetic home, using `--enable none`. Its configuration was byte-identical before and after. A fresh import from the installed plugin exercised the mismatch guard with the classifier function forbidden, verified the request was retained and no stale notice emitted. No real home was installed or configured by this review.
- Global/system Git configuration was disabled only in verification child processes so global ignore rules do not contaminate hermetic fixture enumeration. No host Git configuration was modified.
- The installed-probe home and test servers were bounded under one foreground resource lease; the disposable home was removed on completion.

## Limits and shipping boundary

The current host source passes provider, endpoint, host model and outgoing payload into the middleware, but this is not a live gateway/provider qualification. Same-endpoint credential rotation, authenticated provider identity/entitlements and concurrent first callbacks remain unqualified. Do not enable custom aliases or claim live compatibility, model quality, billed savings or general security from these tests. Audit evidence references are caller assertions until separately authenticated.

This task submits a reviewed follow-up PR. It does not merge #51, close the contributor's PR, install this candidate into real homes, activate routing, restart gateways or alter another writer's source/configuration. The already shipped main version remains the installed artifact until a separately authorized rollout.
