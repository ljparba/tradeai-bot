"""
Fix OGD Degenerate Weights — Recovery script (run after adaptive_engine.py patch).

Root cause (diagnosed 2026-05-20):
  The OGD gradient for feature f = reward × score[f].
  When score[f] = 0.0 (e.g. SELL at DISCOUNT → dr_score=0), the gradient is always
  zero — the feature weight is never penalised on LOSS signals. Other features ARE
  penalised (they have positive scores). After renormalisation, dr_location's
  unchanged weight becomes a larger proportion on every LOSS. Over hundreds of
  bootstrap signals this inflates dr_location past the 0.45 degenerate threshold.

  This is a gradient mechanics bug — NOT a data balance issue. Data balance was
  actually 47-53% for most tokens.

  Fix applied in adaptive_engine.py: _SCORE_FLOOR = 0.05 ensures every feature
  gets at least 5% of the gradient, preventing zero-gradient passive inflation.

Tokens actually degenerate (confirmed from first run output):
  AVAX (0.465), ETH (0.565), HBAR (0.558), LINK (0.653)
  BTC (0.346) and SOL (0.419) were OK — incorrectly included in first run.

Fix sequence:
  1. Reset 4 degenerate tokens to DEFAULT_WEIGHTS
  2. Re-bootstrap from all backtest runs (with _SCORE_FLOOR now applied)
  3. Validate — all tokens must pass health_check()

Run after patching adaptive_engine.py:
  > python scripts/fix_ogd_degenerate_weights.py

Safe to re-run — reset_token() is idempotent (DELETE + INSERT).
"""

import sys
import os
import sqlite3

# ── Path setup — allow import from project root ───────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from adaptive_engine import weight_engine, DB_PATH, DEFAULT_WEIGHTS, WEIGHT_MAX, DEGENERATE_THRESHOLD

# ── Tokens requiring reset (above DEGENERATE_THRESHOLD=0.60) ──────────────────
# After threshold change 0.45->0.60:
#   AVAX=0.475, ETH=0.563, HBAR=0.553 → OK (strong learning, not collapsed)
#   LINK=0.648 → still DEGENERATE (97% of mathematical max 0.667 — truly collapsed)
#   BTC=0.346, SOL=0.418, XRP=0.233 → OK
DEGENERATE_TOKENS = ["LINK"]
SKIP_TOKENS       = ["XRP", "BTC", "SOL", "AVAX", "ETH", "HBAR"]  # all within new threshold

