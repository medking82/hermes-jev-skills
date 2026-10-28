# Bind cached routing decisions to their request context

A cached JEV decision could be reused after Hermes changes provider, endpoint or
model within the same turn. Retain the original request whenever that context
changes, and record the compatibility basis without logging the endpoint. Count
an applied model change only when the outgoing model actually differs.
Invalidation lasts until the next turn, so A -> B -> A cannot revive a stale
decision or routing/effort notice. Normal repeated requests in an unchanged
context still reuse their decision.

| Version scope | Version | Evidence |
|---|---|---|
| Audited installed snapshot | 0.20.0 | Historical runtime/config/log inspection; no live upgrade |
| PR repository base | 0.24.0 | `7b56de6627557e8bebb22f1538d75b37555a5623` |
| Proposed package metadata | 0.24.1 | Paired library/manifest patch bump |

Evaluation comparison excludes synthetic, mixed and unclassified pairs. Measured
inputs require explicit provenance and execution evidence references; billed cost
requires a recognized billing source and receipt reference, and quality requires
structured human-review metadata. These are structurally validated caller
attestations; the tool does not independently authenticate execution or receipts.

Includes regression tests, an offline aggregate audit tool and the baseline,
architecture, evaluation, security and rollback package in `jev-baseline.md`.
Custom-provider routing remains blocked when identity cannot be established;
no live settings, inventory mappings or deployment changes are included.

Validation and known limitations: see `jev-validation.md`. This change does not
establish endpoint execution compatibility, quality improvements or savings.

Focused follow-up validation: **1,628 tests passed** with global/system Git
settings isolated for the test process; 40 middleware and 11 offline evaluation
tests also passed separately. New regressions first reproduced both reported
behavioral gaps, then passed after the fixes. Two independent read-only reviewers
found no actionable issue. Earlier 1,340/1,621 test counts are historical checkpoints.
