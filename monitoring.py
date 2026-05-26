"""
TradeAI — Weight-Degeneration Monitoring Suite
================================================
Roadmap reference:
  • Top-10 #9 / Phase A item observability per docs/ENTERPRISE_ROADMAP.md
  • Sprint 3 item 3.

Purpose
-------
Sidecar observability layer over the OGD weight state stored in
token_weights and weight_history. Detects failure modes that already killed
Run-46 (one feature collapsed to near-100%) and the 6/7 near-degenerate
bootstrap states identified by the ogd-weight-inspector.

What it checks (per token)
--------------------------
  • Max weight vs DEGENERATE_THRESHOLD     — single-feature dominance
  • Shannon entropy                         — distribution collapse (low = bad)
  • Pinning at WEIGHT_MIN / WEIGHT_MAX     — features stuck at hard bounds
  • Recent entropy drift over N history rows — sudden collapse detection
  • Stale tokens (no update in > N days)    — adaptive layer silently dead

What it checks (across tokens)
------------------------------
  • Average pairwise L1 distance between per-token weight vectors —
    homogeneity alert when all tokens converge to identical weights
    (suggests bug in per-token routing or a global feature override).

Hard invariants
---------------
  • Read-only. Never writes to token_weights, weight_history, or any engine
    state. Safe to run concurrently with the bot.
  • Stdlib-only hot path. Prometheus emission is optional, behind try/except.
  • Never logs raw weight values to external sinks — only structured numbers.

Public API
----------
  generate_report(db_path)        — build the structured snapshot dict
  format_text_report(report)      — human-readable text for Telegram / logs
  write_report_json(path, report) — atomic JSON dump
  emit_prometheus_metrics(report) — optional, no-op if package missing
  cli_main(argv)                  — entry point for `python monitoring.py`
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ── Constants (mirror adaptive_engine.py without importing it) ───────────────
# Kept synchronised manually so this module loads even when the adaptive
# engine is mid-migration. CI test asserts they stay aligned.
DEGENERATE_THRESHOLD = 0.40  # Fix #36 (2026-05-22 cycle 9): mirror adaptive_engine 0.45→0.40
WEIGHT_MIN = 0.05
WEIGHT_MAX = 0.50
FEATURES = ("fvg_quality", "mss_quality", "session",
            "confidence", "trend_strength", "dr_location")

# Monitoring thresholds (tunable via env vars in CLI mode, not in import)
LOW_ENTROPY_THRESHOLD     = 1.55  # ln(6) = 1.79 = uniform; <1.55 = collapsed
HOMOGENEITY_THRESHOLD     = 0.05  # avg pairwise L1 < this → all tokens identical
STALE_DAYS_THRESHOLD      = 14    # token not updated in > N days → stale
                                  # tightened from 30 per ogd-weight-inspector review:
                                  # bot fires multi-times/day, one quiet week is abnormal.
ENTROPY_DRIFT_LOOKBACK    = 10    # number of weight_history rows to compare
ENTROPY_DRIFT_ALERT       = 0.30  # sudden entropy drop of > 0.30 → WARN
ENTROPY_DRIFT_CRIT        = 0.60  # catastrophic drop > 0.60 (half of ln(6)) → CRIT
                                  # — the Run-46 collapse fingerprint
FLOOR_PIN_CRIT_COUNT      = 4     # if >= N features pinned at WEIGHT_MIN floor,
                                  # mass is concentrated in 1-2 features → CRIT
                                  # (5/6 at floor with 1 at max is THE Run-46 mode)

_DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "data", "signals.db")


# ── DB helpers (read-only) ────────────────────────────────────────────────────

def _connect_ro(db_path: str) -> sqlite3.Connection:
    """Open a read-only connection so monitoring can never corrupt state."""
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)


# OGD-MON-SCOPE fix (cycle-4 audit 2026-05-26): the monitor previously
# read ONLY the live `token_weights` table. 99% of OGD learning lives
# in `backtest_token_weights` (populated by bootstrap_from_backtest).
# Run-46-style degeneration in the bootstrap pool was invisible. The
# fetch helpers now accept an explicit `table` argument so callers can
# audit either source via the `--source {live,bootstrap}` CLI flag.
_TABLE_LIVE      = "token_weights"
_TABLE_BOOTSTRAP = "backtest_token_weights"
_VALID_TABLES    = (_TABLE_LIVE, _TABLE_BOOTSTRAP)


def _fetch_current_weights(db_path: str,
                            table: str = _TABLE_LIVE
                            ) -> Dict[str, Dict[str, float]]:
    """Return {token: {feature: weight}} from `table`.

    `table` defaults to live `token_weights` for backward compatibility.
    Set to `backtest_token_weights` to audit the bootstrap-learned pool.
    """
    if table not in _VALID_TABLES:
        raise ValueError(f"invalid table {table!r}; expected one of {_VALID_TABLES}")
    out: Dict[str, Dict[str, float]] = {}
    try:
        conn = _connect_ro(db_path)
    except sqlite3.Error:
        return out
    try:
        rows = conn.execute(
            f"SELECT token, feature, weight FROM {table}"  # noqa: S608 (whitelisted)
        ).fetchall()
    except sqlite3.Error:
        rows = []
    conn.close()
    for token, feat, weight in rows:
        if feat not in FEATURES:
            continue
        out.setdefault(token, {})[feat] = float(weight)
    return out


def _fetch_n_updates(db_path: str, table: str = _TABLE_LIVE) -> Dict[str, int]:
    if table not in _VALID_TABLES:
        raise ValueError(f"invalid table {table!r}")
    out: Dict[str, int] = {}
    try:
        conn = _connect_ro(db_path)
    except sqlite3.Error:
        return out
    try:
        rows = conn.execute(
            f"SELECT token, MAX(n_updates) FROM {table} GROUP BY token"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    conn.close()
    for token, n in rows:
        out[token] = int(n or 0)
    return out


def _fetch_last_updated(db_path: str, table: str = _TABLE_LIVE) -> Dict[str, Optional[str]]:
    if table not in _VALID_TABLES:
        raise ValueError(f"invalid table {table!r}")
    out: Dict[str, Optional[str]] = {}
    try:
        conn = _connect_ro(db_path)
    except sqlite3.Error:
        return out
    try:
        rows = conn.execute(
            f"SELECT token, MAX(updated_at) FROM {table} GROUP BY token"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    conn.close()
    for token, ts in rows:
        out[token] = ts
    return out


def _fetch_recent_history(db_path: str, token: str, limit: int
                          ) -> List[Tuple[str, Dict[str, float]]]:
    """Return last N weight snapshots from weight_history for one token.

    Returns list of (recorded_at, {feature: weight_after}) sorted oldest-first.
    Rows from the same recorded_at are grouped together (one row per feature).
    """
    try:
        conn = _connect_ro(db_path)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            """SELECT recorded_at, feature, weight_after FROM weight_history
               WHERE token = ?
               ORDER BY id DESC
               LIMIT ?""",
            (token, limit * len(FEATURES)),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    conn.close()

    # Group by recorded_at; preserve order (newest first), reverse at end.
    grouped: List[Tuple[str, Dict[str, float]]] = []
    current_ts: Optional[str] = None
    current_map: Dict[str, float] = {}
    for recorded_at, feat, weight_after in rows:
        if recorded_at != current_ts:
            if current_ts is not None and current_map:
                grouped.append((current_ts, current_map))
            current_ts = recorded_at
            current_map = {}
        if feat in FEATURES:
            current_map[feat] = float(weight_after)
    if current_ts is not None and current_map:
        grouped.append((current_ts, current_map))

    grouped.reverse()  # oldest-first
    return grouped[-limit:]


# ── Pure metric functions ─────────────────────────────────────────────────────

def compute_entropy(weights: Dict[str, float]) -> float:
    """Shannon entropy of the weight distribution in nats.

    Returns 0.0 for empty or degenerate dicts. Uniform over N features gives ln(N).
    """
    if not weights:
        return 0.0
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    h = 0.0
    for v in weights.values():
        p = v / total
        if p > 0:
            h -= p * math.log(p)
    return h


def detect_pinning(weights: Dict[str, float],
                   min_w: float = WEIGHT_MIN,
                   max_w: float = WEIGHT_MAX,
                   tol: float = 1e-4) -> List[str]:
    """Return features pinned at WEIGHT_MIN or WEIGHT_MAX (within tol)."""
    pinned: List[str] = []
    for feat, val in weights.items():
        if abs(val - min_w) <= tol or abs(val - max_w) <= tol:
            pinned.append(feat)
    return pinned


def count_floor_pins(weights: Dict[str, float],
                     min_w: float = WEIGHT_MIN,
                     tol: float = 1e-4) -> int:
    """Count features pinned at WEIGHT_MIN floor (per ogd-weight-inspector recommendation).

    The Run-46 degeneracy fingerprint is N-1 features at the floor with mass
    concentrated in the remaining one. is_degenerate catches the dominant
    feature; this catches the symmetric "floor saturation" signature directly.
    """
    return sum(1 for v in weights.values() if abs(v - min_w) <= tol)


def is_degenerate(weights: Dict[str, float],
                  threshold: float = DEGENERATE_THRESHOLD
                  ) -> Tuple[bool, Optional[str], float]:
    """Mirrors AdaptiveWeightEngine._check_degenerate() — kept here so monitoring
    has no runtime dependency on the engine module."""
    if not weights:
        return False, None, 0.0
    worst_feat = max(weights, key=weights.get)
    worst_val = weights[worst_feat]
    return worst_val > threshold, worst_feat, worst_val


def entropy_drift(history: List[Tuple[str, Dict[str, float]]]
                  ) -> Optional[float]:
    """Return entropy(latest) - entropy(oldest) over the supplied history slice.
    None if fewer than 2 snapshots are available."""
    if len(history) < 2:
        return None
    e_first = compute_entropy(history[0][1])
    e_last  = compute_entropy(history[-1][1])
    return e_last - e_first


def pairwise_l1(a: Dict[str, float], b: Dict[str, float]) -> float:
    """L1 distance between two weight vectors (sum of absolute differences)."""
    keys = set(a) | set(b)
    return sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)


def cross_token_diversity(snapshot: Dict[str, Dict[str, float]]
                          ) -> Tuple[float, float, int]:
    """Returns (avg_pairwise_l1, min_pairwise_l1, n_pairs).

    Lower numbers = tokens are converging to the same weight vector — a sign
    that per-token routing is broken or a global override is in effect.
    """
    tokens = sorted(snapshot)
    pairs: List[float] = []
    for i, t1 in enumerate(tokens):
        for t2 in tokens[i + 1:]:
            pairs.append(pairwise_l1(snapshot[t1], snapshot[t2]))
    if not pairs:
        return 0.0, 0.0, 0
    return sum(pairs) / len(pairs), min(pairs), len(pairs)


def _days_since(ts: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Parse 'YYYY-MM-DD HH:MM:SS' (UTC) → days delta from now. None on parse fail."""
    if not ts:
        return None
    try:
        when = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    ref = now or datetime.now(timezone.utc)
    return (ref - when).total_seconds() / 86400.0


