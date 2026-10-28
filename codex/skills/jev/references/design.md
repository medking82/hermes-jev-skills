# Design Routing

`design` selects among the existing `$design` mode guides. It does not design a UI,
choose arbitrary dependencies, add review phases or run the browser.

Input: `{"turn":"Fix sticky hover and safe-area behavior on mobile web"}`.
Output: `{"status":"ok","mode":"mobile-native","source":"jev",...}`.
On uncertainty or failure use the main model's judgment, with general component polish
(`emil-design-eng`) as the existing design default. The 0.5 confidence floor is a
starting policy, not a calibrated accuracy guarantee for this user's CJK requests.

`impeccable` is a regular candidate for UI creative direction and distinctive visual
design. It names the corresponding `$design` mode, not a separate skill installation
or an authorization to run the upstream installer, engine, hook, browser or prototype.
Preserve the existing identity for scoped refinements and follow the actual request.

The default candidate set excludes `prototype`, `pick-ui-library`, `review-animations`
and `break-ui`. Add an explicit mode in `allowed_modes` only when the actual request
authorizes it. The allowed set must also retain all other relevant regular modes;
the helper always includes the general default. A Jev result cannot authorize those modes.

If a hook already returned `design.mode`, reuse it as a second opinion on the main
LLM's mode choice. Otherwise use the helper only when two or more modes plausibly fit.
On disagreement, recheck the request, opt-in constraints and guide evidence once, then
choose the mode without another Jev call. Preserve the user's model, tool bans,
existing UI copy preference, framework, tokens and dependencies. If the corresponding
guide is unavailable, decide normally; a mode recommendation cannot create one.
