# Swap — Eval Harness (Testing Infra)

> Status: design, ready to build. Owner: TBD.

## The one question

> **For a given `intent × model`, is the cheap model a safe substitute for the frontier model on this call-shape?**

Everything in this harness exists to answer that with a number and a verdict: **SAFE / RISKY / UNSAFE**, plus the cost saved and the latency paid.

That single answer does double duty:

1. **Quality gate** — decides which intents are safe to delegate and ship in `SKILL.md`. Lets us honestly claim "no quality regression on the calls that matter."
2. **Coverage signal** — tells us *which call-shapes save the most with acceptable quality*, so delegation effort goes where it pays off.

If we only built one thing beyond the binary, it would be this.

---

## Design principles

- **Deterministic where possible, judged where not.** `classify` and `extract` have checkable answers — score them with code, no frontier dependency, runnable offline and free. `summarize` and `code` don't — score them by comparing against a frontier reference with an LLM judge.
- **Real calls are the best eval set.** A hand-written seed corpus gets us moving; `--record` turns actual delegated calls into eval cases over time. The harness treats both identically.
- **No new framework.** A thin Python runner over the same `swap` binary. Wrap in pytest later for CI; don't start there.
- **Frontier is optional.** Deterministic intents run with zero API keys. The reference/judge path activates only when a `reference` model is configured — so the harness degrades gracefully.
- **Verdicts, not vibes.** Output is a table an engineer can act on, not a wall of diffs.

---

## Two eval modes

### Mode 1 — Deterministic (golden answer)
For intents with a checkable answer: **`classify`, `extract`**.

| Intent | Scorer | Metric |
|---|---|---|
| `classify` | exact label match vs gold | accuracy |
| `extract` | JSON field match vs gold (subset/F1) | field-level F1 |

No frontier model needed. Fast, free, deterministic, CI-friendly.

### Mode 2 — Reference-diff (frontier-as-oracle)
For intents with no single right answer: **`summarize`, `code`** (and any case lacking a gold).

Run the same case through:
- **candidate** = the cheap model under test, and
- **reference** = the configured frontier model (`reference.model`, default `anthropic/claude-sonnet-4-6`).

Then an **LLM judge** (the frontier model, strict per-intent rubric) scores:
> "Is the candidate output an acceptable substitute for the reference, given the instruction? Does it preserve the key facts and introduce no errors?" → score `0.0–1.0` + one-line rationale.

This is also the mode that runs over captured real traces (`~/.swap/corpus/`), turning usage into continuous quality measurement.

---

## Corpus format

Cases live in `swap/eval/cases/<intent>/<case-id>.yaml`. Inputs (logs, dumps, source) live alongside in `swap/eval/inputs/`.

```yaml
# eval/cases/extract/build-errors-001.yaml
id: build-errors-001
intent: extract
instruction: "Extract every error with its file path and line number as a JSON array"
input: inputs/tsc-build-001.txt          # piped to stdin
gold:                                     # optional; presence => deterministic scoring
  type: json_subset                       # json_subset | json_f1 | label | regex | contains
  value:
    - { file: "src/handler.ts", line: 42, msg: "TS2532: possibly undefined" }
    - { file: "src/store.ts",   line: 7,  msg: "TS2304: cannot find name" }
```

```yaml
# eval/cases/summarize/ci-log-003.yaml
id: ci-log-003
intent: summarize
instruction: "Summarize this CI log: what failed, where, and the likely cause"
input: inputs/ci-failure-003.txt
# no `gold` => reference-diff + LLM judge
rubric: |                                 # optional per-case judge guidance
  Must name the failing test, the file, and the root cause if stated in the log.
  Must NOT invent a cause not present in the log.
```

`gold.type` values:
- `label` — exact string match (classify).
- `json_subset` — every key/value in gold must appear in candidate (extract; tolerant of extra fields).
- `json_f1` — precision/recall over gold items (extract; penalizes misses *and* hallucinated items).
- `regex` / `contains` — lightweight checks for simple cases.

---

## Scoring → verdict

Per `intent × model`, aggregate across that intent's cases:

- **quality** = mean deterministic score (Mode 1) or mean judge score (Mode 2), in `[0,1]`.
- **saved** = mean `est_saved_vs_ref_usd` per call (from the trace cost model).
- **latency** = p50 / p95 candidate latency.

