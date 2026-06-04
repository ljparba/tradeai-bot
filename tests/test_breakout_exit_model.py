"""test_breakout_exit_model.py — POST-TP2 TRAIL FIX (2026-06-04) verification.

Drives the canonical backtest exit logic (run_tf_grid.check_outcome +
_calc_realized_r) with synthetic bar paths covering EVERY exit case, asserting both
the outcome LABEL and the friction-inclusive realized_R. Also:
  - regression: the pre-existing tiers (LOSS / PARTIAL_TP1 / PARTIAL_TP2 / WIN) are
    byte-unchanged in R.
  - monotonic-up: the protective stop only ever moves up (SL -> entry -> TP1).
  - the exact ATOM #38 shape (TP1 -> TP2 -> dip below TP1) now resolves PARTIAL_TP2_T1.
  - parity: soak A, soak B, and the backtest contain identical trail logic; tz-fix intact.

Run:  python3 -m pytest tests/test_breakout_exit_model.py -q
  or: python3 tests/test_breakout_exit_model.py   (prints the full result table)
"""
import os, re, sys
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
RT = 0.3                       # XRP rt_cost_pct (0.3%)
E, SL, T1, T2, T3 = 100.0, 99.5, 101.0, 101.5, 102.0
N1, N2, N3, NS = _nets("BUY", E, SL, T1, T2, T3, RT)   # 0.7, 1.2, 1.7, -0.8 ; risk 0.8

CASES = [
    # id, label, direction, bars, expected_outcome
    ("a", "SL pre-TP1 -> LOSS", "BUY",
     [_bar(100.2, 99.4)], "LOSS"),
    ("b", "TP1 then back to entry (pre-TP2) -> PARTIAL_TP1", "BUY",
     [_bar(101.1, 100.0), _bar(100.5, 99.9)], "PARTIAL_TP1"),
    ("c", "TP1 -> TP2 -> back to TP1 -> PARTIAL_TP2_T1 (NEW)", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(101.3, 100.9)], "PARTIAL_TP2_T1"),
    ("d", "TP1 -> TP2 -> TP3 -> WIN", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(102.1, 101.6)], "WIN"),
    ("e", "TP1 -> TP2 -> expire above TP1 -> PARTIAL_TP2", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(101.4, 101.1)], "PARTIAL_TP2"),
    ("f", "TP1 -> TP2 (wick near TP1, not hit) -> TP3 -> WIN", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 101.05), _bar(102.1, 101.5)], "WIN"),
    ("h", "strong TP2 bar (low<TP1 same bar) NOT trail-stopped -> PARTIAL_TP2", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 100.7), _bar(101.3, 101.05)], "PARTIAL_TP2"),
    ("i", "strong TP2 bar then LATER retrace to TP1 -> PARTIAL_TP2_T1", "BUY",
     [_bar(101.1, 100.5), _bar(101.6, 100.7), _bar(101.2, 100.95)], "PARTIAL_TP2_T1"),
]

# Expected R per outcome under XRP geometry (computed from the canonical formula)
EXP_R = {o: _expected_r(o, N1, N2, N3, NS, RT)
         for o in ("LOSS", "PARTIAL_TP1", "PARTIAL_TP2_T1", "PARTIAL_TP2", "WIN")}


def test_all_exit_cases():
    rows = []
    for cid, label, d, bars, exp_out in CASES:
        out, tier = check_outcome(d, E, SL, T1, T2, T3, bars)
        r = _expected_r(out, N1, N2, N3, NS, RT)
        rows.append((cid, label, out, exp_out, r))
        assert out == exp_out, f"case {cid}: outcome {out} != expected {exp_out}"
    # tier-R sanity for the explicit tiers
    assert EXP_R["LOSS"] == -1.0
    assert EXP_R["PARTIAL_TP1"] == 0.25
    assert EXP_R["PARTIAL_TP2_T1"] == 0.875
    assert EXP_R["PARTIAL_TP2"] == 1.1875
    assert EXP_R["WIN"] == 1.5
    # ordering: TP1-trail sits strictly between BE and full TP2 lock
    assert EXP_R["PARTIAL_TP1"] < EXP_R["PARTIAL_TP2_T1"] < EXP_R["PARTIAL_TP2"] < EXP_R["WIN"]
    return rows


def test_sell_mirror():
    # SELL geometry: entry 100, sl 100.5, tp1 99, tp2 98.5, tp3 98
    e, sl, t1, t2, t3 = 100.0, 100.5, 99.0, 98.5, 98.0
    # TP1 -> TP2 -> price rises back to TP1 -> PARTIAL_TP2_T1
    bars = [_bar(99.5, 98.9), _bar(98.8, 98.4), _bar(99.1, 98.7)]
    out, _ = check_outcome("SELL", e, sl, t1, t2, t3, bars)
    assert out == "PARTIAL_TP2_T1", f"SELL trail: {out}"
    # SL pre-TP1
    out2, _ = check_outcome("SELL", e, sl, t1, t2, t3, [_bar(100.6, 99.8)])
    assert out2 == "LOSS"


