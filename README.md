<div align="center">

# 🔀 swap

**Why burn frontier tokens on grunt work? Route the boring sub-tasks to a cheap model.**

swap lets your AI coding agent hand off the mechanical firehose — summarizing
2000-line logs, extracting errors, classifying flaky-vs-real, drafting
boilerplate — to a cheap **local (Ollama)** or **cloud** model, so your expensive
frontier agent spends its tokens on planning and reasoning instead.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Phytonking/swap/actions/workflows/ci.yml/badge.svg)](https://github.com/Phytonking/swap/actions/workflows/ci.yml)
[![skills.sh](https://img.shields.io/badge/install-skills.sh-black)](https://skills.sh)
[![Python](https://img.shields.io/badge/python-stdlib%20only-blue)](skills/swap/swap.py)

</div>

---

## The idea in one picture

```
your agent hits a 2000-line build log
        │
        ├─ without swap:  frontier model reads all 2000 lines   ($$$, slow, context full)
        │
        └─ with swap:     cheap model reads it, hands back
                          "2 errors: handler.ts:42 (TS2532), store.ts:7 (TS2304)"
                          frontier model reads those 2 lines, does the smart fix
```

Your agent stays the boss. It just stops spending genius-priced tokens on
copy-paste work. Modern agents make **30–100+ model calls per task** — most are
mechanical. swap routes those to a model that costs ~nothing.

## Quickstart

```bash
# any of 70+ agents (Claude Code, Cursor, Codex, Gemini CLI, …)
npx skills add Phytonking/swap

# or, no Node:
curl -fsSL https://raw.githubusercontent.com/Phytonking/swap/main/install.sh | sh
```

Then just use your agent. On the first delegate-worthy sub-task it self-bootstraps
(`doctor --ensure`): detects your local Ollama, picks the best model, and installs
a stable `~/.swap/bin/swap`. No local model? It offers `ollama pull qwen3:8b`.
Full matrix in **[INSTALL.md](INSTALL.md)**.

## Works with your harness

One rule file, the [`AGENTS.md`](AGENTS.md) open standard, drives them all:

| Harness | Reads | Status |
|---|---|---|
| **Claude Code** | Agent Skill / `CLAUDE.md` | ✅ first-class (self-bootstrapping skill) |
| **Codex** | `AGENTS.md` | ✅ |
| **opencode** | `AGENTS.md` | ✅ |
| **Windsurf** | `AGENTS.md` / `.windsurfrules` | ✅ |
| **Cursor** | `AGENTS.md` / `.cursor/rules` | ✅ |
| **Cline** | `AGENTS.md` | ✅ |
| **Gemini CLI** | `GEMINI.md` | ✅ |
| **Aider** + any shell agent | `CONVENTIONS.md` / system prompt | ✅ |

The agent just needs to (1) run shell commands and (2) read a rule file.

## The four intents

| Intent | Use it for | Example |
|---|---|---|
| `summarize` | digest a big log / dump | `swap summarize "what failed and where" < build.log` |
| `extract` | pull structured data (JSON) | `swap extract --json "errors with file+line" < build.log` |
| `classify` | yes/no triage (JSON) | `swap classify --json "flaky or real?" < ci.log` |
| `code` | draft mechanical code/diff | `swap code "add a null check on line 42" < handler.ts` |

Context on **stdin**, instruction as the argument. You keep the judgment; swap
does the grunt work.

## Local first, cloud when you want it

- **Local (default, free, private):** Ollama at `localhost:11434`. `doctor`
  auto-detects installed models and prioritizes a sensible default (family →
  size; coder models reserved for `code`). **No data leaves your machine.**
- **Cloud (off by default):** an agent that needs a cloud model emits a
  structured `NEEDS_KEY` signal and asks you for *that model's* key:

  ```bash
  swap add-backend gemini --model gemini-2.5-flash   # presets: gemini, openai,
                                                     # openrouter, groq, deepinfra, …
  swap set-key gemini        # paste the key when prompted — hidden, never echoed,
                             # stored in ~/.swap/config.json (mode 600), never in any repo
  ```

  swap routes to it automatically from then on.

## Does the cheap model actually work? Measure it.

swap ships an **eval harness** that answers, per `intent × model`, *is the cheap
model a safe substitute?* — a **SAFE / RISKY / UNSAFE** verdict plus a capability
band (**reasoning** vs **workhorse** vs **code-only**), all deterministic and free:

```bash
python3 eval/eval_doctor.py          # autodetection + prioritization (offline, mock Ollama)
python3 eval/eval_applicability.py   # the verdict table for your installed models
```

```
intent     model                    quality  verdict     |  model            band
classify   ollama/qwen3.5:9b          1.00    SAFE        |  qwen3.5:9b       reasoning
extract    ollama/qwen3.5:9b          1.00    SAFE        |  gemma3:4b        workhorse
summarize  ollama/qwen3.5:9b          1.00    SAFE        |  deepseek-coder   code-only
```

Set `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` to also score a frontier baseline.
Design notes in **[EVAL.md](EVAL.md)**.

## Cost & trust

```bash
swap report      # "you saved ~$X today routing to cheap models instead of the frontier"
```

- **Explicit, never silent.** swap only runs when your agent (or you) calls it.
  No proxy, no env-var hijacking, no background routing.
- **Local-first.** The default path sends nothing off your machine.
- **Keys stay private.** Stored only in `~/.swap/config.json` (mode 600), never in
  a repo, a command argument, or the chat.

## How it's built

```
swap/
├── skills/swap/        # the product
│   ├── SKILL.md        #   teaches the agent the `swap <intent>` reflex + self-bootstrap
│   └── swap.py         #   the router — Python stdlib only, ~600 lines, no deps
├── AGENTS.md           # universal rule file (Codex, opencode, Windsurf, Cursor, Cline)
├── CLAUDE.md GEMINI.md # per-harness pointers
├── eval/               # SAFE/RISKY/UNSAFE verdict harness + seed corpus
├── tests/              # stdlib unittest smoke tests (CI)
└── install.sh INSTALL.md
```

## Contributing

Issues and PRs welcome — see **[CONTRIBUTING.md](CONTRIBUTING.md)**. The one hard
rule: the router stays **zero-dependency** (Python stdlib only) and delegation
stays **explicit**.

## License

[MIT](LICENSE).
