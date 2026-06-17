<div align="center">

# 🔀 swap

**Route an agent's grunt work to a cheap model. Keep the reasoning on the frontier.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Phytonking/swap/actions/workflows/ci.yml/badge.svg)](https://github.com/Phytonking/swap/actions/workflows/ci.yml)
[![install: skills.sh](https://img.shields.io/badge/install-skills.sh-black)](https://skills.sh)
[![deps: none](https://img.shields.io/badge/runtime%20deps-none-brightgreen)](skills/swap/swap.py)

</div>

`swap` is a tiny CLI + agent skill. It lets your AI coding agent hand off
mechanical sub-tasks — digesting logs, extracting structured data, yes/no
triage, drafting boilerplate — to a cheap **local (Ollama)** or **cloud** model,
instead of spending frontier tokens (and context) on them.

```bash
swap summarize "what failed and where"          < build.log
swap extract --json "errors with file + line"   < build.log   # -> [{"file":"…","line":42}, …]
swap classify --json "flaky test or real?"      < ci.log      # -> {"label":"flaky","confidence":0.9}
swap code "add a null check on line 42"         < handler.ts
```

Context on **stdin**, instruction as the argument. The agent spends ~20 tokens
issuing the call instead of reading a 2000-line log into its own context — then
reasons over the distilled result. Delegation is always **explicit**; the local
path sends **nothing** off your machine.

## Install

```bash
# any of 70+ agents (Claude Code, Cursor, Codex, Gemini CLI, opencode, Zed, …)
npx skills add Phytonking/swap

# or, no Node — bootstraps the router + prints harness wiring:
curl -fsSL https://raw.githubusercontent.com/Phytonking/swap/main/install.sh | sh
```

First use auto-bootstraps (`doctor --ensure`): detects your Ollama, picks the
best model, installs a stable `~/.swap/bin/swap`. No local model? It offers
`ollama pull qwen3:8b`. Full per-harness matrix: **[INSTALL.md](INSTALL.md)**.

## Intents

| Intent | For | Output |
|---|---|---|
| `summarize` | digest a big log / dump | text |
| `extract` | pull structured data | JSON |
| `classify` | yes/no triage | JSON `{label, confidence}` |
| `code` | draft mechanical code/diff | text |

Flags: `--tier cheap\|fast\|local` · `-m backend/model` · `--json`.

## Works with your harness

One rule file — the [`AGENTS.md`](AGENTS.md) open standard — drives them all:

| Harness | Reads |
|---|---|
| Claude Code | Agent Skill / `CLAUDE.md` |
| Codex · opencode · Windsurf · Cursor · Cline | `AGENTS.md` |
| Gemini CLI | `GEMINI.md` |
| Aider · any shell agent | `CONVENTIONS.md` / system prompt |

The agent only needs to run shell commands and read a rule file.

## Slash commands (Claude Code)

Installed as a plugin, swap adds user-invoked commands:

| Command | Does |
|---|---|
| `/swap:report` | show how much you've saved routing to cheap models |
| `/swap:doctor` | detect/configure backends and show readiness |
| `/swap:add-model gemini gemini-2.5-flash` | add a cloud model + store its key |

The model-invoked skill works in every harness; these are a Claude Code convenience.

## Backends

**Local (default, free, private):** Ollama at `localhost:11434`. `doctor`
auto-detects installed models and prioritizes a sensible default (family → size;
coder checkpoints reserved for `code`).

**Cloud (off by default):** when an agent needs a cloud model, swap emits a
structured `NEEDS_KEY` signal so the agent can ask you for *that model's* key:

```bash
swap add-backend gemini --model gemini-2.5-flash   # presets: gemini, openai,
                                                   # openrouter, groq, deepinfra, …
swap set-key gemini        # key read hidden on stdin, stored ~/.swap/config.json
                           # (mode 600) — never in a repo, an argument, or the chat
```

swap routes to it automatically thereafter.

## Is the cheap model good enough? Measure it.

```bash
python3 eval/eval_applicability.py   # SAFE / RISKY / UNSAFE per intent × model
```

```
model                 mechanical  judgment  class
qwen3.5:9b               1.00       1.00     reasoning   # safe for judgment + grunt work
gemma3:4b                1.00       0.80     workhorse   # grunt work only
deepseek-coder:6.7b      0.78       0.60     code-only   # code drafting only
```

Deterministic, free, offline. Methodology: **[EVAL.md](EVAL.md)**.

## How it works

```
swap <intent> "<instruction>"  <stdin>
        │  resolve intent → tier → backend (config-driven)
        │  fit context to the model's window · temperature 0 · repair JSON
        ▼
   Ollama (local)  or  any OpenAI-compatible cloud
        │
        ▼  result on stdout   +   one line appended to ~/.swap/trace.jsonl
   swap report   →   "saved ~$X routing to cheap models instead of the frontier"
```

- **Explicit, never silent** — no proxy, no env-var hijacking, no auto-routing.
- **Zero runtime deps** — one self-contained Python stdlib file, runs on any `python3 ≥ 3.8`.
- **Keys stay private** — only in `~/.swap/config.json` (mode 600).

## Layout

```
skills/swap/swap.py   the router (CLI + skill) — stdlib only
skills/swap/SKILL.md  Claude Code skill (self-bootstrapping)
AGENTS.md CLAUDE.md GEMINI.md   per-harness rule files
.claude-plugin/ commands/       Claude Code plugin + slash commands
eval/                 SAFE/RISKY/UNSAFE verdict harness + corpus
tests/                stdlib unittest smoke tests (CI)
install.sh INSTALL.md
```

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)**. Two hard rules: the router stays
**zero-dependency** (stdlib only), and delegation stays **explicit**.

## License

[MIT](LICENSE)
