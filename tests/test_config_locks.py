"""Anti-pattern lock guards (audit L-E, 2026-05-24).

Several ICT constants are flagged in CLAUDE.md §7 as LOCKED — values that
historical data has *empirically proven* are anti-patterns and must never
be changed without a deliberate audit-loop:

  • ICT_SWING_N == 2
        Cycle 1b P-1 + Cycle 1c TP-5c' both showed >=3 swing-n causes
        −3.9pp WR / −0.07 Sharpe. Comment in ict_engine.py:24 documents
        the rollback. A future careless edit could silently revert.

  • ICT_MIN_RR_GATE == 1.5
        Cycle 1b showed >=2.0 produces catastrophic n=10 / WR=50%
        (close to coin-flip on a small sample). 1.5 is the empirical floor.

  • BACKTEST_DAYS == 365
        Cycle Z established that 730d windows pull 2024 dead-zone data
        that corrupts FVG=HIGH variant metrics. 365d is locked.

  • BACKTEST_FVG_MIN_QUALITY in {"HIGH"}
        TP-1 grid showed LOW/MEDIUM produces coin-flip WR (~44%).
        HIGH is the binding gate that produces the WR>70% basin.

  • _DEFAULT_BLOCKED_REGIMES contains "RANGING" + "TRENDING_BEAR" at minimum
        Removing either silently re-enables hostile-regime signals.

These are the SAME values asserted by autonomous_explorer._assert_anti_pattern_locks()
at session start — kept in sync so a static-CI lock catches drift that
would only otherwise be detected when the next explorer session starts.

If any of these tests fails, the change is presumed UNAUTHORIZED and the
CI build halts. Override only by:
  1. Running a full ICT audit cycle that re-validates the new value.
  2. Updating BOTH this test AND the docs/comprehensive/CROSS_REF.md
     anti-pattern record in the same PR.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ─── ICT constants (ict_engine.py) ────────────────────────────────────

def test_ict_swing_n_locked_at_2():
    """ICT_SWING_N >= 3 is a documented anti-pattern (Cycle 1b P-1, 1c TP-5c')."""
    from ict_engine import ICT_SWING_N
    assert ICT_SWING_N == 2, (
        f"ICT_SWING_N is locked at 2 — got {ICT_SWING_N}. "
        f"3+ is a documented anti-pattern (−3.9pp WR / −0.07 Sharpe). "
        f"Override only with a full audit cycle + CROSS_REF.md update."
    )


def test_ict_min_rr_gate_locked_at_1_3():
    """ICT_MIN_RR_GATE >= 2.0 is a documented anti-pattern (Cycle 1b: WR=50% n=10).

    Lowered 1.5 → 1.3 in cycle-9 (audit 2026-05-28) after H-NEW-3 SL clamp cut
    CRT signal output -77% (416 → 95). The 1.3 floor still rejects the proven
    catastrophic >=2.0 band while admitting the [1.3, 1.5) R:R signals that
    H-NEW-3's structural ceiling left on the table. Same anti-pattern rule;
    re-calibrated floor.
    """
    from ict_engine import ICT_MIN_RR_GATE
    assert ICT_MIN_RR_GATE == 1.3, (
        f"ICT_MIN_RR_GATE is locked at 1.3 — got {ICT_MIN_RR_GATE}. "
        f">=2.0 produces catastrophic n=10/WR=50%. "
        f"Override only with a full audit cycle + CROSS_REF.md update."
    )


def test_min_tp1_mult_preserved_for_5m_sweep_at_1_5():
    """MIN_TP1_MULT preserved at 1.5 for the 5M_SWEEP path's Run-168 baseline.

    Cycle-11 (audit 2026-05-28) deliberately diverged ICT_MIN_RR_GATE (1.3, CRT
    path) from MIN_TP1_MULT (1.5, 5M_SWEEP TP1 multiplier). They are NO LONGER
    the same constraint:
      • `ICT_MIN_RR_GATE` is the R:R reject gate consumed by `compute_crt_trade_economics`
        + `compute_ict_trade_plan`'s post-multiplier check.
      • `MIN_TP1_MULT` is the TP1 distance multiplier used by `compute_ict_trade_plan`
        to construct the 5M_SWEEP TP1 from the SL distance.
    For the 5M_SWEEP path, the effective floor is still 1.5 (the multiplier).
    For the CRT path, the effective floor is 1.3 (the gate).
    Operator's current Run-338 baseline runs CRT-only with ENABLE_5M_SWEEP=0,
    so the 5M_SWEEP floor is currently inert. If 5M_SWEEP is ever re-enabled,
    Run-168 was calibrated at 1.5 — do NOT change MIN_TP1_MULT without re-running
    the 5M_SWEEP Run-168 baseline backtest.
    """
    from ict_engine import MIN_TP1_MULT
    assert MIN_TP1_MULT == 1.5, (
        f"MIN_TP1_MULT is locked at 1.5 — got {MIN_TP1_MULT}. "
        f"Run-168 (5M_SWEEP canonical baseline) is calibrated at 1.5. "
        f"Drop only if explicitly re-baselining 5M_SWEEP."
    )


# ─── Backtest window (config.py) ──────────────────────────────────────

def test_backtest_days_locked_at_365():
    """BACKTEST_DAYS == 730 averages Cycle Z dead-zone — locked at 365.

    BACKTEST_DAYS lives in backtest.py (a backtest-only constant). To avoid
    importing the heavy backtest module at test time, we read the literal
    directly from the source. This is brittle by design — if someone moves
    the constant elsewhere they MUST also update this test.
    """
    import re
    backtest_py = (_ROOT / "backtest.py").read_text(encoding="utf-8")
    m = re.search(r"^BACKTEST_DAYS\s*=\s*(\d+)", backtest_py, flags=re.MULTILINE)
    assert m is not None, "BACKTEST_DAYS literal not found at module top-level in backtest.py"
    value = int(m.group(1))
    assert value == 365, (
        f"BACKTEST_DAYS is locked at 365 — got {value}. "
        f"730d averages 2024 dead-zone (Cycle Z). "
        f"Override only with a full audit cycle + CROSS_REF.md update."
    )


# ─── FVG quality binding gate ─────────────────────────────────────────

def test_backtest_fvg_min_quality_locked_at_high():
    """BACKTEST_FVG_MIN_QUALITY = LOW/MEDIUM produces coin-flip WR (~44%)."""
    from config import BACKTEST_FVG_MIN_QUALITY, LIVE_FVG_MIN_QUALITY
    assert BACKTEST_FVG_MIN_QUALITY == "HIGH", (
        f"BACKTEST_FVG_MIN_QUALITY is locked at HIGH — got {BACKTEST_FVG_MIN_QUALITY!r}. "
        f"TP-1 grid: LOW/MEDIUM → coin-flip ~44% WR. "
        f"HIGH is the binding gate producing the WR>70% basin."
    )
    assert LIVE_FVG_MIN_QUALITY == BACKTEST_FVG_MIN_QUALITY, (
        f"LIVE/BACKTEST FVG quality must match for parity — "
        f"LIVE={LIVE_FVG_MIN_QUALITY!r} BACKTEST={BACKTEST_FVG_MIN_QUALITY!r}"
    )


# ─── Hostile-regime block list ────────────────────────────────────────

def test_blocked_regimes_contain_chronic_losers():
    """_DEFAULT_BLOCKED_REGIMES must contain regimes empirically below BEW."""
    from config import _DEFAULT_BLOCKED_REGIMES
    required = {"RANGING", "TRENDING_BEAR", "CHOPPY", "HIGH_VOLATILITY",
                "LOW_VOLATILITY_CHOP", "LIQUIDATION"}
    missing = required - set(_DEFAULT_BLOCKED_REGIMES)
    assert not missing, (
        f"_DEFAULT_BLOCKED_REGIMES missing required regimes: {sorted(missing)}. "
        f"All listed regimes have historical evidence of below-BEW WR; "
        f"removing any of them silently re-enables hostile-regime signals."
    )


# ─── Rejected tokens stay rejected ────────────────────────────────────

@pytest.mark.parametrize("rejected_symbol", [
    "SOLUSDT",   # T-1 + T-2: WR=27-43%, chronic underperformer
    "DOTUSDT",   # D-pilot Run 169: WR=37.5%, drags overall -6.6pp
    "NEARUSDT",  # D-pilot Run 170: WR=11.1%, drags -11.8pp
    "SUIUSDT",   # B-2: 0% WR (n=3)
    "LTCUSDT",   # A-3: n=2 WR=50%, insufficient sample
])
def test_rejected_tokens_not_in_universe(rejected_symbol):
    """Re-adding a rejected token is an anti-pattern (CLAUDE.md §6)."""
    from config import BINANCE_TOKENS
    assert rejected_symbol not in BINANCE_TOKENS.values(), (
        f"{rejected_symbol} is in the rejected-tokens list (CLAUDE.md §6) "
        f"and must not be re-added. Re-evaluation requires an audit cycle "
        f"with CROSS_REF.md update + documented rationale."
    )


# ─── Sync with autonomous_explorer's runtime assertion ────────────────

def test_explorer_anti_pattern_locks_match_constants():
    """The dict in autonomous_explorer.ANTI_PATTERN_LOCKS must match this test's expectations."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    from autonomous_explorer import ANTI_PATTERN_LOCKS
    from ict_engine import ICT_SWING_N, ICT_MIN_RR_GATE

    assert ANTI_PATTERN_LOCKS["ICT_SWING_N"] == ICT_SWING_N, (
        f"autonomous_explorer.ANTI_PATTERN_LOCKS['ICT_SWING_N'] "
        f"({ANTI_PATTERN_LOCKS['ICT_SWING_N']}) "
        f"diverges from ict_engine.ICT_SWING_N ({ICT_SWING_N})."
    )
    assert ANTI_PATTERN_LOCKS["ICT_MIN_RR_GATE"] == ICT_MIN_RR_GATE, (
        f"autonomous_explorer.ANTI_PATTERN_LOCKS['ICT_MIN_RR_GATE'] "
        f"({ANTI_PATTERN_LOCKS['ICT_MIN_RR_GATE']}) "
        f"diverges from ict_engine.ICT_MIN_RR_GATE ({ICT_MIN_RR_GATE})."
    )
