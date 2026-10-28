# Jev 1.14 synthetic gate qualification

This records pre-installation candidate evidence, not policy-promotion authority. The shipped policies retain their existing calibration markers. Publishing or installing the guard/rescorer does not promote the private candidate policies or change a fleet mode.

## What was measured

A pinned `jev-1.14.0` run applied both policies to the 118 historical synthetic fixtures and ten newly frozen encoded-shell cases. These 256 policy/case results contain 243 sent requests, nine local code decisions and four privacy skips. The training sets each had zero false approves. The ten-case holdout exposed one ask-policy false approve: a base64-decoded stream piped to `zsh`. That holdout is now discovery/regression evidence, not an independent test of the repair.

The local rule was repaired for standalone/absolute decoders, `-D`, additional shell families and a direct `env` shell wrapper. It does not decode or execute anything and is not a complete shell parser. Existing shadow modes remain unchanged; no model threshold or live approval behavior was promoted.

Private candidate policy files retained the original numerical thresholds, versioned their calibration marker for 1.14 and were frozen before a fresh 60-case heldout run. Training rows were rescored offline with their original readings, not purchased again. Thirty fresh hazardous cases and thirty benign cases were labelled before collection:

- Ask policy: 30 human gates, 30 benign approvals, zero false approves, no response errors. Twelve hazardous cases were decided by code; the remainder used Jev.
- Strict policy: zero false approves, 19 of 30 benign cases approved. One hazardous-case reply failed the existing response validator and remained `no_opinion`; it was not retried or counted as a successful classification.
- The fresh run sent 108 requests. Both stages together sent 351. Configured-rate usage estimate was USD 0.01596756; known usage plus the unresolved response reservation was bounded at USD 0.016460682. Sum of all per-attempt conservative reservations was USD 0.197029308. These are computed estimates/bounds, not invoice verification.

Original result digests:

- Baseline: `710cc7c69072e94e79077842927eb34dc4bb0350000375c143c6819cd9a2599e`
- Recalibrated candidate: `15043e112dec4400f9cba826e33355dd6bcff18949c5043013b46be15502b1a1`
- New 60-case corpus: `1b8a0cb9c6cbacf2a8a5c8923be2e3ec68988821c41ec03009f887b75c8f5615`

The completed collector was resumed with its network function patched to raise. No request was made and the result bytes stayed identical. Every attempted row had a durable marker; known local privacy skips and one validation rejection remained in the denominator. No unresolved attempt was resent.

## Reproduction discipline

Use pinned synthetic fixtures and explicit policy files in an isolated evidence directory. Native `jev gate replay` currently calls the batch engine with retries enabled; do not assume that CLI is a single-attempt paid collector. A one-attempt evaluation uses the same `decide` engine with `retries=0`, records a write-ahead attempt marker, pins the returned model and preserves cumulative reservations across continuation. Keep the original collector/freeze when repairing local collection or scoring; do not conceal an invalid reply with a fresh request.

The numerical thresholds were retained because the original training replay met its zero-false-approve criterion, not because heldout answers were used to optimize them. Retaining them is a measured no-change decision, not proof they are globally optimal. Any later threshold tuning needs a new training/frozen-holdout separation.

## Limits

The new corpus is synthetic, small and partly generated around the repaired rule. This is evidence for the measured boundary, not portable security, full shell understanding or general model reliability. Privacy skips and a rejected reply do not establish model correctness. Strict-policy real-shadow sample requirements, confidence bounds, observed harmless-command friction, host integration and explicit owner promotion remain unqualified. The ask gate remains advisory; an `approve` reading is not authority for protected actions.

The full suite passed 1,616 tests on both Python 3.9.6 and the Hermes qualification runtime after one unrelated 5 ms asynchronous timing test failed at 6.01 ms on the first full run. That failed run is retained in private evidence. The passing rerun changed no timing threshold and did not modify the queue implementation.
