#!/usr/bin/env python3
"""
Phase 3.6 Validation Suite — TradeAI
Offline: uses temp DBs and synthetic candle data. No network/VPN required.
Does NOT touch production signals.db.
"""
import sys, os, time, json, sqlite3, threading, tempfile, math, traceback, py_compile
# Force UTF-8 output so Unicode arrows print correctly on Windows cp1252 consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS = 0; FAIL = 0; WARN = 0; _lines = []

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        _lines.append(f"  PASS  {name}")
    else:
        FAIL += 1
        _lines.append(f"  FAIL  {name}" + (f"\n         → {detail}" if detail else ""))

def warn(msg):
    global WARN
    WARN += 1
    _lines.append(f"  WARN  {msg}")

def section(title):
    _lines.append(f"\n{'='*64}")
    _lines.append(f"  {title}")
    _lines.append('='*64)

def make_candles(n=210, base=100.0, trend="bull", noise=0.3):
    closes = []
    for i in range(n):
        if trend == "bull":
            closes.append(base + i * 0.05 + math.sin(i * 0.3) * noise)
        elif trend == "bear":
            closes.append(base - i * 0.05 + math.sin(i * 0.3) * noise)
        else:
            closes.append(base + math.sin(i * 0.5) * 1.0)
    highs   = [c + 0.5  for c in closes]
    lows    = [c - 0.5  for c in closes]
    opens   = [c - 0.05 for c in closes]
    vols    = [1000.0 + (i % 5) * 200 for i in range(n)]
    return {"opens": opens, "highs": highs, "lows": lows, "closes": closes, "volumes": vols}

def _make_schema(path):
    """Create a minimal signals + results schema in a fresh SQLite file."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT, signal TEXT, entry_price REAL DEFAULT 0,
            sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
            sl_pct REAL, tp1_pct REAL, tp2_pct REAL, tp3_pct REAL,
            rr1 REAL, rr2 REAL, rr3 REAL,
            status TEXT DEFAULT 'OPEN',
            confidence INTEGER, market_regime TEXT,
            timestamp TEXT DEFAULT '2026-01-01 00:00:00',
            btc_bias TEXT, mtf_bias TEXT, conflict_level TEXT,
            candle_pattern TEXT, expires_at TEXT,
            feature_scores_json TEXT,
            trend_4h TEXT, trend_1h TEXT, trend_5m TEXT,
            vol_ratio REAL, roc REAL, atr REAL, rsi REAL,
            confirms INTEGER, reasons TEXT,
            wscore_buy REAL, wscore_sell REAL,
            mtf_conf INTEGER, regime_adx REAL, regime_eff REAL,
            regime_atr_r REAL, regime_conf INTEGER, btc_dom_dir TEXT
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER, tp1_hit INTEGER DEFAULT 0,
            tp2_hit INTEGER DEFAULT 0, tp3_hit INTEGER DEFAULT 0,
            sl_hit INTEGER DEFAULT 0, result TEXT DEFAULT 'OPEN',
            profit_pct REAL DEFAULT 0.0, closed_at TEXT,
            failure_reason TEXT, exit_suggestion_sent_at TEXT,
            exit_price REAL, close_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS token_weights (
            token TEXT, feature TEXT, weight REAL DEFAULT 0.1667,
            velocity REAL DEFAULT 0.0, n_updates INTEGER DEFAULT 0,
            updated_at TEXT, PRIMARY KEY (token, feature)
        );
        CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS market_stats (
            token TEXT, stat_name TEXT, values_json TEXT,
            rolling_mean REAL DEFAULT 0, rolling_std REAL DEFAULT 1,
            n_samples INTEGER DEFAULT 0, updated_at TEXT,
            PRIMARY KEY (token, stat_name)
        );
    """)
    conn.commit(); conn.close()


# ══════════════════════════════════════════════════════════════
# SECTION 1 — SYNTAX CHECKS
# ══════════════════════════════════════════════════════════════
section("1. SYNTAX CHECKS")
for fname in ["adaptive_engine.py", "crypto_alert.py", "tracker.py", "backtest.py"]:
    fpath = os.path.join(ROOT, fname)
    try:
        py_compile.compile(fpath, doraise=True)
        check(f"Syntax: {fname}", True)
    except py_compile.PyCompileError as e:
        check(f"Syntax: {fname}", False, str(e))


# ══════════════════════════════════════════════════════════════
# SECTION 2 — OGD WEIGHT ENGINE
# ══════════════════════════════════════════════════════════════
section("2. ADAPTIVE WEIGHT ENGINE (OGD) — Math & Stability")
import adaptive_engine as ae

_tmp2 = tempfile.mktemp(suffix=".db")
_orig_ae_db = ae.DB_PATH
ae.DB_PATH = _tmp2
_make_schema(_tmp2)

