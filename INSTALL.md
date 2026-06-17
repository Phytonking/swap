# Installing swap

swap is one small thing: a zero-dependency Python router (`skills/swap/swap.py`)
plus a rule file that teaches your agent when to call it. Pick the path for your
harness — they all end up calling the same `~/.swap/bin/swap`.

## Fastest — any of 70+ agents

```bash
npx skills add Phytonking/swap
```

The [skills.sh](https://skills.sh) CLI installs the skill into your agent's native
location (Claude Code, Cursor, Codex, Gemini CLI, Copilot, Zed, …) and bundles
the router. Then just use your agent — it self-bootstraps on first use.

## One-line script (no Node)

```bash
curl -fsSL https://raw.githubusercontent.com/Phytonking/swap/main/install.sh | sh
```

Bootstraps the router, installs the Claude Code skill if present, and prints the
one file to add for every other harness.

## Per-harness (manual)

First bootstrap the router once (writes `~/.swap/config.json` + `~/.swap/bin/swap`):

```bash
python3 skills/swap/swap.py doctor --ensure
```

Then wire your harness — **every modern agent reads the `AGENTS.md` open
standard**, so for most tools you just copy `AGENTS.md` into your project root.

| Harness | What it reads | Do this |
|---|---|---|
| **Claude Code** | Agent Skill / `CLAUDE.md` | `cp -r skills/swap ~/.claude/skills/swap` (or `npx skills add …`) |
| **Codex** | `AGENTS.md` | copy `AGENTS.md` to your repo root |
| **opencode** | `AGENTS.md` (only this if present) | copy `AGENTS.md` to your repo root |
| **Windsurf** | `AGENTS.md` or `.windsurfrules` | copy `AGENTS.md` (or paste it into `.windsurfrules`) |
| **Cursor** | `AGENTS.md` or `.cursor/rules` | copy `AGENTS.md` to your repo root |
| **Cline** | `AGENTS.md` / `.clinerules/` | copy `AGENTS.md` |
| **Gemini CLI** | `GEMINI.md` | copy `GEMINI.md` to your repo root |
| **Aider** | `CONVENTIONS.md` | paste the contents of `AGENTS.md` |
| any shell agent | system prompt | point it at `~/.swap/bin/swap` + the snippet in `AGENTS.md` |

## Requirements

- **python3 ≥ 3.8** (already on every dev machine; the router is stdlib-only).
- **A model to route to** — either:
  - **Local (recommended, free, private):** [Ollama](https://ollama.com) with a
    chat model. `doctor` auto-detects it; if none is pulled it offers
    `ollama pull qwen3:8b`.
  - **Cloud:** an OpenAI-compatible key. After bootstrap:
    ```bash
    swap add-backend gemini --model gemini-2.5-flash
    swap set-key gemini        # paste the key when prompted (hidden, never echoed)
    ```

## Verify

```bash
~/.swap/bin/swap doctor --ensure     # should end with STATUS: READY
echo "build failed: TS2532 in handler.ts:42" | ~/.swap/bin/swap classify "real or flaky?"
```

## Uninstall

```bash
rm -rf ~/.swap                       # router, config, trace
rm -rf ~/.claude/skills/swap         # Claude Code skill, if installed
# delete any AGENTS.md / GEMINI.md / .windsurfrules you copied into projects
```
