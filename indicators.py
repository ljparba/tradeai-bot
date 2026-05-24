"""
indicators.py -- Pure-math indicator functions.
Extracted from crypto_alert.py. No project-level imports.
"""

def ema(prices, period):
    if not prices: return 0.0
    if len(prices)<period: return prices[-1]
    k=2.0/(period+1); val=sum(prices[:period])/period
    for p in prices[period:]: val=p*k+val*(1-k)
    return round(val,8)

def calculate_rsi(prices, period=14):
    """Wilder's RSI — matches TradingView/industry standard.
    Seeds with SMA of first `period` deltas, then applies Wilder's smoothing."""
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    # Seed: simple average of first period gains/losses
    avg_gain = sum(max(d, 0.0) for d in deltas[:period]) / period
    avg_loss = sum(abs(min(d, 0.0)) for d in deltas[:period]) / period
    # Wilder's smoothing: EMA with alpha = 1/period
    for d in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + abs(min(d, 0.0))) / period
    if avg_loss == 0.0:
        return 99.0
    if avg_gain == 0.0:
        return 1.0
    return round(100.0 - (100.0 / (1.0 + avg_gain / avg_loss)), 2)

def calculate_atr(highs, lows, closes, period=14):
    """Wilder's ATR — matches TradingView/industry standard.
    Seeds with SMA of first `period` true ranges, then applies Wilder's smoothing."""
    if len(closes) < period + 1:
        return 0.0
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    if len(trs) < period:
        return 0.0
    # Seed: simple average of first period true ranges
    atr = sum(trs[:period]) / period
    # Wilder's smoothing: EMA with alpha = 1/period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 8)

def calculate_roc(prices,period=10):
    if len(prices)<period+1: return 0.0
    old=prices[-(period+1)]; return 0.0 if old==0 else round((prices[-1]-old)/old*100,2)

def get_trend(closes):
    """Trend via EMA50 / EMA200 alignment.
    Returns NEUTRAL when fewer than 200 bars are available — computing EMA200
    on a shorter series produces a meaningless value and is not attempted."""
    if len(closes) < 200: return "NEUTRAL"
    e50  = ema(closes, 50)
    e200 = ema(closes, 200)
    c    = closes[-1]
    if c > e50 and e50 > e200: return "STRONG_BULL"
    elif c > e50:               return "BULL"
    elif c < e50 and e50 < e200: return "STRONG_BEAR"
    elif c < e50:               return "BEAR"
    return "NEUTRAL"

def get_macd(prices, fast=12, slow=26, signal_period=9):
    """MACD with signal-line crossover.

    Builds the full MACD line (EMA_fast − EMA_slow) across all available bars,
    then computes the signal line as a 9-period EMA of that series.
    bullish = MACD above signal line (momentum accelerating upward).
    bearish = MACD below signal line (momentum accelerating downward).

    This provides genuinely independent information from get_trend():
    trend tells you *direction*, MACD crossover tells you *momentum acceleration*.
    Minimum bars: slow + signal_period = 35 (vs previous 27).
    """
    min_bars = slow + signal_period   # 35
    if len(prices) < min_bars:
        return {"value": 0.0, "valid": False, "bullish": False,
                "bearish": False, "histogram": 0.0}

    # Build the full MACD line so the signal EMA has enough history to be meaningful.
    macd_line = [
        ema(prices[:i + 1], fast) - ema(prices[:i + 1], slow)
        for i in range(slow - 1, len(prices))
    ]

    sig = ema(macd_line, signal_period)
    v   = macd_line[-1]
    return {
        "value":     round(v, 8),
        "valid":     True,
        "bullish":   v > sig,        # momentum accelerating upward
        "bearish":   v < sig,        # momentum accelerating downward
        "histogram": round(v - sig, 8),
    }

# ══════════════════════════════════════════════════════════
# MARKET REGIME DETECTION (NEW in v8)
# ══════════════════════════════════════════════════════════
def calculate_adx(highs,lows,closes,period=14):
    """True ADX — measures trend strength 0-100."""
    if len(closes)<period*2+1: return 0.0
    trs,pdms,mdms=[],[],[]
    for i in range(1,len(closes)):
        tr=max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1]))
        up=highs[i]-highs[i-1]; down=lows[i-1]-lows[i]
        pdms.append(up if up>down and up>0 else 0)
        mdms.append(down if down>up and down>0 else 0)
        trs.append(tr)
    if len(trs)<period: return 0.0
    def ws(data,p):
        r=[sum(data[:p])]
        for i in range(p,len(data)): r.append(r[-1]-r[-1]/p+data[i])
        return r
    st=ws(trs,period); sp=ws(pdms,period); sm=ws(mdms,period)
    dxs=[]
    for i in range(len(st)):
        if st[i]==0: continue
        pdi=100*sp[i]/st[i]; mdi=100*sm[i]/st[i]
        dsum=pdi+mdi
        dxs.append(100*abs(pdi-mdi)/dsum if dsum>0 else 0)
    if not dxs: return 0.0
    if len(dxs)<period: return round(sum(dxs)/len(dxs),2)
    adx=sum(dxs[:period])/period
    for dx in dxs[period:]: adx=(adx*(period-1)+dx)/period
    return round(adx,2)

