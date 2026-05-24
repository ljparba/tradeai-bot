"""
TradeAI — Phase 2 Step 1: Live Training Data Collection & Readiness Validation

Extracts clean, validated live closed trades from signals.db and checks whether
the dataset meets minimum quality gates for safe OGD retraining.

Design constraints:
  - Does NOT trigger OGD weight updates — retraining is the caller's responsibility.
  - Does NOT modify strategy logic or gate parameters.
  - Separates live data from backtest/bootstrap data by table (signals vs backtest_signals).
  - Excludes test tokens (names starting with '_').
  - Handles legacy feature_scores_json format (pre-fix: text quality strings mixed with
    float scores) via sanitisation, so older records are not silently dropped.

Minimum retraining gates (all must pass for ok=True):
  min_total          — ≥ 30 validated records total (matches OGD_MIN_SAMPLES)
  min_tokens         — ≥ 2 tokens each with ≥ 10 records (multi-token generalisation)
  min_loss_fraction  — ≥ 20% LOSS/EXPIRED outcomes (OGD needs negative signal)
  buy_sell_balance   — minority direction ≥ 10% of total (avoid one-sided gradient)
  session_diversity  — no single session > 90% of records
  fvg_diversity      — no single FVG quality value > 90% of records
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

_ROOT   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_ROOT, "data", "signals.db")

# ── Valid value sets ──────────────────────────────────────────────────────────
VALID_OUTCOMES   = {"WIN", "LOSS", "PARTIAL", "PARTIAL_TP1", "PARTIAL_TP2", "EXPIRED"}
VALID_DIRECTIONS = {"BUY", "SELL"}
VALID_FVG        = {"HIGH", "MEDIUM", "LOW"}        # NONE excluded — no FVG = incomplete
VALID_MSS        = {"HIGH", "MEDIUM", "LOW"}
VALID_SESSIONS   = {"NY_AM_KZ", "LONDON_KZ", "ASIA_KZ", "OVERNIGHT"}
VALID_DR         = {"PREMIUM", "DISCOUNT", "EQUILIBRIUM", "UNKNOWN"}

# The 6 canonical OGD feature keys stored in feature_scores_json
REQUIRED_OGD_FEATURES = {
    "fvg_quality", "mss_quality", "session",
    "confidence", "trend_strength", "dr_location",
}

# Score lookup tables used to sanitise legacy text values in feature_scores_json
# (pre-fix records stored "HIGH"/"MEDIUM" strings instead of floats for 3 of 6 keys)
_QUALITY_SCORE = {"HIGH": 1.0, "MEDIUM": 0.75, "LOW": 0.50, "NONE": 0.0}
_SESSION_SCORE = {
    "NY_AM_KZ": 1.0, "LONDON_KZ": 0.85, "ASIA_KZ": 0.5, "OVERNIGHT": 0.0,
}
_TEXT_FALLBACK: Dict[str, Dict[str, float]] = {
    "fvg_quality": _QUALITY_SCORE,
    "mss_quality": _QUALITY_SCORE,
    "session":     _SESSION_SCORE,
}

# ── Minimum retraining quality gates ─────────────────────────────────────────
GATE_MIN_TOTAL          = 30     # total validated records (= OGD_MIN_SAMPLES threshold)
GATE_MIN_PER_TOKEN      = 10     # minimum per-token to count toward GATE_MIN_TOKENS
GATE_MIN_TOKENS         = 2      # tokens meeting GATE_MIN_PER_TOKEN
GATE_MIN_LOSS_FRACTION  = 0.20   # fraction of LOSS + EXPIRED outcomes
GATE_MIN_BUY_FRACTION   = 0.10   # minority direction fraction
GATE_MAX_SINGLE_SESSION = 0.90   # no single session may dominate
GATE_MAX_SINGLE_FVG     = 0.90   # no single FVG quality may dominate


# ── DB connection ─────────────────────────────────────────────────────────────
def _connect(db_path: str = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ── SQL VIEW for dashboard use ────────────────────────────────────────────────
def ensure_live_training_view(db_path: str = None) -> None:
    """Create the live_training_records SQL VIEW if the underlying tables exist.

    The VIEW joins signals + results to expose one row per closed live trade with
    r_multiple pre-computed. Safe to call even when signals/results do not yet exist.
    """
    sql = """
        CREATE VIEW live_training_records AS
        SELECT
            s.id,
            s.token,
            s.signal                                              AS direction,
            s.confidence,
            s.trend_1h,
            s.session,
            s.dr_location,
            s.mss_quality,
            s.fvg_quality,
            s.sl_pct,
            s.tp1_pct,
            s.feature_scores_json,
            s.strategy_version,
            s.timestamp                                           AS entry_time,
            s.hour_utc,
            r.result                                              AS outcome,
            r.profit_pct,
            r.closed_at                                           AS close_time,
            CASE WHEN s.sl_pct > 0
                 THEN ROUND(r.profit_pct / s.sl_pct, 3)
                 ELSE NULL END                                    AS r_multiple
        FROM signals s
        JOIN results r ON s.id = r.signal_id
        WHERE s.status  = 'CLOSED'
          AND r.result  IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
          AND r.closed_at IS NOT NULL
          AND SUBSTR(s.token, 1, 1) != '_'
    """
    try:
        conn = sqlite3.connect(db_path or DB_PATH, timeout=30)
        conn.execute("DROP VIEW IF EXISTS live_training_records")
        conn.execute(sql)
        conn.commit()
        conn.close()
    except Exception:
        pass  # tables may not exist yet; view is created on next successful call


# ── Feature score parsing ─────────────────────────────────────────────────────
def _parse_feature_scores(fs_json: str) -> Tuple[Optional[Dict[str, float]], str]:
    """Parse feature_scores_json and return (clean_dict, error_string).

    Handles two formats:
      New (post-fix): all 6 OGD keys are normalised floats in [0, 1].
      Legacy (pre-fix): fvg_quality / mss_quality / session may be stored as
          text strings ("HIGH", "NY_AM_KZ", …). Sanitises using lookup tables.

    Returns (None, reason) on any failure.
    """
    if not fs_json:
        return None, "missing_feature_scores_json"
    try:
        raw = json.loads(fs_json)
    except (json.JSONDecodeError, TypeError):
        return None, "feature_scores_json_parse_error"

    clean: Dict[str, float] = {}
    for feat in REQUIRED_OGD_FEATURES:
        v = raw.get(feat)
        if v is None:
            return None, f"missing_feature:{feat}"
        if isinstance(v, str):
            lookup = _TEXT_FALLBACK.get(feat)
            if lookup and v in lookup:
                clean[feat] = lookup[v]
            else:
                return None, f"unrecognised_feature_value:{feat}={v!r}"
        elif isinstance(v, (int, float)):
            score = float(v)
            if not (0.0 <= score <= 1.0):
                return None, f"feature_score_out_of_range:{feat}={score}"
            clean[feat] = score
        else:
            return None, f"invalid_feature_type:{feat}={type(v).__name__}"
    return clean, ""


# ── Per-record validation ─────────────────────────────────────────────────────
def validate_record(row: dict) -> Tuple[bool, str]:
    """Validate one raw DB row for OGD retraining eligibility.

    Returns (True, "") if the record is clean, or (False, reason) if not.
    All required fields must be present, have known values, and be self-consistent.

    Public (not prefixed with _) so the test suite can call it directly.
    """
    token = row.get("token") or ""
    if token.startswith("_"):
        return False, f"test_token:{token}"

    direction = row.get("direction") or row.get("signal") or ""
    if direction not in VALID_DIRECTIONS:
        return False, f"invalid_direction:{direction!r}"

    outcome = row.get("outcome") or row.get("result") or ""
    if outcome not in VALID_OUTCOMES:
        return False, f"invalid_outcome:{outcome!r}"

    fvg = row.get("fvg_quality") or ""
    if fvg not in VALID_FVG:
        return False, f"invalid_fvg_quality:{fvg!r}"

    mss = row.get("mss_quality") or ""
    if mss not in VALID_MSS:
        return False, f"invalid_mss_quality:{mss!r}"

    session = row.get("session") or ""
    if session not in VALID_SESSIONS:
        return False, f"invalid_session:{session!r}"

    dr = row.get("dr_location") or ""
    if dr not in VALID_DR:
        return False, f"invalid_dr_location:{dr!r}"

    try:
        conf = int(row.get("confidence") or 0)
        if not (0 <= conf <= 10):
            return False, f"confidence_out_of_range:{conf}"
    except (TypeError, ValueError):
        return False, "confidence_not_integer"

    try:
        sl_pct = float(row.get("sl_pct") or 0)
        if sl_pct <= 0:
            return False, "sl_pct_zero_or_negative"
    except (TypeError, ValueError):
        return False, "sl_pct_invalid"

    close_time = row.get("close_time") or row.get("closed_at")
    if not close_time:
        return False, "not_closed"

    ogd_scores, err = _parse_feature_scores(row.get("feature_scores_json") or "")
    if ogd_scores is None:
        return False, err

    return True, ""


# ── Clean record builder ──────────────────────────────────────────────────────
def _make_clean_record(row: dict) -> dict:
    """Build a clean, flat training dict from a validated raw DB row.

    r_multiple is the magnitude (always positive); direction of P&L is encoded
    in outcome ('LOSS' → bad, 'WIN' → good). Signed R is not used by OGD directly.
    """
    ogd_scores, _ = _parse_feature_scores(row.get("feature_scores_json") or "")
    sl_pct      = float(row.get("sl_pct") or 0)
    profit_pct  = float(row.get("profit_pct") or 0)
    r_multiple  = round(abs(profit_pct) / sl_pct, 3) if sl_pct > 0 else None

    return {
        "signal_id":        row.get("id"),
        "token":            row.get("token"),
        "direction":        row.get("direction") or row.get("signal"),
        "outcome":          row.get("outcome") or row.get("result"),
        "confidence":       int(row.get("confidence") or 0),
        "session":          row.get("session"),
        "dr_location":      row.get("dr_location"),
        "mss_quality":      row.get("mss_quality"),
        "fvg_quality":      row.get("fvg_quality"),
        "trend_1h":         row.get("trend_1h"),
        # Pre-computed OGD feature scores (normalised floats)
        "fvg_score":        float((ogd_scores or {}).get("fvg_quality", 0.0)),
        "mss_score":        float((ogd_scores or {}).get("mss_quality", 0.0)),
        "session_score":    float((ogd_scores or {}).get("session", 0.0)),
        "conf_score":       float((ogd_scores or {}).get("confidence", 0.0)),
        "trend_strength":   float((ogd_scores or {}).get("trend_strength", 0.0)),
        "dr_score":         float((ogd_scores or {}).get("dr_location", 0.0)),
        "ogd_scores":       ogd_scores or {},
        # Risk metadata
        "sl_pct":           sl_pct,
        "profit_pct":       profit_pct,
        "r_multiple":       r_multiple,
        # Timing
        "entry_time":       row.get("entry_time") or row.get("timestamp"),
        "close_time":       row.get("close_time") or row.get("closed_at"),
        "hour_utc":         row.get("hour_utc"),
        "strategy_version": row.get("strategy_version"),
    }


# ── Main extraction API ───────────────────────────────────────────────────────
def get_training_records(
    strategy_version: Optional[str] = None,
    min_date: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Tuple[List[dict], List[dict]]:
    """Extract and validate all live closed trades from signals.db.

    Returns (valid_records, rejected_records).
      valid_records   — list of clean dicts ready for OGD retraining analysis
      rejected_records — list of {signal_id, token, outcome, reason} for excluded rows

    Args:
        strategy_version: if set, restrict to signals with this exact strategy_version
        min_date:         if set, restrict to trades closed on or after this ISO date
        db_path:          override DB path (used by tests with temp databases)
    """
    ensure_live_training_view(db_path)

    query = """
        SELECT
            s.id,
            s.token,
            s.signal              AS direction,
            s.confidence,
            s.trend_1h,
            s.session,
            s.dr_location,
            s.mss_quality,
            s.fvg_quality,
            s.sl_pct,
            s.tp1_pct,
            s.feature_scores_json,
            s.strategy_version,
            s.timestamp           AS entry_time,
            s.hour_utc,
            r.result              AS outcome,
            r.profit_pct,
            r.closed_at           AS close_time
        FROM signals s
        JOIN results r ON s.id = r.signal_id
        WHERE s.status   = 'CLOSED'
          AND r.result   IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
          AND r.closed_at IS NOT NULL
          AND SUBSTR(s.token, 1, 1) != '_'
    """
    params: list = []
    if strategy_version:
        query += " AND s.strategy_version = ?"
        params.append(strategy_version)
    if min_date:
        query += " AND r.closed_at >= ?"
        params.append(min_date)
    query += " ORDER BY r.closed_at ASC"

    try:
        conn = _connect(db_path)
        rows = conn.execute(query, params).fetchall()
        conn.close()
    except Exception as e:
        print(f"[PHASE2] get_training_records DB error: {e}")
        return [], []

    valid: List[dict] = []
    rejected: List[dict] = []
    for row in rows:
        row_dict = dict(row)
        ok, reason = validate_record(row_dict)
        if ok:
            valid.append(_make_clean_record(row_dict))
        else:
            rejected.append({
                "signal_id": row_dict.get("id"),
                "token":     row_dict.get("token"),
                "outcome":   row_dict.get("outcome"),
                "reason":    reason,
            })
    return valid, rejected


# ── Readiness gate evaluation ─────────────────────────────────────────────────
def check_readiness(
    records: Optional[List[dict]] = None,
    db_path: Optional[str] = None,
) -> dict:
    """Check whether the live dataset passes all minimum quality gates for OGD retraining.

    Returns:
        ok            — True only if every gate passes
        gates         — {gate_name: {passed, value, threshold, detail}}
        n_valid       — validated record count
        n_rejected    — rejected record count (None when records= is passed directly)
        ready_tokens  — list of tokens meeting GATE_MIN_PER_TOKEN
        blockers      — names of failed gates
    """
    n_rejected = None
    if records is None:
        records, rejected_list = get_training_records(db_path=db_path)
        n_rejected = len(rejected_list)

    n = len(records)
    gates: Dict[str, dict] = {}

    # Gate 1: minimum total validated records
    gates["min_total"] = {
        "passed":    n >= GATE_MIN_TOTAL,
        "value":     n,
        "threshold": GATE_MIN_TOTAL,
        "detail":    f"{n} validated records (need {GATE_MIN_TOTAL})",
    }

    # Short-circuit: no records means all remaining gates also fail
    if n == 0:
        for name in ("min_tokens", "min_loss_fraction",
                     "buy_sell_balance", "session_diversity", "fvg_diversity"):
            gates[name] = {
                "passed":    False,
                "value":     0,
                "threshold": 0,
                "detail":    "no data",
            }
        return {
            "ok":          False,
            "gates":       gates,
            "n_valid":     0,
            "n_rejected":  n_rejected,
            "ready_tokens": [],
            "blockers":    list(gates.keys()),
        }

    # Per-token record counts
    token_counts: Dict[str, int] = {}
    for r in records:
        t = r["token"]
        token_counts[t] = token_counts.get(t, 0) + 1
    ready_tokens = sorted(t for t, c in token_counts.items() if c >= GATE_MIN_PER_TOKEN)

    # Gate 2: token coverage
    gates["min_tokens"] = {
        "passed":    len(ready_tokens) >= GATE_MIN_TOKENS,
        "value":     len(ready_tokens),
        "threshold": GATE_MIN_TOKENS,
        "detail":    (f"{len(ready_tokens)} token(s) with "
                      f">={GATE_MIN_PER_TOKEN} records (need {GATE_MIN_TOKENS})"),
    }

    # Gate 3: loss fraction — OGD needs negative examples to learn avoidance
    loss_outcomes = {"LOSS", "EXPIRED"}
    n_losses  = sum(1 for r in records if r["outcome"] in loss_outcomes)
    loss_frac = n_losses / n
    gates["min_loss_fraction"] = {
        "passed":    loss_frac >= GATE_MIN_LOSS_FRACTION,
        "value":     round(loss_frac, 4),
        "threshold": GATE_MIN_LOSS_FRACTION,
        "detail":    (f"{n_losses}/{n} LOSS+EXPIRED ({loss_frac:.1%}) "
                      f"(need >={GATE_MIN_LOSS_FRACTION:.0%})"),
    }

    # Gate 4: BUY/SELL balance — one-sided gradient causes weight collapse
    n_buys         = sum(1 for r in records if r["direction"] == "BUY")
    n_sells        = n - n_buys
    minority_frac  = min(n_buys, n_sells) / n
    gates["buy_sell_balance"] = {
        "passed":    minority_frac >= GATE_MIN_BUY_FRACTION,
        "value":     round(minority_frac, 4),
        "threshold": GATE_MIN_BUY_FRACTION,
        "detail":    (f"BUY={n_buys} SELL={n_sells}, "
                      f"minority={minority_frac:.1%} (need >={GATE_MIN_BUY_FRACTION:.0%})"),
    }

    # Gate 5: session diversity — prevents single-session overfitting
    session_counts: Dict[str, int] = {}
    for r in records:
        s = r.get("session") or "UNKNOWN"
        session_counts[s] = session_counts.get(s, 0) + 1
    max_sess_frac = max(c / n for c in session_counts.values())
    top_session   = max(session_counts, key=session_counts.__getitem__)
    gates["session_diversity"] = {
        "passed":    max_sess_frac <= GATE_MAX_SINGLE_SESSION,
        "value":     round(max_sess_frac, 4),
        "threshold": GATE_MAX_SINGLE_SESSION,
        "detail":    (f"Dominant session: {top_session} = {max_sess_frac:.1%} "
                      f"(limit {GATE_MAX_SINGLE_SESSION:.0%})"),
    }

    # Gate 6: FVG quality diversity — prevents FVG-only learning
    fvg_counts: Dict[str, int] = {}
    for r in records:
        f = r.get("fvg_quality") or "UNKNOWN"
        fvg_counts[f] = fvg_counts.get(f, 0) + 1
    max_fvg_frac = max(c / n for c in fvg_counts.values())
    top_fvg      = max(fvg_counts, key=fvg_counts.__getitem__)
    gates["fvg_diversity"] = {
        "passed":    max_fvg_frac <= GATE_MAX_SINGLE_FVG,
        "value":     round(max_fvg_frac, 4),
        "threshold": GATE_MAX_SINGLE_FVG,
        "detail":    (f"Dominant FVG quality: {top_fvg} = {max_fvg_frac:.1%} "
                      f"(limit {GATE_MAX_SINGLE_FVG:.0%})"),
    }

    blockers = [name for name, g in gates.items() if not g["passed"]]
    return {
        "ok":          len(blockers) == 0,
        "gates":       gates,
        "n_valid":     n,
        "n_rejected":  n_rejected,
        "ready_tokens": ready_tokens,
        "blockers":    blockers,
    }


# ── Training dataset report ───────────────────────────────────────────────────
def training_report(
    records: Optional[List[dict]] = None,
    db_path: Optional[str] = None,
) -> str:
    """Generate a human-readable training dataset quality report.

    Covers: record counts, per-token stats, direction/outcome/feature distributions,
    and readiness gate pass/fail table.
    """
    rejected_list: List[dict] = []
    if records is None:
        records, rejected_list = get_training_records(db_path=db_path)

    readiness = check_readiness(records)
    n = len(records)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "=" * 62,
        "  LIVE TRAINING DATASET — Phase 2 Step 1 Report",
        f"  Generated: {ts}",
        "=" * 62,
        "",
        f"  Valid records:    {n}",
        f"  Rejected records: {len(rejected_list)}",
        "",
    ]

    if n == 0:
        lines += [
            "  No valid training records found.",
            "  The bot must generate and close live signals before",
            "  OGD retraining can be evaluated.",
            "",
            "  Retraining status: NOT READY",
            "=" * 62,
        ]
        return "\n".join(lines)

    # ── Per-token breakdown ───────────────────────────────────
    lines.append("  Trades per Token")
    lines.append("  " + "-" * 58)
    token_stats: Dict[str, dict] = {}
    for r in records:
        t = r["token"]
        if t not in token_stats:
            token_stats[t] = {"n": 0, "wins": 0, "buys": 0, "sells": 0}
        token_stats[t]["n"] += 1
        if r["outcome"] in ("WIN", "PARTIAL_TP1", "PARTIAL_TP2", "PARTIAL"):
            token_stats[t]["wins"] += 1
        if r["direction"] == "BUY":
            token_stats[t]["buys"] += 1
        else:
            token_stats[t]["sells"] += 1

    for tok in sorted(token_stats):
        s   = token_stats[tok]
        wr  = s["wins"] / s["n"]
        tag = "OK" if s["n"] >= GATE_MIN_PER_TOKEN else f"low (need {GATE_MIN_PER_TOKEN})"
        lines.append(
            f"    {tok:<8} n={s['n']:>4}  WR={wr:.1%}"
            f"  BUY={s['buys']} SELL={s['sells']}  [{tag}]"
        )

    # ── Direction balance ─────────────────────────────────────
    n_buys  = sum(1 for r in records if r["direction"] == "BUY")
    n_sells = n - n_buys
    lines += [
        "",
        "  Direction Balance",
        "  " + "-" * 58,
        f"    BUY:  {n_buys:>4}  ({n_buys/n:.1%})",
        f"    SELL: {n_sells:>4}  ({n_sells/n:.1%})",
    ]

    # ── Outcome distribution ──────────────────────────────────
    outcome_counts: Dict[str, int] = {}
    for r in records:
        outcome_counts[r["outcome"]] = outcome_counts.get(r["outcome"], 0) + 1
    lines += ["", "  Outcome Distribution", "  " + "-" * 58]
    for outcome in ["WIN", "PARTIAL_TP2", "PARTIAL_TP1", "PARTIAL", "EXPIRED", "LOSS"]:
        c = outcome_counts.get(outcome, 0)
        if c:
            lines.append(f"    {outcome:<14} {c:>4}  ({c/n:.1%})")

    # ── FVG quality distribution ──────────────────────────────
    fvg_counts: Dict[str, int] = {}
    for r in records:
        fvg_counts[r.get("fvg_quality") or "?"] = (
            fvg_counts.get(r.get("fvg_quality") or "?", 0) + 1
        )
    lines += ["", "  FVG Quality Distribution", "  " + "-" * 58]
    for q in ["HIGH", "MEDIUM", "LOW"]:
        c = fvg_counts.get(q, 0)
        lines.append(f"    {q:<8} {c:>4}  ({c/n:.1%})")

    # ── MSS quality distribution ──────────────────────────────
    mss_counts: Dict[str, int] = {}
    for r in records:
        mss_counts[r.get("mss_quality") or "?"] = (
            mss_counts.get(r.get("mss_quality") or "?", 0) + 1
        )
    lines += ["", "  MSS Quality Distribution", "  " + "-" * 58]
    for q in ["HIGH", "MEDIUM", "LOW"]:
        c = mss_counts.get(q, 0)
        lines.append(f"    {q:<8} {c:>4}  ({c/n:.1%})")

    # ── Session distribution ──────────────────────────────────
    session_counts: Dict[str, int] = {}
    for r in records:
        session_counts[r.get("session") or "?"] = (
            session_counts.get(r.get("session") or "?", 0) + 1
        )
    lines += ["", "  Session Distribution", "  " + "-" * 58]
    for s in ["NY_AM_KZ", "LONDON_KZ", "ASIA_KZ", "OVERNIGHT"]:
        c = session_counts.get(s, 0)
        if c:
            lines.append(f"    {s:<14} {c:>4}  ({c/n:.1%})")

    # ── DR location distribution ──────────────────────────────
    dr_counts: Dict[str, int] = {}
    for r in records:
        dr_counts[r.get("dr_location") or "?"] = (
            dr_counts.get(r.get("dr_location") or "?", 0) + 1
        )
    lines += ["", "  DR Location Distribution", "  " + "-" * 58]
    for dr in ["DISCOUNT", "EQUILIBRIUM", "PREMIUM", "UNKNOWN"]:
        c = dr_counts.get(dr, 0)
        if c:
            lines.append(f"    {dr:<14} {c:>4}  ({c/n:.1%})")

    # ── Readiness gates ───────────────────────────────────────
    lines += ["", "  Retraining Readiness Gates", "  " + "-" * 58]
    for gate_name, gate in readiness["gates"].items():
        status = "PASS" if gate["passed"] else "FAIL"
        lines.append(f"    [{status}] {gate_name}: {gate['detail']}")

    lines.append("")
    overall = "READY" if readiness["ok"] else "NOT READY"
    lines.append(f"  Overall retraining status: {overall}")
    if readiness["blockers"]:
        lines.append(f"  Blockers: {', '.join(readiness['blockers'])}")
    if readiness["ready_tokens"]:
        lines.append(
            f"  Tokens ready for retraining: {', '.join(readiness['ready_tokens'])}"
        )

    # ── Rejection summary ─────────────────────────────────────
    if rejected_list:
        lines += ["", "  Rejection Summary", "  " + "-" * 58]
        reason_counts: Dict[str, int] = {}
        for r in rejected_list:
            reason_counts[r["reason"]] = reason_counts.get(r["reason"], 0) + 1
        for reason, c in sorted(reason_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {c:>3}x  {reason}")

    lines.append("=" * 62)
    return "\n".join(lines)