# ── Per-token report builder ──────────────────────────────────────────────────

def _per_token_report(token: str,
                      weights: Dict[str, float],
                      n_updates: int,
                      last_updated: Optional[str],
                      history: List[Tuple[str, Dict[str, float]]],
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    entropy = compute_entropy(weights)
    is_degen, worst_feat, worst_val = is_degenerate(weights)
    pinned = detect_pinning(weights)
    floor_pins = count_floor_pins(weights)
    drift = entropy_drift(history)
    days_old = _days_since(last_updated, now)

    alerts: List[str] = []
    level = "OK"

    def _escalate(target: str) -> None:
        # OK < WARN < CRIT — only escalate, never downgrade
        nonlocal level
        order = {"OK": 0, "WARN": 1, "CRIT": 2}
        if order[target] > order[level]:
            level = target

    if is_degen:
        alerts.append(f"DEGENERATE: {worst_feat}={worst_val:.3f} > {DEGENERATE_THRESHOLD}")
        _escalate("CRIT")
    if floor_pins >= FLOOR_PIN_CRIT_COUNT:
        # Run-46 fingerprint: most features at the floor → mass concentrated in 1-2
        alerts.append(f"FLOOR_SATURATION: {floor_pins}/{len(weights)} features at WEIGHT_MIN")
        _escalate("CRIT")
    if entropy < LOW_ENTROPY_THRESHOLD:
        alerts.append(f"LOW_ENTROPY: H={entropy:.3f} < {LOW_ENTROPY_THRESHOLD}")
        _escalate("WARN")
    if pinned:
        alerts.append(f"PINNED at bounds: {','.join(pinned)}")
        _escalate("WARN")
    if drift is not None:
        if drift < -ENTROPY_DRIFT_CRIT:
            alerts.append(f"CATASTROPHIC_ENTROPY_DROP: Δ={drift:+.3f} over last {len(history)} snapshots")
            _escalate("CRIT")
        elif drift < -ENTROPY_DRIFT_ALERT:
            alerts.append(f"ENTROPY_DROP: Δ={drift:+.3f} over last {len(history)} snapshots")
            _escalate("WARN")
    if days_old is not None and days_old > STALE_DAYS_THRESHOLD:
        alerts.append(f"STALE: {days_old:.1f} days since last update")
        _escalate("WARN")

    return {
        "max_weight":    round(worst_val, 4),
        "max_feature":   worst_feat,
        "is_degenerate": is_degen,
        "entropy":       round(entropy, 4),
        "entropy_drift": None if drift is None else round(drift, 4),
        "pinned_features": pinned,
        "floor_pin_count": floor_pins,
        "n_updates":     n_updates,
        "last_updated":  last_updated,
        "days_since_update": None if days_old is None else round(days_old, 2),
        "alert_level":   level,
        "alerts":        alerts,
    }


# ── Top-level report ──────────────────────────────────────────────────────────

def generate_report(db_path: str = _DEFAULT_DB_PATH,
                    now: Optional[datetime] = None,
                    table: str = _TABLE_LIVE) -> Dict[str, Any]:
    """Build the full monitoring snapshot. Read-only, never raises.

    `table` selects which weight table to audit:
      - `token_weights` (default, live OGD updates)
      - `backtest_token_weights` (bootstrap pool — where most OGD
        learning actually lives until paper trading accumulates)
    See OGD-MON-SCOPE fix (cycle-4 audit 2026-05-26).
    """
    now = now or datetime.now(timezone.utc)
    snapshot = _fetch_current_weights(db_path, table=table)
    n_map    = _fetch_n_updates(db_path, table=table)
    last_map = _fetch_last_updated(db_path, table=table)

    per_token: Dict[str, Dict[str, Any]] = {}
    for token, weights in snapshot.items():
        history = _fetch_recent_history(db_path, token, ENTROPY_DRIFT_LOOKBACK)
        per_token[token] = _per_token_report(
            token, weights, n_map.get(token, 0), last_map.get(token),
            history, now=now,
        )

    avg_l1, min_l1, n_pairs = cross_token_diversity(snapshot)
    homogeneous = bool(snapshot) and avg_l1 < HOMOGENEITY_THRESHOLD

    # Aggregate counts
    degen = sum(1 for t in per_token.values() if t["is_degenerate"])
    low_e = sum(1 for t in per_token.values()
                if t["entropy"] < LOW_ENTROPY_THRESHOLD)
    pinned_n = sum(1 for t in per_token.values() if t["pinned_features"])
    stale_n  = sum(1 for t in per_token.values()
                   if t["days_since_update"] is not None
                   and t["days_since_update"] > STALE_DAYS_THRESHOLD)

    # Global alert level: CRIT if any degenerate; WARN if any warn-level
    # condition or cross-token homogeneity; OK otherwise.
    if degen > 0:
        global_level = "CRIT"
    elif (low_e + pinned_n + stale_n) > 0 or homogeneous:
        global_level = "WARN"
    else:
        global_level = "OK"

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": 1,
        "source_table": table,  # OGD-MON-SCOPE — surfaces which pool was audited
        "summary": {
            "tokens_monitored":   len(per_token),
            "tokens_degenerate":  degen,
            "tokens_low_entropy": low_e,
            "tokens_pinned":      pinned_n,
            "tokens_stale":       stale_n,
            "global_alert_level": global_level,
        },
        "thresholds": {
            "degenerate":         DEGENERATE_THRESHOLD,
            "low_entropy":        LOW_ENTROPY_THRESHOLD,
            "homogeneity":        HOMOGENEITY_THRESHOLD,
            "stale_days":         STALE_DAYS_THRESHOLD,
            "entropy_drift":      ENTROPY_DRIFT_ALERT,
            "entropy_drift_crit": ENTROPY_DRIFT_CRIT,
            "entropy_drift_lookback": ENTROPY_DRIFT_LOOKBACK,
            "floor_pin_crit_count": FLOOR_PIN_CRIT_COUNT,
        },
        "cross_token": {
            "avg_pairwise_l1":    round(avg_l1, 4),
            "min_pairwise_l1":    round(min_l1, 4),
            "n_pairs":            n_pairs,
            "homogeneity_alert":  homogeneous,
        },
        "per_token": per_token,
    }


