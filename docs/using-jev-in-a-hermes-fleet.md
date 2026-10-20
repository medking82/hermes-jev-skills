# Running Jev across a Hermes fleet

A single agent with Jev is useful. A fleet of agents that all make the same cheap decisions the
same way is a different thing, and it needs a written posture rather than each lane improvising.
This is that posture, and it is portable: nothing here names a machine, a path or a model pool.

## The standing principle

**Code owns deterministic checks; Jev handles useful ambiguity.** Run known, inexpensive
rules locally. Use a bounded Jev choice, ranking or rubric when unresolved ambiguity warrants
its measured cost. The caller still authors plans, owns permissions and verifies artifacts.
More inference is not inherently better or cheaper.

Jev never writes executable authority. Closed-choice features accept only caller-owned IDs.
Experimental image localization can return untrusted geometry, but only a separately qualified,
explicitly opted-in executor may validate and use it. Bounds, target identity, permission,
confidence and independent verification still apply; it is not a default screenshot driver.
Neither a choice nor a coordinate authorizes spending, publication or protected actions.

## Never bypass Jev

**Never bypass Jev for a GUI/browser action assigned to its chooser.** Each action comes
from the caller's current table of prevalidated operations. Unknown IDs, stale targets or
inadequate confidence mean reobserve, a specifically qualified fallback or stop, not an
improvised click. Preserve a fleet's existing mandatory chooser rule.

This does not assign deterministic preconditions, known-ahead builds or artifact verifiers to
a model. Blender deliberately skips inference for routine checks. Such code-first decisions
are compliant, not bypasses. Availability fallback must never become protected-action approval.

Fail-open is not a bypass, and the difference matters:

- A fail-open answer is **exactly what the agent would have done without Jev** — routing keeps the
  current model, memory returns the original list, compaction drops nothing, skill selection
  suggests nothing, and GUI and browser use return `reobserve`.
- An answer that contradicts itself is a failure, not a reading: a Choice whose probabilities do not
  cover exactly the options offered, a chosen option that is not the maximum, a Score that disagrees
  with its own distribution — `client.ask` refuses these as `invalid_response` and the feature takes
  its fail-open path. The reply parses; the answer is what is unusable.
- A bypass is improvising an action the applicable feature policy assigns to its chooser.
  That is forbidden; a fail-open path is never cover for it. Explicit local pre-rules are different.

A fleet that treats fail-open as "and then do whatever you like" has no rule at all.

## Which decisions Jev owns

| Decision | Fires when | Fail-open |
|---|---|---|
| Model routing | Every routed turn | Keep the current model |
| Skill selection | A turn arrives and a skill might apply | Suggest nothing |
| Memory filtering | A retrieval returns more than a handful of passages | Return the original list |
| Web result screening | Every `web_search` / `web_extract` result (`/jev screen on`) | The result as fetched, minus what the local pattern screen withholds |
| Turn selection | A transcript must be cut to a fixed size | Drop nothing |
| Search picking | After a search, before opening results | Screened head of the list, marked `unknown` |
| GUI action | Before each step in a desktop loop | `reobserve` |
| Browser action | Before each step in a page loop | `reobserve` |
| Escalation | A task is already judged hard | Name no seat and carry on |
| Supervision | While delegated work is running | Keep polling the transcript |

The gate to hold onto: an agent should be able to say which row a decision came from. "I decided"
without a row is the thing this whole arrangement exists to remove.

## Thresholds a fleet must not quietly change

Preserve existing confidence floors. Confidence needs evidence for the specific model,
question, state shape, domain and downstream outcome; installing Jev does not establish
universal calibration. Freeze a new evaluation when a question or domain changes; do not
lower a threshold to manufacture actions. Relevant floors include:

- the floor before a GUI action,
- the floor before a transcript turn may be dropped,
- the routing floors on probability mass, and "unsure is not hard".

Substituting a model that reports its own confidence, or changing a question, changes
what those numbers mean even when the response
still parses. A different model belongs behind its own named contract and qualification.
Report unsafe clears, useful coverage, abstentions, clean referrals and actual executor
outcomes separately. A model clear is not final acceptance or permission to expose private data.

## Rolling it out

1. **Shadow.** Decide and log without switching anything. A day of shadow decisions is the
   cheapest evidence a fleet will ever get, and it is the honest way to see what Jev would do.
2. **Read the log, not the silence.** A quiet log proves nothing; confirm the decisions actually
   arrived and look like decisions.
3. **Turn it on**, then watch. Per-profile settings override the fleet default, so a lane can be
   opted in or out without touching everyone else.
4. **Bound by the clock, not the count.** A decision that has not answered in its budget is a
   fail-open, not a reason to wait longer.

## Default workflow evidence and honest economics

Use [the workflow evidence matrix](workflow-evidence.md): elements first on labelled UIs,
code-first Blender, and guarded video triage with mandatory audits/full-review fallback.
None of the small fixtures proves universal speed, artistic quality or security.

[Measurement and provenance](measurement-and-provenance.md) separates published main,
checkout, installed files and actually loaded code. A file install does not prove a running
gateway reloaded. Separate decision-call latency from observation, execution, fallback,
verification and full review. Shadow still runs the original path, so its avoided tokens are
counterfactual estimates, not realized savings. List-rate estimates are not invoices; an
unresolved attempt is unknown usage, not zero cost. No new mode, provider, handoff, screenshot
upload or gateway restart is authorized merely by these portable instructions.

## Where the fleet's own facts live

The public repo holds the **loop**. Anything specific to one fleet — which machine, which
credential source, which driver or harness version, which older skills are retired, which
profiles are private, and the standing posture above — belongs in that fleet's own rules file,
not here. On Hermes that is `~/.hermes/shared/rules/<topic>-fleet.md`, and the shipped skills
point at it rather than forking.

Skills **point, they do not duplicate.** A skill that repeats a fleet's runtime facts will be
wrong within a release, and a reader will not know which copy is authoritative.

## What a fleet should write down

- which decisions Jev owns, and which it deliberately does not;
- the thresholds in force, and who may change them;
- the pointer to its own fleet rules file;
- which profiles are private, and therefore send coarse features only;
- the escalation order for hard work, and where a refusal is recorded so other lanes skip that
  seat;
- the one-line rule for the fleet's own agents: local rules first, bounded Jev for useful ambiguity.