"""
Walk-Forward Validation (WFV) — sequential expanding-window backtest analysis.

Phase C of LIVE_BACKTEST_PARITY_ROADMAP. Complements (does NOT replace) CPCV.

Why this module:
- CPCV (validation.py) is k-fold combinatorial purged — better statistical power
  at small n but DOES NOT enforce temporal ordering. A configuration that works
  on average across folds may have systematic parameter decay over time that
  CPCV cannot detect.
- WFV trains on prefix [0:T] and tests on [T:T+W] for increasing T. If the
  test-window WR systematically decays as T grows, the strategy is non-stationary
  and the CPCV mean overstates expected forward performance.
- WFV is INFORMATIONAL — its primary value is decay detection, not verdict.
  The verdict gate stays on CPCV + DSR (López de Prado 2018 / Bailey & LdP 2014).

Held-Out Lockbox:
- A separate concept from WFV. The held-out is a FIXED wall-clock window at
  the END of the data, NEVER touched during tuning/optimization. WFV runs
  inside the tuning period; held-out is a one-shot final validation.
- Together they form the standard "train + WFV-monitor + held-out-verify"
  protocol used in academic + institutional quant practice.

This module is PURE (no DB, no I/O). Caller supplies sorted signals; we return
per-window metrics + an aggregate decay flag.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence
from datetime import datetime, timezone
import math


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ts_to_epoch(ts: Any) -> float:
    """Accept datetime, ISO string, or epoch float. Return UNIX epoch (UTC)."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _default_is_win(s: dict) -> bool:
    return s.get("outcome") in ("WIN", "PARTIAL_TP1", "PARTIAL_TP2")


