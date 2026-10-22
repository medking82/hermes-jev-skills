# Routing A/B Benchmark

[2026-10-22 live report](runs/20261022-live/REPORT.md) and
[audited raw records](runs/20261022-live/records.json) are retained locally.

Compare the same native ChatGPT-authenticated Codex model with and without advice
from the installed Jev adapters. These are synthetic classification requests;
no case executes its requested implementation, release, browser action or review.

- A: one fresh LLM classification with a fixed contract, catalog and request.
- B: the corresponding installed Jev adapter, then the same LLM classification
  with its short, fallible recommendation. The LLM retains final choice.
- The installed adapter's explicit-choice, trivial and opt-out bypasses remain
  active. This benchmark invokes the adapter on each B case; it does not model
  an additional main-agent judgment of whether a case is ambiguous enough to call.
- Cases and acceptable gold labels are independently authored from installed
  contracts, then frozen and hashed before any scored prediction. They are a
  development evaluation, not independently human-adjudicated production traffic.
- The five suites cover entrypoint selection (including autotrigger), design
  modes, Matt workflows, Jev workflows, and native-review task-fit subsets.
  Native-review dispatch, quota balancing and reviewer quality are outside scope.
- Jev workflow selection uses the real `codex.select` auxiliary workflow result;
  it includes that selector's overhead. Native task fit uses `reviewer_fit.narrow`.
- A/B order alternates within pairs; case order is shuffled with seed 20261022.
  Calls run sequentially, concurrency 1, one sample per arm/case, no agent retries.

`benchmark.py` uses the current main model settings: `gpt-6-astra`, `max`,
`priority` (Fast), through existing ChatGPT CLI login. It ignores user config in
the leaf calls and explicitly disables hooks, apps, browser and execution tools;
it uses a read-only sandbox and validates that only one structured answer and no
tool activity occurred. It does not change the current conversation's settings.
Native context and process startup overhead remain part of the measurement.
CLI configuration is model identity evidence, not independent backend attestation.

## Metrics

- Accuracy: exact allowed-label membership, all attempted cases; failed LLM
  responses count incorrect and are separately reported.
- Wall time: per routing transaction, including Jev on B, CLI/PowerShell startup,
  network and local packet setup. Median and linearly interpolated p95, paired
  differences and totals are reported. These are not implementation task times.
- Tokens: actual native `turn.completed.usage`, with input, cached input,
  output and reasoning output separate. Reasoning is included in output and
  must not be added again. Jev's API-reported input/output usage is separate.
  Missing fields or timeout usage are unknown, never zero. Across-provider token
  sums are descriptive token counts, not monetary or subscription-credit costs.
- Raw adapter replies, per-call latency/usage, CLI JSON events, model packets,
  source hashes, frozen cases and per-pair results are retained under `runs/`.
  Gold and rationales never enter either model prompt. No credential is read by
  this harness; existing private auth remains owned by the adapters.

## Run On Windows

Use the workstation's hidden runner and the actual Python interpreter, with this
repository as working directory. Commands after `python.exe` are:

```text
-m unittest discover -s evals/routing_ab -p test_benchmark.py
evals/routing_ab/benchmark.py check
evals/routing_ab/benchmark.py smoke --run-dir <new-repository-local-directory>
evals/routing_ab/benchmark.py run --run-dir <new-repository-local-directory>
evals/routing_ab/benchmark.py summary --run-dir <completed-run-directory>
evals/routing_ab/audit.py <completed-run-directory>
evals/routing_ab/report.py <completed-run-directory>
```

The live benchmark uses existing subscription/API quota; no fallback provider or
purchased credits are configured. A smoke is transport validation and excluded
from scored results. `runs/` is ignored so local transport evidence is not
accidentally published. This benchmark does not modify the installed skills.
