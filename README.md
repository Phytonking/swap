# swap

Delegate the mechanical firehose of agent sub-tasks — summarizing logs, extracting
fields, classifying, drafting boilerplate — to cheap local/cloud models, so your
frontier agent spends its expensive tokens on planning and reasoning, not on
ingesting 2000-line build logs.

**One download (a skill), zero manual setup.** The agent wires up the router and
detects your local model on first use.

## What's here

```
swap/
├── EVAL.md             # the testing-infra design (SAFE/RISKY/UNSAFE per intent×model)
└── skills/swap/        # the installable skill (this is the product)
    ├── SKILL.md        # teaches the agent the `swap <intent>` reflex + self-bootstrap
    └── swap.py         # the router — Python stdlib only, runs on any machine Python
```

## Install

**Any agent (recommended)** — via the [skills.sh](https://skills.sh) registry,
which translates the one skill into 70+ agents (Claude Code, Cursor, Codex,
Gemini CLI, Copilot, Zed, …):

```bash
npx skills add avi-ox-agola/swap
```

**Claude Code, manually:**

```bash
cp -r skills/swap ~/.claude/skills/swap
```

Then just use your agent. The first time it hits a delegate-worthy sub-task it runs
the bundled bootstrap (`swap.py doctor --ensure`), which detects your local Ollama,
writes `~/.swap/config.json`, and installs a stable entrypoint at `~/.swap/bin/swap`.
The only manual step you'd ever take is if you have **no** local model — the agent
will offer to run `ollama pull qwen3:8b` for you.

## Use it directly (CLI)

```bash
swap summarize "what failed and where"          < build.log
swap extract --json "all errors with file+line" < build.log
swap classify --json "flaky test or real?"      < ci.log
swap code "add a null check on line 42"         < handler.ts
swap report                                     # how much you've saved
swap doctor --ensure                            # (re)detect backends, write config
```

Context on **stdin**, instruction as the argument. `extract`/`classify` return JSON.

## Backends

- **Local (default):** Ollama at `localhost:11434`. `doctor` auto-detects installed
  models and picks a sensible default (prefers a Qwen3 model).
- **Cloud (blank by default):** add an OpenAI-compatible backend to
  `~/.swap/config.json` and reference it from a tier — e.g.

  ```json
  "backends": {
    "deepinfra": { "kind": "openai",
                   "base_url": "https://api.deepinfra.com/v1/openai",
                   "api_key": "env(DEEPINFRA_API_KEY)" }
  },
  "tiers": { "fast": "deepinfra/Qwen3-32B" }
  ```

No cloud is configured unless you add it. No data leaves the machine on the local path.

## Status

Working v0.1 prototype: 4 intents (`summarize`, `extract`, `classify`, `code`),
stdin context, local trace log (`~/.swap/trace.jsonl`), self-bootstrapping skill.
Next: the eval harness (`EVAL.md`) and a Claude Code plugin wrapper for one-click
install + nicer discoverability.