Verdict thresholds (config-tunable):

| quality | verdict | meaning |
|---|---|---|
| ≥ 0.90 | **SAFE** | ship this intent as delegate-by-default in `SKILL.md` |
| 0.75 – 0.90 | **RISKY** | keep manual-only, or escalate to a bigger cheap model |
| < 0.75 | **UNSAFE** | do not delegate this intent on this model |

---

## Report shape

`swap eval` prints a table and writes `~/.swap/eval/<timestamp>/results.jsonl`:

```
intent      model                      quality   saved/call   p50     p95    verdict   n
summarize   ollama/qwen3:32b            0.91      $0.024       1.3s    2.1s   SAFE      18
extract     ollama/qwen3:32b           0.97      $0.019       0.9s    1.4s   SAFE      15
classify    deepinfra/Qwen3-32B        0.99      $0.004       0.3s    0.5s   SAFE      20
code        ollama/qwen3-coder:14b      0.68      $0.090       4.1s    7.8s   UNSAFE    12
```

Read directly: **summarize / extract / classify are safe to delegate on qwen3:32b; code is not — keep it on the frontier or try a bigger code model.**

Each `results.jsonl` row is one case:
```json
{"intent":"summarize","model":"ollama/qwen3:32b","case":"ci-log-003",
 "quality":0.93,"mode":"reference-diff","judge_rationale":"names test+file+cause, no invention",
 "cand_latency_ms":1290,"saved_usd":0.026,"ref_model":"anthropic/claude-sonnet-4-6"}
```

---

## CLI surface

```
swap eval                       # run full corpus, all configured candidate models, print table
swap eval --intent extract      # one intent
swap eval -m ollama/qwen3:32b   # one candidate model
swap eval --mode deterministic  # skip anything needing the frontier (offline / no keys)
swap eval --corpus ~/.swap/corpus   # run over captured real traces instead of the seed set
swap eval --ci --threshold 0.9  # nonzero exit if any SAFE-shipped intent regresses (CI guard)
```

---

## Build plan (~1 day, after the binary exists)

1. **Case loader + input piping** — parse `*.yaml`, pipe `input` to `swap <intent>` via the same code path the binary uses. (~1h)
2. **Deterministic scorers** — `label`, `json_subset`, `json_f1`, `regex`, `contains`. (~2h)
3. **Reference-diff + judge** — call `reference.model`, then judge with a per-intent rubric prompt; parse `score`+`rationale`. (~2h)
4. **Aggregation + verdict + table/JSONL output.** (~1h)
5. **Seed corpus** — 10–20 real-feeling cases per intent: tsc/build logs, grep dumps, stack traces, file dumps for `code`, CI logs for `summarize`, yes/no triage for `classify`. (~2h)
6. **`--ci` mode** — threshold gate, nonzero exit, pin to corpus. (~30m)

Deliverable: `swap eval` produces the verdict table above on the seed corpus, and re-runs cleanly over `~/.swap/corpus/` once `--record` has captured real calls.

---

## What this is NOT (v0.1)

- Not a learned router — it measures, it doesn't decide routing at runtime.
- Not a public benchmark (that's `ConsolidationBench`'s lane, unrelated).
- Not a continuous online monitor — it's a batch harness you run on demand / in CI. Live drift alerting is v0.2 "quality guardrail mode."

---

## Open eval questions

1. **Judge reliability** — frontier-as-judge has known biases (length, self-preference). Mitigation: strict rubric, score the *substitutability* not absolute quality, and spot-check judge calls by hand on the seed set before trusting verdicts. Consider a second judge model for disagreement sampling.
2. **Reference drift** — when the frontier reference model version changes, deterministic scores are stable but reference-diff scores shift. Pin `reference.model` per eval run; record it in every results row (already in schema).
3. **Corpus representativeness** — hand-written seed cases may not match real traffic. The `--record` → `--corpus` path is the fix; weight verdicts toward the real corpus once it's large enough.
4. **Per-case vs per-intent verdicts** — start per-intent (simpler, matches what `SKILL.md` ships). Add per-case-shape breakdowns (e.g. "summarize works on logs but not on diffs") only if the aggregate hides a meaningful split.
