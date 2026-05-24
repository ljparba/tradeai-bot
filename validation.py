"""
TradeAI — Honest-Metrics Validation Suite
==========================================
Roadmap reference:
  • Top-10 #5 / Phase A item #2-complete of docs/ENTERPRISE_ROADMAP.md
  • Sprint 3 item 4.

Replaces the simple walk-forward IS/OOS split (which produces a single point
estimate easy to overfit to) with two honest statistical tools:

  1. Combinatorial Purged K-Fold Cross-Validation (CPCV)
     Lopez de Prado, "Advances in Financial Machine Learning" (2018), Ch. 7.
     Generates many disjoint test sets from the full sample, with purging
     (remove training events whose label window overlaps test events) and
     embargo (gap between test end and resumed training) so leakage cannot
     inflate test performance.

  2. Deflated Sharpe Ratio (DSR)
     Bailey & López de Prado, "The Deflated Sharpe Ratio" (J. Portfolio
     Management 40(5), 2014). Adjusts the observed Sharpe ratio for
     multiple-testing selection bias plus non-normality (skew, kurtosis).

Why this module exists
----------------------
Run-93 reported WR=76.2% from a SINGLE WF split. With ~93 total backtest
runs over the project life and ~50 trades per run, the probability that the
best-of-93 result is a spurious overfit is non-trivial. CPCV + DSR give an
honest answer to "does this strategy still look profitable after we
account for everything we tried?"

Hard invariants
---------------
  • No mlfinlab dependency. All formulas implemented from the primary
    literature using stdlib + (optional) numpy for vectorisation.
  • No network calls.
  • Read-only — never writes to the DB. Operates on in-memory signal dicts
    passed in by the caller.
  • Pure functions where possible — the index generator is a generator,
    the metric functions are stateless.

Mapping to TradeAI signal dicts
-------------------------------
The signal dicts used in backtest.py carry these keys we care about:

    {
      "ts":         "YYYY-MM-DD HH:MM:SS",   # entry timestamp (UTC)
      "outcome":    "WIN"|"LOSS"|"PARTIAL_TP1"|"PARTIAL_TP2"|"EXPIRED"|...,
      "closed_at":  "YYYY-MM-DD HH:MM:SS",   # exit timestamp (or None)
      ... per-signal metrics (net_tp1_pct, net_sl_pct, ...)
    }

The CPCV index generator uses `ts` for the event start time and `closed_at`
(or a fallback horizon) for the event end — these define the label window
that must be purged from training.

Public API
----------
  combinatorial_purged_kfold(...)  → yields (train_idx, test_idx)
  expected_max_sharpe(...)         → E[max SR] under null SR=0
  probabilistic_sharpe_ratio(...)  → PSR
  deflated_sharpe_ratio(...)       → DSR
  cpcv_summary(signals, ...)       → full CPCV WR / Sharpe / DSR report
  cpcv_text_report(summary)        → human-readable text dump
"""
from __future__ import annotations

import itertools
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

# Standard normal CDF and inverse CDF (stdlib, Python ≥ 3.8)
_norm = statistics.NormalDist()
_phi      = _norm.cdf       # Φ(z) — standard normal CDF
_phi_inv  = _norm.inv_cdf   # Φ⁻¹(p) — inverse standard normal CDF

# Euler-Mascheroni constant (used in E[max SR] under Gumbel approx)
_EULER_GAMMA = 0.5772156649015329

# Sentinels and defaults
_DEFAULT_N_GROUPS      = 5     # K — calibrated for ~40-50 signal samples (∼8 per group)
_DEFAULT_N_TEST_GROUPS = 2     # k — test set per split = 2 groups (∼16 signals)
_DEFAULT_EMBARGO_FRAC  = 0.02  # 2% of sample length as embargo gap


# ══════════════════════════════════════════════════════════════════════════════
# 1) CPCV — Combinatorial Purged K-Fold
# ══════════════════════════════════════════════════════════════════════════════

def _split_into_groups(n: int, n_groups: int) -> List[List[int]]:
    """Partition indices 0..n-1 into `n_groups` contiguous groups (time-ordered).

    Group sizes are balanced — earlier groups get the extra element when n
    does not divide evenly. Caller must pre-sort indices by time.
    """
    if n <= 0 or n_groups <= 0:
        return []
    if n_groups > n:
        # Degenerate: more groups than samples — one sample per group, rest empty
        return [[i] for i in range(n)]
    base, extra = divmod(n, n_groups)
    groups: List[List[int]] = []
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)
        groups.append(list(range(start, start + size)))
        start += size
    return groups


