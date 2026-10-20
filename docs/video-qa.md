# Default video-QA screening and review planning

Use `jev-video-qa` by default for a video-QA job. This replaces the **optional workflow choice**, not final acceptance. It does not turn on the general Hermes cloud-vision switch. The experimental fixed-heading runner in `video-qa-trial.md` remains a historical pilot, not this general-purpose implementation.

## Run

```sh
python3 scripts/video_qa.py JOB.json --out receipt.json
# Explicitly keep a job local, even when its source contract permits cloud work:
python3 scripts/video_qa.py JOB.json --out local-receipt.json --local-only
```

A new command needs a fresh output/journal name. An attempt is durably journalled before sending. Do not silently replay a partial run. A zero exit means the screening pass completed, **never** artifact approval. Exit 3 routes to local/visual fallback; exit 2 means invalid inputs or a command error. No background worker, listener, schedule or gateway restart is involved.

## Job contract

```json
{
  "schema": "jev.video_qa_v1",
  "source_sha256": "<actual lowercase SHA-256 of the encoded video>",
  "cloud_policy": "authorized_synthetic",
  "review_risk": "routine",
  "local_checks": {
    "decode": "pass", "geometry": "pass", "duration": "pass",
    "cadence": "pass", "audio": "not_applicable"
  },
  "requirements": {
    "required_text": ["Build with AI", "Explore"],
    "required_elements": ["a button labelled Explore"],
    "palette": ["#28b4ad", "#102037"],
    "allow_blank": false,
    "allow_overlap": false
  },
  "frames": [
    {
      "id": "f0001", "image": "frames/0001.png",
      "sha256": "<actual lowercase SHA-256 of this decoded frame>",
      "local": "pass", "scene": "opening", "transition": false
    }
  ]
}
```

The angle-bracket values above are placeholders, deliberately not runnable hashes. Use real computed identities, never padded dummy values. The module validates identity **format** and the CLI checks actual frame bytes; the caller owns extraction lineage and must verify the source video and applicable local checks. A manifest is not proof by itself.

- Top-level, requirement and frame keys are closed. Job source identity is required. Frame paths stay within the job directory; the CLI bounds file size before reading. Bytes are rechecked before creating the exact image asset sent. Image format/dimensions are checked by `jevkit.images` without resizing or silently re-encoding.
- `cloud_policy` is `authorized_synthetic`, `authorized_public`, `local_only` or `unknown`. Omitted policy is `unknown` and reads/sends no image. The authorized values record **existing legitimate upload authority**, not a way to grant it. Owner-approved internal workflow defaults can cover safe synthetic/public jobs. Private/customer footage must not use these values; use `local_only` until a separate project/provider approval boundary is resolved. This helper deliberately has no private-upload bypass.
- `review_risk` is `routine`, `high` or `unknown`. Omitted risk is unknown and audits every candidate clear. Numerical/medical/legal claims, identity, captions and other high-risk content still need their own factual/semantic review, not a model's layout opinion.
- Each local check is `pass`, `fail` or `unknown`; only audio additionally permits `not_applicable`. No absent or unknown check becomes a pass. Global failures/unknown checks do not read/send images. Individual frames use `local: pass|fail|unknown`.
- Requirements are authored by the owning agent from the actual brief, not inferred from the pilot. String arrays hold at most eight nonempty strings each, with at most 160 characters per string. Palette entries use six-digit hexadecimal colors. Both intent flags are mandatory booleans. Blank frames may have empty required lists. Intent flags are not blanket defect suppressors: permitted overlap still must not make required text unreadable.
- Paths, scene IDs, source identity and labels never enter the outbound state. Only the reviewed image and requirements do. Sensitive or redactable requirement text returns to local review. This is **not image privacy detection**. A screenshot cannot be made safe by a textual scrubber. Generated/synthetic media can still be private or subject to likeness/license restrictions; synthetic origin alone grants no upload authority.

## Deterministic safeguards

Pinned model `jev-1.14.0`; fixed general question; candidate-clear floor 0.9. These identities are in the receipt. No lower threshold was selected after seeing the broader holdout. A model version change, invalid/missing confidence, missing token accounting, errors and unknown answers route to review. TypeSafe endpoint overrides are refused for this image path. The key is resolved by the existing secret-store client and never printed.

At most 64 model calls per invocation, 30 seconds by default, a 120-second maximum, a 100,000 **reported** input-token stop and three errors. This is not a hard dollar reservation: a final in-flight call can add tokens and provider billing must be checked independently. After eight calls with no high-confidence clear, the helper stops buying more decisions and sends the remaining work to full visual review. Job sizes are bounded at 10,000 frame entries. Deferred frames never become clear.

Only **exact identical encoded image bytes within the same job and requirements** reuse a decision. There is no cross-project or persistent cache. Distinct metadata/paths are not deduplication evidence. Temporal defects remain local/video checks, not a reason to reuse a single-frame visual verdict.

The receipt explicitly lists likely-failure triage order, review IDs, audit IDs, required full-visual fallback, calls, tokens, timings and configured list-price estimate. It always returns `final_acceptance: false`. Estimated cost is not an invoice.

For routine work, audit first/last candidates, the first candidate of each scene, all transition candidates and every tenth candidate. High/unknown risk audits every candidate. A small clean-looking sample is not proof of privacy, identity, caption accuracy, motion, factual truth or artistic quality. Keep the existing production workflow's playback, audio, temporal, privacy and delivery checks. Re-render/recheck repairs.

## Evidence, not a broad speed promise

The fixed-heading 18-frame pilot was perfect in two same-set passes. The fresh 33-frame, four-layout/two-font holdout was harder: two tiny-text images received raw `clear` decisions below the floor. All 33 frames were conservatively referred. None of the 17 clean frames crossed 0.9, so that holdout demonstrated **no review-work savings**. Keeping it is important: it prevents the pilot's result from becoming a false general-quality claim.

The new default is useful first-pass prioritization with bounded fallback, not a claim that Jev replaces frontier vision or is generally faster. Look at `evidence/video-default/REPORT.md` for the preserved initial receipts, cost-reporting repair and the distinction between live measurements and offline regressions. Keep the cloud-vision switch off outside explicit, separately authorized image scopes.

## Offline regression command

```sh
python3 -m unittest discover -s tests -p 'test_video_qa*.py'
```

The full release gate remains `python3 -m unittest discover -s tests` and `python3 scripts/check_release.py`.