def calculate_atr_ratio(highs,lows,closes,period=14):
    """ATR as % of price — normalized volatility."""
    if len(closes)<period+1: return 0.0
    trs=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1]))
         for i in range(1,len(closes))]
    if not trs: return 0.0
    atr=sum(trs[-period:])/len(trs[-period:])
    return round(atr/closes[-1]*100,3) if closes[-1]>0 else 0.0

def detect_regime(closes, highs, lows,
                  adx_trend: float = 25.0,
                  adx_range: float = 20.0,
                  adx_choppy: float = 15.0) -> dict:
    """
    Classify market into 7 regimes using 3 signals:
      1. ADX          — trend strength (0-100)
      2. Efficiency   — net move / total path (0-1), detects trending vs choppy
      3. ATR ratio    — normalized volatility vs rolling baseline

    Regimes (Task 11):
      LIQUIDATION        — ATR > 5× baseline AND efficient move (flash crash / cascade)
      HIGH_VOLATILITY    — ATR > 2.5× baseline (elevated but not cascade-level)
      LOW_VOLATILITY_CHOP— ADX < 10 AND ATR < 0.6× baseline (dead market, no moves)
      TRENDING_BULL      — ADX>adx_trend, efficient upward movement
      TRENDING_BEAR      — ADX>adx_trend, efficient downward movement
      RANGING            — moderate ADX, moderate efficiency (scalper's zone)
      CHOPPY             — ADX<adx_choppy, low efficiency (noisy, no follow-through)
      UNKNOWN            — insufficient data

    adx_trend/adx_range/adx_choppy are passed by get_regime_for_token() using
    drift-adjusted thresholds from DriftDetector so the classification adapts
    to regime shifts rather than relying on static constants.
    """
    if len(closes) < 40:
        return {"regime":"UNKNOWN","adx":0,"atr_ratio":0,
                "efficiency":0,"confidence":0,"bullish":False,"bearish":False}

    adx_val = calculate_adx(highs, lows, closes)
    atr_r   = calculate_atr_ratio(highs, lows, closes)

    # EMA trend direction
    e20  = ema(closes, 20)
    e50  = ema(closes, min(50, len(closes)))
    bull = closes[-1] > e20 and e20 > e50
    bear = closes[-1] < e20 and e20 < e50

    # Price efficiency: net move / total path
    lb       = min(40, len(closes))
    net_move = abs(closes[-1] - closes[-lb])
    total_path = sum(abs(closes[i]-closes[i-1])
                     for i in range(max(1,len(closes)-lb),len(closes)))
    efficiency = round(net_move/total_path, 3) if total_path > 0 else 0

    # Volatility baseline (rolling median ATR — 7-period ATR sampled every 10 bars)
    baseline_atrs = [calculate_atr_ratio(highs,lows,closes[max(0,i-20):i+1],7)
                     for i in range(20,len(closes),10)]
    med_atr = sorted(baseline_atrs)[len(baseline_atrs)//2] if baseline_atrs else atr_r

    # Volatility conditions
    is_liquidation   = med_atr > 0 and atr_r > med_atr * 5.0 and efficiency > 0.35
    is_high_vol      = med_atr > 0 and atr_r > med_atr * 2.5 and not is_liquidation
    is_low_vol_chop  = adx_val < 10.0 and (med_atr <= 0 or atr_r < med_atr * 0.6)

    # Classify — order matters: liquidation checked before high_vol
    if is_liquidation:
        regime = "LIQUIDATION"
        conf   = min(int(atr_r / max(med_atr, 0.001) * 20), 100)
    elif is_high_vol:
        regime = "HIGH_VOLATILITY"
        conf   = min(int(atr_r / max(med_atr, 0.001) * 30), 100)
    elif is_low_vol_chop:
        regime = "LOW_VOLATILITY_CHOP"
        conf   = min(int((10.0 - adx_val) / 10.0 * 80), 100)
    elif adx_val >= adx_trend and efficiency >= 0.20:
        # Direction must be confirmed by EMA alignment; ambiguous EMA crossovers
        # (price between e20 and e50) are treated as RANGING — no directional bias injected.
        regime = "TRENDING_BULL" if bull else "TRENDING_BEAR" if bear else "RANGING"
        conf   = min(int(adx_val * 1.5), 100)
    elif adx_val >= adx_range and efficiency < 0.20:
        regime = "RANGING"
        conf   = 55
    elif adx_val < adx_range and efficiency >= 0.15:
        regime = "RANGING"
        conf   = 45
    elif adx_val < adx_choppy or efficiency < 0.10:
        regime = "CHOPPY"
        conf   = min(int((0.15 - min(efficiency, 0.15)) / 0.15 * 80), 100)
    else:
        regime = "RANGING"
        conf   = 40

    return {"regime":regime,"adx":round(adx_val,1),"atr_ratio":atr_r,
            "efficiency":efficiency,"bullish":bull,"bearish":bear,"confidence":conf}
