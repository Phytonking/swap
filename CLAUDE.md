# swap — Claude Code instructions

Claude Code uses the bundled **skill** at `skills/swap/SKILL.md` (install it to
`~/.claude/skills/swap/`, or via `npx skills add <owner>/swap`). The skill
auto-loads when a delegate-worthy sub-task appears and self-bootstraps on first use.

The full rule set is shared with every harness in **[AGENTS.md](./AGENTS.md)** —
read it for the bootstrap flow, the four intents (`summarize`, `extract`,
`classify`, `code`), and the cloud-key (`NEEDS_KEY` → `set-key`) flow.

TL;DR: when you hit a big log, a structured-extraction, a yes/no triage, or
boilerplate code, pipe it to `~/.swap/bin/swap <intent>` instead of reading it
into your own context. You keep the judgment; swap does the grunt work.
Delegation is always explicit.