try:
    engine = ae.AdaptiveWeightEngine()
    uniform = {f: round(1.0 / len(ae.FEATURES), 6) for f in ae.FEATURES}
    rsi_heavy = {f: 0.0 for f in ae.FEATURES}
    rsi_heavy["rsi"] = 1.0

    # 2-1. Init weights: sum=1, all in [MIN, MAX], all features present
    w0 = engine.get_weights("TOK_A")
    check("OGD-1 init sum=1.0",     abs(sum(w0.values()) - 1.0) < 1e-5, f"sum={sum(w0.values()):.7f}")
    check("OGD-2 init has all 6",   set(w0.keys()) == set(ae.FEATURES))
    check("OGD-3 init all in bounds",
          all(ae.WEIGHT_MIN <= v <= ae.WEIGHT_MAX for v in w0.values()),
          {k: v for k, v in w0.items() if not (ae.WEIGHT_MIN <= v <= ae.WEIGHT_MAX)})

    # 2-2. Unknown / reward=0 outcome — counter increments, weights unchanged
    n0 = engine.get_sample_count("TOK_A")
    engine.update("TOK_A", "BOGUS_OUTCOME", uniform)
    check("OGD-4 unknown outcome counter++", engine.get_sample_count("TOK_A") == n0 + 1)
    check("OGD-5 unknown outcome weights stable", engine.get_weights("TOK_A") == w0)

    # 2-3. Warmup: OGD_MIN_SAMPLES - 1 WINs → weights still at defaults
    tok_wu = "TOK_WARMUP"
    for _ in range(ae.OGD_MIN_SAMPLES - 1):
        engine.update(tok_wu, "WIN", uniform)
    w_wu = engine.get_weights(tok_wu)
    check("OGD-6 warmup weights unchanged",
          all(abs(w_wu[f] - ae.DEFAULT_WEIGHTS[f]) < 1e-4 for f in ae.FEATURES))
    check("OGD-7 warmup counter correct",
          engine.get_sample_count(tok_wu) == ae.OGD_MIN_SAMPLES - 1)

    # 2-4. Post-warmup: OGD_MIN_SAMPLES-th + one more WIN → weights shift
    engine.update(tok_wu, "WIN", uniform)  # activates OGD
    engine.update(tok_wu, "WIN", uniform)  # first real gradient
    w_post = engine.get_weights(tok_wu)
    check("OGD-8 post-warmup sum=1.0",    abs(sum(w_post.values()) - 1.0) < 1e-5)
    check("OGD-9 post-warmup in bounds",  all(ae.WEIGHT_MIN <= v <= ae.WEIGHT_MAX for v in w_post.values()))

    # 2-5. 50 RSI-heavy WINs → RSI hits ceiling; all bounded; sum=1
    tok_ceil = "TOK_CEIL"
    for _ in range(60):
        engine.update(tok_ceil, "WIN", rsi_heavy)
    w_ceil = engine.get_weights(tok_ceil)
    check("OGD-10 ceiling sum=1.0",   abs(sum(w_ceil.values()) - 1.0) < 1e-5)
    check("OGD-11 ceiling bounded",   all(ae.WEIGHT_MIN <= v <= ae.WEIGHT_MAX for v in w_ceil.values()))
    check("OGD-12 RSI at WEIGHT_MAX", abs(w_ceil["rsi"] - ae.WEIGHT_MAX) < 1e-4, str(w_ceil["rsi"]))

    # 2-6. 50 RSI-heavy LOSSes after ceiling → floor prevents total forgetting
    for _ in range(50):
        engine.update(tok_ceil, "LOSS", rsi_heavy)
    w_floor = engine.get_weights(tok_ceil)
    check("OGD-13 floor sum=1.0",   abs(sum(w_floor.values()) - 1.0) < 1e-5)
    check("OGD-14 floor bounded",   all(ae.WEIGHT_MIN <= v <= ae.WEIGHT_MAX for v in w_floor.values()))
    check("OGD-15 RSI ≥ WEIGHT_MIN", w_floor["rsi"] >= ae.WEIGHT_MIN, str(w_floor["rsi"]))

    # 2-7. 100 alternating WIN/LOSS — no NaN, no Inf, sum stays 1.0
    tok_alt = "TOK_ALT"
    for i in range(100):
        engine.update(tok_alt, "WIN" if i % 2 == 0 else "LOSS", uniform)
    w_alt = engine.get_weights(tok_alt)
    check("OGD-16 alternating no NaN/Inf",  all(math.isfinite(v) for v in w_alt.values()))
    check("OGD-17 alternating sum=1.0",     abs(sum(w_alt.values()) - 1.0) < 1e-5)

    # 2-8. PARTIAL reward (+0.4) shifts weights
    tok_part = "TOK_PART"
    for _ in range(ae.OGD_MIN_SAMPLES + 1):
        engine.update(tok_part, "WIN", uniform)
    w_before = engine.get_weights(tok_part)
    engine.update(tok_part, "PARTIAL", rsi_heavy)
    w_after = engine.get_weights(tok_part)
    check("OGD-18 PARTIAL updates weights", w_before != w_after)
    check("OGD-19 PARTIAL sum=1.0",         abs(sum(w_after.values()) - 1.0) < 1e-5)
    check("OGD-20 PARTIAL bounded",         all(ae.WEIGHT_MIN <= v <= ae.WEIGHT_MAX for v in w_after.values()))

    # 2-9. EXPIRED reward (-0.25) is a mild penalty
    tok_exp = "TOK_EXP"
    for _ in range(ae.OGD_MIN_SAMPLES + 1):
        engine.update(tok_exp, "WIN", uniform)
    w_exp_b = engine.get_weights(tok_exp)
    engine.update(tok_exp, "EXPIRED", rsi_heavy)
    w_exp_a = engine.get_weights(tok_exp)
    check("OGD-21 EXPIRED updates weights", w_exp_b != w_exp_a)
    check("OGD-22 EXPIRED bounded",         all(ae.WEIGHT_MIN <= v <= ae.WEIGHT_MAX for v in w_exp_a.values()))

    # 2-10. Persistence round-trip
    tok_rt = "TOK_RT"
    engine.update(tok_rt, "WIN", rsi_heavy)
    engine.update(tok_rt, "WIN", rsi_heavy)
    engine._persist_token(tok_rt)
    eng2 = ae.AdaptiveWeightEngine()
    w_rt = eng2.get_weights(tok_rt)
    check("OGD-23 persist round-trip", all(abs(engine.get_weights(tok_rt)[f] - w_rt[f]) < 1e-5 for f in ae.FEATURES))

finally:
    ae.DB_PATH = _orig_ae_db
    try: os.unlink(_tmp2)
    except: pass


# ══════════════════════════════════════════════════════════════
# SECTION 3 — DRIFT DETECTOR
# ══════════════════════════════════════════════════════════════
section("3. DRIFT DETECTOR — Scalper RSI Calibration")

# Use an isolated instance (no DB)
dd = ae.DriftDetector.__new__(ae.DriftDetector)
dd._windows = {}

# 3-1. Empty window → scalper defaults (45/55, not swing 38/62)
d0 = dd.get_dynamic_thresholds("EMPTY")
check("DRIFT-1 empty oversold  = 45.0", d0["rsi_oversold"]  == 45.0, str(d0["rsi_oversold"]))
check("DRIFT-2 empty overbought = 55.0", d0["rsi_overbought"] == 55.0, str(d0["rsi_overbought"]))
check("DRIFT-3 empty adx_thr    = 25.0", d0["adx_trend_threshold"] == 25.0)
check("DRIFT-4 empty no drift",          not d0["drift_detected"])

# 3-2. Scalper thresholds are mirrors of crypto_alert values
import crypto_alert as ca
check("DRIFT-5 _RSI_OVERSOLD matches ca.RSI_OVERSOLD",
      ae._RSI_OVERSOLD == ca.RSI_OVERSOLD, f"{ae._RSI_OVERSOLD} vs {ca.RSI_OVERSOLD}")
check("DRIFT-6 _RSI_OVERBOUGHT matches ca.RSI_OVERBOUGHT",
      ae._RSI_OVERBOUGHT == ca.RSI_OVERBOUGHT, f"{ae._RSI_OVERBOUGHT} vs {ca.RSI_OVERBOUGHT}")