# ── Output formatters ─────────────────────────────────────────────────────────

def format_text_report(report: Dict[str, Any]) -> str:
    """Compact human-readable text suitable for Telegram or terminal."""
    lines: List[str] = []
    s = report["summary"]
    lines.append(f"OGD WEIGHT MONITOR — {report['generated_at']}")
    lines.append(f"  global={s['global_alert_level']}  "
                 f"tokens={s['tokens_monitored']}  "
                 f"degen={s['tokens_degenerate']}  "
                 f"low_H={s['tokens_low_entropy']}  "
                 f"pinned={s['tokens_pinned']}  "
                 f"stale={s['tokens_stale']}")
    ct = report["cross_token"]
    lines.append(f"  cross_token: avg_L1={ct['avg_pairwise_l1']:.3f}  "
                 f"min_L1={ct['min_pairwise_l1']:.3f}  "
                 f"homog_alert={ct['homogeneity_alert']}")
    lines.append("")
    for token in sorted(report["per_token"]):
        t = report["per_token"][token]
        line = (f"  {token:<5} {t['alert_level']:<4} "
                f"H={t['entropy']:.3f}  "
                f"max={t['max_feature'] or '-':<14}={t['max_weight']:.3f}  "
                f"n={t['n_updates']:<4}  "
                f"d_old={t['days_since_update']}")
        lines.append(line)
        for alert in t["alerts"]:
            lines.append(f"        ! {alert}")
    return "\n".join(lines)