def _purge_train_indices(train_idx: List[int],
                         test_idx: List[int],
                         t0: Sequence[float],
                         t1: Sequence[float]) -> List[int]:
    """Drop training indices whose label window [t0, t1] overlaps any test event.

    Standard purging from Lopez de Prado AFML §7.4. Two events overlap if
    their [t0, t1] intervals intersect.
    """
    if not test_idx:
        return list(train_idx)
    # Test event time spans
    test_intervals = [(t0[i], t1[i]) for i in test_idx]
    keep: List[int] = []
    for i in train_idx:
        a0, a1 = t0[i], t1[i]
        overlap = False
        for (b0, b1) in test_intervals:
            # Two intervals [a0,a1] and [b0,b1] overlap iff a0 <= b1 AND b0 <= a1
            if a0 <= b1 and b0 <= a1:
                overlap = True
                break
        if not overlap:
            keep.append(i)
    return keep


def _apply_embargo(train_idx: List[int],
                   test_idx: List[int],
                   t0: Sequence[float],
                   embargo_pct: float) -> List[int]:
    """Remove training samples within `embargo_pct` of total time-span after
    each contiguous test block. Prevents serial-dependence leakage when
    label windows are shorter than the natural autocorrelation horizon.
    """
    if not test_idx or embargo_pct <= 0:
        return list(train_idx)
    span = max(t0) - min(t0) if t0 else 0.0
    if span <= 0:
        return list(train_idx)
    embargo_dt = embargo_pct * span

    # Find contiguous test blocks (by index, after sorting)
    sorted_test = sorted(test_idx)
    blocks: List[Tuple[int, int]] = []
    block_start = sorted_test[0]
    block_end = sorted_test[0]
    for i in sorted_test[1:]:
        if i == block_end + 1:
            block_end = i
        else:
            blocks.append((block_start, block_end))
            block_start = i
            block_end = i
    blocks.append((block_start, block_end))

    # For each block, exclude any training event whose t0 falls within
    # [t0_at_block_end, t0_at_block_end + embargo_dt]
    forbidden_windows: List[Tuple[float, float]] = [
        (t0[b_end], t0[b_end] + embargo_dt) for (_, b_end) in blocks
    ]
    keep: List[int] = []
    for i in train_idx:
        in_forbidden = any(lo < t0[i] <= hi for (lo, hi) in forbidden_windows)
        if not in_forbidden:
            keep.append(i)
    return keep


def combinatorial_purged_kfold(
    n: int,
    *,
    n_groups: int = _DEFAULT_N_GROUPS,
    n_test_groups: int = _DEFAULT_N_TEST_GROUPS,
    t0: Optional[Sequence[float]] = None,
    t1: Optional[Sequence[float]] = None,
    embargo_pct: float = _DEFAULT_EMBARGO_FRAC,
) -> Iterator[Tuple[List[int], List[int]]]:
    """Yield (train_idx, test_idx) for every combination of n_test_groups
    out of n_groups, with purging and embargo applied.

    Parameters
    ----------
    n              total number of events (assumed pre-sorted by time)
    n_groups       K — total partition count (typical 5-10)
    n_test_groups  k — groups used as test per split (typical 2)
    t0, t1         optional event start/end times (any numeric). If both
                   provided, training events overlapping any test event's
                   label window are purged. If omitted, no purging is
                   performed — use this only when label windows are
                   guaranteed non-overlapping (rare in practice).
    embargo_pct    fraction of total span to embargo after each test block.

    Yields
    ------
    (train_idx, test_idx) — each a list of integer indices into the
    original 0..n-1 range.

    Number of splits = C(n_groups, n_test_groups).
    """
    if n < n_groups:
        # Too few samples — fall back to a single 60/40 train/test split.
        cut = max(1, int(n * 0.6))
        train_idx = list(range(cut))
        test_idx  = list(range(cut, n))
        if t0 is not None and t1 is not None:
            train_idx = _purge_train_indices(train_idx, test_idx, t0, t1)
            train_idx = _apply_embargo(train_idx, test_idx, t0, embargo_pct)
        yield train_idx, test_idx
        return

    groups = _split_into_groups(n, n_groups)
    if not groups or n_test_groups > n_groups:
        return

    for test_combo in itertools.combinations(range(n_groups), n_test_groups):
        test_idx: List[int] = []
        for g in test_combo:
            test_idx.extend(groups[g])
        train_idx: List[int] = []
        for g in range(n_groups):
            if g not in test_combo:
                train_idx.extend(groups[g])
        if t0 is not None and t1 is not None:
            train_idx = _purge_train_indices(train_idx, test_idx, t0, t1)
            train_idx = _apply_embargo(train_idx, test_idx, t0, embargo_pct)
        yield sorted(train_idx), sorted(test_idx)


