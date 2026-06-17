---
description: Show how much swap has saved by routing sub-tasks to cheap models.
allowed-tools: Bash(~/.swap/bin/swap:*)
---

Run `~/.swap/bin/swap report` and present the savings table to the user.

If the command reports that swap isn't set up yet (no calls logged, or the
entrypoint is missing), tell them to run `/swap:doctor` first.
