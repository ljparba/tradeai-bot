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
    """Boolean win classifier — True for any win/partial outcome.

    Kept for back-compat of the `is_win_func` parameter. New WR
    calculations use `_default_win_score()` instead so the TT-7
    convention (PARTIAL = 0.5 weight) is honored — see MOD-3 fix
    (cycle-4 audit 2026-05-26).
    """
    return s.get("outcome") in ("WIN", "PARTIAL_TP1", "PARTIAL_TP2")


def _default_win_score(s: dict) -> float:
    """TT-7-consistent weighted win scorer.

    Returns:
      1.0 for WIN
      0.5 for PARTIAL_TP1 / PARTIAL_TP2  (full TP1 hit + retrace to BE)
      0.0 otherwise
    Mirrors tracker.py _canonical_wr() + the per-fold PnL convention in
    validation.py. MOD-3 fix (cycle-4 audit 2026-05-26) — previously
    `walk_forward` counted PARTIAL as full-win, inflating WFV test_wr
    and decay-slope readings in PARTIAL-heavy periods (Phase A's
    stale-reject raised PARTIAL share from 18.6% → 28.6% across recent
    runs).
    """
    outcome = s.get("outcome")
    if outcome == "WIN":
        return 1.0
    if outcome in ("PARTIAL_TP1", "PARTIAL_TP2"):
        return 0.5
    return 0.0


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
    score_func: Callable[[dict], float] = _default_win_score,
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
        # MOD-3 fix: weighted scorer honors PARTIAL=0.5 (TT-7 convention)
        train_wins = sum(score_func(s) for s in train_sigs)
        test_wins  = sum(score_func(s) for s in test_sigs)
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
    score_func: Callable[[dict], float] = _default_win_score,
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
    # MOD-3 fix: weighted score (PARTIAL=0.5) for WR; integer wins/losses
    # for Wilson CI retain binomial interpretation but PARTIALs are split
    # 0.5 by counting them as half-win + half-loss in the integer split.
    weighted_wins = sum(score_func(s) for s in held_out_signals)
    wr = (weighted_wins / n) * 100.0
    # For the binomial CI, round to nearest integer count (Wilson CI is
    # defined on integer success counts).
    wins_int = int(round(weighted_wins))
    losses_int = n - wins_int
    out["wins"]   = wins_int
    out["losses"] = losses_int
    out["wr_pct"] = wr

    # Wilson 95% CI on a binomial proportion.
    z = 1.96
    p = weighted_wins / n
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
    # M-4 fix (cycle-4 audit 2026-05-26): warn when valid-window count is
    # too thin to support a meaningful slope estimate. Below 5 the decay
    # regression has ≥3-point dimensions; readings should be treated as
    # informational only.
    n_valid = wf.get("n_valid_windows", 0)
    if 0 < n_valid < 5:
        lines.append(f"  !! WARN-SPARSE-WFV: n_valid_windows={n_valid} < 5 — "
                     f"decay slope is high-variance; treat as informational only.")
    if wf.get("decay_detected"):
        # M-3 fix (cycle-4 audit 2026-05-26): annotate the decay flag with
        # the sample-size caveat. At n~43 over 12 windows (~3.6 signals/window)
        # individual WR readings have ~±26pp CIs; a random walk will trigger
        # decay detection ~30% of the time at the current 10pp threshold.
        lines.append("  *** DECAY DETECTED *** investigate parameter drift before promoting.")
        if n_valid < 5:
            lines.append("      (Decay-flag confidence is LOW at this sample size — "
                         "verify on additional data before acting.)")
    lines.append(f"  VERDICT: {wf.get('verdict', '?')}")
    lines.append("-----------------------------------------------------------------")
    return "\n".join(lines)


def held_out_text_report(
    ho: Dict[str, Any],
    *,
    tuning_wr: Optional[float] = None,
    held_out_days: int = 90,
) -> str:
    """Compact human-readable held-out report block.

    Per S-1 fix (cycle-4 audit 2026-05-26): `held_out_days` is now a parameter
    so the report header truthfully reflects the actual lockbox window size
    (previously hardcoded to "90d" regardless of HELD_OUT_DAYS value).
    """
    lines = []
    lines.append("-----------------------------------------------------------------")
    lines.append(f"  HELD-OUT LOCKBOX (final {held_out_days}d window, never touched during tuning)")
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