def _safe_mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _safe_std(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = _safe_mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


# ── Core ─────────────────────────────────────────────────────────────────────


def walk_forward(
    signals: Sequence[dict],
    *,
    n_windows: int = 12,
    min_train_signals: int = 10,
    is_win_func: Callable[[dict], bool] = _default_is_win,
    decay_threshold_pp: float = 10.0,
) -> Dict[str, Any]:
    """Run expanding-window WFV.

    Protocol:
    - Sort signals chronologically by their `ts` field.
    - Partition the time axis into `n_windows` equal calendar segments.
    - For window i (i=0..n_windows-1):
        train = signals with ts in [t_start, t_start + i*W)
        test  = signals with ts in [t_start + i*W, t_start + (i+1)*W)
      where W = (t_end - t_start) / n_windows.
    - The first window is skipped because train would be empty.
    - Windows with train < `min_train_signals` are reported but flagged
      as `insufficient_train=True` — their test_wr is not aggregated.

    Decay detection:
    - Linear regression of (window_index, test_wr) across all valid windows.
    - If slope is more negative than `-decay_threshold_pp / n_windows`,
      flag `decay_detected=True`. Operator should investigate parameter
      drift before promoting.

    Parameters
    ----------
    signals             dict list with at least 'ts' and 'outcome' (win classifier).
    n_windows           total calendar partitions (default 12 ≈ 1 month each on 365d).
    min_train_signals   minimum train sample to consider a window's test result valid.
    is_win_func         custom win classifier.
    decay_threshold_pp  pp/window slope threshold for decay flag (default 10pp).

    Returns
    -------
    Dict with:
      n_signals         total signal count
      n_windows         echoed
      windows           list of per-window dicts:
                          {idx, t_start, t_end, n_train, n_test, train_wr, test_wr,
                           insufficient_train}
      test_wr_mean      mean of test_wr across valid windows
      test_wr_std       sample std
      train_wr_mean     mean of train_wr across valid windows
      decay_slope_pp    test_wr regression slope (pp per window index)
      decay_detected    True if slope < -threshold/n_windows
      n_valid_windows   count of windows with train >= min_train_signals
      verdict           "ROBUST" / "DECAYING" / "INSUFFICIENT_SAMPLE"
    """
    n = len(signals)
    out: Dict[str, Any] = {
        "n_signals":      n,
        "n_windows":      n_windows,
        "windows":        [],
        "test_wr_mean":   0.0,
        "test_wr_std":    0.0,
        "train_wr_mean":  0.0,
        "decay_slope_pp": 0.0,
        "decay_detected": False,
        "n_valid_windows": 0,
        "verdict":        "INSUFFICIENT_SAMPLE",
    }
    if n == 0 or n_windows < 2:
        return out

    sorted_sigs = sorted(signals, key=lambda s: _ts_to_epoch(s.get("ts", "")))
    t_eps = [_ts_to_epoch(s.get("ts", "")) for s in sorted_sigs]
    t_start, t_end = t_eps[0], t_eps[-1]
    if t_end <= t_start:
        return out
    window_secs = (t_end - t_start) / n_windows

    valid_test_wrs: List[float] = []
    valid_train_wrs: List[float] = []
    valid_indices: List[int] = []

    for i in range(1, n_windows):
        t_split = t_start + i * window_secs
        t_test_end = t_start + (i + 1) * window_secs
        train_sigs = [
            sorted_sigs[j] for j in range(n)
            if t_eps[j] < t_split
        ]
        test_sigs = [
            sorted_sigs[j] for j in range(n)
            if t_split <= t_eps[j] < t_test_end
        ]
        train_wins = sum(1 for s in train_sigs if is_win_func(s))
        test_wins  = sum(1 for s in test_sigs  if is_win_func(s))
        train_wr = (train_wins / len(train_sigs) * 100.0) if train_sigs else 0.0
        test_wr  = (test_wins  / len(test_sigs)  * 100.0) if test_sigs  else 0.0
        insufficient = len(train_sigs) < min_train_signals or len(test_sigs) == 0
        out["windows"].append({
            "idx":                 i,
            "t_start":             t_start,
            "t_split":             t_split,
            "t_test_end":          t_test_end,
            "n_train":             len(train_sigs),
            "n_test":              len(test_sigs),
            "train_wr":            train_wr,
            "test_wr":             test_wr,
            "insufficient_train":  insufficient,
        })
        if not insufficient:
            valid_test_wrs.append(test_wr)
            valid_train_wrs.append(train_wr)
            valid_indices.append(i)

    out["n_valid_windows"] = len(valid_test_wrs)
    if not valid_test_wrs:
        out["verdict"] = "INSUFFICIENT_SAMPLE"
        return out

    out["test_wr_mean"]  = _safe_mean(valid_test_wrs)
    out["test_wr_std"]   = _safe_std(valid_test_wrs)
    out["train_wr_mean"] = _safe_mean(valid_train_wrs)

    # Linear regression slope: cov(idx, test_wr) / var(idx)
    if len(valid_test_wrs) >= 3:
        mean_idx = _safe_mean(valid_indices)
        mean_wr  = out["test_wr_mean"]
        num = sum((valid_indices[k] - mean_idx) * (valid_test_wrs[k] - mean_wr)
                  for k in range(len(valid_test_wrs)))
        den = sum((valid_indices[k] - mean_idx) ** 2
                  for k in range(len(valid_test_wrs)))
        slope = (num / den) if den > 0 else 0.0
        out["decay_slope_pp"] = slope
        decay_floor = -decay_threshold_pp / n_windows
        out["decay_detected"] = slope < decay_floor
    out["verdict"] = "DECAYING" if out["decay_detected"] else "ROBUST"
    return out


# ── Held-out lockbox (separate concept; complements walk_forward) ────────────


def split_held_out(
    signals: Sequence[dict],
    held_out_days: int,
    *,
    now_utc: Optional[datetime] = None,
) -> Dict[str, List[dict]]:
    """Chronologically split signals into tuning + held_out.

    The held-out window is the FINAL `held_out_days` days of the data (relative
    to `now_utc` — defaults to current UTC time). Tuning is everything before.

    This split is the operational primitive for the Phase C "held-out lockbox"
    protocol: optimization/Optuna touches only the tuning portion; held-out is
    reserved for one-shot final validation per promotion.

    Parameters
    ----------
    signals         dict list with 'ts' field.
    held_out_days   number of days at the end of the data to reserve as held-out.
                    If <= 0, returns all signals as tuning + empty held_out.
    now_utc         optional override for current time (testable).

    Returns
    -------
    {"tuning":   list of dicts with ts < cutoff,
     "held_out": list of dicts with ts >= cutoff,
     "cutoff_epoch": float (cutoff in epoch seconds),
     "cutoff_iso":   str  (cutoff in ISO-8601 UTC)}
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    cutoff_epoch = now_utc.timestamp() - held_out_days * 86400.0
    cutoff_iso = datetime.fromtimestamp(cutoff_epoch, tz=timezone.utc).isoformat()
    if held_out_days <= 0:
        return {
            "tuning":       list(signals),
            "held_out":     [],
            "cutoff_epoch": cutoff_epoch,
            "cutoff_iso":   cutoff_iso,
        }
    tuning:   List[dict] = []
    held_out: List[dict] = []
    for s in signals:
        if _ts_to_epoch(s.get("ts", "")) < cutoff_epoch:
            tuning.append(s)
        else:
            held_out.append(s)
    return {
        "tuning":       tuning,
        "held_out":     held_out,
        "cutoff_epoch": cutoff_epoch,
        "cutoff_iso":   cutoff_iso,
    }


def held_out_summary(
    held_out_signals: Sequence[dict],
    *,
    is_win_func: Callable[[dict], bool] = _default_is_win,
    tuning_wr: Optional[float] = None,
    max_gap_pp: float = 8.0,
    min_wr_pct: float = 58.0,
) -> Dict[str, Any]:
    """One-shot held-out evaluation.

    Reports headline WR + Wilson 95% CI + train/test gap against `tuning_wr`
    (if provided). No CPCV folds — held-out is a single-window verdict.

    Parameters
    ----------
    held_out_signals  dict list (output of split_held_out["held_out"]).
    is_win_func       custom win classifier.
    tuning_wr         optional reference WR from the tuning-period CPCV.
    max_gap_pp        verdict threshold for |tuning_wr - held_out_wr| (default 8pp).
    min_wr_pct        verdict floor on held-out WR (default 58pp).

    Returns
    -------
    Dict with:
      n               held-out signal count
      wins / losses
      wr_pct          headline WR
      wilson_lo_pct   Wilson 95% CI lower bound
      wilson_hi_pct   Wilson 95% CI upper bound
      gap_pp          |tuning_wr - held_out_wr| (None if tuning_wr not supplied)
      verdict         "ROBUST" | "BORDERLINE" | "OVERFIT" | "INSUFFICIENT_SAMPLE"
                      ROBUST     = WR >= min_wr_pct AND gap < max_gap_pp/2
                      BORDERLINE = WR >= min_wr_pct AND gap < max_gap_pp
                      OVERFIT    = otherwise (when n >= 5)
    """
    n = len(held_out_signals)
    out: Dict[str, Any] = {
        "n":             n,
        "wins":          0,
        "losses":        0,
        "wr_pct":        0.0,
        "wilson_lo_pct": 0.0,
        "wilson_hi_pct": 0.0,
        "gap_pp":        None,
        "verdict":       "INSUFFICIENT_SAMPLE",
    }
    if n == 0:
        return out
    wins = sum(1 for s in held_out_signals if is_win_func(s))
    losses = n - wins
    wr = (wins / n) * 100.0
    out["wins"]   = wins
    out["losses"] = losses
    out["wr_pct"] = wr

    # Wilson 95% CI on a binomial proportion.
    z = 1.96
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    out["wilson_lo_pct"] = max(0.0, (center - half) * 100.0)
    out["wilson_hi_pct"] = min(100.0, (center + half) * 100.0)

    if tuning_wr is not None:
        out["gap_pp"] = abs(tuning_wr - wr)

    # Verdict
    if n < 5:
        out["verdict"] = "INSUFFICIENT_SAMPLE"
    elif wr >= min_wr_pct and (out["gap_pp"] is None or out["gap_pp"] < max_gap_pp / 2):
        out["verdict"] = "ROBUST"
    elif wr >= min_wr_pct and out["gap_pp"] is not None and out["gap_pp"] < max_gap_pp:
        out["verdict"] = "BORDERLINE"
    else:
        out["verdict"] = "OVERFIT"
    return out


# ── Report formatting ────────────────────────────────────────────────────────


def walk_forward_text_report(wf: Dict[str, Any]) -> str:
    """Compact human-readable WFV report block."""
    lines = []
    lines.append("-----------------------------------------------------------------")
    lines.append("  WALK-FORWARD VALIDATION (expanding-window decay test)")
    lines.append("-----------------------------------------------------------------")
    lines.append(f"  n_signals         = {wf.get('n_signals', 0)}")
    lines.append(f"  n_windows         = {wf.get('n_windows', 0)}")
    lines.append(f"  n_valid_windows   = {wf.get('n_valid_windows', 0)}")
    lines.append(f"  test_wr (mean)    = {wf.get('test_wr_mean', 0.0):.2f}%")
    lines.append(f"  test_wr (std)     = {wf.get('test_wr_std', 0.0):.2f}%")
    lines.append(f"  train_wr (mean)   = {wf.get('train_wr_mean', 0.0):.2f}%")
    lines.append(f"  decay_slope       = {wf.get('decay_slope_pp', 0.0):+.2f} pp/window")
    if wf.get("decay_detected"):
        lines.append("  *** DECAY DETECTED *** investigate parameter drift before promoting.")
    lines.append(f"  VERDICT: {wf.get('verdict', '?')}")
    lines.append("-----------------------------------------------------------------")
    return "\n".join(lines)


def held_out_text_report(ho: Dict[str, Any], *, tuning_wr: Optional[float] = None) -> str:
    """Compact human-readable held-out report block."""
    lines = []
    lines.append("-----------------------------------------------------------------")
    lines.append("  HELD-OUT LOCKBOX (final 90d window, never touched during tuning)")
    lines.append("-----------------------------------------------------------------")
    lines.append(f"  n                 = {ho.get('n', 0)}")
    lines.append(f"  wins / losses     = {ho.get('wins', 0)} / {ho.get('losses', 0)}")
    lines.append(f"  WR                = {ho.get('wr_pct', 0.0):.2f}%")
    lines.append(f"  Wilson 95% CI     = [{ho.get('wilson_lo_pct', 0.0):.1f}%, {ho.get('wilson_hi_pct', 0.0):.1f}%]")
    if tuning_wr is not None:
        lines.append(f"  tuning WR (ref)   = {tuning_wr:.2f}%")
    if ho.get("gap_pp") is not None:
        lines.append(f"  gap (|tune-held|) = {ho['gap_pp']:.2f} pp")
    lines.append(f"  VERDICT: {ho.get('verdict', '?')}")
    if ho.get("verdict") == "OVERFIT":
        lines.append("  *** OVERFIT *** baseline may not generalize. Operator review required.")
    lines.append("-----------------------------------------------------------------")
    return "\n".join(lines)
