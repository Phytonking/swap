# swap — agent instructions

> This is the canonical, harness-agnostic rule file for **swap**. It is the
> [AGENTS.md](https://agents.md) open standard, so Codex, opencode, Windsurf,
> Cursor, and Cline read it directly. Claude Code reads `CLAUDE.md` + the
> bundled skill; Gemini CLI reads `GEMINI.md`. All point at this same content.

You (the agent) stay in charge of planning and reasoning. Hand off the
**mechanical firehose** — summarizing big tool outputs, extracting fields,
classifying/triaging, drafting boilerplate — to a cheap local or cloud model via
`swap`, so you spend ~20 tokens issuing a call instead of ingesting a 2000-line
log into your own (expensive) context.

## First use in a session: bootstrap (once, idempotent)

```bash
python3 "<SKILL_DIR>/swap.py" doctor --ensure      # or: ~/.swap/bin/swap doctor --ensure
```

Read the final `STATUS:` line + exit code:

- **`READY`** (0) — set up. Use the stable entrypoint `~/.swap/bin/swap` for all calls.
- **`NEEDS_MODEL`** (3) — Ollama running, no model. Show the `NEXT:` line; offer to run the `ollama pull …` it suggests.
- **`NEEDS_BACKEND`** (4) — no local model, no cloud. Show `NEXT:`; **ask before installing software.** Until a backend exists, do the task yourself.

## When to delegate (and which intent)

| Situation | Call |
|---|---|
| Big log / build output / file dump to digest | `swap summarize "what failed and where" < build.log` |
| Pull structured data out of text | `swap extract --json "all errors with file+line" < build.log` |
| Categorize or triage yes/no | `swap classify --json "flaky test or real failure?" < ci.log` |
| Draft mechanical code/diff | `swap code "add a null check on line 42" < handler.ts` |

Context goes on **stdin**; the instruction is the quoted argument. `extract` and
`classify` return JSON. Use the cheap-model result to inform your next step — you
keep the judgment, swap does the grunt work.

## When NOT to delegate

- The reasoning itself is the task (planning, architecture, a tricky bug). Do it yourself.
- The content is small (<~500 tokens) — just read it; a round trip isn't worth it.
- Correctness is safety-critical and unverifiable downstream.

## Adding a cloud model (when local isn't enough)

Any call that needs a key it lacks prints **`STATUS: NEEDS_KEY`** (exit 5) plus a
`NEED_KEY: {…}` line naming the `backend` + `env`. When you see it:

1. `swap add-backend <name> --model <model>` — presets: `gemini, openai, openrouter, groq, deepinfra, together, fireworks, mistral`.
2. **Ask the user for their API key for that specific model**, then have them run
   `swap set-key <name>` (reads the key hidden on stdin). **Never ask the user to
   paste a key into the chat; never put a key in a command argument; never invent one.**
3. Retry the original call — it now routes to the cloud model.

## Flags & cost

- `--tier cheap|fast|local` · `-m backend/model` · `--json`
- `swap report` — how much routing to cheap models has saved vs the frontier.

Delegation is always **explicit** — swap never routes silently and never sends
data anywhere on the local path. No key is configured unless the user adds one.
