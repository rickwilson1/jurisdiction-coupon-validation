#!/usr/bin/env bash
# PostToolUse hook: lint & format a just-edited Python file with ruff.
# Auto-fixes safe lint issues and formats, then reports anything left that
# needs a human/AI judgment call back to Claude.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUFF="$ROOT/.venv/bin/ruff"

# The hook receives the tool call as JSON on stdin; pull out the file path.
FILE="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)"

# Only act on Python files that exist and when ruff is installed.
case "$FILE" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$FILE" ] || exit 0
[ -x "$RUFF" ] || exit 0

# Auto-fix safe lint issues (imports, quotes, whitespace, etc.) and format.
"$RUFF" check --fix "$FILE" >/dev/null 2>&1 || true
"$RUFF" format "$FILE" >/dev/null 2>&1 || true

# Re-check for anything the auto-fixer couldn't resolve on its own.
OUT="$("$RUFF" check "$FILE" 2>&1)" && exit 0

# Remaining issues need a judgment call: report them to Claude.
{
  echo "ruff auto-fixed & formatted $FILE, but these remain (need manual fix):"
  echo "$OUT"
} >&2
exit 2