# ══════════════════════════════════════════════════════════════════════════════
# 2) Probabilistic / Deflated Sharpe Ratio
# ══════════════════════════════════════════════════════════════════════════════

def _safe_std(values: Sequence[float]) -> float:
    """Sample std with n-1 ddof. Returns 0.0 for len < 2."""
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(max(0.0, var))


def _moments(values: Sequence[float]) -> Tuple[float, float, float, float]:
    """Return (mean, std, skew, kurt) of values. kurt is Pearson (normal=3).
    Returns zeros for degenerate inputs."""
    n = len(values)
    if n < 2:
        return 0.0, 0.0, 0.0, 3.0
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / n   # population variance for moments
    if var <= 0:
        return m, 0.0, 0.0, 3.0
    std = math.sqrt(var)
    skew = sum((v - m) ** 3 for v in values) / (n * std ** 3) if std > 0 else 0.0
    kurt = sum((v - m) ** 4 for v in values) / (n * std ** 4) if std > 0 else 3.0
    # Sample std (n-1) for downstream Sharpe; moments use population std
    sample_std = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    return m, sample_std, skew, kurt


def sharpe_ratio(returns: Sequence[float], periods_per_year: float = 1.0
                 ) -> float:
    """Sharpe ratio = mean(returns) / std(returns) × sqrt(periods_per_year).

    For per-trade Sharpe (no annualisation), pass periods_per_year=1.
    For daily returns annualised, pass periods_per_year=252.
    Returns 0 if std == 0 or n < 2.

    Numeric guard: the textbook variance formula loses precision when all
    inputs are identical (e.g. [0.05, 0.05, 0.05] produces std ≈ 1e-17 from
    accumulated rounding). Any std below 1e-12 is treated as zero — the
    smallest realistic per-trade return is ~1e-6 (0.0001%) and a meaningful
    Sharpe needs std at least one order of magnitude above that.
    """
    if len(returns) < 2:
        return 0.0
    m = sum(returns) / len(returns)
    s = _safe_std(returns)
    if s <= 1e-12:
        return 0.0
    return (m / s) * math.sqrt(periods_per_year)


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """E[max SR] under null SR=0 across N independent trials.

    Gumbel-based approximation from Bailey & López de Prado (2014), eq. 6:

        E[max SR] ≈ sr_std × ( (1-γ)·Z⁻¹(1 - 1/N)
                              + γ·Z⁻¹(1 - 1/(N·e)) )

    where γ ≈ 0.5772 is the Euler-Mascheroni constant.

    Returns 0 for n_trials ≤ 1 or sr_std ≤ 0.
    """
    if n_trials <= 1 or sr_std <= 0:
        return 0.0
    # Guard the inverse CDF against p exactly 1.0
    p_a = 1.0 - 1.0 / n_trials
    p_b = 1.0 - 1.0 / (n_trials * math.e)
    p_a = min(max(p_a, 1e-12), 1 - 1e-12)
    p_b = min(max(p_b, 1e-12), 1 - 1e-12)
    z_a = _phi_inv(p_a)
    z_b = _phi_inv(p_b)
    return sr_std * ((1.0 - _EULER_GAMMA) * z_a + _EULER_GAMMA * z_b)


