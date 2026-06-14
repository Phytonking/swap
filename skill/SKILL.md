---
name: swap
description: >-
  Delegate mechanical sub-tasks to cheap local/cloud models to save on frontier
  token cost. Use whenever you need to (1) summarize tool output, logs, file
  dumps, or grep/search results longer than ~500 tokens, (2) extract structured
  data (errors, fields, entities) from text, (3) classify text into categories or
  make a yes/no triage call, or (4) draft mechanical code/diffs — INSTEAD of
  reading the raw content into your own context. Routes to the user's local Ollama
  (or a configured cloud model). Self-installs on first use.
---

# swap — route mechanical sub-tasks to cheap models

You (the frontier agent) stay in charge of planning and reasoning. Hand off the
*mechanical firehose* — summarizing big outputs, extracting fields, classifying,
drafting boilerplate — to a cheap model via `swap`, so you spend ~20 tokens
issuing a call instead of ingesting a 2000-line log into your own context.

## First use this session: bootstrap (one time)

Before the first `swap` call in a session, run the bundled router's setup. It is
idempotent — safe to run every time; it no-ops once configured.

```bash
python3 "<THIS_SKILL_DIR>/swap.py" doctor --ensure
```

Read the final `STATUS:` line and the exit code:

- **`STATUS: READY`** (exit 0) — set up. A stable entrypoint now exists at
  `~/.swap/bin/swap`. Use it for all calls below.
- **`STATUS: NEEDS_MODEL`** (exit 3) — Ollama is running but has no model. Show the
  `NEXT:` line to the user and offer to run the suggested `ollama pull ...` command.
- **`STATUS: NEEDS_BACKEND`** (exit 4) — no local model and no cloud configured. Show
  the `NEXT:` line and offer to run the suggested install command. **Ask before
  installing software.** Until a backend exists, do the task yourself.

After bootstrap, always call the stable entrypoint:

```bash
python3 ~/.swap/bin/swap <intent> "<instruction>" < <file-or-piped-content>
```

## When to delegate (and which intent)

| Situation | Call |
|---|---|
| Big log / build output / file dump to digest | `swap summarize "what failed and where" < build.log` |
| Pull structured data out of text | `swap extract --json "all errors with file + line" < build.log` |
| Categorize or triage | `swap classify --json "flaky test or real failure?" < ci.log` |
| Draft mechanical code/diff | `swap code "add a null check on line 42" < handler.ts` |

Context goes on **stdin**; the instruction is the quoted argument. `extract` and
`classify` return JSON. Use the cheap-model output to inform your next step — you
do the judgment, swap does the grunt work.

## When NOT to delegate

- The reasoning itself is the task (planning, architecture, a tricky bug). Do it yourself.
- The content is small (<~500 tokens) — just read it; delegation isn't worth a round trip.
- Correctness of the sub-result is safety-critical and unverifiable downstream.

## Flags

- `--tier cheap|fast|local` — override the model tier for this call.
- `-m, --model backend/model` — force a specific model (e.g. `-m ollama/qwen3:32b`).
- `--json` — force JSON output (default for `extract`/`classify`).

## Cost visibility

`python3 ~/.swap/bin/swap report` prints how much routing to cheap models has
saved versus running the same calls on the frontier.
