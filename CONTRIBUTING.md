# Contributing to swap

Thanks for your interest in improving swap.

## Ground rules

- **Zero runtime dependencies.** swap uses the Python standard library only. Do not add third-party packages.
- **Single self-contained router.** All router logic lives in one file: `skills/swap/swap.py`. Keep it self-contained — no helper modules, no package layout.
- **Cross-platform.** Code must run on macOS, Linux, and Windows. Avoid shell-specific assumptions and use stdlib paths/process APIs.

## Dev setup

1. Clone the repo.
2. Install Python 3.8 or newer (`python3 --version`).
3. Optionally install [Ollama](https://ollama.com/) if you want to test the local backend.

## Running checks

```sh
python3 -m py_compile skills/swap/swap.py
python3 -m unittest discover -s tests
```

## How to add a backend preset

Cloud backends are defined in the `CLOUD_PRESETS` dict in `skills/swap/swap.py`. Add an entry there with the preset's base URL and defaults, then verify it with `swap add-backend`.

## How to add an intent

Intents are defined in the `INTENTS` dict in `skills/swap/swap.py`. Add an entry there describing the new intent and its prompt handling.

## Commit style

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, etc.

## PR process

- Open an issue first for large or design-affecting changes.
- Keep PRs focused on a single concern.
- Do not introduce new dependencies.

All delegation must stay explicit and opt-in. swap never routes work silently — an agent or user always chooses to delegate.