def probabilistic_sharpe_ratio(
    sr_observed: float,
    n_returns: int,
    *,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    sr_benchmark: float = 0.0,
) -> float:
    """PSR = Φ( (SR* - SR_bench) × √(T-1) /
                √(1 - skew·SR* + (kurt-1)/4 · SR*²) )

    From Bailey & López de Prado (2012, 2014). Returns probability in [0,1].
    Returns 0.5 (no info) on degenerate inputs.
    """
    if n_returns < 2:
        return 0.5
    excess = sr_observed - sr_benchmark
    denom_sq = 1.0 - skew * sr_observed + ((kurtosis - 1.0) / 4.0) * sr_observed ** 2
    if denom_sq <= 0:
        # Non-normality correction blows up — fall back to plain z-test
        denom_sq = 1.0
    z = excess * math.sqrt(n_returns - 1) / math.sqrt(denom_sq)
    return _phi(z)


def deflated_sharpe_ratio(
    sr_observed: float,
    n_returns: int,
    n_trials: int,
    sr_trial_std: float,
    *,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """DSR = PSR with sr_benchmark = E[max SR | null, n_trials].

    Returns probability in [0,1] that the observed SR exceeds what we would
    expect as the maximum of n_trials independent SR=0 trials.

    Decision rule: DSR > 0.95 → survives multiple-testing inflation at 5%.
    """
    bench = expected_max_sharpe(n_trials, sr_trial_std)
    return probabilistic_sharpe_ratio(
        sr_observed=sr_observed,
        n_returns=n_returns,
        skew=skew,
        kurtosis=kurtosis,
        sr_benchmark=bench,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3) Top-level CPCV summary on a signal list
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CPCVSplitMetrics:
    n_train: int
    n_test: int
    train_wr: float
    test_wr: float
    test_sharpe: float
    test_realized_pnl_mean: float


def _ts_to_epoch(ts: str) -> float:
    """Parse 'YYYY-MM-DD HH:MM:SS' → epoch seconds. Falls back to hash on
    parse failure so the function is total."""
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()
    except (ValueError, TypeError):
        return 0.0


def _default_outcome_to_pnl(s: dict) -> float:
    """Default scorer when caller does not supply one. Mirrors backtest.py's
    `_realized_pnl_pct()` semantics in a self-contained form so this module
    stays decoupled from backtest.py."""
    outcome = s.get("outcome", "")
    n_tp1 = s.get("net_tp1_pct", 0.0) or 0.0
    n_sl  = s.get("net_sl_pct",  0.0) or 0.0
    n_tp2 = s.get("net_tp2_pct")
    n_tp3 = s.get("net_tp3_pct")
    if outcome == "LOSS":
        return n_sl
    if outcome == "PARTIAL_TP1":
        return 0.5 * n_tp1
    if outcome == "PARTIAL_TP2":
        return 0.5 * n_tp1 + 0.5 * (n_tp2 if n_tp2 is not None else n_tp1)
    if outcome == "WIN":
        return 0.5 * n_tp1 + 0.5 * (n_tp3 if n_tp3 is not None else n_tp1)
    return 0.0  # EXPIRED / NO_FILL / unknown


def _default_is_win(s: dict) -> bool:
    return s.get("outcome", "") in ("WIN", "PARTIAL_TP1", "PARTIAL_TP2")


def cpcv_summary(
    signals: Sequence[dict],
    *,
    n_groups: int = _DEFAULT_N_GROUPS,
    n_test_groups: int = _DEFAULT_N_TEST_GROUPS,
    embargo_pct: float = _DEFAULT_EMBARGO_FRAC,
    is_win_func: Callable[[dict], bool] = _default_is_win,
    pnl_func: Callable[[dict], float] = _default_outcome_to_pnl,
    n_trials_for_dsr: Optional[int] = None,
    sr_trial_std_for_dsr: Optional[float] = None,
) -> Dict[str, Any]:
    """Run CPCV over a list of signal dicts and return aggregated metrics.

    Parameters
    ----------
    signals               list of dicts with 'ts', 'outcome', and the PnL keys
                          required by `pnl_func` (default mirrors backtest.py).
    n_groups              K — partition count.
    n_test_groups         k — test groups per split.
    embargo_pct           embargo as fraction of total time span.
    is_win_func           custom win-classifier (default: WIN/PARTIAL_TP1/TP2).
    pnl_func              custom PnL extractor (default: split-exit realised %).
    n_trials_for_dsr      number of historical backtest variants tested across
                          the whole project (Run-history count). If None,
                          DSR is skipped and only PSR is reported.
    sr_trial_std_for_dsr  std of trial Sharpes across the run history. If None
                          and n_trials_for_dsr is provided, std is estimated
                          from the CPCV per-split Sharpe distribution.
                          WARNING (per backtest-bias-detector audit, Fix #2):
                          this proxy is ANTI-CONSERVATIVE (optimistic). Real
                          trial-Sharpe variance across N different parameter
                          configs is larger than within-run fold variance of
                          the same parameters → real E[max SR] is HIGHER →
                          real DSR is LOWER than what this proxy returns.
                          Always supply the real trial std when known. The
                          report flags use of the proxy explicitly.

    Returns
    -------
    Dict with:
      n_signals               total signals
      n_splits                C(n_groups, n_test_groups)
      n_groups, n_test_groups echoed for reproducibility
      embargo_pct             echoed
      wr_per_split            list of test-set WR per split (%)
      wr_mean / wr_std        across splits
      wr_q05 / wr_q50 / wr_q95 percentiles across splits
      sharpe_per_split        list of test-set Sharpe per split
      sharpe_mean / std       across splits
      psr                     Probabilistic Sharpe vs SR=0 (whole-sample)
      dsr                     Deflated Sharpe (if n_trials_for_dsr supplied)
      dsr_bench_sharpe        E[max SR] used as DSR benchmark (if computed)
      verdict                 "PASS" / "MARGINAL" / "FAIL" against Phase A
                              exit criteria (WR≥58% mean across CPCV splits)
    """
    n = len(signals)
    out: Dict[str, Any] = {
        "n_signals":     n,
        "n_groups":      n_groups,
        "n_test_groups": n_test_groups,
        "embargo_pct":   embargo_pct,
        "n_splits":      0,
        "wr_per_split":     [],
        "sharpe_per_split": [],
        "splits":           [],
    }
    if n == 0:
        out.update({
            "wr_mean": 0.0, "wr_std": 0.0,
            "wr_q05": 0.0, "wr_q50": 0.0, "wr_q95": 0.0,
            "sharpe_mean": 0.0, "sharpe_std": 0.0,
            "psr": 0.5, "dsr": None, "dsr_bench_sharpe": None,
            "verdict": "INSUFFICIENT_SAMPLE",
        })
        return out

    # Sort signals by entry time so groups are contiguous in time.
    sorted_sigs = sorted(signals, key=lambda s: s.get("ts", ""))
    t0 = [_ts_to_epoch(s.get("ts", "")) for s in sorted_sigs]
    t1 = [_ts_to_epoch(s.get("closed_at") or s.get("ts", ""))
          for s in sorted_sigs]
    # Label-window fallback (Fix #6 per backtest-bias-detector audit):
    # When closed_at is missing, defaulting t1 = t0 produces a zero-length label
    # window that NEVER overlaps any test event → purging is silently disabled
    # for that signal. Instead, default to the median observed label duration so
    # signals without close timestamps still get purged honestly.
    valid_durations = [t1[i] - t0[i] for i in range(n) if t1[i] > t0[i]]
    if valid_durations:
        valid_durations.sort()
        median_horizon = valid_durations[len(valid_durations) // 2]
    else:
        # No closed_at in any signal — assume 24h horizon as a conservative
        # default (most ICT setups resolve within a session/day).
        median_horizon = 24 * 3600.0
    for i in range(n):
        if t1[i] <= t0[i]:
            t1[i] = t0[i] + median_horizon

    wr_list:    List[float] = []
    sr_list:    List[float] = []
    pnl_pool:   List[float] = [pnl_func(s) for s in sorted_sigs]
    splits_meta: List[CPCVSplitMetrics] = []

    for train_idx, test_idx in combinatorial_purged_kfold(
        n,
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        t0=t0, t1=t1,
        embargo_pct=embargo_pct,
    ):
        out["n_splits"] += 1
        train_sigs = [sorted_sigs[i] for i in train_idx]
        test_sigs  = [sorted_sigs[i] for i in test_idx]

        train_wins = sum(1 for s in train_sigs if is_win_func(s))
        train_wr   = (train_wins / len(train_sigs) * 100.0) if train_sigs else 0.0

        test_wins  = sum(1 for s in test_sigs if is_win_func(s))
        test_wr    = (test_wins / len(test_sigs) * 100.0) if test_sigs else 0.0

        test_pnls  = [pnl_pool[i] for i in test_idx]
        test_sr    = sharpe_ratio(test_pnls, periods_per_year=1.0)
        test_mean  = sum(test_pnls) / len(test_pnls) if test_pnls else 0.0

        wr_list.append(test_wr)
        sr_list.append(test_sr)
        splits_meta.append(CPCVSplitMetrics(
            n_train=len(train_sigs),
            n_test=len(test_sigs),
            train_wr=train_wr,
            test_wr=test_wr,
            test_sharpe=test_sr,
            test_realized_pnl_mean=test_mean,
        ))

    out["wr_per_split"]     = wr_list
    out["sharpe_per_split"] = sr_list
    out["splits"]           = [vars(m) for m in splits_meta]

    if wr_list:
        out["wr_mean"] = sum(wr_list) / len(wr_list)
        out["wr_std"]  = _safe_std(wr_list)
        sorted_wr = sorted(wr_list)
        out["wr_q05"] = sorted_wr[max(0, int(0.05 * len(sorted_wr)))]
        out["wr_q50"] = sorted_wr[len(sorted_wr) // 2]
        out["wr_q95"] = sorted_wr[min(len(sorted_wr) - 1, int(0.95 * len(sorted_wr)))]
    else:
        out["wr_mean"] = out["wr_std"] = 0.0
        out["wr_q05"] = out["wr_q50"] = out["wr_q95"] = 0.0

    if sr_list:
        out["sharpe_mean"] = sum(sr_list) / len(sr_list)
        out["sharpe_std"]  = _safe_std(sr_list)
    else:
        out["sharpe_mean"] = out["sharpe_std"] = 0.0

    # Whole-sample PSR using overall trade PnLs (IN-SAMPLE — informational)
    _mean, _std, _skew, _kurt = _moments(pnl_pool)
    overall_sr = sharpe_ratio(pnl_pool)
    out["overall_sharpe"] = overall_sr
    out["overall_skew"]   = _skew
    out["overall_kurt"]   = _kurt
    out["psr_is"] = probabilistic_sharpe_ratio(
        sr_observed=overall_sr,
        n_returns=len(pnl_pool),
        skew=_skew,
        kurtosis=_kurt,
        sr_benchmark=0.0,
    )

    # Fix #5 per backtest-bias-detector audit: also compute PSR from the
    # CPCV out-of-sample Sharpe distribution (uses mean of test-fold Sharpes
    # as the point estimate). This is the honest OOS PSR — the in-sample
    # PSR above can read 100% for an overfit strategy that fails OOS.
    out["psr_oos"] = probabilistic_sharpe_ratio(
        sr_observed=out["sharpe_mean"],
        n_returns=len(pnl_pool),
        skew=_skew,
        kurtosis=_kurt,
        sr_benchmark=0.0,
    )
    # Back-compat alias — older callers read 'psr'. Now points to the OOS one
    # so verdicts use the honest metric by default.
    out["psr"] = out["psr_oos"]

    # DSR — only if caller supplied n_trials. Per Fix #5, scored against
    # OOS mean Sharpe (sharpe_mean) so the verdict uses honest metrics.
    if n_trials_for_dsr and n_trials_for_dsr > 1:
        sr_std_used = (sr_trial_std_for_dsr
                       if sr_trial_std_for_dsr is not None
                       else out["sharpe_std"])  # ANTI-CONSERVATIVE proxy — see Fix #2
        proxy_used = (sr_trial_std_for_dsr is None)
        if sr_std_used <= 0:
            out["dsr"] = None
            out["dsr_bench_sharpe"] = None
            out["dsr_note"] = "sr_trial_std=0 - DSR undefined"
        else:
            bench = expected_max_sharpe(n_trials_for_dsr, sr_std_used)
            out["dsr_bench_sharpe"] = bench
            out["dsr"] = probabilistic_sharpe_ratio(
                sr_observed=out["sharpe_mean"],  # OOS mean across CPCV folds
                n_returns=len(pnl_pool),
                skew=_skew,
                kurtosis=_kurt,
                sr_benchmark=bench,
            )
            out["dsr_n_trials"] = n_trials_for_dsr
            out["dsr_sr_trial_std"] = sr_std_used
            out["dsr_proxy_used"] = proxy_used
            if proxy_used:
                out["dsr_note"] = (
                    "Using within-run fold-Sharpe std as sr_trial_std. "
                    "ANTI-CONSERVATIVE - real DSR likely LOWER than reported."
                )
    else:
        out["dsr"] = None
        out["dsr_bench_sharpe"] = None

    # Verdict against Phase A exit criteria: CPCV-validated WR >= 58% AND
    # (DSR >= 95% when DSR is computed). Per backtest-bias-detector audit
    # Fix #3: MARGINAL must also enforce the DSR gate — without it, a run
    # with WR=57.9% but DSR=0.001% would slip through as MARGINAL.
    wr_mean = out["wr_mean"]
    dsr_ok = (out["dsr"] is None) or (out["dsr"] >= 0.95)
    if wr_mean >= 58.0 and dsr_ok:
        out["verdict"] = "PASS"
    elif wr_mean >= 55.0 and dsr_ok:
        out["verdict"] = "MARGINAL"
    else:
        out["verdict"] = "FAIL"

    return out


# ══════════════════════════════════════════════════════════════════════════════
# 4) Text report
# ══════════════════════════════════════════════════════════════════════════════

def cpcv_text_report(summary: Dict[str, Any]) -> str:
    """Human-readable text dump, suitable for the backtest report block.

    Pure ASCII — safe on Windows cp1252 console and in any tee/log capture.
    """
    lines = [
        "-" * 65,
        "  HONEST METRICS - CPCV + Deflated Sharpe (Top-10 #5)",
        "-" * 65,
        f"  n_signals     = {summary.get('n_signals', 0)}",
        f"  CPCV config   = K={summary.get('n_groups')} groups, "
        f"k={summary.get('n_test_groups')} test, "
        f"embargo={summary.get('embargo_pct', 0) * 100:.1f}%",
        f"  n_splits      = {summary.get('n_splits', 0)}",
        "",
        f"  WR (CPCV)      mean={summary.get('wr_mean', 0):.2f}%  "
        f"std={summary.get('wr_std', 0):.2f}%",
        f"                 q05={summary.get('wr_q05', 0):.1f}%  "
        f"q50={summary.get('wr_q50', 0):.1f}%  "
        f"q95={summary.get('wr_q95', 0):.1f}%",
        f"  Sharpe (CPCV)  mean={summary.get('sharpe_mean', 0):.3f}  "
        f"std={summary.get('sharpe_std', 0):.3f}",
        "",
        f"  Overall Sharpe = {summary.get('overall_sharpe', 0):.3f}  (in-sample, full pool)",
        f"  Skew           = {summary.get('overall_skew', 0):+.3f}",
        f"  Kurtosis       = {summary.get('overall_kurt', 0):.3f}  (normal=3)",
        f"  PSR (in-sample) = {summary.get('psr_is', 0) * 100:.1f}%   "
        f"(informational - can read 100% for overfit strategies)",
        f"  PSR (OOS CPCV)  = {summary.get('psr_oos', 0) * 100:.1f}%   "
        f"(HONEST - uses mean of CPCV test-fold Sharpes)",
    ]
    dsr = summary.get("dsr")
    if dsr is not None:
        lines.append(
            f"  DSR (multi-test) = {dsr * 100:.1f}%   "
            f"[n_trials={summary.get('dsr_n_trials')}, "
            f"bench_SR={summary.get('dsr_bench_sharpe', 0):.3f}, "
            f"SR_trial_std={summary.get('dsr_sr_trial_std', 0):.3f}]"
        )
        if summary.get("dsr_proxy_used"):
            lines.append(
                f"  !!  DSR uses within-run fold-Sharpe std as proxy for"
            )
            lines.append(
                f"      cross-trial std. Real DSR likely LOWER than reported."
            )
    else:
        note = summary.get("dsr_note", "n_trials_for_dsr not supplied")
        lines.append(f"  DSR              = (skipped - {note})")

    lines.append("")
    lines.append(f"  VERDICT: {summary.get('verdict', 'UNKNOWN')}   "
                 f"(Phase A exit: CPCV mean WR >= 58%, DSR >= 95% if computed)")
    lines.append("-" * 65)
    return "\n".join(lines)


__all__ = [
    "combinatorial_purged_kfold",
    "expected_max_sharpe",
    "probabilistic_sharpe_ratio",
    "deflated_sharpe_ratio",
    "sharpe_ratio",
    "cpcv_summary",
    "cpcv_text_report",
    "CPCVSplitMetrics",
]
