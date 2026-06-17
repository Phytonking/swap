# swap evals

Two suites, both Python-stdlib-only, both runnable with zero API keys. Design
rationale lives in `../EVAL.md`.

## 1. Doctor — model autodetection + auto-prioritization

```bash
python3 eval/eval_doctor.py            # 13 scenarios, offline, ~2s
python3 eval/eval_doctor.py -k coder   # filter by name substring
```

Runs `swap.py doctor --ensure` against a **mock Ollama** (so every scenario —
no backend, empty model list, embedding-only, multi-family, coder-vs-general —
is reproducible on any machine) with an isolated `$HOME`. Asserts on exit code,
`STATUS:` line, and the config doctor wrote. Covers:

- detection: unreachable Ollama → `NEEDS_BACKEND` (4); no/unusable models →
  `NEEDS_MODEL` (3); chat model present → `READY` (0) + tiers + shim; cloud
  keys in env stay OFF by default (hint only).
- prioritization: qwen3-family preference (incl. qwen3.5) over bigger
  non-qwen models; biggest checkpoint within a family; embedding models never
  picked; coder models reserved for the `code` intent (`intents.code.model`)
  and excluded from the general default unless they're all there is.
- idempotency: re-running doctor keeps existing tier choices sticky.

## 2. Applicability — per intent × model, is this model a safe substitute?

```bash
python3 eval/eval_applicability.py                       # doctor's default model
python3 eval/eval_applicability.py --all-local           # every installed chat model
python3 eval/eval_applicability.py --models ollama/qwen3:8b --intent extract -v
python3 eval/eval_applicability.py --ci --threshold 0.9  # gate configured routes
```

Pipes the seed corpus (`cases/`, inputs in `inputs/`) through the real router
against each candidate model, scores **deterministically**, and prints the
EVAL.md verdict table — `SAFE` (≥0.90) / `RISKY` (≥0.75) / `UNSAFE` — plus
saved-per-call (from the trace) and p50/p95 latency. `*` marks the model the
current config would actually route that intent to; `--ci` gates on those rows.
Per-case rows land in `results/<timestamp>/results.jsonl` (gitignored).

### Model capability classes (the classification that matters)

Every case is tagged with a `level`:

- **`mechanical`** — the answer is literally present in the input: extraction,
  faithful summarization, format conversion, boilerplate code. Low-level work.
- **`judgment`** — the answer must be *inferred*: flaky-vs-real triage,
  "does this diff change auth behavior?", "should this auto-merge?",
  "which failure first?". High-thinking work.

Aggregating per model across levels yields the **class table** — the actual
deliverable of this suite:

| class | meaning | delegate to it |
|---|---|---|
| `reasoning` | ≥0.90 on judgment **and** mechanical | judgment calls + grunt work |
| `workhorse` | ≥0.90 on mechanical only | grunt work; keep judgment on the frontier |
| `code-only` | ≥0.90 only on code drafting | mechanical code/diffs only |
| `unfit` | below the bar everywhere | nothing |

The run ends with delegation guidance per level ("judgment -> qwen3.5:9b…" or
"(none — keep on the frontier agent)"). The frontier baseline, when enabled,
should land in `reasoning` — if it doesn't, the golds are broken, not the model.

**Local vs frontier:** local candidates come from the live Ollama. When
`ANTHROPIC_API_KEY` is set, the same corpus also runs through a frontier
baseline (Anthropic's OpenAI-compatible endpoint, default
`anthropic/claude-sonnet-4-6`) — which both sanity-checks the golds (the
frontier should pass them) and shows the quality bar each local model is
being measured against. `--no-frontier` skips it.

## Corpus format

One JSON file per case (EVAL.md sketches YAML; v0 uses JSON to honor the
stdlib-only constraint — schema is otherwise identical, plus the `level` tag):

```json
{
  "id": "tsc-errors-001",
  "intent": "extract",
  "level": "mechanical",
  "instruction": "Extract every TypeScript compile error as ...",
  "input": "inputs/tsc-build-001.txt",
  "gold": {"type": "json_subset", "value": [{"file": "src/handler.ts", "line": 42}]}
}
```

Gold types (all deterministic, no LLM judge in v0):

| type | scoring |
|---|---|
| `label` | exact label match; reads `{"label": ...}` or a bare string |
| `json_subset` | fraction of gold items present in the candidate JSON |
| `json_f1` | F1 over gold items — penalizes hallucinated extras |
| `checks` | composite `contains_all` / `regex_all` / `forbid` (summarize, code) |

The reference-diff + LLM-judge mode from EVAL.md (for open-ended summarize/code
quality) is the designed next step; `checks` golds are its deterministic v0
stand-in.
