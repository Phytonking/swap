#!/usr/bin/env sh
# swap installer — POSIX, no dependencies beyond python3.
#
#   curl -fsSL https://raw.githubusercontent.com/Phytonking/swap/main/install.sh | sh
#   # or, from a clone:
#   ./install.sh
#
# Bootstraps the router (~/.swap/bin/swap), installs the Claude Code skill if
# present, and prints the one-step wiring for every other harness.
set -eu

REPO="Phytonking/swap"
RAW="https://raw.githubusercontent.com/${REPO}/main"

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

have python3 || { say "error: python3 is required (>=3.8)."; exit 1; }

# Locate the router: a local clone, else fetch swap.py to a temp dir.
SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "${SELF_DIR}/skills/swap/swap.py" ]; then
  SKILL_SRC="${SELF_DIR}/skills/swap"
else
  have curl || { say "error: need curl to fetch swap.py (or run from a clone)."; exit 1; }
  TMP=$(mktemp -d)
  SKILL_SRC="${TMP}/swap"
  mkdir -p "$SKILL_SRC"
  curl -fsSL "${RAW}/skills/swap/swap.py"  -o "${SKILL_SRC}/swap.py"
  curl -fsSL "${RAW}/skills/swap/SKILL.md" -o "${SKILL_SRC}/SKILL.md" 2>/dev/null || true
fi

say "==> Bootstrapping swap router…"
set +e
python3 "${SKILL_SRC}/swap.py" doctor --ensure
STATUS=$?
set -e
say ""

# Install the Claude Code skill (copy the whole dir so swap.py rides along).
if [ -d "${HOME}/.claude" ]; then
  DEST="${HOME}/.claude/skills/swap"
  mkdir -p "$DEST"
  cp "${SKILL_SRC}/swap.py" "$DEST/"
  [ -f "${SKILL_SRC}/SKILL.md" ] && cp "${SKILL_SRC}/SKILL.md" "$DEST/"
  say "==> Installed Claude Code skill -> ${DEST}"
fi

say ""
say "swap router ready at ~/.swap/bin/swap"
say ""
say "Wire your harness (all read one rule file — copy AGENTS.md into your project):"
say "  • Codex / opencode / Windsurf / Cursor / Cline  ->  AGENTS.md  (open standard)"
say "  • Claude Code                                    ->  installed above (or CLAUDE.md)"
say "  • Gemini CLI                                     ->  GEMINI.md"
say "  • Any of 70+ agents, one command                 ->  npx skills add ${REPO}"
say ""
case "$STATUS" in
  0) say "Status: READY — try:  echo 'hi' | ~/.swap/bin/swap summarize 'say ok'";;
  3) say "Status: NEEDS_MODEL — run:  ollama pull qwen3:8b";;
  4) say "Status: NEEDS_BACKEND — install a local model (ollama) or add a cloud key:";
     say "        ~/.swap/bin/swap add-backend gemini --model gemini-2.5-flash";;
  *) say "Status: see the doctor output above.";;
esac