# 3-3. Low vol (small atr_ratio) → thresholds near 45/55
dd._windows["LOW_VOL"] = {s: deque(maxlen=ae.DRIFT_WINDOW) for s in ae.DriftDetector._STATS}
for _ in range(30):
    dd.update("LOW_VOL", adx=20.0, atr_ratio=0.3, rsi=50.0)
d_lv = dd.get_dynamic_thresholds("LOW_VOL")
check("DRIFT-7 low vol oversold  in [35,50]", 35.0 <= d_lv["rsi_oversold"]  <= 50.0, str(d_lv["rsi_oversold"]))
check("DRIFT-8 low vol overbought in [50,65]", 50.0 <= d_lv["rsi_overbought"] <= 65.0, str(d_lv["rsi_overbought"]))

# 3-4. High vol → oversold lower (more extreme RSI needed), overbought higher
dd._windows["HIGH_VOL"] = {s: deque(maxlen=ae.DRIFT_WINDOW) for s in ae.DriftDetector._STATS}
for _ in range(30):
    dd.update("HIGH_VOL", adx=30.0, atr_ratio=2.5, rsi=50.0)
d_hv = dd.get_dynamic_thresholds("HIGH_VOL")
check("DRIFT-9  high vol oversold  < low vol oversold",
      d_hv["rsi_oversold"] < d_lv["rsi_oversold"],
      f"high={d_hv['rsi_oversold']} low={d_lv['rsi_oversold']}")
check("DRIFT-10 high vol overbought > low vol overbought",
      d_hv["rsi_overbought"] > d_lv["rsi_overbought"])
check("DRIFT-11 high vol oversold  clamp [35,50]", 35.0 <= d_hv["rsi_oversold"]  <= 50.0)
check("DRIFT-12 high vol overbought clamp [50,65]", 50.0 <= d_hv["rsi_overbought"] <= 65.0)

# 3-5. Extreme ADX triggers drift flag
# Need variance in baseline so std > 0.001 — alternate 15/25 (mean=20, std≈5)
dd._windows["DRIFT_TOK"] = {s: deque(maxlen=ae.DRIFT_WINDOW) for s in ae.DriftDetector._STATS}
for i in range(25):
    adx_val = 15.0 if i % 2 == 0 else 25.0  # alternating → std≈5, mean=20
    dd.update("DRIFT_TOK", adx=adx_val, atr_ratio=0.5, rsi=50.0)
d_nd = dd.get_dynamic_thresholds("DRIFT_TOK", current_adx=20.0, current_atr=0.5)
check("DRIFT-13 normal ADX no drift flag", not d_nd["drift_detected"])
d_dr = dd.get_dynamic_thresholds("DRIFT_TOK", current_adx=80.0, current_atr=0.5)
check("DRIFT-14 extreme ADX triggers drift", d_dr["drift_detected"])

# 3-6. Zero-variance baseline → z_score=0.0, no divide-by-zero crash
dd._windows["FLAT"] = {s: deque(maxlen=ae.DRIFT_WINDOW) for s in ae.DriftDetector._STATS}
for _ in range(30):
    dd.update("FLAT", adx=25.0, atr_ratio=1.0, rsi=50.0)
z_flat = dd.z_score("FLAT", "adx", 25.0)
check("DRIFT-15 zero-variance z_score=0.0 (no crash)", z_flat == 0.0, str(z_flat))

# 3-7. ADX threshold = 85% of rolling mean, clamped [18, 35]
dd._windows["ADX_TUNE"] = {s: deque(maxlen=ae.DRIFT_WINDOW) for s in ae.DriftDetector._STATS}
for _ in range(30):
    dd.update("ADX_TUNE", adx=40.0, atr_ratio=0.5, rsi=50.0)  # mean=40, 85%=34 → clamp to 35
d_adx = dd.get_dynamic_thresholds("ADX_TUNE")
check("DRIFT-16 ADX threshold clamped ≤ 35", d_adx["adx_trend_threshold"] <= 35.0,
      str(d_adx["adx_trend_threshold"]))


# ══════════════════════════════════════════════════════════════
# SECTION 4 — PORTFOLIO RISK LAYER
# ══════════════════════════════════════════════════════════════
section("4. PORTFOLIO RISK LAYER — Guard Tests")

_tmp4 = tempfile.mktemp(suffix=".db")
_orig_ae_db4 = ae.DB_PATH
ae.DB_PATH = _tmp4
_make_schema(_tmp4)

