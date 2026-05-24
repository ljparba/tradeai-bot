"""
Phase 4.3 — ICT + IFVG Validation Suite
Synthetic-candle tests for every detection function.
Run: python validate_ict.py
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# ── Import check ─────────────────────────────────────────
try:
    from crypto_alert import (
        find_ict_swings,
        detect_ict_sweep,
        detect_ict_displacement,
        detect_ict_fvg,
        detect_ict_mss,
        get_ict_4h_bias,
        detect_ict_ifvg,
        compute_ict_trade_plan,
        ICT_SWING_N, ICT_SWEEP_LOOKBACK,
        ICT_DISP_MAX_LOOK, ICT_MSS_HORIZON,
        ICT_FVG_MIN_GAP, ICT_IFVG_LOOKBACK,
        MIN_SL_PCT, MAX_SL_PCT, MAX_BREAKEVEN_WR, MIN_TP1_MULT,
        ROUND_TRIP_COST_PCT,
    )
    print("  [IMPORT] crypto_alert.py ... OK")
except Exception as e:
    print(f"  [IMPORT] crypto_alert.py FAILED: {e}")
    sys.exit(1)

try:
    from backtest import (
        precompute_tf, _lookup_trend, _lookup_4h_bias,
        check_outcome, walk_forward_split, FORWARD_BARS,
        COOLDOWN_BARS, ENTRY_WINDOW, WARMUP_BARS,
        ROUND_TRIP_COST_PCT as BT_RT, SLIPPAGE_PCT,
    )
    print("  [IMPORT] backtest.py ........ OK")
except Exception as e:
    print(f"  [IMPORT] backtest.py FAILED: {e}")
    sys.exit(1)

# ── Test harness ─────────────────────────────────────────
RESULTS = []

def test(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    RESULTS.append((name, status, detail))
    marker = "  [PASS]" if cond else "  [FAIL]"
    msg = f"{marker} {name}"
    if detail and not cond:
        msg += f"\n         detail: {detail}"
    print(msg)
    return cond

# ════════════════════════════════════════════════════════
# HELPER: build a flat price series
# ════════════════════════════════════════════════════════
def flat_series(n, base=100.0, spread=0.5):
    """n bars of flat OHLC at base price."""
    H = [base + spread] * n
    L = [base - spread] * n
    C = [base] * n
    O = [base] * n
    return O, H, L, C

def bull_bar(base, size=2.0, wick_top=0.3, wick_bot=0.3):
    O = base
    C = base + size
    H = C + wick_top
    L = O - wick_bot
    return O, H, L, C

def bear_bar(base, size=2.0, wick_top=0.3, wick_bot=0.3):
    O = base + size
    C = base
    H = O + wick_top
    L = C - wick_bot
    return O, H, L, C

# ════════════════════════════════════════════════════════
# TEST 1: find_ict_swings — confirmed swing high/low
# ════════════════════════════════════════════════════════
print("\n--- Test 1: find_ict_swings ---")
# Bar 2 is the highest (12), bars 3 and 4 are lower → confirmed with n=2
# Bar 5 is a higher local high (13) but only 1 bar follows → NOT confirmed (end=6-2=4)
H = [10, 11, 12, 11, 10, 13, 12]
L = [8,   9,  9,  8,  7,  9,  8]
sh, sl = find_ict_swings(H, L, n=2)
test("Swing high detected at bar 2 (peak=12, has 2+ bars after)",
     any(lev == 12 for _, lev in sh), f"got sh={sh}")
test("Swing high at bar 5 (val=13) NOT confirmed — too close to end (only 1 bar after)",
     not any(lev == 13 for _, lev in sh), f"got sh={sh}")
# Bar 4 is the lowest (7), bars 5 and 6 both higher → confirmed swing low
test("Swing low detected at bar 4 (trough=7)", any(lev == 7 for _, lev in sl),
     f"got sl={sl}")

# ════════════════════════════════════════════════════════
# TEST 2: detect_ict_sweep — bullish sweep (SSL → BUY)
# Swing low at bar 3, sweep at bar 12 (within last 10 of 15 bars).
# ICT_SWEEP_LOOKBACK=10: searches bars 5..14 for a 15-bar series.
# ════════════════════════════════════════════════════════
print("\n--- Test 2: detect_ict_sweep — bullish SSL ---")
N = 15
H = [100.0] * N
L = [99.0]  * N
C = [99.5]  * N

# Bar 3: swing low at 98.0 (confirmed: bars 4,5 both have L=99.0 > 98.0)
L[3] = 98.0; C[3] = 99.8

# Bar 12: wick below swing_low (97.5 < 98.0) but close back above (99.2 > 98.0)
L[12] = 97.5; H[12] = 100.5; C[12] = 99.2

sh, sl = find_ict_swings(H, L)
sweep = detect_ict_sweep(H, L, C, sh, sl)
test("SSL sweep detected", sweep is not None and sweep["type"] == "SSL",
     f"sweep={sweep}, sl={sl}")
test("SSL sweep_low < swing_low",
     sweep is not None and sweep["sweep_low"] < 98.0,
     f"sweep_low={sweep['sweep_low'] if sweep else 'N/A'}")
test("SSL close > swing_low (close-back confirmation)",
     sweep is not None and C[sweep["bar"]] > 98.0,
     f"C[{sweep['bar'] if sweep else '?'}]={C[sweep['bar']] if sweep else '?'}")

# ════════════════════════════════════════════════════════
# TEST 3: detect_ict_sweep — bearish sweep (BSL → SELL)
# Swing high at bar 3, sweep at bar 12 (within last 10 of 15 bars).
# ════════════════════════════════════════════════════════
print("\n--- Test 3: detect_ict_sweep — bearish BSL ---")
N = 15
H = [100.0] * N
L = [99.0]  * N
C = [99.5]  * N

# Bar 3: swing high at 102.0 (bars 4,5 both have H=100.0 < 102.0)
H[3] = 102.0; C[3] = 99.2

# Bar 12: wick above swing_high (102.8 > 102.0) but close back below (100.5 < 102.0)
H[12] = 102.8; L[12] = 99.0; C[12] = 100.5

sh, sl = find_ict_swings(H, L)
sweep = detect_ict_sweep(H, L, C, sh, sl)
test("BSL sweep detected", sweep is not None and sweep["type"] == "BSL",
     f"sweep={sweep}, sh={sh}")
test("BSL sweep_high > swing_high",
     sweep is not None and sweep["sweep_high"] > 102.0,
     f"sweep_high={sweep['sweep_high'] if sweep else 'N/A'}")
test("BSL close < swing_high (close-back confirmation)",
     sweep is not None and C[sweep["bar"]] < 102.0,
     f"C[{sweep['bar'] if sweep else '?'}]={C[sweep['bar']] if sweep else '?'}")

# ════════════════════════════════════════════════════════
# TEST 4: detect_ict_fvg — bullish FVG
# ════════════════════════════════════════════════════════
print("\n--- Test 4: detect_ict_fvg — bullish ---")
# d=1: highs[0]=99, displacement candle, lows[2]=100.5 > highs[0] → gap
H_fvg = [99.0, 101.0, 103.0, 104.0]
L_fvg = [98.0,  99.5, 100.5, 101.0]
fvg = detect_ict_fvg(1, H_fvg, L_fvg)
test("Bullish FVG detected", fvg is not None and fvg["direction"] == "BUY",
     f"fvg={fvg}")
test("FVG bottom = highs[d-1] = 99.0",
     fvg is not None and abs(fvg["bottom"] - 99.0) < 1e-9)
test("FVG top = lows[d+1] = 100.5",
     fvg is not None and abs(fvg["top"] - 100.5) < 1e-9)
test("FVG gap >= ICT_FVG_MIN_GAP",
     fvg is not None and (fvg["top"] - fvg["bottom"]) / fvg["top"] >= ICT_FVG_MIN_GAP)

# ════════════════════════════════════════════════════════
# TEST 5: detect_ict_fvg — bearish FVG
# ════════════════════════════════════════════════════════
print("\n--- Test 5: detect_ict_fvg — bearish ---")
H_fvg = [104.0, 103.0, 101.0, 100.0]
L_fvg = [102.0, 100.5,  99.5,  98.0]
fvg = detect_ict_fvg(1, H_fvg, L_fvg)
test("Bearish FVG detected", fvg is not None and fvg["direction"] == "SELL",
     f"fvg={fvg}")
test("FVG top = lows[d-1] = 102.0",
     fvg is not None and abs(fvg["top"] - 102.0) < 1e-9)
test("FVG bottom = highs[d+1] = 101.0",
     fvg is not None and abs(fvg["bottom"] - 101.0) < 1e-9)

# ════════════════════════════════════════════════════════
# TEST 6: detect_ict_ifvg — bullish IFVG
# Bullish IFVG: former bearish FVG (highs[d+1] < lows[d-1]) where price
# later CLOSES ABOVE fvg_top → gap reclaimed → acts as support for BUY
# ════════════════════════════════════════════════════════
print("\n--- Test 6: detect_ict_ifvg — bullish IFVG ---")
# Build 10-bar series
# Bars 0-3: price around 100
# Bars 1-3: bearish FVG at d=2: highs[3] < lows[1]
# lows[1] = 100.5, highs[3] = 99.5 → bearish FVG bottom=99.5 top=100.5
# Bar 4+: price closes above 100.5 (reclaim)
# Bars 5-9: remain above 100.5
H_i = [101.0, 102.0, 101.0, 99.5,  101.0, 102.0, 102.5, 103.0, 103.5, 104.0]
L_i = [99.5,  100.5,  98.5, 98.0,  100.0, 101.0, 101.5, 102.0, 102.5, 103.0]
C_i = [100.0, 101.5,  99.0, 98.5,  101.0, 101.5, 102.0, 102.5, 103.0, 103.5]

# Check: d=2 → highs[d+1]=highs[3]=99.5 < lows[d-1]=lows[1]=100.5 → bearish FVG
test("Precondition: bearish FVG exists at d=2",
     H_i[3] < L_i[1],
     f"highs[3]={H_i[3]} vs lows[1]={L_i[1]}")

ifvg = detect_ict_ifvg(H_i, L_i, C_i, "BUY")
test("Bullish IFVG detected", ifvg["ifvg_present"] is True,
     f"ifvg={ifvg}")
test("IFVG direction = BUY", ifvg.get("ifvg_direction") == "BUY")
test("IFVG top = lows[d-1] = 100.5",
     abs(ifvg.get("ifvg_top", 0) - 100.5) < 1e-6)
test("IFVG bottom = highs[d+1] = 99.5",
     abs(ifvg.get("ifvg_bottom", 0) - 99.5) < 1e-6)
test("ifvg_age_bars returned as integer",
     isinstance(ifvg.get("ifvg_age_bars"), int))
test("ifvg_age_bars > 0 (IFVG was in the past)",
     ifvg.get("ifvg_age_bars", 0) > 0,
     f"age={ifvg.get('ifvg_age_bars')}")

# ════════════════════════════════════════════════════════
# TEST 7: detect_ict_ifvg — bearish IFVG
# Bearish IFVG: former bullish FVG (lows[d+1] > highs[d-1]) where price
# later CLOSES BELOW fvg_bottom → gap violated → acts as resistance for SELL
# ════════════════════════════════════════════════════════
print("\n--- Test 7: detect_ict_ifvg — bearish IFVG ---")
# d=2: lows[d+1]=lows[3]=100.5 > highs[d-1]=highs[1]=99.5 → bullish FVG
# fvg_bottom=highs[1]=99.5, fvg_top=lows[3]=100.5
# Bar 4+: closes below 99.5 (violation)
H_b = [100.0, 99.5,  101.0, 102.0, 99.0,  98.0,  97.5,  97.0,  96.5,  96.0]
L_b = [98.0,  98.5,   99.5, 100.5, 97.5,  97.0,  96.5,  96.0,  95.5,  95.0]
C_b = [99.0,  99.0,  100.0, 101.0, 99.0,  98.5,  97.0,  96.5,  96.0,  95.5]

test("Precondition: bullish FVG exists at d=2",
     L_b[3] > H_b[1],
     f"lows[3]={L_b[3]} vs highs[1]={H_b[1]}")

ifvg_b = detect_ict_ifvg(H_b, L_b, C_b, "SELL")
test("Bearish IFVG detected", ifvg_b["ifvg_present"] is True,
     f"ifvg={ifvg_b}")
test("IFVG direction = SELL", ifvg_b.get("ifvg_direction") == "SELL")

# ════════════════════════════════════════════════════════
# TEST 8: detect_ict_ifvg — no IFVG (price never reclaims)
# ════════════════════════════════════════════════════════
print("\n--- Test 8: detect_ict_ifvg — no IFVG (no reclaim) ---")
# Same bearish FVG at d=2 but price stays below 100.5 (never reclaims)
H_no = [101.0, 102.0, 101.0, 99.5,  100.0, 100.0, 99.0,  98.5,  98.0,  97.5]
L_no = [99.5,  100.5,  98.5, 98.0,   98.5,  98.0,  97.5, 97.0,   96.5, 96.0]
C_no = [100.0, 101.5,  99.0, 98.5,   99.5,  99.0,  98.5, 98.0,   97.5, 97.0]

ifvg_no = detect_ict_ifvg(H_no, L_no, C_no, "BUY")
test("No IFVG when price never reclaims gap top",
     ifvg_no["ifvg_present"] is False,
     f"ifvg={ifvg_no}")
test("ifvg_age_bars = 0 when no IFVG",
     ifvg_no.get("ifvg_age_bars", -1) == 0)

# ════════════════════════════════════════════════════════
# TEST 9: 4H bias — BULLISH (EMA trend)
# ════════════════════════════════════════════════════════
print("\n--- Test 9: get_ict_4h_bias — bullish ---")
# Rising price series → EMA50 > EMA200 eventually → STRONG_BULL → BULLISH bias
import random
random.seed(42)
closes_bull = [100.0]
for _ in range(209):
    closes_bull.append(closes_bull[-1] * (1.0 + random.uniform(0.001, 0.003)))
highs_bull = [c * 1.002 for c in closes_bull]
lows_bull  = [c * 0.998 for c in closes_bull]

bias_bull = get_ict_4h_bias(closes_bull, highs_bull, lows_bull)
test("4H bias BULLISH on rising series",
     bias_bull == "BULLISH",
     f"got '{bias_bull}'")

# ════════════════════════════════════════════════════════
# TEST 10: 4H bias — BEARISH (EMA trend)
# ════════════════════════════════════════════════════════
print("\n--- Test 10: get_ict_4h_bias — bearish ---")
closes_bear = [200.0]
for _ in range(209):
    closes_bear.append(closes_bear[-1] * (1.0 - random.uniform(0.001, 0.003)))
highs_bear = [c * 1.002 for c in closes_bear]
lows_bear  = [c * 0.998 for c in closes_bear]

bias_bear = get_ict_4h_bias(closes_bear, highs_bear, lows_bear)
test("4H bias BEARISH on declining series",
     bias_bear == "BEARISH",
     f"got '{bias_bear}'")

# ════════════════════════════════════════════════════════
# TEST 11: 4H bias — NEUTRAL (insufficient data)
# ════════════════════════════════════════════════════════
print("\n--- Test 11: get_ict_4h_bias — neutral (< 200 bars) ---")
bias_neutral = get_ict_4h_bias([100.0] * 150, [101.0] * 150, [99.0] * 150)
test("4H bias NEUTRAL when < 200 bars",
     bias_neutral == "NEUTRAL",
     f"got '{bias_neutral}'")

# ════════════════════════════════════════════════════════
# TEST 12: No-lookahead — IFVG at exactly current bar
# The reclaim bar should NOT be the last bar in the slice
# (d+2..n-1 must have at least one bar after formation)
# ════════════════════════════════════════════════════════
print("\n--- Test 12: IFVG no-lookahead boundary ---")
# 8-bar series; IFVG formed at d=2 (bars 1,2,3), reclaim at bar 4
# If slice ends at bar 4 (n=5, last_closed), d=2, range(4,5) = [4] → reclaim visible
H_la = [101.0, 102.0, 101.0, 99.5,  101.0]
L_la = [99.5,  100.5,  98.5, 98.0,  100.6]
C_la = [100.0, 101.5,  99.0, 98.5,  100.8]   # bar 4 closes above 100.5

ifvg_at_n5 = detect_ict_ifvg(H_la, L_la, C_la, "BUY")
test("IFVG detected when reclaim is last bar (n=5, d=2, reclaim@4)",
     ifvg_at_n5["ifvg_present"] is True,
     f"ifvg={ifvg_at_n5}")

# If we cut the slice at bar 3 (n=4) — reclaim has NOT happened yet
H_la4 = H_la[:4]; L_la4 = L_la[:4]; C_la4 = C_la[:4]
ifvg_at_n4 = detect_ict_ifvg(H_la4, L_la4, C_la4, "BUY")
test("No IFVG when reclaim bar is excluded (n=4, d=2, reclaim@4 not in slice)",
     ifvg_at_n4["ifvg_present"] is False,
     f"ifvg={ifvg_at_n4}")

# ════════════════════════════════════════════════════════
# TEST 13: No-lookahead — swing confirmation requires ICT_SWING_N bars
# ════════════════════════════════════════════════════════
print("\n--- Test 13: find_ict_swings no-lookahead ---")
# Series where bar 5 is a high but only 1 confirmation bar follows
H_sw = [10, 10, 12, 10, 9, 11, 10]   # bar 5 has only 1 bar after (bar 6)
L_sw = [8,   8,  8,  7,  7,  8,  7]
sh_sw, _ = find_ict_swings(H_sw, L_sw, n=2)
bar5_confirmed = any(idx == 5 and lev == 11 for idx, lev in sh_sw)
test("Swing at bar 5 NOT confirmed (only 1 bar after, need 2)",
     not bar5_confirmed,
     f"sh={sh_sw}")

# ════════════════════════════════════════════════════════
# TEST 14: compute_ict_trade_plan — BUY plan basic
# ════════════════════════════════════════════════════════
print("\n--- Test 14: compute_ict_trade_plan — BUY ---")
price_t   = 100.0
wick_t    = 98.5    # swept wick → SL = 98.5 * 0.997 = 98.2055
sh_1h_t   = [102.0, 104.0, 106.0]
sl_1h_t   = [95.0, 92.0]
plan_buy  = compute_ict_trade_plan(price_t, "BUY", wick_t, sh_1h_t, sl_1h_t)
test("BUY plan generated", plan_buy is not None, f"plan={plan_buy}")
if plan_buy:
    test("SL is below price", plan_buy["sl"] < price_t,
         f"sl={plan_buy['sl']}")
    test("TP1 > price (BUY direction)", plan_buy["tp1"] > price_t,
         f"tp1={plan_buy['tp1']}")
    test("net_tp1_pct > 0 (profit after fees)", plan_buy["net_tp1_pct"] > 0,
         f"net_tp1={plan_buy['net_tp1_pct']}")
    test("BEW <= MAX_BREAKEVEN_WR", plan_buy["breakeven_wr"] <= MAX_BREAKEVEN_WR,
         f"bew={plan_buy['breakeven_wr']}")
    test("R:R >= MIN_TP1_MULT", plan_buy["rr1"] >= MIN_TP1_MULT,
         f"rr1={plan_buy['rr1']}")

# ════════════════════════════════════════════════════════
# TEST 15: compute_ict_trade_plan — SELL plan basic
# ════════════════════════════════════════════════════════
print("\n--- Test 15: compute_ict_trade_plan — SELL ---")
wick_sell  = 101.5
plan_sell  = compute_ict_trade_plan(price_t, "SELL", wick_sell, sh_1h_t, sl_1h_t)
test("SELL plan generated", plan_sell is not None, f"plan={plan_sell}")
if plan_sell:
    test("SL is above price (SELL)", plan_sell["sl"] > price_t,
         f"sl={plan_sell['sl']}")
    test("TP1 < price (SELL direction)", plan_sell["tp1"] < price_t,
         f"tp1={plan_sell['tp1']}")
    test("net_tp1_pct > 0 (SELL profit after fees)", plan_sell["net_tp1_pct"] > 0)
    test("BEW <= MAX_BREAKEVEN_WR (SELL)", plan_sell["breakeven_wr"] <= MAX_BREAKEVEN_WR)

# ════════════════════════════════════════════════════════
# TEST 16: compute_ict_trade_plan — SL too wide → rejected
# ════════════════════════════════════════════════════════
print("\n--- Test 16: trade plan — SL exceeds MAX_SL_PCT ---")
wick_far  = 88.0   # SL would be ~12% away → rejected
plan_wide = compute_ict_trade_plan(price_t, "BUY", wick_far, sh_1h_t, sl_1h_t)
test("Plan rejected when SL > MAX_SL_PCT",
     plan_wide is None,
     f"got plan: {plan_wide}")

# ════════════════════════════════════════════════════════
# TEST 17: check_outcome — WIN (TP1 hit before SL)
# ════════════════════════════════════════════════════════
print("\n--- Test 17: check_outcome — BUY WIN ---")
future_win = [
    {"h": 99.0, "l": 98.5},   # fluctuates
    {"h": 101.5, "l": 100.0}, # TP1=101.0 hit here
    {"h": 102.5, "l": 101.5}, # TP2=102.0 hit
    {"h": 103.5, "l": 102.5}, # TP3=103.0 hit
]
out, tp = check_outcome("BUY", 98.0, 101.0, 102.0, 103.0, future_win)
test("BUY WIN outcome", out == "WIN" and tp == 3,
     f"outcome={out} tp={tp}")

# ════════════════════════════════════════════════════════
# TEST 18: check_outcome — LOSS (SL hit before TP)
# ════════════════════════════════════════════════════════
print("\n--- Test 18: check_outcome — BUY LOSS ---")
future_loss = [
    {"h": 100.5, "l": 97.5},  # low <= SL=98.0 → LOSS
    {"h": 102.0, "l": 100.0},
]
out_l, tp_l = check_outcome("BUY", 98.0, 101.0, 102.0, 103.0, future_loss)
test("BUY LOSS outcome (SL hit)", out_l == "LOSS" and tp_l == 0,
     f"outcome={out_l} tp={tp_l}")

# ════════════════════════════════════════════════════════
# TEST 19: walk_forward_split — chronological 60/40
# ════════════════════════════════════════════════════════
print("\n--- Test 19: walk_forward_split ---")
fake_sigs = [{"ts": f"2024-01-{i:02d} 00:00", "outcome": "WIN"} for i in range(1, 21)]
train, test_sigs, cutoff = walk_forward_split(fake_sigs, train_frac=0.60)
test("Train = 60% of signals", len(train) == 12,
     f"train={len(train)}")
test("Test = 40% of signals",  len(test_sigs) == 8,
     f"test={len(test_sigs)}")
test("Cutoff date is first test signal ts",
     cutoff == test_sigs[0]["ts"])
test("Train is chronologically before test",
     train[-1]["ts"] < test_sigs[0]["ts"])

# ════════════════════════════════════════════════════════
# TEST 20: IFVG metadata fields present in all returns
# ════════════════════════════════════════════════════════
print("\n--- Test 20: IFVG metadata completeness ---")
for label, result in [("IFVG present", ifvg), ("No IFVG", ifvg_no)]:
    for field in ("ifvg_present", "ifvg_direction", "ifvg_top", "ifvg_bottom", "ifvg_age_bars"):
        test(f"{label}: field '{field}' present",
             field in result,
             f"keys={list(result.keys())}")

# ════════════════════════════════════════════════════════
# TEST 21: Backtest constants match live bot
# ════════════════════════════════════════════════════════
print("\n--- Test 21: backtest/live constant parity ---")
test(f"ROUND_TRIP_COST_PCT matches (BT={BT_RT} live={ROUND_TRIP_COST_PCT})",
     abs(BT_RT - ROUND_TRIP_COST_PCT) < 1e-9)
test(f"FORWARD_BARS=144 (12H at 5M)",   FORWARD_BARS == 144)
test(f"COOLDOWN_BARS=12 (60min at 5M)", COOLDOWN_BARS == 12)
test(f"ENTRY_WINDOW=48 (4H at 5M)",    ENTRY_WINDOW == 48)
test(f"WARMUP_BARS=210",               WARMUP_BARS == 210)

# ════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════
print("\n" + "=" * 60)
passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
print(f"  VALIDATION RESULTS: {passed}/{len(RESULTS)} PASS   {failed} FAIL")
print("=" * 60)

if failed:
    print("\nFAILED TESTS:")
    for name, status, detail in RESULTS:
        if status == "FAIL":
            print(f"  - {name}")
            if detail:
                print(f"    {detail}")

sys.exit(0 if failed == 0 else 1)
