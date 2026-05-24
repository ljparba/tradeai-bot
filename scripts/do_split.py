"""
do_split.py — Extract indicators.py and ict_engine.py from crypto_alert.py.
Run from the project root:  python scripts/do_split.py
"""
import re, os, sys

ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC     = os.path.join(ROOT, "crypto_alert.py")
OUT_IND = os.path.join(ROOT, "indicators.py")
OUT_ICT = os.path.join(ROOT, "ict_engine.py")

with open(SRC, encoding="utf-8-sig") as f:
    ca = f.read()

# ── 1. Locate boundaries ──────────────────────────────────────────────────────

IND_FUNC  = "\ndef ema(prices, period):"
IND_END   = "\ndef get_regime_for_token("
ICT_FUNC  = "\ndef find_ict_swings("
ICT_END   = "\ndef calculate_trade_plan("

ind_func_pos = ca.index(IND_FUNC)
ind_end_pos  = ca.index(IND_END)
ict_func_pos = ca.index(ICT_FUNC)
ict_end_pos  = ca.index(ICT_END)

# Walk back from first indicator function to find the start of the INDICATORS
# header block (the first === line of the three-line header).
ind_header_label = ca.index("\n# INDICATORS\n")
ind_hdr_start    = ca.rfind("\n# ═", 0, ind_header_label)

# Walk back from find_ict_swings to find the start of the TRADE PLAN header block.
ict_header_label = ca.index("\n# TRADE PLAN\n")
ict_hdr_start    = ca.rfind("\n# ═", 0, ict_header_label)

# ── 2. Build indicators.py ────────────────────────────────────────────────────

# Extract from first `def ema(` to just before `def get_regime_for_token(`
ind_content = ca[ind_func_pos + 1 : ind_end_pos].strip()
# Fix hardcoded default arguments that referenced crypto_alert constants
ind_content = ind_content.replace("period=RSI_PERIOD", "period=14")
ind_content = ind_content.replace("period=ATR_PERIOD", "period=14")
ind_content = ind_content.replace("period=ROC_PERIOD", "period=10")

indicators_py = (
    '"""\n'
    'indicators.py -- Pure-math indicator functions.\n'
    'Extracted from crypto_alert.py. No project-level imports.\n'
    '"""\n\n'
    + ind_content + "\n"
)

# ── 3. Build ict_engine.py ────────────────────────────────────────────────────

# Extract all ICT functions (find_ict_swings ... compute_ict_trade_plan)
ict_functions = ca[ict_func_pos + 1 : ict_end_pos].strip()

ICT_CONSTS = """\
# ICT Strategy parameters
ICT_SWING_N          = 2       # bars required after swing for confirmation
ICT_SWEEP_LOOKBACK   = 10      # max 15M closed bars to scan for a valid sweep
ICT_DISP_MAX_LOOK    = 3       # max bars after sweep to find displacement candle
ICT_MSS_HORIZON      = 10      # max bars after sweep for MSS to confirm
ICT_FVG_MIN_GAP      = 0.001   # min FVG gap as fraction of price (0.1%)
ICT_IFVG_LOOKBACK    = 50      # bars to scan backward for IFVG detection
ICT_5M_IFVG_LOOKBACK = 60      # 5M bars to scan for precision entry iFVG
DEALING_RANGE_LOOKBACK = 50    # 4H/1H bars to define the active dealing range

# Trade plan constants
MIN_TP1_MULT         = 1.5
MAX_SL_PCT           = 0.030   # ICT structural SL - swept wick up to 3% away
MIN_SL_PCT           = 0.005   # 0.5% floor - SL must be meaningful
ROUND_TRIP_COST_PCT  = 0.003   # 0.10%/side fee + 0.05%/side slippage = 0.30% RT
MAX_BREAKEVEN_WR     = 0.60    # relaxed - ICT structural SLs are larger
"""

ict_engine_py = (
    '"""\n'
    'ict_engine.py -- ICT strategy functions and constants.\n'
    'Extracted from crypto_alert.py. Imports get_trend from indicators.py.\n'
    '"""\n\n'
    'from indicators import get_trend\n\n'
    + ICT_CONSTS + "\n"
    + ict_functions + "\n"
)