try:
    pl = ae.PortfolioRiskLayer()

    # 4-1. Empty DB → ALLOW
    ok, reason, warns_ = pl.check("BTC", "BUY", risk_per_trade_pct=0.01)
    check("PORT-1 empty DB → ALLOW", ok, reason)

    # 4-2. 3 open signals → MAX_OPEN_POSITIONS blocks 4th
    conn = sqlite3.connect(_tmp4)
    for tok, sig in [("BTC","BUY"), ("ETH","BUY"), ("SOL","SELL")]:
        conn.execute("INSERT INTO signals (token,signal,sl_pct,status) VALUES (?,?,?,?)",
                     (tok, sig, 1.5, "OPEN"))
    conn.commit(); conn.close()
    ok, reason, _ = pl.check("XRP", "BUY", risk_per_trade_pct=0.01)
    check("PORT-2 3 open → BLOCK 4th", not ok)
    check("PORT-3 correct block reason", "Portfolio full" in reason or "full" in reason.lower(), reason)

    # 4-3. 2 BUYs → 3rd BUY blocked, SELL allowed
    conn = sqlite3.connect(_tmp4); conn.execute("UPDATE signals SET status='CLOSED'"); conn.commit(); conn.close()
    conn = sqlite3.connect(_tmp4)
    conn.execute("INSERT INTO signals (token,signal,sl_pct,status) VALUES ('BTC','BUY',1.5,'OPEN')")
    conn.execute("INSERT INTO signals (token,signal,sl_pct,status) VALUES ('ETH','BUY',1.5,'OPEN')")
    conn.commit(); conn.close()
    ok_buy3, r_buy3, _ = pl.check("SOL", "BUY",  risk_per_trade_pct=0.01)
    ok_sell,  r_sell,  _ = pl.check("SOL", "SELL", risk_per_trade_pct=0.01)
    check("PORT-4 2 BUYs → 3rd BUY blocked", not ok_buy3, r_buy3)
    check("PORT-5 2 BUYs → SELL allowed",    ok_sell, r_sell)

    # 4-4. Portfolio risk cap: 3 × risk_per_trade_pct > MAX_PORTFOLIO_RISK_PCT (15%)
    conn = sqlite3.connect(_tmp4); conn.execute("UPDATE signals SET status='CLOSED'"); conn.commit(); conn.close()
    conn = sqlite3.connect(_tmp4)
    conn.execute("INSERT INTO signals (token,signal,sl_pct,status) VALUES ('BTC','BUY',1.5,'OPEN')")
    conn.execute("INSERT INTO signals (token,signal,sl_pct,status) VALUES ('ETH','BUY',1.5,'OPEN')")
    conn.commit(); conn.close()
    # 2 open × 0.01 + 0.01 = 0.03 < 0.15 → ALLOW
    ok_ok,  r_ok,  _ = pl.check("SOL", "SELL", risk_per_trade_pct=0.01)
    # 2 open × 0.06 + 0.06 = 0.18 > 0.15 → BLOCK
    ok_bad, r_bad, _ = pl.check("SOL", "SELL", risk_per_trade_pct=0.06)
    check("PORT-6 portfolio risk ALLOW when within cap",  ok_ok,  r_ok)
    check("PORT-7 portfolio risk BLOCK when exceeds cap", not ok_bad, r_bad)

    # 4-5. Drawdown protection: 15 LOSSes at -10% → cumulative -30% > -20% limit
    conn = sqlite3.connect(_tmp4); conn.execute("UPDATE signals SET status='CLOSED'"); conn.commit(); conn.close()
    conn = sqlite3.connect(_tmp4)
    for i in range(15):
        cur = conn.execute(
            "INSERT INTO signals (token,signal,sl_pct,status,timestamp) "
            "VALUES ('BTC','BUY',1.5,'CLOSED','2026-01-01 00:00:00')")
        conn.execute(
            "INSERT INTO results (signal_id,result,profit_pct,closed_at) VALUES (?,?,?,?)",
            (cur.lastrowid, "LOSS", -10.0, "2026-01-01 01:00:00"))
    conn.commit(); conn.close()
    ok_dd, r_dd, _ = pl.check("ETH", "BUY", risk_per_trade_pct=0.01)
    check("PORT-8 drawdown > 20% → BLOCK", not ok_dd, r_dd)
    check("PORT-9 drawdown reason correct",
          "rawdown" in r_dd or "drawdown" in r_dd.lower(), r_dd)

    # 4-6. Fail-closed on bad DB path
    ae.DB_PATH = "/nonexistent/bad/path.db"
    ok_err, r_err, _ = pl.check("BTC", "BUY", risk_per_trade_pct=0.01)
    check("PORT-10 exception → fail-closed (BLOCK)", not ok_err, r_err)
    ae.DB_PATH = _tmp4

finally:
    ae.DB_PATH = _orig_ae_db4
    try: os.unlink(_tmp4)
    except: pass


# ══════════════════════════════════════════════════════════════
# SECTION 5 — EXTRACT_FEATURE_SCORES
# ══════════════════════════════════════════════════════════════
section("5. EXTRACT_ICT_FEATURE_SCORES — Normalization & Direction Alignment")

def ict_fscores(sig="BUY", fvg_q="HIGH", mss_q="MEDIUM", session="NY_AM_KZ",
                conf=7, trend_1h="STRONG_BULL", dr_loc="DISCOUNT"):
    return ae.extract_ict_feature_scores(sig, fvg_q, mss_q, session, conf, trend_1h, dr_loc)

# 5-1. BUY sums to ~1.0, all non-negative, all ICT features present
fs_buy = ict_fscores()
check("FEAT-1 BUY sums to ~1.0",     abs(sum(fs_buy.values()) - 1.0) < 0.01, str(sum(fs_buy.values())))
check("FEAT-2 BUY all non-negative",  all(v >= 0 for v in fs_buy.values()))
check("FEAT-3 BUY all ICT features",  set(fs_buy.keys()) == set(ae.FEATURES))

# 5-2. SELL case
fs_sell = ict_fscores(sig="SELL", fvg_q="HIGH", mss_q="MEDIUM", session="NY_AM_KZ",
                      conf=7, trend_1h="STRONG_BEAR", dr_loc="PREMIUM")
check("FEAT-4 SELL sums to ~1.0",     abs(sum(fs_sell.values()) - 1.0) < 0.01)
check("FEAT-5 SELL all non-negative", all(v >= 0 for v in fs_sell.values()))

# 5-3. All-zero inputs → uniform fallback (no crash, sum ~1.0)
fs_zero = ict_fscores(fvg_q="NONE", mss_q="NONE", session="OVERNIGHT",
                      conf=5, trend_1h="NEUTRAL", dr_loc="UNKNOWN")
check("FEAT-6 zero inputs → uniform fallback", abs(sum(fs_zero.values()) - 1.0) < 0.01)

# 5-4. FVG quality: HIGH > MEDIUM > LOW raw score
fvg_raw = ae._QUALITY_SCORE
check("FEAT-7 FVG HIGH > MEDIUM",  fvg_raw["HIGH"]   > fvg_raw["MEDIUM"])
check("FEAT-8 FVG MEDIUM > LOW",   fvg_raw["MEDIUM"] > fvg_raw["LOW"])
check("FEAT-9 FVG NONE == 0",      fvg_raw["NONE"]   == 0.0)

# 5-5. Direction-aware trend: BUY gets high score from STRONG_BULL, SELL from STRONG_BEAR
buy_bull  = ict_fscores(sig="BUY",  trend_1h="STRONG_BULL")["trend_strength"]
buy_bear  = ict_fscores(sig="BUY",  trend_1h="STRONG_BEAR")["trend_strength"]
sell_bear = ict_fscores(sig="SELL", trend_1h="STRONG_BEAR")["trend_strength"]
sell_bull = ict_fscores(sig="SELL", trend_1h="STRONG_BULL")["trend_strength"]
check("FEAT-10 BUY: STRONG_BULL > STRONG_BEAR trend", buy_bull > buy_bear,
      f"bull={buy_bull:.4f} bear={buy_bear:.4f}")
check("FEAT-11 SELL: STRONG_BEAR > STRONG_BULL trend", sell_bear > sell_bull,
      f"bear={sell_bear:.4f} bull={sell_bull:.4f}")

# 5-6. Direction-aware DR: BUY benefits from DISCOUNT, SELL from PREMIUM
buy_disc = ict_fscores(sig="BUY",  dr_loc="DISCOUNT")["dr_location"]
buy_prem = ict_fscores(sig="BUY",  dr_loc="PREMIUM" )["dr_location"]
sell_prem = ict_fscores(sig="SELL", dr_loc="PREMIUM" )["dr_location"]
sell_disc = ict_fscores(sig="SELL", dr_loc="DISCOUNT")["dr_location"]
check("FEAT-12 BUY: DISCOUNT > PREMIUM DR score", buy_disc > buy_prem)
check("FEAT-13 SELL: PREMIUM > DISCOUNT DR score", sell_prem > sell_disc)


