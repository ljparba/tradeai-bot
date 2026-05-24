#!/usr/bin/env bash
# Export local Claude Code memory files to a portable bundle.
#
# Use this to transfer memory + context from one machine to another
# (e.g., from local PC to VPS for VSCode Remote SSH Claude sessions).
#
# Usage (on the source machine):
#   bash scripts/export_claude_memory.sh
#   → creates ./claude_memory_export.tar.gz
#
# Then on the target machine:
#   bash scripts/import_claude_memory.sh ./claude_memory_export.tar.gz
set -e

# Find the auto-memory directory for THIS project
PROJECT_HASH=$(echo "$(pwd)" | sed 's/\//-/g; s/^-//')
MEMORY_DIR="$HOME/.claude/projects/${PROJECT_HASH//[:.]/-}/memory"

# Fallback patterns
if [ ! -d "$MEMORY_DIR" ]; then
    # Windows path translation attempt
    MEMORY_DIR="$HOME/.claude/projects/c--Users-User-Desktop-TradeAI/memory"
fi

if [ ! -d "$MEMORY_DIR" ]; then
    echo "[export] could not auto-locate memory dir. Checking common paths..."
    ls -d "$HOME/.claude/projects/"*/memory 2>/dev/null | head -5
    echo "[export] please set MEMORY_DIR env var to the correct path and rerun"
    exit 1
fi

echo "[export] found memory dir: $MEMORY_DIR"
echo "[export] files to bundle:"
ls -la "$MEMORY_DIR" | head -20
echo ""

OUT="claude_memory_export.tar.gz"
tar -czf "$OUT" -C "$(dirname $MEMORY_DIR)" memory/

echo "[export] bundle written: $(pwd)/$OUT ($(du -h $OUT | cut -f1))"
echo ""
echo "Transfer to target machine, then run:"
echo "  bash scripts/import_claude_memory.sh $OUT"
