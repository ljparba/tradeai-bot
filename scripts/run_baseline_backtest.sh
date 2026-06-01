#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/run_baseline_backtest.sh
#
# Run the TradeAI backtest under the EXACT Run-3704 baseline config with full
# isolation flags. Prevents accidental modification of:
#   - bot_state.latest_cpcv_verdict (WRITE_CPCV_VERDICT=0)
#   - backtest_token_weights         (BOOTSTRAP_AFTER_RUN=0)
#
# Uses `env -i` so leftover shell environment variables CANNOT leak in and
# silently change the config. Every Run-3704 env var is set explicitly here.
#
# Expected output (a successful reproduction of Run-3704):
#   n_signals=106, WR=71.7%, CPCV mean=65.98%, Sharpe=0.638, DSR≈96.3%
#   config_hash=e9808bd1fe1b7e12...
#
# NOTE ON THE config_hash: the value above (e9808bd1...) is the POST-cycle-15-loop
# hash. The pin file (data/baseline_pin.json) records 3ee13531... which is the
# PRE-fix hash — Run-3704 was promoted before backtest.py:265 changed COOLDOWN_BARS
# from a hardcoded 8 to env-derived (max(1, SIGNAL_COOLDOWN//5) = 12 at the current
# .env). The strategy behavior is IDENTICAL between the two hashes — the CRT
# scanner doesn't use COOLDOWN_BARS at all. The hash function output changed
# without affecting signal generation. This is expected and harmless; see
# docs/HELD_OUT_DAYS_EXPLAINED.md and the cycle-15-loop ledger for full detail.
#
# DOES NOT MODIFY:
#   - baseline_pin.json
#   - .env
#   - backtest.py or any strategy code
#   - the live tradeai service
#
# Usage:
#   bash scripts/run_baseline_backtest.sh
#   bash scripts/run_baseline_backtest.sh --fresh        # force OHLCV re-fetch
#   bash scripts/run_baseline_backtest.sh --clear-cache  # wipe cache + exit
#
# Source-of-truth for these values: data/baseline_pin.json::key_settings
# Last-synced: 2026-05-31 (Run-3704, pin hash 3ee13531... / runtime hash e9808bd1...)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Locate repo root (this script lives in scripts/, so repo root is one level up)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Sanity: refuse to run if baseline_pin.json doesn't say Run-3704.
# Prevents accidental mismatch if pin gets promoted later without updating this
# script. To use this wrapper after a future pin promotion, update the env block
# below AND this run_id check.
PIN_RUN_ID="$(python3 -c "import json; print(json.load(open('data/baseline_pin.json'))['run_id'])")"
if [ "$PIN_RUN_ID" != "3704" ]; then
  echo "[ABORT] baseline_pin.json points to Run-$PIN_RUN_ID, not Run-3704."
  echo "        This wrapper is hard-coded for Run-3704. Update the env block"
  echo "        in scripts/run_baseline_backtest.sh and the run_id check above"
  echo "        before re-running, or use a different wrapper for the new pin."
  exit 1
fi

echo "[INFO] Running Run-3704 baseline backtest with isolation flags ON"
echo "[INFO] WRITE_CPCV_VERDICT=0  → live bot_state.latest_cpcv_verdict untouched"
echo "[INFO] BOOTSTRAP_AFTER_RUN=0 → backtest_token_weights untouched"
echo "[INFO] env -i                → leftover shell vars cannot leak in"
echo "[INFO] Expected: n=106, WR=71.7%, hash e9808bd1fe1b7e12... (POST-fix hash)"
echo ""

# env -i wipes ALL inherited environment; only what we explicitly pass survives.
# HOME + PATH preserved so python3 can find user-site packages.
exec env -i \
  HOME="$HOME" \
  PATH="$PATH" \
  EXECUTION_MODE=PAPER \
  ENABLE_5M_SWEEP=0 \
  ENABLE_H4_CRT=1 \
  WYCKOFF_PHASE_FILTER=off \
  LIVE_BIAS_4H_GATE=loose \
  BACKTEST_BIAS_4H_GATE=loose \
  CRT_TP1_MODE=dynamic \
  CRT_TP2_RR=1.8 \
  CRT_TP3_RR=2.7 \
  CRT_FORWARD_BARS=864 \
  CRT_REQUIRE_1H_TREND=0 \
  H4_CRT_C2_LOOKBACK=4 \
  H4_CRT_MSS_HORIZON=35 \
  H4_CRT_OB_SCAN_LOOKBACK=20 \
  H4_CRT_FVG_PROBE_WIDTH=5 \
  H4_CRT_MITIGATION_TTL_H=24 \
  ICT_FVG_MIN_GAP=0.0025 \
  ICT_SL_BUFFER_PCT=0.005 \
  MIN_TP1_MULT=1.5 \
  SIGNAL_COOLDOWN=60 \
  FUNDING_BONUS_PCT=0.1 \
  FUNDING_EXTREME_LONG_THRESH=-0.0004 \
  FUNDING_EXTREME_SHORT_THRESH=0.0005 \
  FUNDING_GATE_ENABLED=1 \
  BTC_CORR_BONUS_PCT=0.08 \
  BTC_CORR_HIGH_THRESH=0.9 \
  BTC_CORR_WINDOW_MIN=50 \
  WRITE_CPCV_VERDICT=0 \
  BOOTSTRAP_AFTER_RUN=0 \
  python3 backtest.py "$@"
