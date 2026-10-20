# Jev video-frame trial: measured result

## Verdict

Promising **opt-in visual-QA assistance**, not a production auto-clear gate. The pinned TypeSafe image model identified every deliberately defective frame in this tiny known-answer fixture, including checks the simple local pixel baseline cannot perform. No frontier-model savings, broad video-QA accuracy or artistic quality claim is established.

## Actual experiment

An original diagnostic video was encoded to H.264 and decoded to 18 individual 640×360 PNGs. The source has six clean frames and twelve defects, two per class: clipped heading, overlapping text, absent required Start button, red rather than orange button, blank frame and tiny heading. The deliberately held 2 fps frames do not test animation cadence or temporal defects. Defect labels and image identities were frozen before inference and never sent to Jev.

The first live pass used `jev-1.14.0`, a fixed question and a predeclared 0.9 candidate-clear threshold:

- 18/18 requests returned the pinned model successfully. Every defective frame was flagged; all six clean frames were clear. Zero known misses and zero clean-frame escalations.
- 2.668 seconds whole trial; 144.839 ms median per-frame wall latency; 19,910 reported input tokens.
- Configured list-rate estimate $0.00083622. This uses the repository's $0.042/million-input-token setting, not a current-price guarantee or verified bill.

After safety hardening, a **same-set recheck**, without changing images, question or confidence floor, again flagged all twelve defects and cleared all six clean frames. It used 19,900 tokens in 2.680 seconds, 136.520 ms median, with configured list-rate estimate $0.00083580. This is not 36 independent examples and does not improve the statistical sample size.

Including the earlier single-request image-readiness check, there were 37 live requests and 40,956 reported input tokens in this task. Configured list-rate estimate for those requests: $0.00172015. Invoice-level billing was not retrieved.

## Baselines and what improved

Two cheap measured pixel checks, for uniform/blank luminance and gross red-palette violations, detected four of the twelve defects with no clean-frame flags. Adding a predeclared every-sixth-frame review queue selected six of twelve defects and one clean frame for review. That is **queue coverage**, assuming a later reviewer recognizes all queued defects. It is not a measured frontier model's detection rate, latency or bill.

Jev's own raw choices were `flag` for all twelve defects and `clear` for all six clean frames, so local code did not hide a Jev miss. The hybrid review queue therefore covered all twelve defects and skipped immediate deep review of six clean frames. No 90% saving is claimed. The useful evidence here is extra **semantic defect coverage** for a small measured screening cost, not proof that Jev is faster than local code.

The pixel baseline is not the complete Cinetic-derived checks, OCR, source-layout instrumentation or an optimized classical detector. Existing frame-count, timestamps, cadence, audio, loop-seam and brand/visual review gates remain necessary.

## Safety, review and tests

The runner requires explicit synthetic-upload consent, refuses alternate endpoints, validates the manifest/path/hash set before any outbound request, checks the exact byte hash again immediately before upload, and journals attempts. It refuses silent replay or overwrites. Transport failure, unknown usage, unexpected model identity, low confidence and budget exhaustion stay in the review queue. Known code failures cannot be overruled. No automatic delivery/acceptance hook was installed.

Critical self-review fixed an overly broad test that confused the ordinary phrase 'button label' with actual ground-truth leakage, an existing local font's tiny-size rasterizer failure by selecting another already-installed licensed font, and conservative handling of usage/mutation/replay failures. A scaled contact-sheet visual helper also confused some tiles. Actual single decoded images plus generated-source and pixel checks confirmed the original labels; they were not relabelled to agree with the helper.

Twelve new offline boundary/accounting tests pass. The full offline repository suite passes: 1,545 tests run, five skipped, in 34.815 seconds. The public text-release guard passes. Binary artifacts are only the original synthetic fixture and an unchanged pre-existing public dashboard image; no font files, private footage, customer content, keys or host paths are shipped. This is critical self-review, not independent review.

No fleet `vision_cloud`, routing, key flow or gateway state was changed. Only these specifically authorized synthetic frame images were sent through the existing TypeSafe key flow. The experiment's scripts and skill guidance are opt-in.

## Next useful step

Keep Jev advisory. A separately authorized holdout of varied real-world or synthetic scenes should include near-miss clipping, legitimate overlaps, dark intentional frames, diverse typography, gradual motion and transitions. Measure false negatives and review workload against code plus selective visual review before any production use. Private/customer image upload still needs its own explicit approval.

Evidence: `manifest.json`, `live-trial.json`, `guarded-recheck.json`, their row/attempt receipts, `provenance.json`, `offline-tests.json`, `frames/`, `trial.mp4`, and `labelled-contact-sheet.png` in this directory. No private assets are required to read the receipts.