# ══════════════════════════════════════════════════════════════════════════════
# Dual-track Phase D.1 (2026-05-26): WFV with adaptive OGD weights
#
# The H6 isolation in backtest scoring is correct for CPCV validity (model
# parameters must be independent of test data when k-fold combinatorial splits
# break chronology). But it creates a known unquantified divergence between
# backtest WR (default weights) and live WR (learned weights).
#
# The literature-supported answer: do BOTH validation tracks in parallel.
#   - CPCV with defaults (validation.py) — selection-bias correction, DSR
#   - WFV with online OGD (this function) — live-parity expected performance
#
# This function processes signals chronologically, applying OGD weight updates
# as each signal closes. For each signal, it captures:
#   - default_score: weighted sum with AE_DEFAULT_WEIGHTS (what backtest used)
#   - ogd_score:     weighted sum with current learned weights (what live computes)
# Aggregated into parity metrics + per-window WR.
#
# Uses a sandboxed AdaptiveWeightEngine instance (persist=False on every update,
# weights wiped to defaults at start) — does NOT touch live token_weights.
# ══════════════════════════════════════════════════════════════════════════════


def _sandboxed_adaptive_engine():
    """Return an AdaptiveWeightEngine with fresh in-memory state.

    Loads the engine (which initializes tables + reads live state into memory)
    then clears every dict so the simulation starts from defaults. All update()
    calls in walk_forward_with_ogd() pass persist=False, so live DB rows are
    never modified. The returned engine is throwaway — caller does not need to
    close it.
    """
    from adaptive_engine import AdaptiveWeightEngine
    eng = AdaptiveWeightEngine()
    eng._weights.clear()
    eng._velocity.clear()
    eng._n.clear()
    eng._n_effective.clear()
    eng._last_update_time.clear()
    return eng


