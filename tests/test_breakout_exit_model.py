"""test_breakout_exit_model.py — POST-TP2 HOLD-AT-ENTRY (V_ENTRY, 2026-06-04) verification.

The LIVE soak model is now V_ENTRY: after TP2 the stop STAYS at entry (breakeven), not
trailed to TP1. A dip to TP1 does NOT terminate; only a return to ENTRY exits (PARTIAL_TP2_BE),
or TP3 (WIN), or expiry (PARTIAL_TP2). `run_tf_grid.check_outcome` defaults to "hold_entry" to
match the soaks; "trail_tp1" is kept as a retired reference (POSTTP2_STOP_COMPARISON).

Drives the canonical backtest exit logic (run_tf_grid.check_outcome + _calc_realized_r) with
synthetic paths covering EVERY case, asserting outcome LABEL + friction-inclusive realized_R.
Also: regression (LOSS/PARTIAL_TP1/PARTIAL_TP2/WIN unchanged), monotonic-up (SL->entry, stays),
the exact ATOM #38 shape, the KEY V_ENTRY behaviour (dip-to-TP1-only then TP3 = WIN), and
cross-engine parity (soak A, soak B, backtest identical) + tz-fix intact.

Run:  python3 -m pytest tests/test_breakout_exit_model.py -q
  or: python3 tests/test_breakout_exit_model.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_tf_grid import check_outcome, _calc_realized_r
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bar(h, l):
    return {"h": h, "l": l}


def _nets(direction, entry, sl, tp1, tp2, tp3, rt_pct):
    if direction == "BUY":
        g1 = (tp1 - entry) / entry * 100; g2 = (tp2 - entry) / entry * 100
        g3 = (tp3 - entry) / entry * 100; gs = (sl - entry) / entry * 100
    else:
        g1 = (entry - tp1) / entry * 100; g2 = (entry - tp2) / entry * 100
        g3 = (entry - tp3) / entry * 100; gs = (entry - sl) / entry * 100
    return (round(g1 - rt_pct, 3), round(g2 - rt_pct, 3),
            round(g3 - rt_pct, 3), round(gs - rt_pct, 2))


def _expected_r(outcome, n1, n2, n3, ns, rt):
    return _calc_realized_r(outcome, n1, ns, n2, n3, rt)


# ── XRP-standard geometry (BUY): entry 100, sl 99.5, tp1 101, tp2 101.5, tp3 102 ──
RT = 0.3
E, SL, T1, T2, T3 = 100.0, 99.5, 101.0, 101.5, 102.0
N1, N2, N3, NS = _nets("BUY", E, SL, T1, T2, T3, RT)   # 0.7, 1.2, 1.7, -0.8 ; risk 0.8

# Default mode = hold_entry (the live V_ENTRY model)
CASES = [
    ("a", "SL pre-TP1 -> LOSS", "BUY",
     [_bar(100.2, 99.4)], "LOSS"),
    ("b", "TP1 then back to entry (pre-TP2) -> PARTIAL_TP1", "BUY",
     [_bar(101.1, 100.0), _bar(100.5, 99.9)], "PARTIAL_TP1"),
    ("c", "TP1 -> TP2 -> back to ENTRY -> PARTIAL_TP2_BE (V_ENTRY)", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(100.5, 99.95)], "PARTIAL_TP2_BE"),
    ("d", "TP1 -> TP2 -> TP3 -> WIN", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(102.1, 101.6)], "WIN"),
    ("e", "TP1 -> TP2 -> dip to TP1-only, expire above entry -> PARTIAL_TP2", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(101.3, 100.9)], "PARTIAL_TP2"),
    ("f", "TP1 -> TP2 -> dip to TP1-only -> TP3 -> WIN  [KEY V_ENTRY behaviour]", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(101.3, 100.9), _bar(102.1, 101.5)], "WIN"),
    ("h", "TP2 bar dips between entry & TP1, expires above entry -> PARTIAL_TP2", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 100.5), _bar(101.3, 100.4)], "PARTIAL_TP2"),
    ("i", "TP2 (low>entry) then LATER return to entry -> PARTIAL_TP2_BE", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 100.5), _bar(101.2, 99.95)], "PARTIAL_TP2_BE"),
]

EXP_R = {o: _expected_r(o, N1, N2, N3, NS, RT)
         for o in ("LOSS", "PARTIAL_TP1", "PARTIAL_TP2_BE", "PARTIAL_TP2", "WIN")}


def test_all_exit_cases():
    rows = []
    for cid, label, d, bars, exp_out in CASES:
        out, tier = check_outcome(d, E, SL, T1, T2, T3, bars)   # default hold_entry
        r = _expected_r(out, N1, N2, N3, NS, RT)
        rows.append((cid, label, out, exp_out, r))
        assert out == exp_out, f"case {cid}: outcome {out} != expected {exp_out}"
    assert EXP_R["LOSS"] == -1.0
    assert EXP_R["PARTIAL_TP1"] == 0.25
    assert EXP_R["PARTIAL_TP2_BE"] == 0.25          # runner at breakeven = PARTIAL_TP1 R
    assert EXP_R["PARTIAL_TP2_BE"] == EXP_R["PARTIAL_TP1"]
    assert EXP_R["PARTIAL_TP2"] == 1.1875
    assert EXP_R["WIN"] == 1.5
    assert EXP_R["PARTIAL_TP2_BE"] < EXP_R["PARTIAL_TP2"] < EXP_R["WIN"]
    return rows


def test_sell_mirror():
    e, sl, t1, t2, t3 = 100.0, 100.5, 99.0, 98.5, 98.0
    # TP1 -> TP2 -> price rises back to ENTRY -> PARTIAL_TP2_BE
    bars = [_bar(99.5, 98.9), _bar(98.8, 98.4), _bar(100.05, 99.1)]
    out, _ = check_outcome("SELL", e, sl, t1, t2, t3, bars)
    assert out == "PARTIAL_TP2_BE", f"SELL V_ENTRY: {out}"
    # SL pre-TP1
    assert check_outcome("SELL", e, sl, t1, t2, t3, [_bar(100.6, 99.8)])[0] == "LOSS"


def test_atom_38_shape():
    # EXACT ATOM #38 geometry; TP1 -> TP2 -> dip to 1.86 (<= entry 1.865) -> entry stop.
    e, sl, t1, t2, t3 = 1.865, 1.851147, 1.892706, 1.906559, 1.920412
    bars = [_bar(1.8930, 1.8800), _bar(1.9080, 1.8950), _bar(1.8900, 1.8600)]
    out, tier = check_outcome("BUY", e, sl, t1, t2, t3, bars)
    assert out == "PARTIAL_TP2_BE", f"ATOM#38 should hold-at-entry stop, got {out}"
    rt = 0.4
    n1, n2, n3, ns = _nets("BUY", e, sl, t1, t2, t3, rt)
    r = _expected_r(out, n1, n2, n3, ns, rt)
    assert 0.25 < r < 0.40, f"ATOM#38 PARTIAL_TP2_BE R expected ~0.30, got {r}"
    return out, r


def test_monotonic_up_stop():
    # After TP2 the stop is at ENTRY (100). A dip to TP1-only (100.9, > entry) does NOT stop
    # -> rides on; reaching TP3 = WIN. The stop never sits above entry post-TP2.
    bars = [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(101.3, 100.9), _bar(102.1, 101.5)]
    assert check_outcome("BUY", E, SL, T1, T2, T3, bars)[0] == "WIN"
    # A dip all the way to entry -> PARTIAL_TP2_BE (stop at entry, never below)
    bars2 = [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(101.05, 100.0)]
    assert check_outcome("BUY", E, SL, T1, T2, T3, bars2)[0] == "PARTIAL_TP2_BE"
    # pre-TP2 touch of entry still books PARTIAL_TP1
    bars3 = [_bar(101.1, 100.6), _bar(100.9, 99.95)]
    assert check_outcome("BUY", E, SL, T1, T2, T3, bars3)[0] == "PARTIAL_TP1"


def test_regression_existing_tiers_unchanged():
    assert _expected_r("LOSS", N1, N2, N3, NS, RT) == -1.0
    assert _expected_r("PARTIAL_TP1", N1, N2, N3, NS, RT) == 0.25
    assert _expected_r("PARTIAL_TP2", N1, N2, N3, NS, RT) == 1.1875
    assert _expected_r("WIN", N1, N2, N3, NS, RT) == 1.5


def test_trail_tp1_retired_reference():
    # The retired trail_tp1 mode is still selectable (POSTTP2_STOP_COMPARISON reference):
    # TP1 -> TP2 -> dip to TP1 -> trail-stop at TP1 = PARTIAL_TP2_T1.
    bars = [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(101.3, 100.9)]
    assert check_outcome("BUY", E, SL, T1, T2, T3, bars, "trail_tp1")[0] == "PARTIAL_TP2_T1"
    # same path under the live default (hold_entry) does NOT stop at TP1 -> PARTIAL_TP2
    assert check_outcome("BUY", E, SL, T1, T2, T3, bars)[0] == "PARTIAL_TP2"
    assert _expected_r("PARTIAL_TP2_T1", N1, N2, N3, NS, RT) == 0.875


def test_cross_engine_parity_and_tzfix():
    soakA = open(os.path.join(ROOT, "breakout_paper_soak.py")).read()
    soakB = open(os.path.join(ROOT, "breakout_paper_soak_B.py")).read()
    grid = open(os.path.join(ROOT, "run_tf_grid.py")).read()
    # V_ENTRY hold-at-entry logic present in BOTH soaks (BUY + SELL) + label + R formula
    for src, name in [(soakA, "soakA"), (soakB, "soakB")]:
        assert "l_p <= entry: entry_stopped_post_tp2 = True; break" in src, f"{name} BUY hold-at-entry missing"
        assert "h_p >= entry: entry_stopped_post_tp2 = True; break" in src, f"{name} SELL hold-at-entry missing"
        assert "PARTIAL_TP2_BE" in src, f"{name} new tier label missing"
        assert "PARTIAL_TP2_T1" not in src, f"{name} retired trail tier still present"
        assert "0.5 * net_tp1 + 0.5 * (-rt_cost_pct)" in src, f"{name} BE R formula missing"
    # backtest engine: hold_entry default + matching logic
    assert 'post_tp2_mode: str = "hold_entry"' in grid, "backtest default not hold_entry"
    assert "entry_stopped_post_tp2 = True; break" in grid and "PARTIAL_TP2_BE" in grid
    # tz-fix intact (no deprecated CALL form)
    for src, name in [(soakA, "soakA"), (soakB, "soakB")]:
        assert "tzinfo=timezone.utc" in src, f"{name} tz-aware parse missing"
        assert "datetime.utcfromtimestamp(" not in src, f"{name} deprecated utcfromtimestamp call present"
    # BE-after-TP1 (post-TP1 entry stop, pre-TP2) still intact
    for src, name in [(soakA, "soakA"), (soakB, "soakB")]:
        assert "not be_stopped and l_p <= entry" in src, f"{name} BUY BE-after-TP1 missing"
        assert "not be_stopped and h_p >= entry" in src, f"{name} SELL BE-after-TP1 missing"


if __name__ == "__main__":
    print("=" * 78)
    print("POST-TP2 HOLD-AT-ENTRY (V_ENTRY) — exit-model unit verification (XRP geometry)")
    print(f"  net_tp1={N1} net_tp2={N2} net_tp3={N3} net_sl={NS} risk={abs(NS)}")
    print("=" * 78)
    rows = test_all_exit_cases()
    print(f"{'case':<5}{'description':<56}{'outcome':<16}{'R':>7}")
    for cid, label, out, exp_out, r in rows:
        print(f"{cid:<5}{label:<56}{out:<16}{r:>7.4f}")
    o, r = test_atom_38_shape()
    print(f"{'g':<5}{'ATOM #38 exact path (TP1->TP2->dip to entry)':<56}{o:<16}{r:>7.4f}")
    print("-" * 78)
    test_sell_mirror();                  print("  SELL mirror ........................... PASS")
    test_monotonic_up_stop();            print("  monotonic-up (SL->entry, stays) ....... PASS")
    test_regression_existing_tiers_unchanged(); print("  existing tiers R unchanged ............ PASS")
    test_trail_tp1_retired_reference();  print("  trail_tp1 retired-reference selectable  PASS")
    test_cross_engine_parity_and_tzfix();print("  cross-engine parity + tz-fix intact ... PASS")
    print("=" * 78)
    print("ALL EXIT-MODEL TESTS PASSED (V_ENTRY live model)")
