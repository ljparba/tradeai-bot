#!/usr/bin/env bash
# Import a Claude memory bundle exported via export_claude_memory.sh.
# Places memory files in the correct ~/.claude/projects/<hash>/memory/ for THIS project's path.
set -e

BUNDLE="${1:-claude_memory_export.tar.gz}"

if [ ! -f "$BUNDLE" ]; then
    echo "[import] bundle not found: $BUNDLE"
    echo "Usage: bash scripts/import_claude_memory.sh <path-to-claude_memory_export.tar.gz>"
    exit 1
fi

# Compute this project's memory dir hash
PROJECT_PATH="$(pwd)"
PROJECT_HASH=$(echo "$PROJECT_PATH" | sed 's/\//-/g; s/^-//')
TARGET_DIR="$HOME/.claude/projects/$PROJECT_HASH/memory"

echo "[import] target dir: $TARGET_DIR"

mkdir -p "$TARGET_DIR"
tar -xzf "$BUNDLE" -C "$(dirname $TARGET_DIR)" --strip-components=0

echo "[import] memory files restored. Verify:"
ls -la "$TARGET_DIR"
echo ""
echo "Next Claude session opening $PROJECT_PATH will auto-load these memories."