def _safe_corr(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation; returns 0.0 on degenerate input."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = sum((x - mx) ** 2 for x in xs)
    den_y = sum((y - my) ** 2 for y in ys)
    den = (den_x * den_y) ** 0.5
    return num / den if den > 0 else 0.0


def walk_forward_with_ogd(
    signals: Sequence[dict],
    *,
    n_windows: int = 12,
    min_train_signals: int = 10,
    is_win_func: Callable[[dict], bool] = _default_is_win,
    score_func: Callable[[dict], float] = _default_win_score,
) -> Dict[str, Any]:
    """Sequential WFV with adaptive OGD scoring — live-parity track.

    Mirrors live's online learning: weights start at defaults, get updated
    chronologically as each signal closes. For each signal, captures both
    the default-weights score (matches backtest's H6-isolated scoring) and
    the OGD-weights score (matches what live would have computed at that
    point in time).

    Returns dict with:
      n_signals               int
      n_windows               echoed
      windows                 per-window {idx, n_train, n_test, test_wr}
      wfv_ogd_wr_mean         mean test WR across valid windows
      wfv_ogd_wr_std          sample std
      n_valid_windows         windows with train >= min_train_signals
      mean_score_delta        mean(ogd_score - default_score) — sign + drift
      abs_mean_score_delta    mean(|ogd_score - default_score|) — magnitude
      corr_ogd_outcome        Pearson correlation between ogd_score and win-weight
      corr_default_outcome    same for default_score (baseline for comparison)
      top_decile_wr           WR of top-10% signals ranked by ogd_score
      bottom_decile_wr        WR of bottom-10% signals ranked by ogd_score
      top_decile_lift         top - bottom (the OGD discrimination metric)
      parity_verdict          STRONG_LIFT | WEAK_LIFT | INVERTED | INSUFFICIENT_SAMPLE
    """
    # Defer heavy imports — keeps walk_forward.py importable even on installs
    # that don't have adaptive_engine wired (e.g. minimal CI environments).
    from adaptive_engine import DEFAULT_WEIGHTS, FEATURES, extract_ict_feature_scores
    import json as _json

    n = len(signals)
    out: Dict[str, Any] = {
        "n_signals":            n,
        "n_windows":            n_windows,
        "windows":              [],
        "wfv_ogd_wr_mean":      0.0,
        "wfv_ogd_wr_std":       0.0,
        "n_valid_windows":      0,
        "mean_score_delta":     0.0,
        "abs_mean_score_delta": 0.0,
        "corr_ogd_outcome":     0.0,
        "corr_default_outcome": 0.0,
        "top_decile_wr":        0.0,
        "bottom_decile_wr":     0.0,
        "top_decile_lift":      0.0,
        "parity_verdict":       "INSUFFICIENT_SAMPLE",
    }
    if n == 0 or n_windows < 2:
        return out

    sorted_sigs = sorted(signals, key=lambda s: _ts_to_epoch(s.get("ts", "")))
    t_eps = [_ts_to_epoch(s.get("ts", "")) for s in sorted_sigs]
    t_start, t_end = t_eps[0], t_eps[-1]
    if t_end <= t_start:
        return out
    window_secs = (t_end - t_start) / n_windows

    eng = _sandboxed_adaptive_engine()
    _VALID_OUTCOMES = {"WIN", "PARTIAL_TP1", "PARTIAL_TP2", "PARTIAL", "LOSS", "EXPIRED"}

    enriched: List[dict] = []
    for sig in sorted_sigs:
        token = sig.get("token", "")
        # Feature scores: prefer `feature_scores_json` if the signal carries
        # it (live signals do); otherwise derive on-the-fly from the standard
        # ICT-related fields the backtest signal dict already carries. Both
        # paths route through extract_ict_feature_scores() for parity.
        feat_raw = sig.get("feature_scores_json", "")
        if isinstance(feat_raw, str) and feat_raw:
            try:
                feat_all = _json.loads(feat_raw)
            except Exception:
                feat_all = {}
        elif isinstance(feat_raw, dict):
            feat_all = feat_raw
        else:
            feat_all = {}

        if feat_all and any(k in feat_all for k in FEATURES):
            # Use stored feature scores (live signals path)
            feat = {f: float(feat_all.get(f, 0.0) or 0.0) for f in FEATURES}
        else:
            # Backtest path: derive feature scores from the signal's existing
            # ICT fields. `dr4h_location` is the backtest column name;
            # `dr_location` is the live name. Accept either.
            _dr_loc = sig.get("dr_location") or sig.get("dr4h_location") or "UNKNOWN"
            try:
                feat = extract_ict_feature_scores(
                    signal=sig.get("signal", "BUY"),
                    fvg_quality=sig.get("fvg_quality", "NONE"),
                    mss_quality=sig.get("mss_quality", "NONE"),
                    session=sig.get("session", "OVERNIGHT"),
                    confidence=int(sig.get("confidence", 5) or 5),
                    trend_1h=sig.get("trend_1h", "NEUTRAL"),
                    dr_location=_dr_loc,
                )
                # extract_ict_feature_scores returns a dict that already
                # matches FEATURES — filter defensively.
                feat = {f: float(feat.get(f, 0.0) or 0.0) for f in FEATURES}
            except Exception:
                # Last-resort: uniform contribution = 1/n_features each
                feat = {f: 1.0 / len(FEATURES) for f in FEATURES}

        # Scores at this exact point in chronological time
        default_score = sum(DEFAULT_WEIGHTS.get(f, 0.0) * feat[f] for f in FEATURES)
        current_w = eng.get_weights(token)
        ogd_score = sum(current_w.get(f, 0.0) * feat[f] for f in FEATURES)

        outcome = sig.get("outcome", "")
        # Apply OGD update with this signal's outcome (sandboxed — no DB write)
        if outcome in _VALID_OUTCOMES:
            try:
                eng.update(token, outcome, feat, persist=False, profit_pct=None)
            except Exception:
                pass  # never block simulation on engine error

        enriched.append({
            "ts":            sig.get("ts"),
            "token":         token,
            "outcome":       outcome,
            "default_score": default_score,
            "ogd_score":     ogd_score,
            "score_delta":   ogd_score - default_score,
            "win_weight":    score_func(sig),
        })

    # ── Aggregate parity metrics ─────────────────────────────────────────────
    score_deltas = [e["score_delta"] for e in enriched]
    out["mean_score_delta"] = sum(score_deltas) / n
    out["abs_mean_score_delta"] = sum(abs(d) for d in score_deltas) / n

    ogd_scores      = [e["ogd_score"]     for e in enriched]
    default_scores  = [e["default_score"] for e in enriched]
    win_weights     = [e["win_weight"]    for e in enriched]
    out["corr_ogd_outcome"]     = _safe_corr(ogd_scores, win_weights)
    out["corr_default_outcome"] = _safe_corr(default_scores, win_weights)

    # Decile WR analysis (the discrimination test)
    sorted_by_ogd = sorted(enriched, key=lambda e: e["ogd_score"], reverse=True)
    decile_n = max(1, n // 10)
    out["top_decile_wr"] = (
        sum(e["win_weight"] for e in sorted_by_ogd[:decile_n]) / decile_n * 100.0
    )
    out["bottom_decile_wr"] = (
        sum(e["win_weight"] for e in sorted_by_ogd[-decile_n:]) / decile_n * 100.0
    )
    out["top_decile_lift"] = out["top_decile_wr"] - out["bottom_decile_wr"]

    # ── Per-window WFV WR (using chronological partition) ────────────────────
    valid_test_wrs: List[float] = []
    for i in range(1, n_windows):
        t_split = t_start + i * window_secs
        t_test_end = t_start + (i + 1) * window_secs
        train_e = [e for e, ts in zip(enriched, t_eps) if ts < t_split]
        test_e  = [e for e, ts in zip(enriched, t_eps) if t_split <= ts < t_test_end]
        n_train = len(train_e)
        n_test  = len(test_e)
        insufficient = n_train < min_train_signals or n_test == 0
        if not insufficient:
            test_wr = sum(e["win_weight"] for e in test_e) / n_test * 100.0
            out["windows"].append({
                "idx": i, "n_train": n_train, "n_test": n_test, "test_wr": test_wr,
            })
            valid_test_wrs.append(test_wr)

    out["n_valid_windows"] = len(valid_test_wrs)
    if valid_test_wrs:
        out["wfv_ogd_wr_mean"] = sum(valid_test_wrs) / len(valid_test_wrs)
        out["wfv_ogd_wr_std"]  = _safe_std(valid_test_wrs)

    # ── Parity verdict ───────────────────────────────────────────────────────
    if n < 10:
        out["parity_verdict"] = "INSUFFICIENT_SAMPLE"
    elif out["top_decile_lift"] >= 15.0:
        out["parity_verdict"] = "STRONG_LIFT"
    elif out["top_decile_lift"] >= 5.0:
        out["parity_verdict"] = "WEAK_LIFT"
    elif out["top_decile_lift"] <= -10.0:
        out["parity_verdict"] = "INVERTED"
    else:
        out["parity_verdict"] = "NEUTRAL"
    return out


def walk_forward_ogd_text_report(wf_ogd: Dict[str, Any]) -> str:
    """Compact human-readable WFV-with-OGD report block."""
    lines = []
    lines.append("-----------------------------------------------------------------")
    lines.append("  WFV WITH ADAPTIVE OGD WEIGHTS (Phase D.1 — live-parity track)")
    lines.append("-----------------------------------------------------------------")
    lines.append(f"  n_signals              = {wf_ogd.get('n_signals', 0)}")
    lines.append(f"  n_valid_windows        = {wf_ogd.get('n_valid_windows', 0)}")
    lines.append(f"  WFV-OGD WR (mean)      = {wf_ogd.get('wfv_ogd_wr_mean', 0):.2f}%  "
                 f"std={wf_ogd.get('wfv_ogd_wr_std', 0):.2f}%")
    lines.append("")
    lines.append("  Scoring parity (default vs learned OGD):")
    lines.append(f"    mean(ogd_score - default_score)   = "
                 f"{wf_ogd.get('mean_score_delta', 0):+.4f}")
    lines.append(f"    mean(|ogd_score - default_score|) = "
                 f"{wf_ogd.get('abs_mean_score_delta', 0):.4f}")
    lines.append(f"    corr(ogd_score,     outcome)      = "
                 f"{wf_ogd.get('corr_ogd_outcome', 0):+.3f}")
    lines.append(f"    corr(default_score, outcome)      = "
                 f"{wf_ogd.get('corr_default_outcome', 0):+.3f}")
    lines.append(f"    top-decile WR  (by ogd_score)     = "
                 f"{wf_ogd.get('top_decile_wr', 0):.2f}%")
    lines.append(f"    bottom-decile WR (by ogd_score)   = "
                 f"{wf_ogd.get('bottom_decile_wr', 0):.2f}%")
    lines.append(f"    OGD lift (top - bottom)           = "
                 f"{wf_ogd.get('top_decile_lift', 0):+.2f} pp")
    lines.append("")
    verdict = wf_ogd.get("parity_verdict", "?")
    lines.append(f"  PARITY VERDICT: {verdict}")
    if verdict == "STRONG_LIFT":
        lines.append("    OGD scoring CORRECTLY ranks winners over losers (>=15pp lift).")
        lines.append("    Live should outperform backtest's default-weights estimate as")
        lines.append("    weights converge — H6 isolation is creating a real gap.")
    elif verdict == "WEAK_LIFT":
        lines.append("    OGD scoring shows modest lift (5-15pp). Live performance should")
        lines.append("    track default-weights backtest closely with minor positive bias.")
    elif verdict == "NEUTRAL":
        lines.append("    OGD scoring lift is in the noise band (<5pp). Live performance")
        lines.append("    should closely match default-weights backtest — H6 isolation")
        lines.append("    has minimal practical impact at this sample size.")
    elif verdict == "INVERTED":
        lines.append("    *** INVERTED *** top-scored signals lose more than bottom-scored.")
        lines.append("    Either OGD has degenerated, sample is noise-dominated, or the")
        lines.append("    feature-set anti-correlates with outcomes. Investigate.")
    elif verdict == "INSUFFICIENT_SAMPLE":
        lines.append("    Sample too small (n<10) for meaningful OGD scoring verdict.")
        lines.append("    Re-run after more signals accumulate.")
    lines.append("-----------------------------------------------------------------")
    return "\n".join(lines)