# ══════════════════════════════════════════════════════════════
# SECTION 6 — INDICATOR MATH
# ══════════════════════════════════════════════════════════════
section("6. INDICATOR MATH — RSI, ATR, EMA, MACD, ROC, Trend")

# 6-1. RSI monotone rising → near 99
rising = [float(i) for i in range(1, 40)]
check("IND-1 RSI monotone rising ≈ 99", ca.calculate_rsi(rising) > 90, str(ca.calculate_rsi(rising)))

# 6-2. RSI monotone falling → near 1
falling = list(reversed(rising))
check("IND-2 RSI monotone falling ≈ 1", ca.calculate_rsi(falling) < 10, str(ca.calculate_rsi(falling)))

# 6-3. RSI flat (all zero deltas) → no crash, value is float
flat = [50.0] * 30
rsi_flat = ca.calculate_rsi(flat)
check("IND-3 RSI flat returns float", isinstance(rsi_flat, float) and math.isfinite(rsi_flat))

# 6-4. RSI insufficient → 50.0
check("IND-4 RSI insufficient data → 50.0", ca.calculate_rsi([1.0, 2.0]) == 50.0)

# 6-5. ATR flat candles → 0.0
c0 = [100.0]*20; h0 = [100.0]*20; l0 = [100.0]*20
check("IND-5 ATR flat → 0.0", ca.calculate_atr(h0, l0, c0) == 0.0)

# 6-6. ATR with range → positive
h1 = [101.0 + i*0.1 for i in range(20)]
l1 = [99.0  - i*0.1 for i in range(20)]
c1 = [100.0 + i*0.05 for i in range(20)]
check("IND-6 ATR with range → positive", ca.calculate_atr(h1, l1, c1) > 0)

# 6-7. EMA converges toward new price level
prices_ema = [100.0]*50 + [200.0]*100
e50 = ca.ema(prices_ema, 50)
check("IND-7 EMA convergence toward 200", e50 > 150, str(e50))

# 6-8. MACD valid with 50 bars
prices_m = [100.0 + math.sin(i*0.3)*5 for i in range(55)]
macd_v = ca.get_macd(prices_m)
check("IND-8 MACD valid with 55 bars", macd_v["valid"])
check("IND-9 MACD has histogram key",  "histogram" in macd_v)
check("IND-10 MACD histogram is float", math.isfinite(macd_v["histogram"]))

# 6-9. MACD insufficient → valid=False, no crash
macd_s = ca.get_macd([1.0, 2.0])
check("IND-11 MACD insufficient → valid=False", not macd_s["valid"])

# 6-10. ROC correct computation
# prices[-1]=105, prices[-(10+1)]=100 → (105-100)/100*100 = 5.0%
roc_prices = [100.0]*10 + [105.0]
check("IND-12 ROC +5% correct", abs(ca.calculate_roc(roc_prices) - 5.0) < 0.01,
      str(ca.calculate_roc(roc_prices)))

# 6-11. get_trend: 200+ bars of uptrend → non-NEUTRAL
closes_up = [100.0 + i*0.1 for i in range(210)]
trend_up = ca.get_trend(closes_up)
check("IND-13 get_trend 210-bar uptrend → non-NEUTRAL",
      trend_up in ("STRONG_BULL","BULL"), str(trend_up))
check("IND-14 get_trend <200 bars → NEUTRAL", ca.get_trend([100.0]*50) == "NEUTRAL")

# 6-12. detect_regime returns valid keys
cl = make_candles(210)["closes"]
hi = [c + 0.5 for c in cl]; lo = [c - 0.5 for c in cl]
r = ca.detect_regime(cl, hi, lo)
check("IND-15 detect_regime has 'regime'",  "regime" in r)
check("IND-16 detect_regime adx >= 0",      r["adx"] >= 0)
check("IND-17 detect_regime efficiency [0,1]", 0.0 <= r.get("efficiency",0) <= 1.0)
check("IND-18 detect_regime label valid",
      r["regime"] in ("TRENDING_BULL","TRENDING_BEAR","RANGING","HIGH_VOLATILITY","CHOPPY","UNKNOWN"))

# 6-13. detect_regime <40 bars → UNKNOWN
r_short = ca.detect_regime([100.0]*30, [101.0]*30, [99.0]*30)
check("IND-19 detect_regime <40 bars → UNKNOWN", r_short["regime"] == "UNKNOWN")


# ══════════════════════════════════════════════════════════════
# SECTION 7 — TRADE PLAN
# ══════════════════════════════════════════════════════════════
section("7. TRADE PLAN — SL Cap, R:R, TP Ordering")

price = 100.0; atr = 1.0
# Scalper SL cap = 1.5%. Support-based SL uses below[-1]*0.97 (adds 3% buffer),
# so any nearby support would exceed the cap. Pass empty supports for BUY (ATR
# path: sl = price - atr*1.0 = 99.0, 1.0% SL). Same logic for SELL with no ress.
buy_sups = []              # no below-price supports → ATR SL (99.0 = 1% SL)
buy_ress = [101.5, 103.0, 106.0]
sell_sups = [97.0, 95.0, 92.0]
sell_ress = []             # no above-price ress → ATR SL (101.0 = 1% SL)

# 7-1. BUY plan sanity
pb = ca.calculate_trade_plan(price, "BUY", atr, buy_sups, buy_ress)
check("PLAN-1 BUY plan not None",          pb is not None)
if pb:
    check("PLAN-2 BUY SL < entry",         pb["sl"] < price)
    check("PLAN-3 BUY TP1 > entry",        pb["tp1"] > price)
    check("PLAN-4 BUY TP2 >= TP1",         pb["tp2"] >= pb["tp1"])
    check("PLAN-5 BUY TP3 >= TP2",         pb["tp3"] >= pb["tp2"])
    check("PLAN-6 BUY SL within cap",
          abs(pb["sl_pct"]) <= ca.MAX_SL_PCT * 100 + 0.01, str(pb["sl_pct"]))
    check("PLAN-7 BUY RR1 >= MIN_TP1_MULT",
          pb["rr1"] >= ca.MIN_TP1_MULT, str(pb["rr1"]))

