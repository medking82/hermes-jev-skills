# Fresh video-question A/B: exploratory live result recorded

The production composite question and 0.9 floor stay unchanged. This is an exploratory question-design experiment, not an automatic upgrade.

## Offline preparation

```bash
python3 scripts/prepare_video_qa_ab.py /absolute/new/output-directory \
  --sans /path/to/a/sans-font.ttf --serif /path/to/a/serif-font.ttf
```

Requires Pillow for local rendering; the main library remains standard-library only. The output directory must be new. The script contains **no inference runner**, opens no endpoint, and makes zero model calls. It creates 24 original 640x360 synthetic frames: 12 development and 12 confirmation, six clean and six renderer-injected defects per phase. Layout, palette, typography, positions and headings vary. Defects include clipping, tiny text, overlap and a missing required button. Labels describe the injected contract violations, not independently adjudicated natural-video ground truth.

`manifest.json` binds each frame SHA and requirement. `labels.json` stays separate. `preregistration.json` freezes model, confidence floor, phase counts, seed, source/font hashes and both arm-question hashes. `approval-template.json` explicitly says approval is **false** and contains no spending grant. Do not publish private/customer images as substitutes for these fixtures.

## Arms

- **A**: the existing composite clear/flag/uncertain question.
- **B**: separate presence, delivered-size legibility, unintended occlusion and required-elements questions. Each uses the same three choices and unchanged floor. Only all-clear answers above the floor can qualify as candidate clear; any uncertainty, flag, invalid shape or lower confidence means review.

`jevkit.video_qa_ab.parts` builds the model-visible state; `questions` builds the closed questions. No label, split, dataset filename or scoring metadata is included. Do not use per-question confidence as a mathematically proven joint probability.

## Live execution gate

The initial preparation made no live calls. An owner-approved $1 cap subsequently authorized the frozen 48-request evaluation; see [the collected result](../evidence/question-ab-20261019/REPORT.md). Obtain a new scoped grant before another paid experiment; the template is never authority. Do not interpret the template, a source installation, or the previous pilot's tiny estimated cost as new authority. A local rate estimate is not a provider-enforced invoice ceiling. Preserve unknown dispatch/spend and never silently retry a questionable attempt.

Use the common meter and caller-owned immutable frame/requirements bindings. Pin the model, record the returned model, and do not mix policy/model/question versions. For rigorous follow-up, counterbalance arm order per frame; use no best-of-N reruns. **Protocol deviation in the first exploratory collection:** its collector used fixed A-before-B ordering, despite the planned counterbalance. This confounds latency/cache comparisons. Keep that result visible and do not describe it as a clean preregistered comparison. Keep labels local until responses are durable.

Development comes first. If B has an unsafe clear or no usable coverage, stop before confirmation. If it qualifies for confirmation, consume the already-frozen set without changing questions, floor or exclusion rules. Record every attempted case, fallback, cost/latency and review outcome; do not hide partial runs.

## Offline receipt validation

`jevkit.video_qa_ab.score(manifest, labels, receipt)` verifies manifest and per-row frame/requirements/question digests, exact returned model, complete A/B coverage of the named phase, known IDs/labels, unique rows and valid answer/confidence shapes. It counts unsafe clears, clean clears, defects and referrals. Partial or inconsistent receipts are rejected. It cannot authenticate a supplied JSON file as a real provider receipt; fixture responses in unit tests are explicitly simulated, not live performance evidence.

Confirmation additionally requires `development_passed: true` in the receipt. This records coordinator state, not new authority or an independent attestation. The scorer always returns `auto_promote: false`.

Compare clean coverage and unsafe clears with the full observation, inference, fallback and review cost. A tiny synthetic set cannot establish general video quality, robust confidence calibration or end-to-end savings. Keep mandatory review in production regardless of an encouraging exploratory result.