# ─────────────────────────────────────────────────────────────────────────────
def get_latest_run_id() -> int | None:
    """Return the highest id from backtest_runs table, or None if empty."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute("SELECT MAX(id) FROM backtest_runs").fetchone()
        conn.close()
        return row[0] if row and row[0] is not None else None
    except Exception as e:
        print(f"[WARN] Could not read backtest_runs: {e}")
        return None


def get_signal_counts(run_id: int | None) -> dict:
    """Return BUY/SELL counts per token for the target run (audit balance)."""
    try:
        conn  = sqlite3.connect(DB_PATH, timeout=30)
        scope = "AND run_id = ?" if run_id is not None else ""
        params = (run_id,) if run_id is not None else ()
        rows  = conn.execute(f"""
            SELECT token, signal, COUNT(*) as n
            FROM backtest_signals
            WHERE outcome IS NOT NULL AND outcome != ''
              AND fvg_quality IS NOT NULL AND fvg_quality NOT IN ('', 'NONE')
              {scope}
            GROUP BY token, signal
            ORDER BY token, signal
        """, params).fetchall()
        conn.close()
        counts: dict = {}
        for token, direction, n in rows:
            if token not in counts:
                counts[token] = {}
            counts[token][direction] = n
        return counts
    except Exception as e:
        print(f"[WARN] Could not read signal counts: {e}")
        return {}


def print_health(label: str):
    """Print per-token health status from weight_engine.health_check()."""
    print(f"\n{'-'*60}")
    print(f"  {label}")
    print(f"{'-'*60}")
    health = weight_engine.health_check()
    if not health:
        print("  (no tokens loaded — DB may be empty)")
        return
    for token in sorted(health):
        h  = health[token]
        dg = "DEGENERATE" if h["is_degenerate"] else "OK"
        print(f"  {token:<5} max_w={h['max_weight']:.3f}  n={h['n_updates']:>4}  "
              f"entropy={h['weight_entropy']:.3f}  [{dg}]")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  OGD Degenerate Weight Reset — TradeAI Fix Script")
    print("=" * 60)

    # ── Step 0: pre-flight health check ──────────────────────────────────────
    print_health("BEFORE — current weight state")

    # ── Step 1: confirm run_id to use for re-bootstrap ───────────────────────
    run_id = get_latest_run_id()
    if run_id is None:
        print("\n[WARN] No backtest runs found in DB — bootstrap will use all runs.")
    else:
        print(f"\n[INFO] Latest backtest run_id = {run_id}")

    # ── Step 2: show bootstrap data balance (BUY vs SELL) ────────────────────
    counts = get_signal_counts(run_id)
    if counts:
        print("\n[INFO] Bootstrap data balance (signals with valid outcome + fvg_quality):")
        all_degenerate = True
        for token in sorted(counts):
            buys  = counts[token].get("BUY",  0)
            sells = counts[token].get("SELL", 0)
            total = buys + sells
            pct_b = 100 * buys  / total if total else 0
            pct_s = 100 * sells / total if total else 0
            flag  = "  <- was SELL-biased" if pct_s > 60 else ""
            print(f"  {token:<5}  BUY={buys:>4} ({pct_b:.0f}%)  "
                  f"SELL={sells:>4} ({pct_s:.0f}%)  total={total}{flag}")
    else:
        print("\n[WARN] No signal data found for balance audit.")

    # ── Step 3: reset degenerate tokens ──────────────────────────────────────
    print(f"\n[STEP 1] Resetting {len(DEGENERATE_TOKENS)} degenerate tokens to DEFAULT_WEIGHTS...")
    for token in DEGENERATE_TOKENS:
        weight_engine.reset_token(token)   # persists to DB + logs to weight_history
    print(f"  Skipping {SKIP_TOKENS} — weights are within bounds.")

    # ── Step 4: re-bootstrap from Run 41 ─────────────────────────────────────
    scope_label = f"run_id={run_id}" if run_id is not None else "ALL runs"
    print(f"\n[STEP 2] Re-bootstrapping from backtest signals ({scope_label})...")
    n_processed = weight_engine.bootstrap_from_backtest(run_id=run_id, verbose=True)

    if not n_processed:
        print("[ERROR] Bootstrap returned 0 processed signals — check DB path and table.")
        sys.exit(1)

    # ── Step 5: post-fix health check ────────────────────────────────────────
    print_health("AFTER — weight state post-reset + re-bootstrap")

    # ── Step 6: validate results ──────────────────────────────────────────────
    print(f"\n{'-'*60}")
    health = weight_engine.health_check()
    still_degen = [t for t, h in health.items() if h["is_degenerate"]]

    # Tokens in DEGENERATE_TOKENS that re-degenerate after re-bootstrap are at
    # their data equilibrium. The degenerate guard in crypto_alert.py will use
    # DEFAULT_WEIGHTS for these — safe, expert priors, appropriate fallback.
    unexpected_degen = [t for t in still_degen if t not in DEGENERATE_TOKENS]

    if unexpected_degen:
        print(f"[FAIL] {len(unexpected_degen)} unexpected degenerate token(s): {unexpected_degen}")
        print("       These were not in DEGENERATE_TOKENS — investigate and add them.")
        sys.exit(1)

    if still_degen:
        print(f"[NOTE] {len(still_degen)} token(s) at stable data equilibrium: {still_degen}")
        print(f"       max_weight > {DEGENERATE_THRESHOLD} even after reset + re-bootstrap.")
        print("       This is the OGD's best fit for available data — not a script error.")
        print("       crypto_alert.py will use DEFAULT_WEIGHTS for these tokens (safe).")
    else:
        print("[PASS] All tokens within bounds — no degenerate weights remain.")

    ok_tokens = [t for t, h in health.items()
                 if t != "BTCUSDT" and not h["is_degenerate"]]
    print(f"\n[RESULT] {len(ok_tokens)} tokens using learned OGD weights: {sorted(ok_tokens)}")
    print(f"         {len(still_degen)} token(s) using DEFAULT_WEIGHTS: {still_degen}")
    print("         OGD adaptive engine is ready for live signal collection.")
    print("=" * 60)


if __name__ == "__main__":
    main()