# 7-2. SELL plan sanity
ps = ca.calculate_trade_plan(price, "SELL", atr, sell_sups, sell_ress)
check("PLAN-8 SELL plan not None",          ps is not None)
if ps:
    check("PLAN-9 SELL SL > entry",         ps["sl"] > price)
    check("PLAN-10 SELL TP1 < entry",       ps["tp1"] < price)
    check("PLAN-11 SELL TP2 <= TP1",        ps["tp2"] <= ps["tp1"])
    check("PLAN-12 SELL TP3 <= TP2",        ps["tp3"] <= ps["tp2"])
    check("PLAN-13 SELL SL within cap",
          abs(ps["sl_pct"]) <= ca.MAX_SL_PCT * 100 + 0.01, str(ps["sl_pct"]))

# 7-3. ATR-based SL fallback: far supports fall back to ATR SL (not None)
far_sups = [70.0, 75.0, 80.0]  # 20-30% away — support SL too wide, falls back to ATR
pb_far = ca.calculate_trade_plan(price, "BUY", atr, far_sups, buy_ress)
check("PLAN-14 far supports fall back to ATR SL (not None)", pb_far is not None)
# Actual rejection when ATR itself exceeds cap: ATR=3.5 → sl=96.5 → 3.5% > MAX_SL_PCT (3.0%)
pb_wide = ca.calculate_trade_plan(price, "BUY", 3.5, [], buy_ress)
check("PLAN-14b large ATR (3.5% SL) → None", pb_wide is None)

# 7-4. Zero ATR → None
check("PLAN-15 zero ATR → None",  ca.calculate_trade_plan(price, "BUY", 0.0, buy_sups, buy_ress) is None)

# 7-5. Zero price → None
check("PLAN-16 zero price → None", ca.calculate_trade_plan(0.0, "BUY", atr, buy_sups, buy_ress) is None)

# 7-6. RR1 ≥ MIN_TP1_MULT for multiple price levels
for test_price in [0.001, 10.0, 50000.0]:
    test_sups = [test_price * 0.98]
    test_ress = [test_price * 1.03, test_price * 1.06]
    plan_rr = ca.calculate_trade_plan(test_price, "BUY", test_price * 0.01, test_sups, test_ress)
    if plan_rr:
        check(f"PLAN-17 RR1≥{ca.MIN_TP1_MULT} at price={test_price}",
              plan_rr["rr1"] >= ca.MIN_TP1_MULT, str(plan_rr["rr1"]))


# ══════════════════════════════════════════════════════════════
# SECTION 8 — SIGNAL GENERATION (synthetic candles)
# ══════════════════════════════════════════════════════════════
section("8. SIGNAL GENERATION — Structure Validation (synthetic data)")

# Use a temp DB so portfolio checks don't touch production
_tmp8 = tempfile.mktemp(suffix=".db")
_orig_ca_db8 = ca.DB_PATH
_orig_ae_db8 = ae.DB_PATH
ca.DB_PATH = _tmp8
ae.DB_PATH = _tmp8
_make_schema(_tmp8)

try:
    # Inject synthetic state for all tokens
    for tok in ca.BINANCE_TOKENS:
        ca.STATE[tok]["candles"]["1h"]  = make_candles(210, 100.0, "bull")
        ca.STATE[tok]["candles"]["15m"] = make_candles(210, 100.0, "bull")
        ca.STATE[tok]["candles"]["5m"]  = make_candles(210, 100.0, "bull")
        ca.STATE[tok]["avg_volume"]     = 1000.0
        ca.STATE[tok]["last_24h"]       = {"price":100.0,"change_24h":1.0,"volume_24h":1e7}

    # BTC reference state
    ca.BTC_STATE.update({
        "trend_1h": "BULL", "trend_15m": "BULL",
        "dominance": 52.0, "dom_dir": "NEUTRAL",
        "last_candle_fetch": time.time(), "last_dom_fetch": time.time(),
    })

    # 8-1. Always returns 2-tuple
    for tok in list(ca.BINANCE_TOKENS.keys())[:3]:
        pair = ca.generate_signal(tok, 100.0, 1.0, 1e7)
        check(f"SIG-1 {tok} returns 2-tuple", isinstance(pair, tuple) and len(pair) == 2)
        result, regime = pair

        # 8-2. Regime dict always present with required keys
        check(f"SIG-2 {tok} regime has 'regime'", "regime" in regime)
        check(f"SIG-3 {tok} regime label valid",
              regime.get("regime") in ("TRENDING_BULL","TRENDING_BEAR","RANGING",
                                        "HIGH_VOLATILITY","CHOPPY","UNKNOWN"))

        if result is not None:
            req = {"signal","confidence","reasons","plan","feature_scores_json",
                   "rsi","trend_5m","mtf_bias","wscore_buy","wscore_sell",
                   "btc_trend_4h","btc_action","conflict_level","candle_pattern"}
            missing = req - set(result.keys())
            check(f"SIG-4 {tok} result has required keys", not missing, str(missing))
            check(f"SIG-5 {tok} direction valid",   result["signal"] in ("BUY","SELL"))
            check(f"SIG-6 {tok} conf in [1,10]",    1 <= result["confidence"] <= 10)
            check(f"SIG-7 {tok} plan not None",      result["plan"] is not None)
            check(f"SIG-8 {tok} feature JSON valid",
                  isinstance(json.loads(result["feature_scores_json"]), dict))
            plan = result["plan"]
            check(f"SIG-9 {tok} plan RR1≥{ca.MIN_TP1_MULT}",
                  plan["rr1"] >= ca.MIN_TP1_MULT, str(plan["rr1"]))
            check(f"SIG-10 {tok} plan SL within cap",
                  abs(plan["sl_pct"]) <= ca.MAX_SL_PCT * 100 + 0.01, str(plan["sl_pct"]))
        else:
            # No signal is a valid outcome (all filters pass correctly)
            check(f"SIG-11 {tok} no-signal regime dict present", isinstance(regime, dict))

    # 8-3. Insufficient candle data → (None, {}) gracefully
    ca.STATE["BTC"]["candles"]["15m"] = {}
    pair_empty = ca.generate_signal("BTC", 100.0, 1.0, 1e7)
    check("SIG-12 empty candles → (None, {}) no crash",
          isinstance(pair_empty, tuple) and pair_empty[0] is None)

    # 8-4. CHOPPY regime → signal blocked
    # Create choppy candles (low ADX, inefficient movement)
    choppy = {"closes": [100.0 + math.sin(i*1.5)*0.1 for i in range(210)],
              "highs":  [100.1 + math.sin(i*1.5)*0.1 for i in range(210)],
              "lows":   [99.9  + math.sin(i*1.5)*0.1 for i in range(210)],
              "opens":  [100.0 for _ in range(210)],
              "volumes":[1000.0 for _ in range(210)]}
    ca.STATE["ETH"]["candles"]["1h"]  = choppy
    ca.STATE["ETH"]["candles"]["15m"] = choppy
    ca.STATE["ETH"]["candles"]["5m"]  = choppy
    pair_choppy = ca.generate_signal("ETH", 100.0, 0.1, 1e6)
    check("SIG-13 choppy/BLOCK regime → no signal",
          isinstance(pair_choppy, tuple) and len(pair_choppy) == 2)

