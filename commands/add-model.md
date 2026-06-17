---
description: Add a cloud model (e.g. Gemini) to swap and store its API key securely.
argument-hint: <backend> <model>   (e.g. gemini gemini-2.5-flash)
allowed-tools: Bash(~/.swap/bin/swap:*)
---

Add a cloud backend to swap using the arguments: `$ARGUMENTS`
(first word = backend, second = model). Presets: `gemini, openai, openrouter,
groq, deepinfra, together, fireworks, mistral`.

1. Run `~/.swap/bin/swap add-backend <backend> --model <model>`.
2. If it prints `STATUS: NEEDS_KEY`, **ask the user for their <backend> API key**,
   then have them run `~/.swap/bin/swap set-key <backend>` (it reads the key
   hidden on stdin). **Never ask the user to paste the key into the chat**, and
   never put a key in a command argument.
3. Confirm swap will now route to the model automatically.