# ── 4. Rebuild crypto_alert.py ────────────────────────────────────────────────

# Three "keep" segments:
#   seg1: file start  ..  just before INDICATORS header
#   seg2: def get_regime_for_token(  ..  just before TRADE PLAN header
#   seg3: def calculate_trade_plan(  ..  file end
seg1 = ca[:ind_hdr_start]
seg2 = ca[ind_end_pos : ict_hdr_start]
seg3 = ca[ict_end_pos:]

# Remove constant lines that move to ict_engine.py
CONST_PATTERNS = [
    r'\nMIN_TP1_MULT[^\n]*',
    r'\nMAX_SL_PCT[^\n]*',
    r'\nMIN_SL_PCT[^\n]*',
    r'\nROUND_TRIP_COST_PCT[^\n]*',
    r'\nMAX_BREAKEVEN_WR[^\n]*',
    r'\n# .* ICT Strategy parameters[^\n]*',
    r'\nICT_SWING_N[^\n]*',
    r'\nICT_SWEEP_LOOKBACK[^\n]*',
    r'\nICT_DISP_MAX_LOOK[^\n]*',
    r'\nICT_MSS_HORIZON[^\n]*',
    r'\nICT_FVG_MIN_GAP[^\n]*',
    r'\nICT_IFVG_LOOKBACK[^\n]*',
    r'\nICT_5M_IFVG_LOOKBACK[^\n]*',
    r'\nDEALING_RANGE_LOOKBACK[^\n]*',
]
for pat in CONST_PATTERNS:
    seg1 = re.sub(pat, '', seg1)

# Inject new imports right after the strategy_engine import line
STRAT_IMPORT = "from strategy_engine import LIVE_CONFIG, evaluate_setup\n"
NEW_IMPORTS = (
    "from indicators import (\n"
    "    ema, calculate_rsi, calculate_atr, calculate_roc,\n"
    "    get_trend, get_macd, calculate_adx, calculate_atr_ratio, detect_regime,\n"
    ")\n"
    "from ict_engine import (\n"
    "    ICT_SWING_N, ICT_SWEEP_LOOKBACK, ICT_DISP_MAX_LOOK, ICT_MSS_HORIZON,\n"
    "    ICT_FVG_MIN_GAP, ICT_IFVG_LOOKBACK, ICT_5M_IFVG_LOOKBACK,\n"
    "    DEALING_RANGE_LOOKBACK, MIN_TP1_MULT, MAX_SL_PCT, MIN_SL_PCT,\n"
    "    ROUND_TRIP_COST_PCT, MAX_BREAKEVEN_WR,\n"
    "    find_ict_swings, detect_ict_sweep, detect_ict_displacement,\n"
    "    detect_ict_fvg, score_ict_fvg, score_ict_mss, detect_ict_mss,\n"
    "    detect_fvg_entry_reaction, get_ict_4h_bias, compute_dealing_range,\n"
    "    compute_liquidity_targets, detect_smt_divergence, detect_ict_ifvg,\n"
    "    detect_5m_ifvg_entry, compute_ict_trade_plan,\n"
    ")\n"
)
seg1 = seg1.replace(STRAT_IMPORT, STRAT_IMPORT + NEW_IMPORTS, 1)

ca_new = seg1 + seg2 + seg3

# ── 5. Write files ────────────────────────────────────────────────────────────

with open(OUT_IND, "w", encoding="utf-8") as f:
    f.write(indicators_py)
with open(OUT_ICT, "w", encoding="utf-8") as f:
    f.write(ict_engine_py)
with open(SRC, "w", encoding="utf-8") as f:
    f.write(ca_new)

print("indicators.py  :", len(indicators_py.splitlines()), "lines")
print("ict_engine.py  :", len(ict_engine_py.splitlines()), "lines")
print("crypto_alert.py:", len(ca_new.splitlines()), "lines")
print("DONE")
