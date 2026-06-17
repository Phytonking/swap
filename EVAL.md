# Evaluating swap

Before you let an agent delegate a sub-task to a cheap model, you want an
answer to one question:

> **For a given `intent × model`, is the cheap model a safe substitute?**

swap ships two eval suites under [`eval/`](eval/) that answer it with a number
and a verdict — **SAFE / RISKY / UNSAFE** — plus the cost saved and the latency
paid. Both are Python-stdlib-only and run with **zero API keys**.

## The two suites

```bash
python3 eval/eval_doctor.py          # model autodetection + auto-prioritization
python3 eval/eval_applicability.py   # intent × model verdict table + capability bands
```

### 1. Doctor — autodetection & prioritization

`eval_doctor.py` runs `doctor --ensure` against a **mock Ollama** server (so
every detection scenario is reproducible on any machine, offline) with an
isolated `$HOME`, and asserts on the exit code, `STATUS:` line, and the config
that gets written. It covers: unreachable Ollama → `NEEDS_BACKEND`; no/embedding-only
models → `NEEDS_MODEL`; chat model present → `READY` + tiers + shim; family/size
prioritization; coder models reserved for the `code` intent; idempotency.

### 2. Applicability — is the model a safe substitute?

`eval_applicability.py` runs a seed corpus through the real router against each
candidate model and scores every case **deterministically** (no LLM judge
needed), then prints the verdict table and a **capability-class** table.

```
intent     model                    quality  saved/call  p50    p95   verdict
classify   ollama/qwen3.5:9b          1.00    $0.0009    3.4s   4.3s  SAFE
extract    ollama/qwen3.5:9b          1.00    $0.0014    7.4s   8.4s  SAFE
summarize  ollama/qwen3.5:9b          1.00    $0.0020   10.8s  17.3s  SAFE
code       ollama/deepseek-coder      1.00    $0.0012    3.7s   6.3s  SAFE
```

Local candidates come from the live Ollama. Set `ANTHROPIC_API_KEY` or
`GEMINI_API_KEY` and a frontier baseline runs over the same corpus too — useful
both as a corpus sanity check and as the bar each local model is measured against.

## Scoring modes

| Mode | Used for | How |
|---|---|---|
| **Deterministic** (implemented) | `classify`, `extract`, and `summarize`/`code` via `checks` golds | scored by code — exact label, JSON subset/F1, or contains/regex checks. Fast, free, offline. |
| **Reference baseline** (optional) | any intent | run the same case through a configured frontier model for side-by-side comparison; activates only when a `reference` model + key are set. |

### Gold types

| type | scoring |
|---|---|
| `label` | exact label match; reads `{"label": …}` or a bare string |
| `json_subset` | fraction of gold items present in the candidate JSON |
| `json_f1` | F1 over gold items — penalizes hallucinated extras |
| `checks` | composite `contains_all` / `regex_all` / `forbid` |

## Verdict thresholds

| quality | verdict | meaning |
|---|---|---|
| ≥ 0.90 | **SAFE** | safe to delegate this intent on this model |
| 0.75 – 0.90 | **RISKY** | keep manual-only, or use a stronger model |
| < 0.75 | **UNSAFE** | do not delegate this intent on this model |

## Capability bands

Every case is tagged with a `level`:

- **`mechanical`** — the answer is present in the input (extraction, faithful
  summary, boilerplate). Low-level work.
- **`judgment`** — the answer must be *inferred* (flaky-vs-real triage,
  "does this diff change auth?", "which failure first?"). High-thinking work.

Aggregating per model across levels classifies each checkpoint — the headline
output for routing decisions:

| class | meaning | delegate to it |
|---|---|---|
| `reasoning` | ≥0.90 on judgment **and** mechanical | judgment calls + grunt work |
| `workhorse` | ≥0.90 on mechanical only | grunt work; keep judgment on the frontier |
| `code-only` | ≥0.90 only on code drafting | mechanical code/diffs |
| `unfit` | below the bar everywhere | nothing |

## Corpus format

One JSON file per case in [`eval/cases/<intent>/`](eval/cases), inputs alongside
in [`eval/inputs/`](eval/inputs):

```json
{
  "id": "tsc-errors-001",
  "intent": "extract",
  "level": "mechanical",
  "instruction": "Extract every TypeScript error as JSON [{file, line, code}]",
  "input": "inputs/tsc-build-001.txt",
  "gold": {"type": "json_subset", "value": [{"file": "src/handler.ts", "line": 42}]}
}
```

Add a case by dropping a JSON file in the right folder; the runners discover it
automatically. Per-case results land in `eval/results/<timestamp>/` (gitignored).

## Notes on judging

- The deterministic scorers measure *substitutability against a known answer*,
  not absolute quality — appropriate for the mechanical call-shapes swap targets.
- A frontier reference, when configured, should pass the golds; if it doesn't,
  the gold is wrong, not the model.
- For open-ended `summarize`/`code`, the `checks` golds are a deterministic
  stand-in for a full LLM-judge rubric.
