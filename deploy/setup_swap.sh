#!/usr/bin/env bash
# Idempotent swap setup for the TradeAI VPS.
#
# Adds a 4 GB swapfile at /swapfile + lowers vm.swappiness to 10 (right for a
# long-lived trading bot — only swap when truly forced, never proactively).
#
# Safe to re-run: if swap already exists at /swapfile, exits without changes.
#
# Run once on the VPS:
#     sudo bash /home/tradeai/TradeAI/deploy/setup_swap.sh
#
# To remove later (if ever needed):
#     sudo swapoff /swapfile
#     sudo rm /swapfile
#     sudo sed -i '\|/swapfile|d' /etc/fstab
#     sudo rm /etc/sysctl.d/99-tradeai.conf
set -euo pipefail

SWAPFILE=/swapfile
SWAPSIZE=4G
TARGET_SWAPPINESS=10
SYSCTL_FILE=/etc/sysctl.d/99-tradeai.conf

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: this script must be run as root (use: sudo bash $0)" >&2
  exit 1
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  TradeAI swap setup — ${SWAPSIZE} swapfile + swappiness=${TARGET_SWAPPINESS}"
echo "═══════════════════════════════════════════════════════════════"

# ─── 1. Check if /swapfile already exists ─────────────────────
if swapon --show=NAME --noheadings 2>/dev/null | grep -qx "${SWAPFILE}"; then
  echo "[1/4] /swapfile already active — skipping create."
elif [[ -f "${SWAPFILE}" ]]; then
  echo "[1/4] /swapfile exists but not enabled — enabling..."
  chmod 600 "${SWAPFILE}"
  swapon "${SWAPFILE}"
else
  echo "[1/4] Creating ${SWAPSIZE} swapfile at ${SWAPFILE}..."
  fallocate -l "${SWAPSIZE}" "${SWAPFILE}"
  chmod 600 "${SWAPFILE}"
  mkswap "${SWAPFILE}" > /dev/null
  swapon "${SWAPFILE}"
fi

# ─── 2. Persist to /etc/fstab so swap survives reboot ─────────
if grep -qE "^${SWAPFILE}[[:space:]]+none[[:space:]]+swap" /etc/fstab; then
  echo "[2/4] /etc/fstab already references ${SWAPFILE} — skipping."
else
  echo "[2/4] Adding ${SWAPFILE} to /etc/fstab..."
  echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
fi

# ─── 3. Lower swappiness ──────────────────────────────────────
echo "[3/4] Setting vm.swappiness=${TARGET_SWAPPINESS}..."
sysctl -w "vm.swappiness=${TARGET_SWAPPINESS}" > /dev/null
cat > "${SYSCTL_FILE}" <<EOF
# TradeAI VPS tuning — keep hot trading-bot pages in RAM.
# Only swap when memory is genuinely under pressure.
vm.swappiness=${TARGET_SWAPPINESS}
EOF

# ─── 4. Verify ────────────────────────────────────────────────
echo "[4/4] Verifying..."
echo ""
echo "─── swapon ───────────────────────────────────────────"
swapon --show
echo ""
echo "─── free -h ──────────────────────────────────────────"
free -h
echo ""
echo "─── vm.swappiness ────────────────────────────────────"
sysctl vm.swappiness
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Done. Swap is active + persistent across reboots."
echo "═══════════════════════════════════════════════════════════════"
