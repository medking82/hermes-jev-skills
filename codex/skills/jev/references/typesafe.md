# Build With TypeSafe

Use this reference when building or revising a TypeSafe/Jev application, question spec,
API integration or evaluation. The complete official guidance is bundled as
[Official TypeSafe Skill](official/typesafe-ai/guide.md), with its MIT license and
[source commit/file hashes](official/typesafe-ai/source.json). It is reference material
inside `/jev`; it creates no separately discoverable `typesafe-ai` skill.

Read the relevant [live documentation index](https://docs.typesafe.ai/llms.txt) and follow
its current URLs for the API/chosen SDK, primitive and closest cookbook before changing
an API-dependent integration. The pinned guide supplies design guidance; live docs and
installed SDK types establish current field names, response shapes, models and limits.
If fetching `.md` fails, try the normal page. If neither is available, disclose that
limit and use existing local docs/types without inventing a current contract.

## Design The Decision

- Start with the requested application behavior. Keep exact rules, calculations,
  candidate construction, permissions and execution in code; use semantic judgment
  where those rules need meaning. Preserve the chosen stack and requested scope.
- Use Choice for one option from a complete allowed set; Noul for each independent
  yes/no condition; Score for comparable ordered descriptive levels. Include no-match
  or presence judgments where the application needs them. Images/Box remain opt-in.
- Supply the relevant evidence, identities and relationships as structured state.
  Put the full question meaning in instructions/criteria: question IDs are not model
  context. Missing candidates/evidence cannot be recovered by confidence thresholds.
- Batch independent questions over the same state, including useful branch-specific
  questions with explicit premises. Consume only the applicable answers. Add a later
  request when earlier answers are needed to obtain evidence or construct new options.

## Compose And Evaluate

Keep raw judgments distinct from policy and observed facts. Choice/Score confidence
describes distribution concentration; Noul near 0.5 means uncertainty about yes/no, not
medium intensity. Typed output establishes an interface, not truth or permission.
Several acceptable options can spread probability, so calibrate thresholds against the
actual data and consequences instead of copying cookbook constants. Combine scores for
compensating preferences; keep non-compensating conditions separate.

Test representative cases and application outcomes. For a failure, inspect state,
questions, candidate coverage, answers and the composition code to distinguish evidence,
model, code and service failures. Measure actual calls, tokens, latency and task quality
before claiming gains. Reuse application judgments only when evidence/question meanings
are unchanged and that reuse is within the requested application design.

The existing Codex hook still caches only duplicate delivery of the same turn, has its
existing deadline and fail-open behavior, and preserves explicit choices and opt-outs.
Official examples do not change main model/effort/Fast, providers, retry policy, workers,
browser/tool permissions, explicit-only/disabled skills or hook trust. Keep credentials
private/server-side; use the existing connection without reading or printing keys.
