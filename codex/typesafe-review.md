# TypeSafe Documentation Review — 2026-10-20

The [documentation index](https://docs.typesafe.ai/llms.txt) contained 130 unique pages.
The full text snapshot, all 79 SDK pages, 21 cookbook narrative/index pages and 285
cookbook code blocks were reviewed across the parent and one bounded research agent.
[typesafe-docs-index.json](typesafe-docs-index.json) records every URL and content hash.
The OpenAPI schema was fetched separately. Embedded media, nine unexpanded example
components and the interactive Score explorer are outside that text snapshot; they are
not claimed as executed or visually inspected.

## Adopted In The Codex Layer

| Documentation Finding | Implementation Decision |
| --- | --- |
| [Coding-agent boundary](https://docs.typesafe.ai/introduction/coding-agents): Jev returns typed decisions, not chat/code | Keep the main Codex model and execution authority unchanged |
| [Code owns the workflow](https://docs.typesafe.ai/concepts/how-to-build-with-system-one) | Explicit choices, privacy, local scopes and fallback are deterministic |
| [Skill suggestion](https://docs.typesafe.ai/cookbooks/skill_suggestion) legitimately uses two stages | Reuse upstream ranking and candidate-specific verification; preserve host IDs and paths |
| [Speculative fan-out](https://docs.typesafe.ai/patterns/fan-out) evaluates independent questions together | Workflow applicability and design-mode choice share the first skill request |
| [Choice](https://docs.typesafe.ai/primitives/choice) always has a winner | Require a separate workflow-applicability Noul and permit no skill to pass verification |
| [Confidence](https://docs.typesafe.ai/confidence) is derived from probabilities, not correctness or authorization | Abstain on weak choices; scope and permissions are never model decisions |
| [State](https://docs.typesafe.ai/concepts/state) should be small and relevant | Send a bounded redacted task, not full transcripts, paths, source files or private records |
| [Jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13) includes counting, date/math, indirection, order effects and adversarial state | Keep calculations in code; use literal questions and existing eligibility checks |
| [Models](https://docs.typesafe.ai/models) distinguishes aliases, stable/preview and returned versions | Preserve existing settings, record the returned model, enable no preview by source sync |
| Current pricing counts input tokens | Batch to reduce round trips/repeated state; extra question text still has a cost, recorded in receipts |
| [Request rules](https://docs.typesafe.ai/api/errors) require finite JSON numbers | Reject non-finite bounded-decision state locally; failures never block Codex |

## Features Preserved Or Deferred

The current upstream adds Blender and video QA workflows. Their source guides are
packaged as references, while their separate Codex entrypoints are retired. Their
existing explicit opt-ins, code-first behavior and verification requirements still apply.
Browser/computer action tables remain closed choices over caller-observed candidates;
no browser, driver, local worker or GPU workload is started by the adapter.

[Images](https://docs.typesafe.ai/images) and [Box](https://docs.typesafe.ai/primitives/box)
are experimental and require preview behavior. JSON base64 is supported, but has size
overhead; multipart is recommended. A Box always returns coordinates, even for an absent
target, so it needs a separate visibility decision and independent execution checks.
Image-side limits, total expanded references and newer SDK compatibility differ in places
from the current toolkit. These are recorded for a separate, representative image task;
none is needed for text-only skill/design routing, and no image forwarding is enabled.

The SDK/cookbooks do not justify automatic memory storage, model replacement, permission
gating or purchasing routes. Reported batching comparisons use sequential baselines;
they do not prove this adapter is faster than an already concurrent implementation.
English-heavy model performance and the documentation's CJK caveat require representative
local evaluation. The small English/Chinese live smoke checks are functional evidence only.

## Local Validation Limits

The dedicated Codex and affected upstream routing checks run on native Windows. The
complete upstream suite includes Unix permission, shell, home-directory and macOS tests;
its Windows run failed and is not reported as a pass. That run exposed installer tests
that did not isolate Windows `USERPROFILE`, so subsequent local checks use an isolated
profile. The affected runtime entrypoints were reconciled and archived by the consolidated
installer. Linux/macOS CI is the full-suite regression authority.

Installing or replaying a hook is not proof of host activation. Codex requires review and
trust of each new/changed hook definition; inspect the actual host receipt after activation.
