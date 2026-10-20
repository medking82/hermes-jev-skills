# Synthetic video-frame QA trial

This is an **opt-in experiment**, not a production gate or a replacement for a visual reviewer. It asks pinned TypeSafe Jev `jev-1.14.0` to choose `clear`, `flag` or `uncertain` against one known synthetic design specification. Jev never edits a scene or video, never chooses a shell command and never authorizes delivery.

## Scope and privacy

Only explicitly authorized, original synthetic test images may be used. Labels, case names, image paths, local pixel-check outcomes and ground truth stay local. Each request sends one image and the same fixed requirement question to the official TypeSafe endpoint. A compatible endpoint override is refused for this trial. The manifest's `synthetic: true` is a caller assertion, not an automated privacy detector; an operator must inspect and authorize the actual pictures. The script cannot make private pictures safe to upload.

No fleet `vision_cloud` switch is enabled. No routing or gateway change is needed. This experiment does not adopt SageCut, send to Sage, or compare two vendors' models. No private or customer footage is authorized by the command below.

## Reproduce

Optional fixture-generation dependencies are Pillow, numpy, a working FFmpeg and an existing locally licensed font. The trial runner itself uses the standard library and this repo's client. Nothing downloads or installs dependencies or fonts.

```sh
python3 scripts/video_qa_fixture.py "$WORKDIR/fixture" \
  --ffmpeg "$VERIFIED_FFMPEG" --font "$LOCAL_FONT"
# Inspect the generated actual decoded images and local manifest before opting in.
python3 scripts/video_qa_trial.py "$WORKDIR/fixture/manifest.json" \
  --out "$WORKDIR/first-trial.json" --allow-synthetic-upload
```

The fixture generator refuses an existing output directory. The runner checks consent before asset reading, validates all manifest hashes and paths before the first request, rechecks the exact image bytes immediately before sending, keeps per-frame receipts and a write-ahead attempt journal, and refuses to overwrite or silently replay an earlier trial. If interrupted, retain the journals; do not treat an unlogged response as a failed or never-sent request.

There are at most 32 frame calls, no automatic client retry, a 120-second whole-trial budget, a 10-second per-request deadline, a stop after three errors, and a stop after 100,000 reported input tokens. These are operational limits, **not a guaranteed monetary cap**. Unknown usage prevents candidate-clear and stops subsequent calls. List-price estimates use the repository's configured input-token rate, not a live invoice; failed/unknown-usage requests can incur additional unmeasured charges.

The predeclared candidate-clear confidence floor is **0.9**. It was not reduced after examining the answers. A known local pixel-check failure cannot be cleared by Jev; uncertainty, transport failure, missing usage, unexpected model identity, low confidence and budget exhaustion all remain in the review queue. Candidate-clear is still subject to mandatory visual audit sampling and final acceptance elsewhere. No auto-accept hook is installed.

## What was exercised

The finite pilot used an actual H.264 encode and decode of an original 18-frame diagnostic clip. Six clean examples and twelve defects cover blank frames, missing required buttons, edge-clipped headings, overlapping typography, a red button where orange is required, and tiny unreadable headings. There are only two examples per defect class and limited layout variety. Labels were frozen before model calls; no label or case name entered the request. The intentionally held frames and 2 fps diagnostic export do not test smooth motion, shot timing, sound, or production delivery settings.

A simple local baseline checks uniform/blank luminance and gross red-palette violations. It is **not** the entire Cinetic-derived QA system, OCR, source-layout instrumentation or an optimized visual detector. A separate every-sixth-frame review queue is also recorded. Its score is selection coverage against known labels, assuming a later reviewer would catch a queued defect, **not measured frontier-review accuracy or cost**. No expensive model was asked to read every frame and no hypothetical token savings are claimed.

See `evidence/video-qa/` for frozen local-truth manifest, decoded synthetic frames, actual trial outputs, and the detailed qualification note. Initial and guarded recheck outputs are the same dataset, not 36 independent examples. Successful synthetic performance is not calibration on real production footage. Before any automatic workload reduction, measure false negatives on a separate, authorized, varied holdout including near-misses, text styles, gradual motion and scene transitions.

## Review lessons

- Do not relabel a fixture based on a scaled contact-sheet answer. A visual helper confused some tiles here. Inspect the actual single decoded frames, source generation and numerical pixels before accepting or changing ground truth. Contact sheets aid navigation, not authoritative pixel assessment.
- Keep metrics honest about what is avoided. This pilot measures Jev calls and review-queue coverage, not frontier time saved or final film quality.
- Keep the exact model identity, question hash, manifest hash, confidence floor and initial failure/abstention receipts. Changing a question or threshold creates a different experiment.
- A first-party readiness check (`scripts/live_images_check.py`) succeeds only on a simple known image. It does not establish frame-QA competence.