def test_atom_38_shape():
    # EXACT ATOM #38 geometry; path: TP1 hit, TP2 hit, then dip below TP1.
    e, sl, t1, t2, t3 = 1.865, 1.851147, 1.892706, 1.906559, 1.920412
    bars = [
        _bar(1.8930, 1.8800),   # TP1 hit (high>=1.892706)
        _bar(1.9080, 1.8950),   # TP2 hit (high>=1.906559), low above TP1
        _bar(1.8900, 1.8600),   # dip: low 1.86 <= TP1 1.892706 -> trail stop
    ]
    out, tier = check_outcome("BUY", e, sl, t1, t2, t3, bars)
    assert out == "PARTIAL_TP2_T1", f"ATOM#38 should trail-stop at TP1, got {out}"
    rt = 0.4  # ATOM rt_cost_pct
    n1, n2, n3, ns = _nets("BUY", e, sl, t1, t2, t3, rt)
    r = _expected_r(out, n1, n2, n3, ns, rt)
    assert 0.90 < r < 1.00, f"ATOM#38 R expected ~0.95, got {r}"
    return out, r


def test_monotonic_up_stop():
    # After TP2, price dips toward entry. The TP1-trail (101) is ABOVE entry (100),
    # so a downward move hits the TP1 trail FIRST -> PARTIAL_TP2_T1, never PARTIAL_TP1.
    bars = [_bar(101.1, 100.5), _bar(101.6, 101.2), _bar(101.05, 100.0)]
    out, _ = check_outcome("BUY", E, SL, T1, T2, T3, bars)
    assert out == "PARTIAL_TP2_T1", f"stop must be at TP1 post-TP2, got {out}"
    # And a path that touches entry only AFTER TP1 (pre-TP2) still books PARTIAL_TP1
    bars2 = [_bar(101.1, 100.6), _bar(100.9, 99.95)]
    out2, _ = check_outcome("BUY", E, SL, T1, T2, T3, bars2)
    assert out2 == "PARTIAL_TP1"


def test_regression_existing_tiers_unchanged():
    # Existing tier R values must be byte-identical to the pre-trail model.
    assert _expected_r("LOSS", N1, N2, N3, NS, RT) == -1.0
    assert _expected_r("PARTIAL_TP1", N1, N2, N3, NS, RT) == 0.25
    assert _expected_r("PARTIAL_TP2", N1, N2, N3, NS, RT) == 1.1875
    assert _expected_r("WIN", N1, N2, N3, NS, RT) == 1.5


def test_cross_engine_parity_and_tzfix():
    soakA = open(os.path.join(ROOT, "breakout_paper_soak.py")).read()
    soakB = open(os.path.join(ROOT, "breakout_paper_soak_B.py")).read()
    grid = open(os.path.join(ROOT, "run_tf_grid.py")).read()
    # trail logic present in all three (BUY + SELL)
    for src, name in [(soakA, "soakA"), (soakB, "soakB")]:
        assert "l_p <= tp1: t1_trail_stopped = True; break" in src, f"{name} BUY trail missing"
        assert "h_p >= tp1: t1_trail_stopped = True; break" in src, f"{name} SELL trail missing"
        assert 'outcome' in src and "PARTIAL_TP2_T1" in src, f"{name} new tier label missing"
        assert "0.5 * net_tp1 + 0.5 * net_tp1" in src, f"{name} trail R formula missing"
    assert "l <= tp1:" in grid and "t1_trail_stopped = True; break" in grid
    assert "0.5 * net_tp1 + 0.5 * net_tp1" in grid, "backtest trail R formula missing"
    # tz-fix intact (UTC-aware parse, no deprecated utcfromtimestamp)
    for src, name in [(soakA, "soakA"), (soakB, "soakB")]:
        assert "tzinfo=timezone.utc" in src, f"{name} tz-aware parse missing"
        # the deprecated CALL form must be gone (the string may remain only in the F3-FIX comment)
        assert "datetime.utcfromtimestamp(" not in src, f"{name} deprecated utcfromtimestamp call present"
    # BE-after-TP1 (post-TP1 entry stop) still intact
    for src, name in [(soakA, "soakA"), (soakB, "soakB")]:
        assert "not be_stopped and l_p <= entry" in src, f"{name} BUY BE-after-TP1 missing"
        assert "not be_stopped and h_p >= entry" in src, f"{name} SELL BE-after-TP1 missing"


if __name__ == "__main__":
    print("=" * 74)
    print("POST-TP2 TRAIL FIX — exit-model unit verification (XRP geometry)")
    print(f"  net_tp1={N1} net_tp2={N2} net_tp3={N3} net_sl={NS} risk={abs(NS)}")
    print("=" * 74)
    rows = test_all_exit_cases()
    print(f"{'case':<5}{'description':<48}{'outcome':<16}{'R':>7}")
    for cid, label, out, exp_out, r in rows:
        print(f"{cid:<5}{label:<48}{out:<16}{r:>7.4f}")
    o, r = test_atom_38_shape()
    print(f"{'g':<5}{'ATOM #38 exact path (TP1->TP2->dip<TP1)':<48}{o:<16}{r:>7.4f}")
    print("-" * 74)
    test_sell_mirror();                  print("  SELL mirror ......................... PASS")
    test_monotonic_up_stop();            print("  monotonic-up stop (SL->entry->TP1) .. PASS")
    test_regression_existing_tiers_unchanged(); print("  existing tiers R unchanged .......... PASS")
    test_cross_engine_parity_and_tzfix();print("  cross-engine parity + tz-fix intact . PASS")
    print("=" * 74)
    print("ALL EXIT-MODEL TESTS PASSED")