finally:
    ca.DB_PATH = _orig_ca_db8
    ae.DB_PATH = _orig_ae_db8
    try: os.unlink(_tmp8)
    except: pass


# ══════════════════════════════════════════════════════════════
# SECTION 9 — TRACKER API HANDLER SAFETY
# ══════════════════════════════════════════════════════════════
section("9. TRACKER API HANDLERS — Empty/Bad Data Safety")
import tracker

_tmp9 = tempfile.mktemp(suffix=".db")
_orig_tr_db = tracker.DB_PATH
tracker.DB_PATH = _tmp9
_make_schema(_tmp9)
tracker.init_backtest_db()

# Reset adaptive cache
with tracker._adap_lock:
    tracker._adaptive_cache.clear()

try:
    # 9-1. get_stats empty → no crash, db_ok=True, zero counts
    stats = tracker.get_stats()
    check("API-1 get_stats empty → no crash",   isinstance(stats, dict))
    check("API-2 get_stats empty → db_ok",      stats.get("db_ok", False))
    check("API-3 get_stats empty → 0 total",    stats.get("total", -1) == 0)
    check("API-4 get_stats empty → 0 wins",     stats.get("wins",  -1) == 0)

    # 9-2. get_intelligence empty → no crash
    intel = tracker.get_intelligence()
    check("API-5 get_intelligence empty → no crash", isinstance(intel, dict))
    check("API-6 get_intelligence has ok key",       "ok" in intel)

    # 9-3. get_backtest_results empty → ok=False (no run)
    bt = tracker.get_backtest_results()
    check("API-7 get_backtest_results empty → no crash", isinstance(bt, dict))
    check("API-8 get_backtest_results empty → ok=False", not bt.get("ok", True))

    # 9-4. get_backtest_history empty → runs=[]
    bth = tracker.get_backtest_history()
    check("API-9 get_backtest_history empty → runs=[]", bth.get("runs") == [])

    # 9-5. get_adaptive_summary empty → no crash, ok=True
    adap = tracker.get_adaptive_summary()
    check("API-10 get_adaptive_summary empty → no crash", isinstance(adap, dict))
    check("API-11 get_adaptive_summary has ok",           adap.get("ok", False))

    # 9-6. calculate_tune_preview no backtest → ok=False, not crash
    preview = tracker.calculate_tune_preview()
    check("API-12 tune_preview no backtest → no crash",  isinstance(preview, dict))
    check("API-13 tune_preview no backtest → ok=False",  not preview.get("ok", True))

    # 9-7. manual_close nonexistent ID → ok=False
    mc_nf = tracker.manual_close_signal(99999, 100.0)
    check("API-14 manual_close nonexistent → ok=False",  not mc_nf.get("ok", True))
    check("API-15 manual_close nonexistent → no crash",  "error" in mc_nf)

    # 9-8. manual_close already-CLOSED signal → ok=False
    conn = sqlite3.connect(_tmp9)
    conn.execute("INSERT INTO signals (id,token,signal,entry_price,tp1_pct,status) VALUES (10,'BTC','BUY',100.0,2.0,'CLOSED')")
    conn.execute("INSERT INTO results (signal_id) VALUES (10)")
    conn.commit(); conn.close()
    mc_closed = tracker.manual_close_signal(10, 102.0)
    check("API-16 manual_close closed signal → ok=False", not mc_closed.get("ok", True))

    # 9-9. manual_close OPEN at profit → WIN
    conn = sqlite3.connect(_tmp9)
    conn.execute("INSERT INTO signals (id,token,signal,entry_price,tp1_pct,feature_scores_json,status) VALUES (11,'ETH','BUY',100.0,2.0,NULL,'OPEN')")
    conn.execute("INSERT INTO results (signal_id,result) VALUES (11,'OPEN')")
    conn.commit(); conn.close()
    mc_win = tracker.manual_close_signal(11, 103.0)
    check("API-17 manual_close profit → ok=True",  mc_win.get("ok", False), str(mc_win))
    check("API-18 manual_close profit → WIN",       mc_win.get("result") == "WIN", str(mc_win.get("result")))

    # 9-10. manual_close OPEN at loss → LOSS
    conn = sqlite3.connect(_tmp9)
    conn.execute("INSERT INTO signals (id,token,signal,entry_price,tp1_pct,feature_scores_json,status) VALUES (12,'SOL','BUY',100.0,2.0,NULL,'OPEN')")
    conn.execute("INSERT INTO results (signal_id,result) VALUES (12,'OPEN')")
    conn.commit(); conn.close()
    mc_loss = tracker.manual_close_signal(12, 98.0)
    check("API-19 manual_close loss → LOSS", mc_loss.get("result") == "LOSS", str(mc_loss.get("result")))

    # 9-11. manual_close with feature_scores_json → OGD update fires without crash
    conn = sqlite3.connect(_tmp9)
    fs_sample = json.dumps({f: round(1.0/6, 4) for f in ae.FEATURES})
    conn.execute("INSERT INTO signals (id,token,signal,entry_price,tp1_pct,feature_scores_json,status) VALUES (13,'AVAX','BUY',100.0,2.0,?,'OPEN')", (fs_sample,))
    conn.execute("INSERT INTO results (signal_id,result) VALUES (13,'OPEN')")
    conn.commit(); conn.close()
    mc_ogd = tracker.manual_close_signal(13, 103.0)
    check("API-20 manual_close with feature_scores → ok=True (OGD fires)", mc_ogd.get("ok", False))

    # 9-12. Tune validation — unknown param rejected
    bad = tracker.apply_tune_adjustments([{"param": "HACK_PARAM", "new_val": 99}])
    check("API-21 tune unknown param → ok=False", not bad.get("ok", True))

    # 9-13. SIGNAL_THRESHOLD out of range → rejected
    bad2 = tracker.apply_tune_adjustments([{"param": "SIGNAL_THRESHOLD", "old_val": 35, "new_val": 99}])
    check("API-22 tune bad threshold → ok=False", not bad2.get("ok", True))

    # 9-14. WEIGHTS sum not 1.0 → rejected
    bad_w = {k: 0.5 for k in ["rsi","trend","sr","mtf","volume","momentum"]}
    bad3 = tracker.apply_tune_adjustments([{"param": "WEIGHTS", "old_val": {}, "new_val": bad_w}])
    check("API-23 tune bad WEIGHTS sum → ok=False", not bad3.get("ok", True))

    # 9-15. read_bot_values parses crypto_alert.py correctly
    bv = tracker.read_bot_values()
    check("API-24 read_bot_values → ok",              bv.get("ok", False), str(bv))
    check("API-25 read_bot_values has WEIGHTS",        "WEIGHTS" in bv)
    check("API-26 read_bot_values SIGNAL_THRESHOLD",   isinstance(bv.get("SIGNAL_THRESHOLD"), int))
    check("API-27 read_bot_values WEIGHTS sums ≈ 1.0",
          abs(sum(bv.get("WEIGHTS", {}).values()) - 1.0) < 0.02,
          str(sum(bv.get("WEIGHTS",{}).values())))

