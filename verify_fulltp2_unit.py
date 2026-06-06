"""verify_fulltp2_unit.py — synthetic-path unit verification of V_FULLTP2.

Confirms check_outcome_fulltp2() classification + _calc_realized_r_fulltp2() R
formula on hand-built bar paths, and CONTRASTS each path against V_ENTRY's
blended R + explicit exit/fee count. In-memory only; no DB.

All paths use a BUY at entry=100, SL=98 (risk=2.00%), TP1=104 (2R), TP2=106 (3R),
TP3=108 (4R). Friction rt=0.30% round-trip (ROUND_TRIP_COST_PCT default) applied
as a single round-trip per exit leg (the harness convention).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/home/tradeai/TradeAI")

import run_tf_grid as G

ENTRY, SL, TP1, TP2, TP3 = 100.0, 98.0, 104.0, 106.0, 108.0
RT = 0.30  # % round-trip (0.003 * 100)

# Gross % moves (BUY)
g_tp1 = (TP1 - ENTRY) / ENTRY * 100   # +4.0
g_tp2 = (TP2 - ENTRY) / ENTRY * 100   # +6.0
g_tp3 = (TP3 - ENTRY) / ENTRY * 100   # +8.0
g_sl  = (SL  - ENTRY) / ENTRY * 100   # -2.0
n_tp1 = round(g_tp1 - RT, 3)
n_tp2 = round(g_tp2 - RT, 3)
n_tp3 = round(g_tp3 - RT, 3)
n_sl  = round(g_sl  - RT, 2)


def bars(*pairs):
    return [{"h": h, "l": l} for (h, l) in pairs]


# (label, bar path, expected V_FULLTP2 outcome, V_FULLTP2 exits, V_ENTRY exits note)
PATHS = [
    ("SL before TP1",
     bars((101, 99), (101, 97.5)),                       # dips to SL=98 pre-TP1
     "LOSS", 1),
    ("TP1 -> back to ENTRY (BE)",
     bars((104.5, 101), (102, 99.5)),                    # TP1 touched, next bar back to entry
     "BREAKEVEN", 1),
    ("TP1 -> TP2 (WIN, single exit)",
     bars((104.5, 101), (106.5, 103)),                   # TP1 then TP2
     "WIN", 1),
    ("TP1 -> hangs between entry & TP2 -> expiry",
     bars((104.5, 101), (105, 101.5), (105.2, 101.2)),   # never TP2, never back to entry
     "EXPIRED_BE", 1),
    ("never reaches TP1 -> expiry (no SL)",
     bars((101, 99.5), (102, 99.2), (103, 99.1)),        # drifts, never TP1, never SL
     "EXPIRED", 0),
    ("never TP1 -> SL late",
     bars((103, 99), (103.5, 97.9)),                     # SL before TP1 ever touched
     "LOSS", 1),
]


def ventry_r_and_exits(path):
    """Compute V_ENTRY outcome + blended R + exit count for the same path."""
    oc, _ = G.check_outcome("BUY", ENTRY, SL, TP1, TP2, TP3, path)
    r = G._calc_realized_r(oc, n_tp1, n_sl, n_tp2, n_tp3, RT)
    # exit count: any TP1-touched tier books 2 legs; LOSS books 1; EXPIRED ~0
    if oc in ("PARTIAL_TP1", "PARTIAL_TP2", "PARTIAL_TP2_BE", "PARTIAL_TP2_T1", "WIN"):
        exits = 2
    elif oc == "LOSS":
        exits = 1
    else:
        exits = 0
    return oc, r, exits


print("=" * 100)
print("V_FULLTP2 UNIT VERIFICATION  (entry=100 SL=98[1R=2%] TP1=104[2R] TP2=106[3R] TP3=108[4R], rt=0.30%)")
print("=" * 100)
print(f"  nets: net_tp1={n_tp1}  net_tp2={n_tp2}  net_tp3={n_tp3}  net_sl={n_sl}")
print()
hdr = f"  {'path':<42}{'F2 oc':<12}{'F2 R':>8}{'F2 ex':>7}   |  {'ENTRY oc':<16}{'ENTRY R':>9}{'EN ex':>7}{'feeΔ exits':>12}"
print(hdr)
print("  " + "-" * (len(hdr) - 2))

all_ok = True
for label, path, exp_oc, exp_ex in PATHS:
    oc2, _ = G.check_outcome_fulltp2("BUY", ENTRY, SL, TP1, TP2, TP3, path)
    r2 = G._calc_realized_r_fulltp2(oc2, n_tp2, n_sl, RT)
    oc1, r1, ex1 = ventry_r_and_exits(path)
    ok = (oc2 == exp_oc)
    all_ok &= ok
    feed = ex1 - exp_ex
    flag = "OK " if ok else "XX "
    print(f"  {flag}{label:<39}{oc2:<12}{r2:>+8.3f}{exp_ex:>7}   |  {oc1:<16}{r1:>+9.3f}{ex1:>7}{feed:>+12}")

print()
# Explicit R derivations for the 3 economically-distinct outcomes
print("  R DERIVATIONS (single-exit friction made explicit):")
risk = abs(n_sl)
print(f"    risk unit = |net_sl| = {risk:.3f}%")
print(f"    LOSS      : net_sl/risk                 = {n_sl}/{risk:.3f}      = {round(n_sl/risk,4):+.4f}  (1 exit)")
print(f"    WIN       : net_tp2/risk                = {n_tp2}/{risk:.3f}     = {round(n_tp2/risk,4):+.4f}  (1 exit, ONE fee)")
print(f"    BREAKEVEN : -rt/risk                    = -{RT}/{risk:.3f}      = {round(-RT/risk,4):+.4f}  (1 exit, round-trip only)")
print()
print("  CONTRAST — same TP1->TP2->reverse path, V_ENTRY vs V_FULLTP2 fee/exit count:")
print("    V_ENTRY  WIN(full→TP3) R = (0.5*net_tp1 + 0.5*net_tp3)/risk = "
      f"{round((0.5*n_tp1+0.5*n_tp3)/risk,4):+.4f}  → books 2 exits (TP1 half + TP3 half)")
print("    V_FULLTP2 WIN(→TP2)    R = net_tp2/risk = "
      f"{round(n_tp2/risk,4):+.4f}  → books 1 exit (full at TP2)")
print(f"    Headline-R identical at max ({round((0.5*n_tp1+0.5*n_tp3)/risk,4):+.4f}); the DIFFERENCE is the PATH "
      "needed (TP3 vs TP2) and the exit count (2 vs 1).")
print()
print("    Key partial-lock-in contrast — TP1 touched then reverses to entry:")
print(f"    V_ENTRY  PARTIAL_TP1   R = (0.5*net_tp1 + 0.5*(-rt))/risk = "
      f"{round((0.5*n_tp1+0.5*(-RT))/risk,4):+.4f}  (locks half at TP1 = +1R-ish)")
print(f"    V_FULLTP2 BREAKEVEN    R = -rt/risk = "
      f"{round(-RT/risk,4):+.4f}  (gives up the TP1 lock-in → ~0)")
print()
print("ALL CLASSIFICATIONS OK" if all_ok else "*** CLASSIFICATION MISMATCH ***")
sys.exit(0 if all_ok else 1)
