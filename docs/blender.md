# Blender: code first, bounded diagnostic advice

`jev blender-next` reads one closed state from stdin and returns one next-action ID. It does not execute Blender. Use the installed domain skill `jev-blender` as the default entry point for Blender tasks.

```json
{"schema":"jev.blender_state_v1","revision":1,"geometry":"pass","materials":"pass","framing":"pass","lighting":"pass","preview":"unknown","export":"unknown","issue":"none","symptoms":[],"export_requested":true,"private":false,"stagnation":0,"estimated_probe_ms":0}
```

All keys are mandatory; unknown keys are refused. Check states are `unknown`, `pass`, or `fail`. They must be derived from task-specific local checks. `revision`, `stagnation` and `estimated_probe_ms` are nonnegative integers, not booleans. Flags are actual booleans. `estimated_probe_ms` must reflect measured work, not an inflated guess.

Issues: `none`, `geometry`, `materials`, `framing`, `lighting`, `export`, `unclear`.

Symptoms are unique entries from: `render_dark`, `viewport_visible`, `color_mismatch`, `geometry_matches`, `subject_clipped`, `unexpected_shadow`, `faceted_surface`, `export_only_difference`. They are observations, not diagnoses. Missing evidence must not be fabricated to obtain a confident choice.

No free text, source code, asset names, paths, images or private measurements are accepted. The outbound request contains only the fixed vocabulary and a state-bound observation ID. Private work always remains local. Existing client privacy/validation boundaries still apply.

Local logic orders mandatory checks, blocks known failures, bypasses small work and requires preview/export verification. Jev is consulted only for an unclear issue where a measured next probe costs at least 1000 ms. The request is capped at one second. The owning executor must enforce a whole-job deadline, at most two Jev requests, at most six probes and stale/no-progress refusal. The helper cannot certify those executor properties itself.

Possible model-selected IDs: `inspect_geometry`, `inspect_materials`, `inspect_framing`, `inspect_lighting`. The caller supplies complete reviewed read-only implementations; no generated code or arguments are accepted. `reobserve`, `abstain`, low confidence, malformed/contradictory replies, transport errors and missing keys return control to the local planner. The observation ID and the existing confidence floor are retained.

`verify_artifacts` means run the local artifact verifier, not that the task is complete. `planner_repair`, `planner_inspect` and `planner_stop` are not successful completions. The caller must not turn a returned ID into a shell command or infer authorization from it.

## Evidence and limitations

Offline tests cover local bypasses, hard failures, invalid/stale answers, privacy, timeout limits, CLI refusals and completion boundaries. The integration was exercised on a private macOS Blender fixture: compare direct and guarded warm loops, preserve cold-start outliers, inject faults, re-run authored repairs and inspect real exported/rendered artifacts. Live Jev tests initially abstained without evidence; adding fixed symptoms made diagnostic choices actionable. A separate normals/smooth-shading description refinement was tested without lowering confidence.

The useful default is selective, not always-on inference. Benchmarks do not establish lower creative-agent cost, better art, faster final rendering or superiority over MCP. Host-specific scripts, paths, logs, images and private rollout receipts remain outside this public repository. No keys, cloud-image opt-ins, model-routing defaults, public endpoints or gateway restarts are changed by this feature.
