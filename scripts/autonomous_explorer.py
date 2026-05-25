"""
Autonomous Explorer — Phases 1-4 complete (2026-05-24).

Bayesian (Optuna) search over the existing backtest engine.
Persists every trial to data/explorer_learning.db.
Honest CPCV+DSR gates per trial. Auto-promotes Pareto winners with strict
reproducibility + daily cap + 24h soak guards. NEVER flips LIVE.

Phase 1 — Core loop:
  - Optuna TPE sampler, persistent study, trials ledger DB,
    env-overrides for 4 ICT params in ict_engine.py.

Phase 2 — Anti-overfit + observability (operator-triggered, no scheduler):
  - PidFile collision guard, pre-cache warm + frozen snapshot,
    4 anti-overfit trip conditions (basin lost, consecutive errors,
    DSR drop vs pin, code drift, sr_trial_std jump),
    Telegram notify on start/done/pause/error, --status command,
    data/explorer_session.json for live state.

Phase 3 — Auto-promotion + Pareto archive:
  - 8-criteria eligibility gate + reproducibility re-run with config_hash
    match + 2/day cap + 24h soak. data/pareto_archive.json (top-10
    non-dominated). data/promotion_log.json (30-entry rolling audit).
    promote_baseline.py --auto and --rollback-to-run flags. Cross-config
    sr_trial_std auto-refreshed after every promotion.

Phase 4 — Dashboard + on-demand digest:
  - 4 new tracker.py routes (/api/explorer/status, /pareto, /promotions,
    /trials), Auto-Explorer tab in tracker_html.py (auto-refresh 15s
    while visible), --digest [hours] CLI command.

Post-audit fixes (2026-05-24):
  - C1: max_id snapshot before backtest, scoped lookup via WHERE id > ?
    prevents accidentally deleting an operator's concurrent backtest row.
  - H1: try/finally cleanup wrapper prevents orphan backtest_runs rows
    on exception paths.

Search space and gates are documented in docs/AUTONOMOUS_EXPLORER_DESIGN.md §4.

Usage:
    python scripts/autonomous_explorer.py --trials 30 --study-name overnight_v1
    python scripts/autonomous_explorer.py --status
    python scripts/autonomous_explorer.py --digest 24
    python scripts/autonomous_explorer.py --list-recent 20
    python scripts/autonomous_explorer.py --best
"""
import argparse
import hashlib
import html
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

import optuna

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH    = os.path.join(_ROOT, "data", "signals.db")
LEARN_PATH = os.path.join(_ROOT, "data", "explorer_learning.db")
OPTUNA_DB  = os.path.join(_ROOT, "data", "optuna_study.db")
PID_PATH   = os.path.join(_ROOT, "data", "explorer.pid")
SESSION_PATH    = os.path.join(_ROOT, "data", "explorer_session.json")
PARETO_PATH     = os.path.join(_ROOT, "data", "pareto_archive.json")
PROMOTION_LOG   = os.path.join(_ROOT, "data", "promotion_log.json")
PIN_PATH        = os.path.join(_ROOT, "data", "baseline_pin.json")

