# Frozen question A/B: small synthetic confirmation passed

On 2026-10-19, collected 48/48 successful, one-attempt TypeSafe requests using `jev-1.14.0`, with no unknown failures. No private/customer footage. Ground-truth labels and split IDs were kept out of model inputs. The original 24-frame corpus, prompts, model, source and tests were frozen before collection. The previously published 33-frame holdout was not submitted or used to tune this candidate.

## Outcome

Both development and confirmation had six clean and six deliberately defective frames. Each frame was submitted to both arms. The composite A question confidently cleared **0/6 clean frames** in each phase. The four focused B questions confidently cleared **6/6 clean frames** in each phase. **Neither arm confidently cleared a defective frame**, across 12 defects total. Both phases independently passed the predeclared B development/confirmation check at the unchanged **0.9 per-answer floor**.

This is a promising, small synthetic question-design result, not general visual-quality certification. The split experiment stayed frozen between phases. The collector does not promote B into production, lower a threshold, or accept any video. Mandatory final review and confidence-clear sampling remain. The production question remains unchanged pending explicit reviewed promotion.

## Protocol limitation

**Deviation:** the collector used fixed A-before-B ordering instead of the planned counterbalanced arm order. The frame sets and prompts stayed frozen, and both phases passed their numeric safety/coverage checks, but this is an exploratory result, not a clean preregistered comparative confirmation. No end-to-end speed or general robustness conclusion is warranted. The deviation was not hidden with a paid rerun.

## Cost and time

- Configured-rate estimate: **$0.002642514000000000377502**, within the $1 owner ceiling. This is **not verified invoice spend**. Native TypeSafe has no per-request `max_price` field in this protocol; the collector reserves 8M input tokens per sequential request and immediately stops on unknown usage/outcomes, model mismatch, failed send or reservation exhaustion. Unknown spend is never silently recorded as zero.
- Whole collection: **9.39 seconds**. A raw request wall time: **4576.253 ms** summed; B: **4755.36 ms**. Fixed A-before-B ordering and image/backend caching can confound latency. No reviewer-task timing or end-to-end savings were measured. Fewer clean referrals alone is not proof of faster total QA.
- All 48 planned attempts have completed records. No redirects, automatic paid retries, replays, provider switches or unknown outcomes. The managed resource lease is closed.

## Verification and artifacts

The exact paid collector is preserved at **`980c983`**, with all nine frozen source/test hashes in the summary. Its archived source successfully recounted 48 successful attempts and no unknown failures after collection. A later source revision repairs counterbalancing, validated offline; **no paid rerun was performed**. Use `980c983` or its exact archive to audit the original freeze, rather than silently substituting the newer collector.

The full suite passed on Python **3.9.6** (1,609 tests, no skips) and **3.14.8** (1,609 tests, five skips) before collection. Collector tests include end-to-end real-client/PNG/transport rehearsal without network, network failure, redirect refusal/error preservation, cap/source checks and replay refusal. A regression reproduced a hidden stale-socket HTTP retry with `retries=0`; the client now honors one HTTP attempt for that setting using request-local context, while preserving other retry settings.

`summary.json` contains aggregates and source/corpus/test hashes, not credentials or raw service errors. Private approval, attempt journals, replies, any error bodies and original fixtures remain local. Run `scripts/run_video_qa_ab.py audit FIXTURE OUT` against the original frozen source to independently recount attempts and reservations without network. This is self-review and QA, not independent review.
