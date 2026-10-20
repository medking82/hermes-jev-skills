# Report and workflow improvements qualification

## Scope and status

This is a tested source candidate, not a main-branch release or running-gateway attestation. Implementation, critical self-review and offline QA were performed by the same agent; this is not independent review.

1. **Responses compatibility.** Preserve explicit/manual effort and unrelated reasoning fields; use nested `reasoning.effort` only on eligible Responses requests. Do not add an unsupported top-level field, enable absent/disabled reasoning, or emit an applied-effort notice when nothing was applied. Clear stale notices on follow-up requests. This incorporates the issue raised in PR #49 without changing routing or activating modes.
2. **Report identity.** Add exact main/check-out/managed-install provenance, including Jev skills, and separate unknown loaded runtime. The checked steward adapter refuses to downgrade a feature candidate, requires clean exact main plus the existing CI/local-test/NO_AUTO_INSTALL gates before any automatic refresh, uses `--enable none`, and verifies after installation. Record declared local dependencies separately without hashing assets or following foreign links.
3. **Measurement.** Add hash-only durable intent/outcome accounting to the new standalone video, image-action and optional Blender advice paths. Coalesce logical attempts, retain ambiguous sends and unknown cost, suppress hidden retries, and stop budgeted spending on unresolved usage. Video accounting errors request full review; optional Blender advice preserves the local planner. Rate/counterfactual estimates are not invoices or actual shadow savings. The steward helper aggregates only numeric metadata with custom labels/actions withheld.
4. **Confidence and availability.** Replace blanket inference and universal-confidence guidance with code-first decisions and task/model/question-specific evidence. Preserve mandatory GUI/browser chooser boundaries, model/threshold floors, local privacy restrictions and final artifact verification. Update the routing skill's effort-delivery guidance. The protected repository AGENTS.md file remains unchanged.
5. **Evidence matrix.** Connect routing, web, image/action, Blender and video results, including negative findings and fallback costs. Installed/available does not mean active; candidate evidence does not establish general speed gains.
6. **Question-design experiment.** Prepare 24 original, hash-verified synthetic frames in separate development/confirmation sets, frozen question arms and an offline source/model/usage-bound scorer. The production question and 0.9 floor remain unchanged. Model calls: zero. This is preparation, not a live A/B result or authorization to spend.

## Execution evidence

See [machine-readable qualification](offline-qualification.json): Python 3.14.8, 1,600 tests run, five skipped, suite OK. Regression work reproduced the wire-format/notice failures, missing provenance capability, unresolved-accounting and terminal-write failure, unknown-cost budget leakage, and offline experiment binding gaps before their respective repairs. Final tests include the relevant failure paths and existing privacy, budget and GUI contracts.

The fresh fixture's pixel identities and distinct-frame count were checked locally. Offline review added explicit per-row model/frame/requirements binding and image-text-as-evidence guidance before any live experiment. Mock scorer records are unit-test inputs, not measured inference results.

## Remaining boundaries

A live question-design A/B requires a separately approved numeric cap, an authorized executor and complete metered receipts. A receipt scorer validates consistency, not the authenticity of an API call or billing. No automatic promotion is implemented. The protected AGENTS.md wording update was not applied. Main publication/PR merge, gateways, active-mode changes, new private uploads and independent review are not implied by this qualification.

Fleet installation and daily-report wiring must be checked against exact local targets after source integration. Keep those live receipts separate from this offline evidence and never label an already-running process updated merely because source hashes match.

## References

- [Measurement and installation provenance](../../docs/measurement-and-provenance.md)
- [Workflow evidence matrix](../../docs/workflow-evidence.md)
- [Portable fleet guidance](../../docs/using-jev-in-a-hermes-fleet.md)
- [Prepared question A/B protocol](../../docs/video-qa-question-ab.md)
