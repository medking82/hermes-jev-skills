# Default video-QA rollout: result and limits

## Decision

Make Jev-assisted **screening/review planning** the default video-QA workflow, not an optional pilot and not automatic artifact clearance. The shared `vibe-editing` router now requires `jev-video-qa`; the new general helper accepts the actual video's requirements instead of the pilot's hard-coded heading/button. Local measurements, privacy boundaries, confidence/error fallbacks, required audits and final playback/audio/privacy acceptance remain authoritative.

This is **not evidence that general Jev visual screening is faster than competent selective review**. The fresh holdout specifically failed to establish that benefit. The safe default can prioritize likely problems and bound unproductive inference without pretending a model has approved the film.

## Fresh holdout, frozen before inference

Original synthetic footage only: 33 actual encoded/decoded frames at 800x450 and 2 fps, 16.5 seconds with no audio. This is a diagnostic still-frame sequence with intended holds, not a commissioned production film or motion-quality benchmark.

Four distinct layouts, two fonts, different headings/buttons, dark/light palettes, a deliberately allowed red button and a separately authorized intentional blank. There are 16 deliberately defective frames and 17 clean frames. Defects are clipping, overlap, missing button and tiny required text. Labels live only in `truth.json` and the local inspection sheet; the API receives only the decoded image and approved requirements, not paths, IDs or labels. Representative light/serif and chart clean frames were separately inspected at full frame size. The generator, encoded clip, frames, truth, job contracts and every initial receipt are retained.

Pinned model `jev-1.14.0`, fixed general question, unchanged 0.9 candidate-clear floor. The prompt and threshold were **not tuned after seeing the misses**.

## Live observations

- 33 calls, 52,087 input tokens, 6.439 seconds summed screen time across the five jobs. Encoding, fixture generation and human/helper review are outside that time.
- Two raw `clear` errors on tiny text: `h02` at 0.37 confidence and `h19` at 0.55. Neither crossed the floor, so neither was automatically cleared.
- No clean frame was explicitly flagged, but none of the 17 clean frames crossed 0.9 either. Every frame was referred for visual review. **Zero review-work saving was demonstrated.** Zero unsafe automatic clear is not the same as successful defect detection.
- The general helper initially read a nonexistent cost dictionary field, leaving initial cost fields absent and the aggregate erroneously zero. Those original receipts are preserved. `accounting-correction.json` computes the configured list estimate from actual recorded tokens: $0.00218765 for the holdout, not a measured zero bill. The meter was repaired and directly regression-tested.
- Final-code smoke repeated the existing eight paper-layout frames: eight live calls, 12,632 tokens, 1.162 seconds and a configured list estimate of $0.00053054. It truthfully returned `requires_full_visual_review: true` with prioritized IDs and `final_acceptance: false`. This is a safety/installation smoke, not another independent accuracy sample.
- Total live work for this request: 41 calls, 64,719 input tokens, configured-list estimate $0.0027182. No billed invoice, frontier-model time/cost comparison, general speed percentage or artistic-quality gain was measured.

## Default behavior implemented

`jevkit/video_qa.py` plus `scripts/video_qa.py`:

1. Validate a closed task-specific contract and freeze it against caller mutation. Local decode/geometry/duration/cadence/audio states must be measured; failed or unknown prerequisites do not read/send images.
2. Only already-authorized synthetic/public pixels may leave the machine for TypeSafe. Private/customer/unknown work stays local. Synthetic origin does not override likeness, license or privacy restrictions. Requirement text that is sensitive/redactable is not sent. No blanket cloud-vision switch is changed.
3. Pin the model; verify byte hashes; send exact checked assets; keep metadata and ground truth local. Reuse exact duplicate bytes only within that one job and requirements. Unknown/changed identities, invalid confidence, missing usage, provider errors and budget-deferred work never become clear.
4. Bound the loop at 64 model calls, 30 seconds by default, 100,000 reported tokens and three errors. After eight calls with no confident clear, stop buying more decisions and use full visual fallback. This low-coverage circuit is regression-tested rather than presented as a new live speed result.
5. Return triage order, review IDs and mandatory audits. Routine candidates retain first/last, scene-start, transition and every-tenth audit; high/unknown risk audits every candidate. The helper always refuses final acceptance. Keep the original temporal, audio, factual/caption, privacy, artistic and delivery checks, then recheck actual repairs.

`skills/jev-video-qa/SKILL.md`, `docs/video-qa.md`, the setup pointer, README and changelog describe this behavior. The shared master router and `references/jev-video-qa-default.md` make it the production-workflow default without enabling the broad screenshot shadow.

## Critical self-review and QA

This is self-review, not an independent review. The targeted default/pilot tests passed, including privacy/no-pixel/no-send, local failure/unknown blocking, hash mutation, fixed model/confidence, exact duplicate handling, scene/transition/high-risk audits, cost metering, zero-coverage stop, call/time limits, caller mutation and real private CLI fallback/replay refusal.

The full suite initially exposed a second README skill-count occurrence still saying twelve after adding the thirteenth skill. It was repaired without weakening the test; the failure summary is retained in `initial-gate.json`. Full suite rerun: **1,562 tests run, five skipped, exit 0**. Public text release guard passed. All newly included binary footage/images were originally generated synthetic fixtures, not private account/customer material; unchanged pre-existing binary assets were not adopted as new test evidence.

## Installed readback

Canonical installer completed without warnings or failures. Actual `jev-video-qa` and shared `vibe-editing` skill loaders passed at all 40 explicit local homes; all 40 configuration hashes matched their pre-install values. Root general cloud vision remained off and no owned resource leases remained. See `rollout.json`. No gateway restart, remote-machine update or replacement of already-built in-flight prompts is claimed.

The finite trial does not cover arbitrary footage, faces, subtitles, subtle typography, compression artifacts, temporal consistency, audio, multilingual text, factual charts or real-world privacy detection. It does not establish that confidence is calibrated on all those domains. Keep fallback/audits until appropriate evidence exists; never lower the confidence floor to manufacture a fast result.