# Files whose hash defines the "code state" — if any change mid-session, abort
CODE_FILES = ["config.py", "backtest.py", "ict_engine.py"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    trial_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    study_name      TEXT,
    optuna_trial_no INTEGER,
    started_at      TEXT,
    ended_at        TEXT,
    walltime_s      REAL,
    params_json     TEXT,
    config_hash     TEXT,
    backtest_run_id INTEGER,
    n               INTEGER,
    wr              REAL,
    cpcv_mean       REAL,
    cpcv_std        REAL,
    cpcv_q05        REAL,
    sharpe          REAL,
    dsr             REAL,
    dsr_proxy_used  INTEGER,
    verdict         TEXT,
    reject_reason   TEXT,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_trials_verdict ON trials(verdict);
CREATE INDEX IF NOT EXISTS idx_trials_cpcv_mean ON trials(cpcv_mean DESC);
"""

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


# PASS gates for a trial. Defaults match the "high-quality / low-frequency"
# Run-168 profile. All four are env-overridable so the operator can run
# alternative search profiles (e.g. high-frequency / moderate-WR) in a
# separate explorer session without touching this file:
#
#   EXPLORER_N_MIN=180     EXPLORER_WR_MIN=55     EXPLORER_DSR_MIN=80
#
# A trial PASSES only if all four are satisfied (see _verdict in this file).
GATES = {
    "n_min":             _env_int("EXPLORER_N_MIN",       30),    # >= signals/365d
    "cpcv_mean_min_pct": _env_float("EXPLORER_WR_MIN",    60.0),  # >= CPCV mean WR %
    "cpcv_q05_min_pct":  _env_float("EXPLORER_Q05_MIN",   50.0),  # >= worst-fold WR %
    "dsr_min_pct":       _env_float("EXPLORER_DSR_MIN",   95.0),  # >= Deflated Sharpe %
}

ANTI_PATTERN_LOCKS = {
    "ICT_SWING_N":      2,    # 3+ proven net-negative (Cycle 1b P-1 + 1c TP-5c')
    "ICT_MIN_RR_GATE":  1.5,  # >=2.0 catastrophic per Cycle 1b
}


def _assert_anti_pattern_locks() -> None:
    """Verify that the anti-patterns documented in ANTI_PATTERN_LOCKS are
    still hardcoded (not env-overridable) in ict_engine.py. Without this
    check, a future env-override addition would silently let the explorer
    search the locked region. Called once at session start.
    """
    sys.path.insert(0, _ROOT)
    import importlib, ict_engine
    importlib.reload(ict_engine)
    for k, expected in ANTI_PATTERN_LOCKS.items():
        actual = getattr(ict_engine, k, None)
        if actual is None:
            raise RuntimeError(f"anti-pattern check: {k} not found in ict_engine.py")
        if actual != expected:
            raise RuntimeError(
                f"anti-pattern violation: ict_engine.{k}={actual} "
                f"but ANTI_PATTERN_LOCKS expects {expected}. "
                f"Either update the lock or revert ict_engine.py."
            )
        # Verify env-override hasn't been added (would let Optuna change it)
        if k in os.environ:
            raise RuntimeError(
                f"anti-pattern violation: env var {k}={os.environ[k]} is set. "
                f"This param is anti-pattern-locked and must not be env-overridable. "
                f"Unset the env var before starting an explorer session."
            )

# Anti-overfit guard thresholds
GUARD = {
    "consecutive_fail_max":     50,    # PAUSE if N consecutive FAIL verdicts
    "sr_trial_std_jump_pct":    25.0,  # PAUSE if cross-config std rises >X% mid-session
    "best_dsr_drop_vs_pin_pp":  5.0,   # PAUSE if best-of-session DSR < pin DSR - X pp
    "consecutive_error_max":    3,     # PAUSE if N consecutive ERROR (timeouts/crashes)
}

# Phase 3 auto-promotion criteria (must ALL pass to promote)
PROMOTE = {
    "cpcv_mean_delta_pp_min":  0.5,    # cpcv_mean must beat pin by ≥ this
    "sharpe_delta_min":        0.02,   # sharpe must beat pin by ≥ this
    "cpcv_std_widen_pp_max":   1.0,    # cpcv_std must NOT widen by more than this
    "cpcv_q05_delta_pp_min":  -1.0,    # q05 must not drop by more than this
    "n_change_pct_max":       20.0,    # n must be within ±this% of baseline
    "dsr_min_pct":            95.0,    # honest DSR floor
    "repro_metric_tolerance":  0.5,    # second run's cpcv_mean must be within ±this pp
    "daily_promotions_max":   2,       # hard cap per UTC day
    "soak_hours_after_promote": 24,    # min hours between auto-promotions
}


def _connect(path=LEARN_PATH):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def _hash_code_files() -> str:
    h = hashlib.sha256()
    for f in CODE_FILES:
        p = os.path.join(_ROOT, f)
        with open(p, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def _read_pin_dsr() -> float:
    """Read pinned baseline DSR from baseline_pin.json (for guard reference)."""
    try:
        with open(os.path.join(_ROOT, "data", "baseline_pin.json")) as f:
            return float((json.load(f).get("expected") or {}).get("dsr_pct") or 0.0)
    except Exception:
        return 0.0


def _read_pin_run() -> int:
    try:
        with open(os.path.join(_ROOT, "data", "baseline_pin.json")) as f:
            return int(json.load(f).get("run_id") or 0)
    except Exception:
        return 0


def _read_cross_config_std() -> float:
    """Read current cross-config sr_trial_std from bot_state for delta comparisons.
    Uses read-only URI to avoid any chance of contending with a concurrent
    writer (e.g., the live bot persisting state)."""
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        row = con.execute(
            "SELECT value FROM bot_state WHERE key='cross_config_sr_trial_std'"
        ).fetchone()
        con.close()
        if row and row[0]:
            return float(json.loads(row[0]).get("value") or 0.0)
    except Exception:
        pass
    return 0.0


# ── PidFile (lightweight, stdlib-only) ──────────────────────────────────────
class _PidFile:
    def __init__(self, path: str = PID_PATH):
        self.path = path

    def acquire(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    pid = int((f.read() or "0").strip())
                # Cross-platform liveness check
                if sys.platform == "win32":
                    try:
                        import ctypes
                        h = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                        if h:
                            ctypes.windll.kernel32.CloseHandle(h)
                            raise RuntimeError(
                                f"explorer already running (pid={pid}). "
                                f"If stale, delete {self.path}"
                            )
                    except OSError:
                        pass
                else:
                    try:
                        os.kill(pid, 0)
                        raise RuntimeError(
                            f"explorer already running (pid={pid}). "
                            f"If stale, delete {self.path}"
                        )
                    except OSError:
                        pass
            except (ValueError, FileNotFoundError):
                pass
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write(str(os.getpid()))

    def release(self) -> None:
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


# ── Telegram notify ─────────────────────────────────────────────────────────
def _h(value) -> str:
    """HTML-escape a value for safe inclusion in <pre>...</pre> blocks."""
    return html.escape(str(value))


def _telegram(html_text: str) -> bool:
    """Send Telegram in HTML parse-mode. Falls back to plain text on parse error."""
    token   = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("CHAT_ID", "")
    if not token or not chat_id:
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": html_text, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.status_code == 200:
            return True
        body = (r.text or "").lower()
        if "can't parse" in body or "parse" in body:
            plain = re.sub(r"<[^>]+>", "", html_text)
            r2 = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": plain},
                timeout=10,
            )
            return r2.status_code == 200
        return False
    except Exception as e:
        print(f"[explorer] telegram send failed: {e}")
        return False


# ── Session state (for --status) ────────────────────────────────────────────
def _write_session(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
        with open(SESSION_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception:
        pass


def _read_session() -> dict:
    try:
        with open(SESSION_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


# ── Pre-cache warm ──────────────────────────────────────────────────────────
def _precache_warm(cache_minutes_max: int = 30) -> None:
    """Run one backtest with current code state to ensure Binance cache is warm
    for all tokens. Cache TTL means stale data is refreshed once at session start,
    then all subsequent trials use cache hits.
    """
    print("[explorer] pre-cache warm — running 1 backtest with current code state")
    sys.stdout.flush()
    env = os.environ.copy()
    started = time.time()
    # Snapshot before so we only clean OUR precache row (FIX C1)
    max_id_before = 0
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        max_id_before = con.execute("SELECT COALESCE(MAX(id), 0) FROM backtest_runs").fetchone()[0]
        con.close()
    except Exception:
        pass
    clear_proc = subprocess.run(
        [sys.executable, os.path.join(_ROOT, "backtest.py"), "--clear-checkpoint"],
        env=env, cwd=_ROOT, capture_output=True, text=True, timeout=120
    )
    if clear_proc.returncode != 0:
        print(f"[explorer] WARN: --clear-checkpoint failed (rc={clear_proc.returncode}); proceeding anyway")
    subprocess.run(
        [sys.executable, os.path.join(_ROOT, "backtest.py")],
        env=env, cwd=_ROOT, capture_output=True, text=True,
        timeout=cache_minutes_max * 60
    )
    elapsed = round(time.time() - started, 1)
    # Clean ONLY rows we created (FIX C1 — don't touch operator runs)
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        new_rows = con.execute(
            "SELECT id FROM backtest_runs WHERE id > ? ORDER BY id DESC",
            (max_id_before,)
        ).fetchall()
        con.close()
        for (rid,) in new_rows:
            _cleanup_run_row(rid)
    except Exception:
        pass
    print(f"[explorer] pre-cache complete in {elapsed}s (cache now warm for session)")
    sys.stdout.flush()


def _suggest_params(trial: optuna.Trial) -> dict:
    return {
        "ICT_SWEEP_LOOKBACK":       trial.suggest_int("ICT_SWEEP_LOOKBACK", 15, 60, step=5),
        "ICT_MSS_HORIZON":          trial.suggest_int("ICT_MSS_HORIZON",    10, 60, step=5),
        "ICT_FVG_MIN_GAP":          trial.suggest_float("ICT_FVG_MIN_GAP", 0.0005, 0.0030, step=0.0001),
        "DEALING_RANGE_LOOKBACK":   trial.suggest_int("DEALING_RANGE_LOOKBACK", 30, 100, step=10),
        "BACKTEST_BIAS_4H_GATE":    trial.suggest_categorical("BACKTEST_BIAS_4H_GATE",  ["none", "loose", "strict"]),
        "BACKTEST_TREND_1H_GATE":   trial.suggest_categorical("BACKTEST_TREND_1H_GATE", ["none", "loose", "strict"]),
        "BACKTEST_FVG_MIN_QUALITY": trial.suggest_categorical("BACKTEST_FVG_MIN_QUALITY", ["LOW", "MEDIUM", "HIGH"]),
        "BACKTEST_MSS_MIN_QUALITY": trial.suggest_categorical("BACKTEST_MSS_MIN_QUALITY", ["LOW", "MEDIUM", "HIGH"]),
    }


def _params_to_env(params: dict) -> dict:
    env = os.environ.copy()
    for k, v in params.items():
        env[k] = str(v)
    return env


def _run_backtest(env: dict, timeout_s: int = 1800) -> dict:
    """Run backtest.py subprocess and return parsed metrics.

    FIX C1 (2026-05-24): captures MAX(backtest_runs.id) BEFORE the subprocess so
    we can identify OUR new row deterministically, even if the operator runs a
    concurrent manual `python backtest.py` from another terminal. Without this,
    `ORDER BY id DESC LIMIT 1` could match the operator's row and our later
    cleanup would silently destroy their data.
    """
    cmd = [sys.executable, os.path.join(_ROOT, "backtest.py")]

    # Snapshot the latest row id BEFORE we kick off our backtest
    max_id_before = 0
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        max_id_before = con.execute(
            "SELECT COALESCE(MAX(id), 0) FROM backtest_runs"
        ).fetchone()[0]
        con.close()
    except Exception:
        pass  # if read fails, max_id_before=0 which is permissive

    started = time.time()
    try:
        proc = subprocess.run(cmd, env=env, cwd=_ROOT,
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "walltime_s": time.time() - started}
    walltime = time.time() - started
    out = proc.stdout or ""
    if proc.returncode != 0:
        return {"error": f"exit={proc.returncode}", "walltime_s": walltime,
                "stderr_tail": (proc.stderr or "")[-500:]}

    def grab(pat, cast=float):
        m = re.search(pat, out)
        return cast(m.group(1)) if m else None

    m = {
        "n":              grab(r"Total:\s+(\d+)\s+signals",     cast=int),
        "wr":             None,
        "cpcv_mean":      grab(r"WR \(CPCV\)\s+mean=([\d.]+)%"),
        "cpcv_std":       grab(r"WR \(CPCV\)\s+mean=[\d.]+%\s+std=([\d.]+)%"),
        "cpcv_q05":       grab(r"q05[=:]\s*([\d.]+)%"),
        "sharpe":         grab(r"Sharpe \(CPCV\)\s+mean=([\d.\-]+)"),
        "dsr":            grab(r"DSR \(multi-test\)\s*=\s*([\d.]+)%"),
        "dsr_proxy_used": 1 if "ANTI-CONSERVATIVE" in out or "within-fold proxy" in out else 0,
        "walltime_s":     round(walltime, 1),
    }
    if m["cpcv_q05"] is None and m["cpcv_mean"] is not None and m["cpcv_std"] is not None:
        m["cpcv_q05"] = round(m["cpcv_mean"] - 1.645 * m["cpcv_std"], 2)

    # Locate OUR row by id > snapshot. If multiple new rows exist, an operator
    # backtest ran concurrently — take the LATEST (which is most likely ours,
    # since we typically finish last) and log a warning.
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        new_rows = con.execute(
            "SELECT id, overall_wr, config_hash FROM backtest_runs "
            "WHERE id > ? ORDER BY id DESC LIMIT 5",
            (max_id_before,)
        ).fetchall()
        con.close()
        if not new_rows:
            m["error"] = "backtest_subprocess_wrote_no_row"
            return m
        if len(new_rows) > 1:
            print(f"[explorer] WARN: {len(new_rows)} new backtest_runs rows since trial start — "
                  f"concurrent operator backtest detected. Taking latest (id={new_rows[0][0]}). "
                  f"Other ids preserved (will NOT be cleaned up): {[r[0] for r in new_rows[1:]]}")
        row = new_rows[0]
        m["backtest_run_id"] = row[0]
        m["wr"]              = row[1]
        m["config_hash"]     = row[2]
    except Exception as e:
        m["error"] = f"db_read_failed: {e}"
    return m


def _cleanup_run_row(run_id: int) -> None:
    """Delete an explorer-created backtest_runs row + its signals. Idempotent."""
    if not run_id:
        return
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM backtest_signals WHERE run_id=?", (run_id,))
        con.execute("DELETE FROM backtest_runs WHERE id=?", (run_id,))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[explorer] cleanup of Run-{run_id} failed: {e}")


def _verdict(m: dict) -> tuple:
    if m.get("error"):
        return "ERROR", m["error"]
    if m.get("n") is None or m["n"] < GATES["n_min"]:
        return "FAIL", f"n={m.get('n')} < {GATES['n_min']}"
    if m.get("cpcv_mean") is None or m["cpcv_mean"] < GATES["cpcv_mean_min_pct"]:
        return "FAIL", f"cpcv_mean={m.get('cpcv_mean')} < {GATES['cpcv_mean_min_pct']}"
    if m.get("cpcv_q05") is None or m["cpcv_q05"] < GATES["cpcv_q05_min_pct"]:
        return "FAIL", f"cpcv_q05={m.get('cpcv_q05')} < {GATES['cpcv_q05_min_pct']}"
    if m.get("dsr") is None or m["dsr"] < GATES["dsr_min_pct"]:
        return "FAIL", f"dsr={m.get('dsr')} < {GATES['dsr_min_pct']}"
    return "PASS", ""


class _GuardState:
    def __init__(self):
        self.consecutive_fail = 0
        self.consecutive_error = 0
        self.best_dsr = 0.0
        self.start_sr_std = _read_cross_config_std()
        self.pin_dsr = _read_pin_dsr()
        self.pin_run = _read_pin_run()
        self.start_code_hash = _hash_code_files()
        self.pause_reason = None

    def check(self, verdict: str, m: dict) -> str:
        """Return pause reason string if any guard tripped, else empty string."""
        # Track verdict streaks
        if verdict == "FAIL":
            self.consecutive_fail += 1
            self.consecutive_error = 0
        elif verdict == "ERROR":
            self.consecutive_error += 1
        else:  # PASS
            self.consecutive_fail = 0
            self.consecutive_error = 0
            dsr = m.get("dsr") or 0.0
            if dsr > self.best_dsr:
                self.best_dsr = dsr

        # 1. Basin lost
        if self.consecutive_fail >= GUARD["consecutive_fail_max"]:
            return f"basin_lost ({self.consecutive_fail} consecutive FAIL)"

        # 2. Consecutive errors (timeout/crash)
        if self.consecutive_error >= GUARD["consecutive_error_max"]:
            return f"consecutive_errors ({self.consecutive_error} ERROR in a row)"

        # 3. Best DSR vs pin
        if self.pin_dsr > 0 and self.best_dsr > 0:
            if self.best_dsr < (self.pin_dsr - GUARD["best_dsr_drop_vs_pin_pp"]):
                return (f"best_dsr_drop (session best DSR={self.best_dsr:.1f} "
                        f"< pin DSR={self.pin_dsr:.1f} - {GUARD['best_dsr_drop_vs_pin_pp']}pp)")

        # 4. Code drift
        if _hash_code_files() != self.start_code_hash:
            return "code_drift (config.py / backtest.py / ict_engine.py changed mid-session)"

        # 5. sr_trial_std jump (only check after at least one PASS)
        if self.best_dsr > 0 and self.start_sr_std > 0:
            current_std = _read_cross_config_std()
            if current_std > 0:
                jump_pct = (current_std - self.start_sr_std) / self.start_sr_std * 100
                if jump_pct > GUARD["sr_trial_std_jump_pct"]:
                    return (f"sr_trial_std_jump ({jump_pct:.1f}% rise, "
                            f"start={self.start_sr_std:.4f}, now={current_std:.4f})")

        return ""


# ── Phase 3 — Auto-promotion + Pareto archive ───────────────────────────────

def _read_promotion_log() -> list:
    try:
        with open(PROMOTION_LOG) as f:
            return json.load(f)
    except Exception:
        return []


def _append_promotion_log(entry: dict) -> None:
    log = _read_promotion_log()
    log.append(entry)
    # Trim to last 30 entries (operator review window)
    log = log[-30:]
    try:
        os.makedirs(os.path.dirname(PROMOTION_LOG), exist_ok=True)
        with open(PROMOTION_LOG, "w") as f:
            json.dump(log, f, indent=2, default=str)
    except Exception:
        pass


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _hours_since_last_auto_promotion() -> float:
    """Return hours since most recent AUTO_PROMOTED entry, or 1e9 if none."""
    log = _read_promotion_log()
    autos = [e for e in log if e.get("kind") == "AUTO_PROMOTED"]
    if not autos:
        return 1e9
    last_ts = autos[-1].get("promoted_at_utc")
    if not last_ts:
        return 1e9
    try:
        last = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
    except Exception:
        return 1e9


def _auto_promotions_today() -> int:
    """Count AUTO_PROMOTED entries from the current UTC day."""
    today = _today_utc()
    return sum(1 for e in _read_promotion_log()
               if e.get("kind") == "AUTO_PROMOTED"
               and (e.get("promoted_at_utc") or "").startswith(today))


def _read_pareto_archive() -> list:
    try:
        with open(PARETO_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _update_pareto_archive(trial_summary: dict, max_size: int = 10) -> None:
    """Maintain top-K non-dominated configs across (cpcv_mean, -cpcv_std, sharpe, n).

    A entry dominates another if it is >= on every dim and > on at least one.
    Keep all non-dominated; if more than max_size, drop the one with lowest cpcv_mean.
    """
    archive = _read_pareto_archive()
    archive.append(trial_summary)

    def _better(a, b, key, lower_is_better=False):
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None: return False
        return (av < bv) if lower_is_better else (av > bv)

    def _ge(a, b, key, lower_is_better=False):
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None: return False
        return (av <= bv) if lower_is_better else (av >= bv)

    def _dominates(a, b):
        # a dominates b if a >= b on all dims AND a > b on at least one
        dims = [("cpcv_mean", False), ("cpcv_std", True), ("sharpe", False), ("n", False)]
        if not all(_ge(a, b, k, lo) for k, lo in dims): return False
        return any(_better(a, b, k, lo) for k, lo in dims)

    # Filter to non-dominated set
    non_dom = []
    for i, candidate in enumerate(archive):
        is_dominated = any(_dominates(other, candidate)
                            for j, other in enumerate(archive) if i != j)
        if not is_dominated:
            non_dom.append(candidate)
    # Trim to max_size by cpcv_mean
    non_dom.sort(key=lambda x: x.get("cpcv_mean") or 0, reverse=True)
    non_dom = non_dom[:max_size]
    try:
        os.makedirs(os.path.dirname(PARETO_PATH), exist_ok=True)
        with open(PARETO_PATH, "w") as f:
            json.dump(non_dom, f, indent=2, default=str)
    except Exception:
        pass


def _eligibility_check(m: dict, pin: dict) -> tuple:
    """Phase 3 eligibility gate. Returns (eligible: bool, reason: str).
    All numeric criteria from PROMOTE dict must pass.
    """
    exp = pin.get("expected") or {}
    pin_cpcv   = exp.get("cpcv_wr_mean_pct")
    pin_std    = exp.get("cpcv_wr_std_pct")
    pin_sharpe = exp.get("cpcv_sharpe_mean")
    pin_n      = exp.get("n")
    # Derive pin q05 if not stored explicitly (CPCV mean - 1.645 * std → 5th pct)
    pin_q05 = exp.get("cpcv_wr_q05_pct")
    if pin_q05 is None and pin_cpcv is not None and pin_std is not None:
        pin_q05 = pin_cpcv - 1.645 * pin_std

    if m.get("dsr") is None or m["dsr"] < PROMOTE["dsr_min_pct"]:
        return False, f"dsr={m.get('dsr')} < {PROMOTE['dsr_min_pct']}"
    if pin_cpcv is None or pin_sharpe is None or pin_n is None:
        return False, "baseline pin missing key fields"
    if (m.get("cpcv_mean") or 0) - pin_cpcv < PROMOTE["cpcv_mean_delta_pp_min"]:
        return False, f"cpcv_mean delta {m.get('cpcv_mean')-pin_cpcv:.2f} < {PROMOTE['cpcv_mean_delta_pp_min']}"
    if (m.get("sharpe") or 0) - pin_sharpe < PROMOTE["sharpe_delta_min"]:
        return False, f"sharpe delta {(m.get('sharpe') or 0)-pin_sharpe:.3f} < {PROMOTE['sharpe_delta_min']}"
    if pin_std is not None and (m.get("cpcv_std") or 0) - pin_std > PROMOTE["cpcv_std_widen_pp_max"]:
        return False, f"cpcv_std widened by {(m.get('cpcv_std') or 0)-pin_std:.2f}pp"
    if pin_q05 is not None and (m.get("cpcv_q05") or 0) - pin_q05 < PROMOTE["cpcv_q05_delta_pp_min"]:
        return False, f"cpcv_q05 delta {(m.get('cpcv_q05') or 0)-pin_q05:.2f} < {PROMOTE['cpcv_q05_delta_pp_min']}"
    if pin_n > 0:
        n_change_pct = abs((m.get("n") or 0) - pin_n) / pin_n * 100
        if n_change_pct > PROMOTE["n_change_pct_max"]:
            return False, f"n change {n_change_pct:.1f}% > {PROMOTE['n_change_pct_max']}%"
    return True, "all criteria met"


def _reproduce(params: dict, original_metrics: dict, timeout_s: int = 1800) -> tuple:
    """Run a second backtest with the SAME params. Returns (reproduced: bool, m2: dict, reason: str).
    Cleans up the reproduction's backtest_runs row regardless of outcome (the first run is canonical).
    """
    env = _params_to_env(params)
    subprocess.run(
        [sys.executable, os.path.join(_ROOT, "backtest.py"), "--clear-checkpoint"],
        env=env, cwd=_ROOT, capture_output=True, timeout=30
    )
    m2 = _run_backtest(env, timeout_s=timeout_s)
    # Always clean up reproduction row — only the original survives if promoted
    _cleanup_run_row(m2.get("backtest_run_id"))

    if m2.get("error"):
        return False, m2, f"reproduction errored: {m2.get('error')}"
    if m2.get("config_hash") and original_metrics.get("config_hash"):
        if m2["config_hash"] != original_metrics["config_hash"]:
            return False, m2, "config_hash mismatch (non-deterministic env)"
    cpcv_diff = abs((m2.get("cpcv_mean") or 0) - (original_metrics.get("cpcv_mean") or 0))
    if cpcv_diff > PROMOTE["repro_metric_tolerance"]:
        return False, m2, f"cpcv_mean differs by {cpcv_diff:.2f}pp > tol {PROMOTE['repro_metric_tolerance']}"
    return True, m2, "metrics match within tolerance"


def _refresh_cross_config_std() -> None:
    """Re-run compute_cross_config_sr_std.py so the next trial's DSR uses the
    pool that now includes the just-promoted baseline."""
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(_ROOT, "scripts", "compute_cross_config_sr_std.py")],
            cwd=_ROOT, capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            print(f"[promote] cross-config sr_trial_std refreshed (honest DSR pool now includes new baseline)")
        else:
            print(f"[promote] cross-config refresh failed: {result.stderr[:200]}")
    except Exception as e:
        print(f"[promote] cross-config refresh exception: {e}")


def _auto_promote(study_name: str, trial_no: int, params: dict, m: dict, m2: dict) -> bool:
    """Call promote_baseline.py --auto. Returns True if subprocess succeeded."""
    # Pick the strongest changed param to record as the headline tune row
    changed = []
    pin = _read_pin_json()
    pin_settings = (pin.get("key_settings") or {})
    for k, v in params.items():
        # Map env-name to pin key (best-effort)
        nice_key = {
            "BACKTEST_BIAS_4H_GATE":  "bias_4h_gate",
            "BACKTEST_TREND_1H_GATE": "trend_1h_gate",
            "BACKTEST_FVG_MIN_QUALITY": "fvg_min_quality",
            "BACKTEST_MSS_MIN_QUALITY": "mss_min_quality",
            "ICT_SWEEP_LOOKBACK":  "ict_sweep_lookback",
            "ICT_MSS_HORIZON":     "ict_mss_horizon",
            "ICT_FVG_MIN_GAP":     "ict_fvg_min_gap",
            "DEALING_RANGE_LOOKBACK": "dealing_range_lookback",
        }.get(k, k.lower())
        prev = pin_settings.get(nice_key)
        if prev is not None and str(prev) != str(v):
            changed.append((k, prev, v))

    if not changed:
        return False  # nothing actually changed — defensive

    headline_param, old_val, new_val = changed[0]
    label = f"AUTO_PROMOTED by {study_name} trial #{trial_no}"
    notes = (f"Optuna explorer auto-promotion. "
             f"CPCV {m.get('cpcv_mean')} (repro {m2.get('cpcv_mean')}), "
             f"DSR {m.get('dsr')}, params: {json.dumps(params, sort_keys=True)}")
    cmd = [
        sys.executable, os.path.join(_ROOT, "scripts", "promote_baseline.py"),
        "--run-id", str(m.get("backtest_run_id")),
        "--label", label,
        "--notes", notes,
        "--param", headline_param,
        "--old", str(old_val),
        "--new", str(new_val),
        "--cpcv-mean", str(m.get("cpcv_mean")),
        "--cpcv-std",  str(m.get("cpcv_std")),
        "--sharpe",    str(m.get("sharpe")),
        "--dsr",       str(m.get("dsr")),
        "--auto",
    ]
    try:
        result = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[explorer] promote_baseline.py failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"[explorer] promote_baseline.py subprocess error: {e}")
        return False

    # Log
    _append_promotion_log({
        "kind":            "AUTO_PROMOTED",
        "promoted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "study_name":      study_name,
        "trial_no":        trial_no,
        "backtest_run_id": m.get("backtest_run_id"),
        "params":          params,
        "metrics_run1":    {k: m.get(k) for k in
                             ("cpcv_mean", "cpcv_std", "sharpe", "dsr", "n")},
        "metrics_run2":    {k: m2.get(k) for k in
                             ("cpcv_mean", "cpcv_std", "sharpe", "dsr", "n")},
    })

    # Refresh honest cross-config std so the next trial's DSR pool includes
    # the newly-promoted baseline. Critical for honest-metric continuity.
    _refresh_cross_config_std()

    return True


def _read_pin_json() -> dict:
    try:
        with open(PIN_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _try_auto_promote(study_name: str, trial_no: int, params: dict, m: dict) -> str:
    """Top-level auto-promotion gate. Returns one of:
       'promoted', 'skipped:<reason>', 'failed:<reason>'.
    """
    pin = _read_pin_json()
    eligible, reason = _eligibility_check(m, pin)
    if not eligible:
        return f"skipped:eligibility ({reason})"

    if _auto_promotions_today() >= PROMOTE["daily_promotions_max"]:
        return f"skipped:daily_cap ({_auto_promotions_today()}/{PROMOTE['daily_promotions_max']})"

    hours = _hours_since_last_auto_promotion()
    if hours < PROMOTE["soak_hours_after_promote"]:
        return f"skipped:soak ({hours:.1f}h since last < {PROMOTE['soak_hours_after_promote']}h)"

    # Reproducibility check (run #2 with same params)
    print(f"[promote] trial #{trial_no} eligible — running reproducibility backtest "
          f"(~11 min, params={params})")
    sys.stdout.flush()
    repro_ok, m2, repro_reason = _reproduce(params, m)
    if not repro_ok:
        return f"skipped:reproducibility ({repro_reason})"

    if _auto_promote(study_name, trial_no, params, m, m2):
        return "promoted"
    return "failed:subprocess"


def _objective_factory(study_name: str, guard: _GuardState, sess: dict):
    def _objective(trial: optuna.Trial) -> float:
        if guard.pause_reason:
            raise optuna.exceptions.TrialPruned()  # cleanly skip remaining

        params = _suggest_params(trial)
        env = _params_to_env(params)
        subprocess.run(
            [sys.executable, os.path.join(_ROOT, "backtest.py"), "--clear-checkpoint"],
            env=env, cwd=_ROOT, capture_output=True, timeout=30
        )
        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        m = _run_backtest(env)
        ended_at   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        verdict, reason = _verdict(m)

        # FIX H1 (2026-05-24): wrap post-backtest logic in try/finally so any
        # exception (DB insert, file I/O, subprocess) still cleans up our
        # backtest_runs row. Without this, an exception leaves an orphan that
        # silently grows on every failed trial.
        promoted = False
        try:
            con = _connect()
            con.execute("""INSERT INTO trials
                (study_name, optuna_trial_no, started_at, ended_at, walltime_s,
                 params_json, config_hash, backtest_run_id, n, wr,
                 cpcv_mean, cpcv_std, cpcv_q05, sharpe, dsr,
                 dsr_proxy_used, verdict, reject_reason, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (study_name, trial.number, started_at, ended_at, m.get("walltime_s"),
                 json.dumps(params, sort_keys=True),
                 m.get("config_hash"), m.get("backtest_run_id"),
                 m.get("n"), m.get("wr"),
                 m.get("cpcv_mean"), m.get("cpcv_std"), m.get("cpcv_q05"),
                 m.get("sharpe"), m.get("dsr"),
                 m.get("dsr_proxy_used"), verdict, reason, m.get("error")))
            con.commit()
            con.close()

            # Update session counters
            sess["trials_completed"] = sess.get("trials_completed", 0) + 1
            sess["counts"] = sess.get("counts", {"PASS": 0, "FAIL": 0, "ERROR": 0})
            sess["counts"][verdict] = sess["counts"].get(verdict, 0) + 1
            if verdict == "PASS":
                cur_best = sess.get("best_cpcv") or 0
                if (m.get("cpcv_mean") or 0) > cur_best:
                    sess["best_cpcv"]   = m.get("cpcv_mean")
                    sess["best_dsr"]    = m.get("dsr")
                    sess["best_params"] = params
            sess["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _write_session(sess)

            bar = {"PASS": "[OK]", "FAIL": "[XX]", "ERROR": "[!!]"}.get(verdict, "[??]")
            line = (f"  [trial {trial.number:3d}] {bar} verdict={verdict:5s} "
                    f"n={m.get('n')}, WR={m.get('wr')}, CPCV={m.get('cpcv_mean')}, "
                    f"DSR={m.get('dsr')}, walltime={m.get('walltime_s')}s "
                    f"({reason or 'all gates clear'})")
            try:    print(line)
            except UnicodeEncodeError:
                print(line.encode('ascii', errors='replace').decode('ascii'))
            sys.stdout.flush()

            # Phase 3: refresh Pareto archive on every PASS + try auto-promote
            if verdict == "PASS":
                _update_pareto_archive({
                    "trial_id":    trial.number,
                    "study_name":  study_name,
                    "params":      params,
                    "n":           m.get("n"),
                    "wr":          m.get("wr"),
                    "cpcv_mean":   m.get("cpcv_mean"),
                    "cpcv_std":    m.get("cpcv_std"),
                    "sharpe":      m.get("sharpe"),
                    "dsr":         m.get("dsr"),
                    "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })

                promo_result = _try_auto_promote(study_name, trial.number, params, m)
                if promo_result == "promoted":
                    promoted = True
                    print(f"[promote] AUTO_PROMOTED trial #{trial.number} -> new baseline pin "
                          f"CPCV={m.get('cpcv_mean')} DSR={m.get('dsr')} Sharpe={m.get('sharpe')}")
                    _telegram(
                        "<b>Explorer AUTO-PROMOTED</b>\n\n"
                        f"Trial #{_h(trial.number)} is the new baseline pin.\n\n"
                        "<pre>"
                        f"CPCV     {_h(m.get('cpcv_mean'))}%\n"
                        f"DSR      {_h(m.get('dsr'))}%\n"
                        f"Sharpe   {_h(m.get('sharpe'))}\n"
                        f"n        {_h(m.get('n'))}"
                        "</pre>"
                    )
                    guard.pin_dsr = _read_pin_dsr()
                    guard.pin_run = _read_pin_run()
                    sess["auto_promotions"] = sess.get("auto_promotions", 0) + 1
                    _write_session(sess)
                elif promo_result.startswith("skipped"):
                    print(f"[promote] trial #{trial.number}: {promo_result}")
                else:
                    print(f"[promote] trial #{trial.number}: {promo_result}")
                    # Rate-limit: only send Telegram for the FIRST promote-failure
                    # of this session. After that, log to console only — prevents
                    # spam if a persistent issue (e.g., promote_baseline.py
                    # subprocess crash) hits every PASS trial.
                    if not sess.get("promote_failure_telegram_sent"):
                        _telegram(
                            "<b>Explorer AUTO-PROMOTE FAILED</b>\n\n"
                            "<pre>"
                            f"{_h(promo_result)}"
                            "</pre>\n"
                            "Further failures this session will be console-only."
                        )
                        sess["promote_failure_telegram_sent"] = True
                        _write_session(sess)
        finally:
            # Always clean up our trial's backtest_runs row UNLESS it was
            # promoted (a promoted trial's row IS the new baseline).
            if not promoted:
                _cleanup_run_row(m.get("backtest_run_id"))

        # Anti-overfit guard
        guard_msg = guard.check(verdict, m)
        if guard_msg:
            guard.pause_reason = guard_msg
            print(f"\n[explorer] GUARD TRIPPED: {guard_msg}")
            print(f"[explorer] No more trials this session. Optuna study preserved.")
            sys.stdout.flush()
            _telegram(
                "<b>Explorer PAUSED  -  anti-overfit guard tripped</b>\n\n"
                "<pre>"
                f"Reason    {_h(guard_msg)}\n"
                f"Trials    {_h(sess.get('trials_completed'))} done this session\n"
                f"Best      CPCV {_h(sess.get('best_cpcv'))}%  DSR {_h(sess.get('best_dsr'))}%"
                "</pre>\n"
                "Optuna study preserved. Investigate cause, then resume with:\n"
                "<code>sudo systemctl start tradeai-explorer</code>"
            )
            raise optuna.exceptions.TrialPruned()

        if verdict == "PASS":
            return float(m["cpcv_mean"])
        if m.get("cpcv_mean") is not None:
            return float(m["cpcv_mean"]) - 30.0
        return 0.0
    return _objective


def run_study(study_name: str, n_trials: int, skip_precache: bool = False):
    # Hard-fail BEFORE any expensive work if anti-patterns are no longer locked.
    _assert_anti_pattern_locks()

    pid = _PidFile()
    pid.acquire()
    try:
        if not skip_precache:
            _precache_warm()

        storage = f"sqlite:///{OPTUNA_DB}"
        study = optuna.create_study(
            study_name=study_name, storage=storage,
            sampler=optuna.samplers.TPESampler(seed=None),
            direction="maximize", load_if_exists=True,
        )
        guard = _GuardState()
        sess = {
            "study_name":       study_name,
            "pid":              os.getpid(),
            "started_at":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "trials_planned":   n_trials,
            "trials_completed": 0,
            "counts":           {"PASS": 0, "FAIL": 0, "ERROR": 0},
            "best_cpcv":        None,
            "best_dsr":         None,
            "best_params":      None,
            "pin_run":          _read_pin_run(),
            "pin_dsr":          guard.pin_dsr,
            "guard_armed":      True,
            "pause_reason":     None,
        }
        _write_session(sess)

        print(f"[explorer] study '{study_name}' starting — {n_trials} trials")
        print(f"[explorer] storage: {storage}")
        print(f"[explorer] gates: {GATES}")
        print(f"[explorer] anti-pattern lockouts: {ANTI_PATTERN_LOCKS}")
        print(f"[explorer] anti-overfit guard: {GUARD}")
        print(f"[explorer] {len(study.trials)} prior trials in this study")
        print(f"[explorer] baseline pin: Run-{guard.pin_run}  DSR={guard.pin_dsr}")
        print()
        sys.stdout.flush()

        _telegram(
            "<b>Explorer STARTED</b>\n\n"
            "<pre>"
            f"Study     {_h(study_name)}\n"
            f"Trials    {_h(n_trials)}\n"
            f"Baseline  Run-{_h(_read_pin_run())}  (DSR {_h(guard.pin_dsr)})"
            "</pre>"
        )

        # SIGTERM handler — systemctl stop sends SIGTERM. Calls study.stop()
        # so Optuna finishes current trial then exits cleanly. A second
        # SIGTERM forces immediate exit. SIGINT (Ctrl+C) keeps its existing
        # KeyboardInterrupt path.
        _term_count = {"n": 0}
        def _sigterm_handler(signum, _frame):
            _term_count["n"] += 1
            if _term_count["n"] >= 2:
                print(f"\n[explorer] second SIGTERM received — forced exit", flush=True)
                sys.exit(130)
            sig_name = {signal.SIGTERM: "SIGTERM"}.get(signum, f"signal_{signum}")
            print(f"\n[explorer] received {sig_name} — stopping after current trial...", flush=True)
            guard.pause_reason = f"stopped_by_{sig_name.lower()}"
            sess["pause_reason"] = guard.pause_reason
            try:
                study.stop()
            except Exception:
                pass
        signal.signal(signal.SIGTERM, _sigterm_handler)

        try:
            study.optimize(_objective_factory(study_name, guard, sess),
                           n_trials=n_trials, show_progress_bar=False)
        except KeyboardInterrupt:
            print("\n[explorer] interrupted by operator (Ctrl+C)")
            sess["pause_reason"] = "keyboard_interrupt"
            _write_session(sess)
            _telegram(
                "<b>Explorer INTERRUPTED</b>\n\n"
                "<pre>"
                f"Reason    Ctrl+C from operator\n"
                f"Trials    {_h(sess.get('trials_completed'))} / {_h(sess.get('trials_planned'))}\n"
                f"Best      CPCV {_h(sess.get('best_cpcv'))}%"
                "</pre>\n"
                "Optuna study preserved. Resume with:\n"
                "<code>sudo systemctl start tradeai-explorer</code>"
            )
            return

        # Finalize
        if guard.pause_reason:
            sess["pause_reason"] = guard.pause_reason
            _write_session(sess)
            _counts = sess.get("counts", {})
            _telegram(
                "<b>Explorer STOPPED  -  guard tripped</b>\n\n"
                "<pre>"
                f"Reason    {_h(guard.pause_reason)}\n"
                f"Trials    {_h(sess.get('trials_completed'))} / {_h(sess.get('trials_planned'))}\n"
                f"Results   {_h(_counts.get('PASS',0))} PASS  "
                f"{_h(_counts.get('FAIL',0))} FAIL  "
                f"{_h(_counts.get('ERROR',0))} ERROR\n"
                f"Best      CPCV {_h(sess.get('best_cpcv'))}%  DSR {_h(sess.get('best_dsr'))}%"
                "</pre>\n"
                "Optuna study preserved. Resume with:\n"
                "<code>sudo systemctl start tradeai-explorer</code>"
            )
        else:
            sess["ended_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _write_session(sess)
            print()
            print(f"[explorer] session complete. "
                  f"PASS={sess['counts'].get('PASS',0)}, "
                  f"FAIL={sess['counts'].get('FAIL',0)}, "
                  f"ERROR={sess['counts'].get('ERROR',0)}")
            if sess.get("best_cpcv"):
                print(f"[explorer] best CPCV: {sess['best_cpcv']}  DSR: {sess['best_dsr']}")
                print(f"[explorer] best params: {sess['best_params']}")
            _counts = sess.get("counts", {})
            _telegram(
                "<b>Explorer DONE</b>\n\n"
                "<pre>"
                f"Trials    {_h(sess.get('trials_completed'))} / {_h(sess.get('trials_planned'))}\n"
                f"Results   {_h(_counts.get('PASS',0))} PASS  "
                f"{_h(_counts.get('FAIL',0))} FAIL  "
                f"{_h(_counts.get('ERROR',0))} ERROR\n"
                f"Best      CPCV {_h(sess.get('best_cpcv'))}%  DSR {_h(sess.get('best_dsr'))}%\n"
                f"Baseline  Run-{_h(sess.get('pin_run'))}  (CPCV {_h(sess.get('pin_dsr'))}%)"
                "</pre>"
            )
    finally:
        pid.release()


def list_recent(n: int = 20):
    con = _connect()
    rows = con.execute(
        """SELECT trial_id, study_name, optuna_trial_no, backtest_run_id,
                  n, wr, cpcv_mean, cpcv_std, dsr, verdict, reject_reason
           FROM trials ORDER BY trial_id DESC LIMIT ?""", (n,)).fetchall()
    con.close()
    print(f"{'#':>4} {'study':<20} {'#tr':>4} {'Run':>5} {'n':>4} {'WR%':>5} {'CPCV':>5} {'std':>5} {'DSR':>5} {'verdict':<7} reason")
    print("-" * 110)
    for r in rows:
        print(f"{r[0]:>4} {(r[1] or '')[:20]:<20} {r[2] or 0:>4} {r[3] or 0:>5} "
              f"{r[4] or 0:>4} {r[5] or 0:>5} {r[6] or 0:>5} {r[7] or 0:>5} {r[8] or 0:>5} "
              f"{r[9]:<7} {r[10] or ''}")


def show_best(study_name=None):
    con = _connect()
    q = "SELECT trial_id, study_name, params_json, backtest_run_id, n, wr, cpcv_mean, cpcv_std, dsr, verdict FROM trials WHERE verdict='PASS'"
    args = ()
    if study_name:
        q += " AND study_name=?"
        args = (study_name,)
    q += " ORDER BY cpcv_mean DESC, cpcv_std ASC LIMIT 10"
    rows = con.execute(q, args).fetchall()
    con.close()
    if not rows:
        print("[best] no PASS trials yet")
        return
    print(f"{'#':>4} {'Run':>5} {'n':>4} {'WR':>5} {'CPCV':>5} {'std':>5} {'DSR':>5}  params")
    for r in rows:
        print(f"{r[0]:>4} {r[3] or 0:>5} {r[4] or 0:>4} {r[5] or 0:>5} "
              f"{r[6] or 0:>5} {r[7] or 0:>5} {r[8] or 0:>5}  {r[2]}")


def show_digest(hours_back: int = 24):
    """Print a compact summary for operator review — designed for stdout copy
    into a Telegram or email at start of day."""
    # Recent trials
    con = _connect()
    cutoff = (datetime.now(timezone.utc).timestamp() - hours_back * 3600)
    rows = con.execute(
        """SELECT verdict, cpcv_mean, dsr, sharpe, walltime_s, params_json, reject_reason
           FROM trials WHERE started_at >= ?
           ORDER BY trial_id DESC""",
        (datetime.fromtimestamp(cutoff, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),)
    ).fetchall()
    con.close()

    pass_n  = sum(1 for r in rows if r[0] == "PASS")
    fail_n  = sum(1 for r in rows if r[0] == "FAIL")
    error_n = sum(1 for r in rows if r[0] == "ERROR")
    total   = len(rows)
    best    = max((r for r in rows if r[0] == "PASS"), key=lambda x: x[1] or 0, default=None)

    promos = [p for p in _read_promotion_log()
               if p.get("promoted_at_utc","") >= datetime.fromtimestamp(cutoff, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]

    pin = _read_pin_json()
    pareto = _read_pareto_archive()

    print(f"================= TradeAI Auto-Explorer DIGEST =================")
    print(f"Window:      last {hours_back}h")
    print(f"Trials:      {total}")
    if total:
        print(f"Verdicts:    PASS={pass_n} ({100*pass_n/total:.1f}%)  "
              f"FAIL={fail_n}  ERROR={error_n}")
    print(f"Promotions:  {len(promos)} auto-promoted")
    print(f"Baseline pin: Run-{pin.get('run_id')}  "
          f"CPCV={pin.get('expected',{}).get('cpcv_wr_mean_pct')}  "
          f"DSR={pin.get('expected',{}).get('dsr_pct')}")
    if best:
        v, cpcv, dsr, sharpe, walltime, params, _ = best
        print(f"Best PASS:   CPCV={cpcv}  DSR={dsr}  Sharpe={sharpe}  ({walltime}s)")
        try:
            p = json.loads(params)
            print(f"             params={p}")
        except Exception:
            pass
    print(f"Pareto archive size: {len(pareto)} non-dominated configs")
    if pareto[:3]:
        print(f"Pareto top-3 by CPCV:")
        for i, e in enumerate(pareto[:3], 1):
            print(f"  #{i} cpcv={e.get('cpcv_mean')}  std={e.get('cpcv_std')}  "
                  f"sharpe={e.get('sharpe')}  n={e.get('n')}  trial={e.get('trial_id')}")
    if promos:
        print(f"Auto-promotions in window:")
        for p in promos:
            m = p.get("metrics_run1", {})
            print(f"  {p.get('promoted_at_utc')}  Run-{p.get('backtest_run_id')}  "
                  f"cpcv={m.get('cpcv_mean')}  dsr={m.get('dsr')}")
    print(f"================================================================")


def show_status():
    sess = _read_session()
    pid_running = False
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
            if sys.platform == "win32":
                import ctypes
                h = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                if h:
                    pid_running = True
                    ctypes.windll.kernel32.CloseHandle(h)
            else:
                try:    os.kill(pid, 0); pid_running = True
                except OSError: pass
    except (FileNotFoundError, ValueError):
        pass

    if not sess:
        print("[status] no session recorded yet")
        return
    state = "RUNNING" if pid_running else ("PAUSED" if sess.get("pause_reason") else "FINISHED")
    print(f"[status] session     : {sess.get('study_name')}  ({state})")
    print(f"[status] started_at  : {sess.get('started_at')}")
    if sess.get("ended_at"):
        print(f"[status] ended_at    : {sess.get('ended_at')}")
    if sess.get("pause_reason"):
        print(f"[status] pause reason: {sess.get('pause_reason')}")
    counts = sess.get("counts") or {}
    print(f"[status] trials      : {sess.get('trials_completed',0)}/{sess.get('trials_planned',0)}  "
          f"PASS={counts.get('PASS',0)} FAIL={counts.get('FAIL',0)} ERROR={counts.get('ERROR',0)}")
    if sess.get("best_cpcv"):
        print(f"[status] best CPCV   : {sess['best_cpcv']}  DSR: {sess.get('best_dsr')}")
        print(f"[status] best params : {sess.get('best_params')}")
    print(f"[status] pin         : Run-{sess.get('pin_run')}  DSR={sess.get('pin_dsr')}")
    print(f"[status] last update : {sess.get('last_updated')}")
    # Phase 3: auto-promotion + Pareto
    promos_today = _auto_promotions_today()
    hours_since  = _hours_since_last_auto_promotion()
    print(f"[status] auto-promotions today: {promos_today}/{PROMOTE['daily_promotions_max']}  "
          f"(soak: {hours_since:.1f}h since last, threshold {PROMOTE['soak_hours_after_promote']}h)")
    pareto = _read_pareto_archive()
    if pareto:
        print(f"[status] Pareto archive top {len(pareto)} (non-dominated configs):")
        for i, p in enumerate(pareto[:5]):
            print(f"           #{i+1} CPCV={p.get('cpcv_mean')}  std={p.get('cpcv_std')}  "
                  f"Sharpe={p.get('sharpe')}  n={p.get('n')}  trial={p.get('trial_id')}")
        if len(pareto) > 5:
            print(f"           (+{len(pareto)-5} more in {PARETO_PATH})")
    log = _read_promotion_log()
    if log:
        print(f"[status] recent promotion log (last 3):")
        for e in log[-3:]:
            print(f"           {e.get('promoted_at_utc')}  {e.get('kind')}  "
                  f"Run-{e.get('backtest_run_id')}  cpcv={e.get('metrics_run1',{}).get('cpcv_mean')}")


def main():
    # Env-var defaults let systemd EnvironmentFile=.env.explorer drive the
    # session config without exposing trials/study-name as ExecStart args.
    _env_trials = int(os.environ.get("EXPLORER_TRIALS", "0") or "0")
    _env_study  = os.environ.get("EXPLORER_STUDY_NAME", "nightly_explorer")

    ap = argparse.ArgumentParser(description="TradeAI Autonomous Explorer — Phase 1 + 2")
    ap.add_argument("--trials", type=int, default=_env_trials,
                    help="Number of Optuna trials (or EXPLORER_TRIALS env var)")
    ap.add_argument("--study-name", type=str, default=_env_study,
                    help="Optuna study name (or EXPLORER_STUDY_NAME env var)")
    ap.add_argument("--list-recent", type=int, default=0, metavar="N")
    ap.add_argument("--best", action="store_true")
    ap.add_argument("--status", action="store_true",
                    help="Show current/last session state and exit")
    ap.add_argument("--digest", type=int, nargs="?", const=24, default=0, metavar="HOURS",
                    help="Print operator digest for the last N hours (default 24)")
    ap.add_argument("--skip-precache", action="store_true",
                    help="Skip pre-cache warm step (use when cache is known fresh)")
    args = ap.parse_args()

    _connect().close()

    if args.status:        show_status(); return
    if args.digest:        show_digest(args.digest); return
    if args.list_recent:   list_recent(args.list_recent); return
    if args.best:
        show_best(args.study_name if args.study_name != "nightly_explorer" else None); return
    if args.trials > 0:
        run_study(args.study_name, args.trials, skip_precache=args.skip_precache); return

    ap.print_help()


if __name__ == "__main__":
    main()
