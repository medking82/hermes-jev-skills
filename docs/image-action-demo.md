# Image choices on a real native desktop

This is an **opt-in experimental demonstration**, not a new default computer-use driver. PR #47 is merged at `5acac9262b96a275067c90417495518a563afcda`. The installed Hermes image/client modules were used from a real Donna tool run, with the existing paired Co-Agent native computer-use service performing input. The global cloud-vision switch remained **off**. No gateway was restarted.

## Final measured sample

Same pinned `jev-1.14.0`, nine decisions per route, three rounds of three actions, alternating route order. Fresh synthetic fixture state before each route. Each action selected a workspace, typed supplied plaintext into an empty note field, or clicked Preview. A separate colour test asked the image route to choose the teal tile from A/B/C without putting the colour-to-ID mapping in its candidates.

- Elements: median **103.4 ms**, p95 **151.8 ms**, 9/9 independently verified actions.
- Images: median **171.7 ms**, p95 **257.6 ms** for the primary image call. Six of nine primary picks met the unchanged 0.65 confidence floor. Three did not, so the measured hybrid explicitly called the element route instead of forcing an image click.
- Image-first including those text fallback calls: median **203.5 ms**. All nine hybrid actions independently verified.
- Additional visual-only colour decision: **159.8 ms**, correct tile B, confidence 0.99, independently verified by the fixture state.

These are wall-clock **decision calls**, not full task latency. Screen observation, capture/encoding, input execution and verification are excluded. Hybrid timing adds the two decision-call durations, not intervening observation overhead. The recording keeps native footage at 1x. This small synthetic sample is not a universal benchmark or evidence that images beat text. The interesting result is added visual evidence, not a speedup.

## Failures are retained

`evals/image-actions/initial.json` is the first failed attempt: repeated native `type` actions with `replace:true` appended text, breaking Preview. This is an observed Co-Agent input-path limitation, **not fixed by the image PR**. The revised benchmark uses independently checked fresh fixture preconditions, so it tests real typing into empty fields; it does not establish replacement reliability.

`fresh-state.json` retains the next image-only run: 9/9 element actions and 7/9 image actions verified, with two image Preview decisions below threshold. The final `hybrid.json` retains the measured fallback run, including every primary confidence and fallback cost. These are different configurations, not repeated runs discarded until an all-image pass appeared.

## Safety and reproducibility

`python3 scripts/benchmark_image_actions.py --output <private-owned-output> --rounds 3` requires macOS, Swift, Pillow, the installed Hermes Jev package, an authorized TypeSafe key and paired Co-Agent/Cua computer use. It makes live inference calls and sends only its synthetic owned-window captures. Run under the fleet's bounded process-resource wrapper. It owns and closes the native fixture and recording. No account, customer, permission, production or other application input is involved. The default output directory is deliberately not supplied by the script.

Jev returns only a prevalidated action ID. The caller retains the exact target and supplied plaintext. Unknown IDs, stop IDs and low confidence do not execute. After inference the caller reobserves, requires a unique target, uses the normal owner-policy-checked executor, and independently checks fixture state. The Box primitive is not used to execute arbitrary generated coordinates.

Use elements first on well-labelled interfaces. Images can add colour, visual layout and canvas evidence. Low-confidence image choices should reobserve, fall back to trustworthy elements, or stop. This demo does not qualify sensitive screens or a fully autonomous image-based desktop controller.

Seven offline demo/accounting regressions accompany the opt-in fixture. A separate final-code native regression also passed all seven actions, with one text fallback; its timing is retained in `evals/image-actions/regression.json` and is not pooled into the nine-per-route promotional sample. The complete local suite passed 1,518 tests. Production rollout or enabling cloud screenshot forwarding for unrelated tasks is not part of this demonstration.
