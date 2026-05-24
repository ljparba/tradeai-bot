"""
QuantStats integration for tracker.py.

Provides:
- get_returns_series(source, run_id): pandas Series of returns by closed-at datetime
- get_summary(source, run_id):        dict of key risk metrics (Sharpe, Sortino, Calmar, etc.)
- get_tearsheet_html(source, run_id): full quantstats HTML tearsheet (cached on disk)

Sources:
  - "paper":    LIVE/PAPER signals from signals + results tables
  - "backtest": backtest_signals for a given run_id (defaults to latest)
"""
import os
import sqlite3
from typing import Optional, Dict, Any

_ROOT       = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(_ROOT, "data", "signals.db")
CACHE_DIR   = os.path.join(_ROOT, "data", "quantstats_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _connect():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _safe_call(fn, *args, **kwargs):
    try:
        v = fn(*args, **kwargs)
        if v is None:
            return None
        if hasattr(v, "item"):
            v = v.item()
        if isinstance(v, float):
            if v != v or v in (float("inf"), float("-inf")):
                return None
            return round(v, 4)
        return v
    except Exception:
        return None


def get_returns_series(source: str = "paper", run_id: Optional[int] = None):
    """Return a pandas Series of fractional returns indexed by datetime."""
    import pandas as pd
    con = _connect()
    try:
        if source == "backtest":
            if run_id is None:
                row = con.execute("SELECT MAX(run_id) FROM backtest_signals").fetchone()
                run_id = int(row[0] or 0)
            rows = con.execute(
                """SELECT ts, net_tp1_pct, net_sl_pct, outcome, net_rr1
                   FROM backtest_signals
                   WHERE run_id=? AND outcome IS NOT NULL
                   ORDER BY ts ASC""",
                (run_id,),
            ).fetchall()
            data = []
            for ts, tp, sl, outcome, rr in rows:
                if outcome in ("WIN", "PARTIAL", "PARTIAL_TP1", "PARTIAL_TP2"):
                    r = (tp or 0.0) / 100.0
                elif outcome == "LOSS":
                    r = (sl or 0.0) / 100.0
                else:
                    r = 0.0
                data.append((ts, r))
        else:
            rows = con.execute(
                """SELECT COALESCE(r.closed_at, s.timestamp) AS ts, r.profit_pct
                   FROM results r
                   JOIN signals s ON r.signal_id = s.id
                   WHERE r.profit_pct IS NOT NULL
                   ORDER BY ts ASC"""
            ).fetchall()
            data = [(ts, (p or 0.0) / 100.0) for ts, p in rows]
    finally:
        con.close()

    if not data:
        return pd.Series(dtype="float64", name="returns")
    idx = pd.to_datetime([d[0] for d in data], utc=True, errors="coerce")
    s = pd.Series([d[1] for d in data], index=idx, name="returns").dropna()
    s = s[~s.index.isna()]
    s = s.groupby(s.index.date).sum()
    s.index = pd.to_datetime(s.index)
    return s


def _periods_per_year(s) -> int:
    span_days = (s.index.max() - s.index.min()).days
    if span_days <= 0:
        return 252
    return max(1, int(round(len(s) * 365.0 / span_days)))


def get_summary(source: str = "paper", run_id: Optional[int] = None) -> Dict[str, Any]:
    import quantstats as qs
    s = get_returns_series(source, run_id)
    if s.empty or len(s) < 2:
        return {
            "source": source, "run_id": run_id, "n": int(len(s)),
            "ok": False, "reason": "insufficient_data",
            "metrics": {}
        }
    rfr = 0.0
    pp = _periods_per_year(s)
    metrics = {
        "n_trade_days":          int(len(s)),
        "periods_per_year":      pp,
        "cumulative_return_pct": _safe_call(lambda x: float(qs.stats.comp(x)) * 100, s),
        "cagr_pct":              _safe_call(lambda x: float(qs.stats.cagr(x, periods=pp)) * 100, s),
        "volatility_ann_pct":    _safe_call(lambda x: float(qs.stats.volatility(x, periods=pp, annualize=True)) * 100, s),
        "sharpe":                _safe_call(lambda x: qs.stats.sharpe(x, rf=rfr, periods=pp), s),
        "sortino":               _safe_call(lambda x: qs.stats.sortino(x, rf=rfr, periods=pp), s),
        "adjusted_sortino":      _safe_call(lambda x: qs.stats.adjusted_sortino(x, rf=rfr, periods=pp), s),
        "calmar":                _safe_call(lambda x: qs.stats.calmar(x, periods=pp), s),
        "omega":                 _safe_call(qs.stats.omega, s),
        "kelly_criterion":       _safe_call(qs.stats.kelly_criterion, s),
        "profit_factor":         _safe_call(qs.stats.profit_factor, s),
        "common_sense_ratio":    _safe_call(qs.stats.common_sense_ratio, s),
        "tail_ratio":            _safe_call(qs.stats.tail_ratio, s),
        "max_drawdown_pct":      _safe_call(lambda x: float(qs.stats.max_drawdown(x)) * 100, s),
        "value_at_risk_pct":     _safe_call(lambda x: float(qs.stats.value_at_risk(x)) * 100, s),
        "cvar_pct":              _safe_call(lambda x: float(qs.stats.cvar(x)) * 100, s),
        "win_rate_pct":          _safe_call(lambda x: float(qs.stats.win_rate(x)) * 100, s),
        "avg_win_pct":           _safe_call(lambda x: float(qs.stats.avg_win(x)) * 100, s),
        "avg_loss_pct":          _safe_call(lambda x: float(qs.stats.avg_loss(x)) * 100, s),
        "best_day_pct":          _safe_call(lambda x: float(qs.stats.best(x)) * 100, s),
        "worst_day_pct":         _safe_call(lambda x: float(qs.stats.worst(x)) * 100, s),
        "skew":                  _safe_call(qs.stats.skew, s),
        "kurtosis":              _safe_call(qs.stats.kurtosis, s),
    }
    first_ts = s.index.min().isoformat()
    last_ts  = s.index.max().isoformat()
    return {
        "source": source, "run_id": run_id, "n": int(len(s)),
        "first_ts": first_ts, "last_ts": last_ts,
        "ok": True, "metrics": metrics,
    }


def get_tearsheet_html(source: str = "paper", run_id: Optional[int] = None) -> Optional[str]:
    import quantstats as qs
    s = get_returns_series(source, run_id)
    if s.empty or len(s) < 2:
        return None
    cache_key = f"{source}_{run_id or 'paper'}_{len(s)}_{s.index.max().date()}.html"
    cache_path = os.path.join(CACHE_DIR, cache_key)
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()
    title = f"TradeAI — {source.title()}" + (f" Run {run_id}" if source == "backtest" else "")
    try:
        qs.reports.html(s, output=cache_path, title=title)
    except Exception as e:
        return f"<html><body><h1>QuantStats render failed</h1><pre>{e}</pre></body></html>"
    with open(cache_path, "r", encoding="utf-8") as f:
        return f.read()