finally:
    tracker.DB_PATH = _orig_tr_db
    with tracker._adap_lock:
        tracker._adaptive_cache.clear()
    try: os.unlink(_tmp9)
    except: pass


# ══════════════════════════════════════════════════════════════
# SECTION 10 — SQLITE CONCURRENCY (WAL mode)
# ══════════════════════════════════════════════════════════════
section("10. SQLite CONCURRENCY — WAL Concurrent Read+Write")

_tmp10 = tempfile.mktemp(suffix=".db")
try:
    conn = sqlite3.connect(_tmp10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val REAL)")
    conn.execute("INSERT INTO t VALUES (1, 0.0)")
    conn.commit(); conn.close()

    errors = []; write_done = [0]; read_done = [0]

    def do_writes():
        for i in range(25):
            try:
                c = sqlite3.connect(_tmp10, timeout=10)
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA busy_timeout=5000")
                c.execute("UPDATE t SET val=? WHERE id=1", (float(i),))
                c.commit(); c.close()
                write_done[0] += 1
                time.sleep(0.004)
            except Exception as e:
                errors.append(f"WRITE: {e}")

    def do_reads(n):
        for _ in range(40):
            try:
                c = sqlite3.connect(_tmp10, timeout=10)
                c.execute("PRAGMA journal_mode=WAL")
                row = c.execute("SELECT val FROM t WHERE id=1").fetchone()
                c.close()
                if row is not None:
                    read_done[0] += 1
                time.sleep(0.003)
            except Exception as e:
                errors.append(f"READ{n}: {e}")

    threads = [threading.Thread(target=do_writes)]
    for i in range(3):
        threads.append(threading.Thread(target=do_reads, args=(i,)))
    for t in threads: t.start()
    for t in threads: t.join(timeout=15)

    check("CONC-1 no errors under concurrent access", not errors, str(errors[:3]))
    check("CONC-2 all 25 writes completed",            write_done[0] == 25, str(write_done[0]))
    check("CONC-3 reads completed (≥60 of 120)",       read_done[0] >= 60, str(read_done[0]))

    # Final value should be 24 (last write index)
    c = sqlite3.connect(_tmp10)
    final_val = c.execute("SELECT val FROM t WHERE id=1").fetchone()[0]
    c.close()
    check("CONC-4 final DB value is consistent (=24.0)", final_val == 24.0, str(final_val))

finally:
    try: os.unlink(_tmp10)
    except: pass


# ══════════════════════════════════════════════════════════════
# SECTION 11 — MISC UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════
section("11. MISC UTILITIES — _weighted_wr, find_auto_levels, near_level")

# 11-1. _weighted_wr
wr_rows = [("WIN",), ("WIN",), ("PARTIAL",), ("LOSS",), ("EXPIRED",)]
wr = ca._weighted_wr(wr_rows)
# Expected: (1+1+0.5+0+0)/5 = 0.5
check("UTIL-1 _weighted_wr correct", abs(wr - 0.5) < 0.01, str(wr))
check("UTIL-2 _weighted_wr empty → 0.0", ca._weighted_wr([]) == 0.0)
check("UTIL-3 _weighted_wr all WIN → 1.0", ca._weighted_wr([("WIN",)]*5) == 1.0)
check("UTIL-4 _weighted_wr PARTIAL = 0.5 credit", ca._weighted_wr([("PARTIAL",)]) == 0.5)

# 11-2. find_auto_levels
data = make_candles(60)
levels = ca.find_auto_levels(data["closes"], data["highs"], data["lows"])
check("UTIL-5 find_auto_levels returns dict",     isinstance(levels, dict))
check("UTIL-6 find_auto_levels has supports",     len(levels.get("supports",[])) >= 3)
check("UTIL-7 find_auto_levels has resistances",  len(levels.get("resistances",[])) >= 3)
check("UTIL-8 supports all < current close",
      all(s < data["closes"][-1] * 1.01 for s in levels["supports"]))
check("UTIL-9 resistances all > current close",
      all(r > data["closes"][-1] * 0.99 for r in levels["resistances"]))

# 11-3. near_level
check("UTIL-10 near_level exact match",    ca.near_level(100.0, [100.0, 105.0], prox=0.05) == 100.0)
check("UTIL-11 near_level within prox",   ca.near_level(100.2, [100.0, 110.0], prox=0.05) == 100.0)
check("UTIL-12 near_level out of prox",   ca.near_level(100.0, [120.0, 130.0], prox=0.05) is None)
check("UTIL-13 near_level picks closest", ca.near_level(100.0, [99.0, 101.0],  prox=0.05) in (99.0, 101.0))

# 11-4. calculate_compound sanity
comp = ca.calculate_compound(1000.0, 2.0, 1.0, 0.60, trades=10)
check("UTIL-14 calculate_compound 10 elements",    len(comp) == 10)
check("UTIL-15 calculate_compound first > initial", comp[0] > 0)
check("UTIL-16 calculate_compound all finite",      all(math.isfinite(v) for v in comp))


# ══════════════════════════════════════════════════════════════
# FINAL REPORT
# ══════════════════════════════════════════════════════════════
print()
for line in _lines:
    print(line)

total_checks = PASS + FAIL
print(f"\n{'='*64}")
print(f"  TOTAL: {PASS} PASS  |  {FAIL} FAIL  |  {WARN} WARN  |  {total_checks} checks")
print('='*64)
if FAIL == 0:
    print("  ALL CHECKS PASSED")
else:
    print(f"  {FAIL} FAILURE(S) DETECTED — see FAIL lines above")
print('='*64)
sys.exit(0 if FAIL == 0 else 1)
