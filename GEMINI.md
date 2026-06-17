# swap — Gemini CLI instructions

The full, harness-agnostic rule set lives in **[AGENTS.md](./AGENTS.md)** — the
bootstrap flow, the four intents (`summarize`, `extract`, `classify`, `code`),
and the cloud-key (`NEEDS_KEY` → `set-key`) flow.

TL;DR: when you hit a big log to digest, structured data to extract, a yes/no
triage, or boilerplate code to draft, pipe it to `~/.swap/bin/swap <intent>`
(context on stdin) instead of reading it into your own context. You keep the
judgment; swap does the grunt work. Delegation is always explicit; no data
leaves the machine on the local path.