def write_report_json(path: str, report: Dict[str, Any]) -> None:
    """Atomic JSON write. Creates parent dirs as needed."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".monitoring_", dir=parent or ".",
                                suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def emit_prometheus_metrics(report: Dict[str, Any],
                             registry: Any = None) -> bool:
    """Optional Prometheus emission. Returns True if metrics were emitted.

    No-op + False if `prometheus_client` is not installed. Hot path never
    imports the package — kept lazy here.
    """
    try:
        from prometheus_client import Gauge, CollectorRegistry  # type: ignore
    except ImportError:
        return False

    reg = registry or CollectorRegistry()
    g_max = Gauge("tradeai_ogd_max_weight", "Largest per-feature weight",
                  ["token"], registry=reg)
    g_ent = Gauge("tradeai_ogd_entropy", "Shannon entropy of weight vector",
                  ["token"], registry=reg)
    g_n   = Gauge("tradeai_ogd_n_updates", "Number of OGD updates",
                  ["token"], registry=reg)
    g_lvl = Gauge("tradeai_ogd_alert_level", "Per-token alert level (0=OK,1=WARN,2=CRIT)",
                  ["token"], registry=reg)
    g_global = Gauge("tradeai_ogd_global_alert", "Global alert level (0=OK,1=WARN,2=CRIT)",
                     registry=reg)
    g_homog = Gauge("tradeai_ogd_cross_token_l1",
                    "Average pairwise L1 distance between per-token weights",
                    registry=reg)

    level_map = {"OK": 0, "WARN": 1, "CRIT": 2}
    for token, t in report["per_token"].items():
        g_max.labels(token=token).set(t["max_weight"])
        g_ent.labels(token=token).set(t["entropy"])
        g_n.labels(token=token).set(t["n_updates"])
        g_lvl.labels(token=token).set(level_map.get(t["alert_level"], 0))
    g_global.set(level_map.get(report["summary"]["global_alert_level"], 0))
    g_homog.set(report["cross_token"]["avg_pairwise_l1"])
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def cli_main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="OGD weight-degeneration monitoring")
    parser.add_argument("--db", default=_DEFAULT_DB_PATH,
                        help="path to signals.db (read-only)")
    parser.add_argument("--json", default=None,
                        help="write JSON report to this path")
    parser.add_argument("--text", action="store_true",
                        help="print text report to stdout (default if no --json)")
    parser.add_argument("--prometheus", action="store_true",
                        help="emit Prometheus metrics (requires prometheus_client)")
    parser.add_argument("--exit-on-crit", action="store_true",
                        help="exit code 2 if global alert level is CRIT")
    parser.add_argument("--source", choices=("live", "bootstrap"), default="live",
                        help="weight table to audit: 'live' = token_weights "
                             "(live OGD updates), 'bootstrap' = "
                             "backtest_token_weights (where most learning lives "
                             "until paper trading accumulates). OGD-MON-SCOPE fix.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    table = _TABLE_LIVE if args.source == "live" else _TABLE_BOOTSTRAP

    report = generate_report(args.db, table=table)

    if args.json:
        write_report_json(args.json, report)
    if args.text or not args.json:
        print(format_text_report(report))
    if args.prometheus:
        ok = emit_prometheus_metrics(report)
        if not ok:
            print("[monitoring] prometheus_client not installed — metrics not emitted",
                  file=sys.stderr)

    if args.exit_on_crit and report["summary"]["global_alert_level"] == "CRIT":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(cli_main())


__all__ = [
    "compute_entropy", "detect_pinning", "count_floor_pins",
    "is_degenerate", "entropy_drift",
    "pairwise_l1", "cross_token_diversity",
    "generate_report", "format_text_report", "write_report_json",
    "emit_prometheus_metrics", "cli_main",
    "DEGENERATE_THRESHOLD", "WEIGHT_MIN", "WEIGHT_MAX",
    "LOW_ENTROPY_THRESHOLD", "HOMOGENEITY_THRESHOLD",
    "STALE_DAYS_THRESHOLD", "ENTROPY_DRIFT_LOOKBACK", "ENTROPY_DRIFT_ALERT",
    "ENTROPY_DRIFT_CRIT", "FLOOR_PIN_CRIT_COUNT",
]
