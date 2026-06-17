---
description: Detect and configure swap's model backends, and show readiness.
allowed-tools: Bash(~/.swap/bin/swap:*), Bash(python3:*)
---

Bootstrap / re-check swap's backends. Run:

```
~/.swap/bin/swap doctor --ensure
```

If the stable entrypoint doesn't exist yet, run the bundled router instead:
`python3 "${CLAUDE_PLUGIN_ROOT}/skills/swap/swap.py" doctor --ensure`.

Read the final `STATUS:` line and summarize for the user:

- **READY** — set up; report the detected default model.
- **NEEDS_MODEL** — Ollama is running but empty; offer to run `ollama pull qwen3:8b`.
- **NEEDS_BACKEND** — no local model and no cloud; offer to install Ollama, or add
  a cloud model with `/swap:add-model`. **Ask before installing software.**
