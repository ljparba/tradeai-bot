HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crypto Signal Tracker</title>
<!-- C1 (2026-05-22 tracker audit): Chart.js for the equity curve. CDN load is fine
     since tracker is loopback-only and operator is online when they open it. If
     jsdelivr is ever VPN-blocked, mirror to static/chart.umd.js and update src. -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');
:root{
  --bg:#0a0a0f;--bg2:#12121d;--bg3:#1a1a28;--border:#252538;
  --accent:#7c3aed;--accent2:#a855f7;
  --green:#22c55e;--red:#ef4444;--yellow:#eab308;--blue:#3b82f6;
  --text:#f1f5f9;--muted:#94a3b8;--dim:#1e2030;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;min-height:100vh;font-size:14px}
header{
  background:linear-gradient(135deg,#0f0f1a,#1a0a2e,#0f0f1a);
  border-bottom:1px solid var(--border);padding:1.1rem 2rem;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;backdrop-filter:blur(10px)
}
.logo{display:flex;align-items:center;gap:.75rem}
.pulse{width:10px;height:10px;border-radius:50%;background:var(--accent2);
  box-shadow:0 0 12px var(--accent2);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.8)}}
.logo h1{font-family:'Inter',sans-serif;font-size:1rem;font-weight:800;
  letter-spacing:.1em;color:#fff;text-transform:uppercase}
.logo span{color:var(--accent2)}
.hdr-right{display:flex;align-items:center;gap:1rem}
#lastUpdated{font-size:.8rem;color:var(--muted);font-weight:500}
#dbStatus{font-size:.75rem;padding:.25rem .6rem;border-radius:4px;font-weight:600}
.db-ok{background:rgba(34,197,94,.12);color:var(--green)}
.db-err{background:rgba(239,68,68,.12);color:var(--red)}
.btn{background:var(--accent);color:#fff;border:none;padding:.45rem 1.1rem;
  border-radius:5px;font-family:'Inter',sans-serif;font-size:.82rem;font-weight:600;
  cursor:pointer;letter-spacing:.04em;transition:all .2s;text-transform:uppercase}
.btn:hover{background:var(--accent2);transform:translateY(-1px)}
main{max-width:1500px;margin:0 auto;padding:1.75rem 2rem}

/* STATS */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:1.75rem}
.stat{background:var(--bg2);border:1px solid var(--border);border-radius:10px;
  padding:1.1rem 1.25rem;position:relative;overflow:hidden}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--accent),var(--accent2))}
.stat-label{font-size:.72rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:.45rem;font-weight:600}
.stat-val{font-family:'Inter',sans-serif;font-size:1.9rem;font-weight:800;color:#fff}
.stat-val.g{color:var(--green)}.stat-val.r{color:var(--red)}.stat-val.a{color:var(--accent2)}

/* MAIN TABS */
.main-tabs{display:flex;gap:.5rem;margin-bottom:1.25rem;border-bottom:1px solid var(--border);padding-bottom:0}
.main-tab{padding:.6rem 1.4rem;border-radius:6px 6px 0 0;font-family:'Inter',sans-serif;
  font-size:.85rem;font-weight:600;cursor:pointer;border:1px solid transparent;
  border-bottom:none;background:transparent;color:var(--muted);
  transition:all .2s;display:flex;align-items:center;gap:.5rem;
  position:relative;bottom:-1px}
.main-tab.active{background:var(--bg2);color:#fff;border-color:var(--border);
  border-bottom-color:var(--bg2)}
.main-tab:hover:not(.active){color:var(--accent2)}
.tab-count{background:var(--dim);color:var(--muted);padding:.1rem .45rem;
  border-radius:10px;font-size:.72rem;font-weight:700;min-width:20px;text-align:center}
.main-tab.active .tab-count{background:var(--accent);color:#fff}

/* TAB PANELS */
.tab-panel{display:none}.tab-panel.active{display:block}

/* SECTION HEADER */
.sec-hdr{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:1rem;padding-bottom:.75rem;border-bottom:1px solid var(--border)}
.sec-title{font-family:'Inter',sans-serif;font-size:.82rem;font-weight:700;
  text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.badge{background:var(--dim);padding:.2rem .65rem;border-radius:20px;
  font-size:.75rem;color:var(--muted);font-weight:600}

/* ROLLING WALK-FORWARD CHART (C6, 2026-05-22) */
.wf-wrap{position:relative;height:240px;width:100%;background:rgba(10,10,15,0.4);
  border:1px solid var(--border);border-radius:6px;padding:.5rem}
.wf-wrap canvas{width:100% !important;height:100% !important}
.wf-summary{font-size:.74rem;color:var(--muted);margin-top:.5rem;
  font-family:'JetBrains Mono',monospace}

/* OGD WEIGHT SPARKLINES (C3, 2026-05-22) */
.wt-spark-wrap{margin-top:.6rem;background:rgba(10,10,15,0.5);
  border:1px solid var(--border);border-radius:6px;padding:.5rem .6rem}
.wt-spark{width:100%;height:56px;display:block}
.wt-spark-legend{display:flex;flex-wrap:wrap;gap:.65rem;margin-top:.3rem;
  font-size:.66rem;color:var(--muted)}
.wt-spark-legend .wt-leg-item{display:flex;align-items:center;gap:.25rem}
.wt-spark-legend .wt-leg-dot{width:9px;height:9px;border-radius:2px}

/* HOUR×DAY HEATMAP (C2, 2026-05-22) */
.hm-wrap{padding:.5rem 0;overflow-x:auto}
.hm-grid{display:grid;grid-template-columns:38px repeat(24,minmax(22px,1fr));
  gap:2px;min-width:680px;font-size:.65rem}
.hm-cell{aspect-ratio:1;border-radius:3px;display:flex;align-items:center;justify-content:center;
  cursor:default;position:relative;transition:transform .1s,box-shadow .1s;
  font-family:'JetBrains Mono',monospace;font-weight:700;font-size:.6rem;color:#0a0a0f}
.hm-cell:hover{transform:scale(1.5);z-index:5;box-shadow:0 4px 12px rgba(0,0,0,.5)}
.hm-cell.empty{background:rgba(37,37,56,0.5);cursor:default}
.hm-cell.lown{background:rgba(148,163,184,0.18);color:var(--muted)}
.hm-row-label{font-size:.7rem;color:var(--muted);font-weight:600;
  display:flex;align-items:center;justify-content:flex-end;padding-right:6px}
.hm-col-label{font-size:.6rem;color:var(--muted);font-weight:600;text-align:center;
  font-family:'JetBrains Mono',monospace}
.hm-legend{display:flex;align-items:center;gap:.5rem;margin-top:.75rem;font-size:.72rem;
  color:var(--muted)}
.hm-legend-bar{display:flex;gap:1px;width:140px;height:12px;border-radius:2px;overflow:hidden}
.hm-legend-bar div{flex:1}
.hm-summary{font-size:.74rem;color:var(--muted);margin-top:.5rem;
  font-family:'JetBrains Mono',monospace}

/* TOKEN WR BAR + WILSON CI (C5, 2026-05-22) */
.tok-wr-chart{display:flex;flex-direction:column;gap:.45rem;padding:.5rem 0}
.tok-wr-row{display:grid;grid-template-columns:60px 1fr 110px;gap:.75rem;align-items:center;
  font-size:.78rem}
.tok-wr-label{font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--text)}
.tok-wr-track{position:relative;height:20px;background:var(--dim);border:1px solid var(--border);
  border-radius:4px;overflow:hidden}
.tok-wr-fill{position:absolute;top:0;bottom:0;left:0;border-radius:3px 0 0 3px}
.tok-wr-fill.g{background:linear-gradient(90deg,#16a34a,var(--green))}
.tok-wr-fill.y{background:linear-gradient(90deg,#ca8a04,var(--yellow))}
.tok-wr-fill.r{background:linear-gradient(90deg,#dc2626,var(--red))}
.tok-wr-ci{position:absolute;top:6px;bottom:6px;background:rgba(255,255,255,0.15);
  border-left:2px solid rgba(255,255,255,0.55);border-right:2px solid rgba(255,255,255,0.55)}
.tok-wr-50{position:absolute;top:0;bottom:0;width:1px;left:50%;background:rgba(148,163,184,0.4)}
.tok-wr-stats{color:var(--muted);font-size:.74rem;text-align:right;
  font-family:'JetBrains Mono',monospace;line-height:1.3}
.tok-wr-stats .wr-pct{color:var(--text);font-weight:700;font-size:.82rem}
.tok-wr-stats .wr-pct.g{color:var(--green)}.tok-wr-stats .wr-pct.r{color:var(--red)}

/* CONFIDENCE STACKED BAR (C4, 2026-05-22) */
.conf-stack-wrap{display:flex;flex-direction:column;gap:.5rem}
.conf-stack-row{display:grid;grid-template-columns:60px 1fr 130px;gap:.75rem;align-items:center;
  font-size:.78rem;padding:.15rem 0}
.conf-stack-label{color:var(--text);font-weight:600;font-family:'JetBrains Mono',monospace;font-size:.78rem}
.conf-stack-label.best{color:var(--accent2)}
.conf-stack-bar{display:flex;height:22px;border-radius:4px;overflow:hidden;background:var(--dim);
  border:1px solid var(--border);position:relative}
.conf-stack-seg{height:100%;transition:opacity .15s;cursor:default;position:relative}
.conf-stack-seg:hover{opacity:.85}
.conf-stack-seg.win{background:var(--green)}
.conf-stack-seg.par{background:#06b6d4}
.conf-stack-seg.los{background:var(--red)}
.conf-stack-seg.exp{background:#475569}
.conf-stack-meta{color:var(--muted);font-size:.74rem;display:flex;flex-direction:column;gap:.1rem;text-align:right}
.conf-stack-meta .wr-pct{color:var(--text);font-weight:700;font-size:.82rem;
  font-family:'JetBrains Mono',monospace}
.conf-stack-meta .wr-pct.g{color:var(--green)}.conf-stack-meta .wr-pct.r{color:var(--red)}

/* EQUITY CURVE (C1, 2026-05-22) */
.equity-wrap{background:var(--bg2);border:1px solid var(--border);border-radius:10px;
  padding:1rem 1.25rem;margin-bottom:1.25rem;position:relative;overflow:hidden}
.equity-wrap::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--accent),var(--accent2))}
.equity-hdr{display:flex;align-items:flex-start;justify-content:space-between;
  margin-bottom:.6rem;gap:1rem;flex-wrap:wrap}
.equity-titles{display:flex;flex-direction:column;gap:.3rem}
.equity-sub{font-size:.78rem;color:var(--muted);font-weight:500;
  font-family:'JetBrains Mono',monospace}
.equity-range{display:flex;gap:.35rem}
.equity-range .ftab{padding:.22rem .7rem;font-size:.72rem}
.equity-canvas-wrap{position:relative;height:220px;width:100%}
@media(max-width:768px){.equity-canvas-wrap{height:180px}}

/* OPEN CARDS */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;
  padding:1rem 1.25rem;margin-bottom:.75rem;display:grid;
  grid-template-columns:auto 1fr auto;gap:1rem;align-items:center;
  transition:border-color .2s;position:relative;overflow:hidden}
.card:hover{border-color:var(--accent)}
.card.buy::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--green)}
.card.sell::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--red)}
.sig-badge{padding:.35rem .8rem;border-radius:5px;font-size:.78rem;font-weight:700;
  text-transform:uppercase;font-family:'JetBrains Mono',monospace}
.sig-badge.buy{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.sig-badge.sell{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.card-info{display:flex;flex-direction:column;gap:.3rem}
.card-token{font-family:'Inter',sans-serif;font-size:1.05rem;font-weight:700;color:#fff}
.card-sub{font-size:.82rem;color:var(--muted);font-weight:500}
.card-levels{display:flex;flex-direction:column;gap:.28rem;text-align:right}
.lrow{font-size:.8rem;display:flex;gap:.5rem;justify-content:flex-end;align-items:center}
.llbl{color:var(--muted);min-width:32px;font-weight:600}
.lval{color:var(--text);font-weight:600;font-family:'JetBrains Mono',monospace}
.lhit{color:var(--green)}
.dots{display:flex;gap:3px;margin-top:.5rem}
.dot-tp{width:24px;height:6px;border-radius:2px;background:var(--dim)}
.dot-tp.hit{background:var(--green)}
.dot-sl{width:24px;height:6px;border-radius:2px;background:var(--dim)}
.dot-sl.hit{background:var(--red)}

/* FILTER TABS (inside Signal History) */
.filter-tabs{display:flex;gap:.4rem}
.ftab{padding:.3rem .85rem;border-radius:5px;font-family:'Inter',sans-serif;font-size:.8rem;
  font-weight:600;cursor:pointer;border:1px solid var(--border);background:transparent;
  color:var(--muted);text-transform:uppercase;transition:all .2s}
.ftab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.ftab:hover:not(.active){border-color:var(--accent2);color:var(--accent2)}

/* TABLE */
.tbl-wrap{overflow-x:auto;border-radius:10px;border:1px solid var(--border)}
table{width:100%;border-collapse:collapse;font-size:.82rem}
thead tr{background:var(--bg3)}
th{padding:.75rem 1rem;text-align:left;color:var(--muted);font-weight:700;
  text-transform:uppercase;letter-spacing:.06em;font-size:.7rem;
  border-bottom:1px solid var(--border);white-space:nowrap;font-family:'Inter',sans-serif}
td{padding:.65rem 1rem;border-bottom:1px solid rgba(37,37,56,.6);vertical-align:middle;
  font-family:'Inter',sans-serif}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(37,37,56,.45)}
.tok{font-family:'Inter',sans-serif;font-weight:700;color:#fff;font-size:.88rem}
.mono{font-family:'JetBrains Mono',monospace;font-size:.8rem}
.out{padding:.25rem .55rem;border-radius:4px;font-size:.7rem;font-weight:700;
  text-transform:uppercase;font-family:'Inter',sans-serif;letter-spacing:.03em}
.out.WIN{background:rgba(34,197,94,.15);color:var(--green)}
.out.LOSS{background:rgba(239,68,68,.15);color:var(--red)}
.out.PARTIAL{background:rgba(234,179,8,.15);color:var(--yellow)}
.out.OPEN{background:rgba(59,130,246,.15);color:var(--blue)}
.out.EXPIRED{background:rgba(148,163,184,.1);color:var(--muted)}
.pnl-p{color:var(--green);font-weight:700;font-family:'JetBrains Mono',monospace}
.pnl-n{color:var(--red);font-weight:700;font-family:'JetBrains Mono',monospace}
.mtf{font-size:.7rem;padding:.2rem .45rem;border-radius:3px;font-weight:700;font-family:'Inter',sans-serif}
.mtf.BULLISH{background:rgba(34,197,94,.12);color:var(--green)}
.mtf.BEARISH{background:rgba(239,68,68,.12);color:var(--red)}
.mtf.NEUTRAL{background:rgba(148,163,184,.1);color:var(--muted)}
.conf-bar{display:inline-flex;gap:2px;vertical-align:middle}
.cseg{width:9px;height:9px;border-radius:2px;background:var(--dim)}
.cseg.on{background:var(--accent2)}
.trend{font-size:.75rem;font-weight:600;font-family:'JetBrains Mono',monospace;
  padding:.15rem .4rem;border-radius:3px;white-space:nowrap}
.trend.bull,.trend.strong-bull{background:rgba(34,197,94,.1);color:var(--green)}
.trend.bear,.trend.strong-bear{background:rgba(239,68,68,.1);color:var(--red)}
.trend.neutral{color:var(--muted)}
.empty{text-align:center;padding:3rem;color:var(--muted);font-size:.9rem}
.err-banner{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);
  border-radius:6px;padding:.75rem 1rem;margin-bottom:1rem;
  font-size:.82rem;color:var(--red);display:none}

/* INTELLIGENCE TAB */
.intel-sec{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
  padding:1.5rem 2rem;position:relative;overflow:hidden;margin-bottom:1.25rem}
.intel-sec-title{font-family:'Inter',sans-serif;font-size:.78rem;font-weight:700;
  text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
  margin-bottom:1rem;padding-bottom:.6rem;border-bottom:1px solid var(--border)}

/* BOT SCORE */
.bot-score-wrap{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
  padding:1.5rem 2rem;position:relative;overflow:hidden;margin-bottom:1.75rem}
.bot-score-wrap::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:linear-gradient(90deg,var(--accent),var(--accent2),var(--blue))}
.bot-score-layout{display:flex;align-items:center;gap:2.5rem;flex-wrap:wrap}
.bot-score-left{display:flex;flex-direction:column;align-items:center;min-width:120px}
.bot-score-num{font-family:'Inter',sans-serif;font-size:3.5rem;font-weight:800;
  line-height:1;color:#fff}
.bot-score-denom{font-size:.85rem;color:var(--muted);font-weight:600;margin-top:.2rem}
.bot-score-status{font-size:.82rem;font-weight:700;margin-top:.4rem;padding:.25rem .7rem;
  border-radius:20px;letter-spacing:.04em}
.status-excellent{background:rgba(34,197,94,.15);color:var(--green)}
.status-average{background:rgba(234,179,8,.15);color:var(--yellow)}
.status-weak{background:rgba(239,68,68,.15);color:var(--red)}
.status-awaiting{background:rgba(148,163,184,.12);color:var(--muted);text-transform:none;letter-spacing:.02em}
.bot-score-right{flex:1;min-width:200px}
.bot-bar-wrap{background:var(--dim);border-radius:6px;height:10px;margin-bottom:1rem;overflow:hidden}
.bot-bar-fill{height:100%;border-radius:6px;transition:width .6s ease;
  background:linear-gradient(90deg,var(--accent),var(--accent2))}
.bot-parts{display:flex;gap:1.5rem;flex-wrap:wrap}
.bot-part{display:flex;flex-direction:column;gap:.2rem}
.bot-part-label{font-size:.68rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.07em;font-weight:600}
.bot-part-val{font-size:.92rem;font-weight:700;color:var(--text);
  font-family:'JetBrains Mono',monospace}
.bot-part-max{color:var(--muted);font-size:.8rem}

/* CONFIDENCE ANALYTICS CARDS */
.intel-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:1rem;margin-bottom:1.75rem}
.icard{background:var(--bg2);border:1px solid var(--border);border-radius:10px;
  padding:1.1rem 1.25rem;position:relative;overflow:hidden}
.icard::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--accent),var(--accent2))}
.icard-label{font-size:.7rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:.4rem;font-weight:600}
.icard-val{font-family:'Inter',sans-serif;font-size:2rem;font-weight:800;color:#fff;
  line-height:1.1}
.icard-val.g{color:var(--green)}.icard-val.r{color:var(--red)}.icard-val.a{color:var(--accent2)}
.icard-sub{font-size:.75rem;color:var(--muted);margin-top:.3rem;font-weight:500}
.icard-sub strong{color:var(--text)}

/* CONFIDENCE LEVEL BREAKDOWN */
.conf-breakdown{display:flex;flex-direction:column;gap:.5rem}
.clrow{display:flex;align-items:center;gap:.75rem}
.cl-label{font-family:'JetBrains Mono',monospace;font-size:.78rem;color:var(--muted);
  width:52px;flex-shrink:0;font-weight:600}
.cl-bar-wrap{flex:1;background:var(--dim);border-radius:3px;height:8px;overflow:hidden}
.cl-bar-fill{height:100%;border-radius:3px;background:var(--accent2);transition:width .5s}
.cl-bar-fill.best{background:var(--green)}
.cl-stats{font-family:'JetBrains Mono',monospace;font-size:.75rem;
  color:var(--text);width:90px;text-align:right;flex-shrink:0}
.cl-count{font-size:.7rem;color:var(--muted);width:60px;text-align:right;flex-shrink:0}

/* TOKEN PERFORMANCE */
.tok-rating{font-size:.72rem;font-weight:700;padding:.2rem .5rem;border-radius:3px}
.tok-rating.strong{background:rgba(34,197,94,.15);color:var(--green)}
.tok-rating.average{background:rgba(234,179,8,.15);color:var(--yellow)}
.tok-rating.weak{background:rgba(239,68,68,.15);color:var(--red)}
.tok-rating.nodata{background:rgba(148,163,184,.1);color:var(--muted)}
.wr-bar-wrap{display:flex;align-items:center;gap:.5rem}
.wr-mini-bar{width:60px;height:6px;border-radius:2px;background:var(--dim);overflow:hidden}
.wr-mini-fill{height:100%;border-radius:2px}

@media(max-width:768px){main{padding:1rem}.card{grid-template-columns:1fr}.card-levels{text-align:left}
  .bot-score-layout{flex-direction:column}.bot-parts{gap:1rem}}

/* BACKTEST TAB */
.bt-controls{background:var(--bg2);border:1px solid var(--border);border-radius:10px;
  padding:1.25rem 1.5rem;margin-bottom:1.5rem;display:flex;flex-wrap:wrap;
  align-items:center;gap:1rem}
.btn-run{background:linear-gradient(135deg,var(--accent),var(--accent2));
  color:#fff;border:none;padding:.6rem 1.5rem;border-radius:6px;
  font-family:'Inter',sans-serif;font-size:.9rem;font-weight:700;
  cursor:pointer;letter-spacing:.04em;transition:all .2s;text-transform:uppercase}
.btn-run:hover{transform:translateY(-2px);box-shadow:0 4px 20px rgba(124,58,237,.4)}
.btn-run:disabled{opacity:.5;cursor:not-allowed;transform:none}
.bt-status-pill{display:flex;align-items:center;gap:.5rem;padding:.35rem .8rem;
  border-radius:20px;font-size:.8rem;font-weight:600;border:1px solid var(--border)}
.bt-dot{width:8px;height:8px;border-radius:50%}
.bt-dot.idle{background:var(--muted)}
.bt-dot.running{background:var(--yellow);box-shadow:0 0 8px var(--yellow);animation:blink 1s infinite}
.bt-dot.done{background:var(--green)}
.bt-dot.failed{background:var(--red)}
.bt-progress-wrap{flex:1;min-width:200px;display:flex;flex-direction:column;gap:.35rem}
.bt-progress-bar{background:var(--dim);border-radius:4px;height:8px;overflow:hidden}
.bt-progress-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--accent),var(--accent2));
  transition:width .4s ease}
.bt-progress-msg{font-size:.75rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bt-meta-bar{background:var(--bg2);border:1px solid var(--border);border-radius:8px;
  padding:.85rem 1.25rem;display:flex;gap:2rem;flex-wrap:wrap;margin-bottom:1.5rem;
  align-items:center}
.bt-meta-item{display:flex;flex-direction:column;gap:.2rem}
.bt-meta-label{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;font-weight:600}
.bt-meta-val{font-family:'Inter',sans-serif;font-size:1.3rem;font-weight:800;color:#fff}
.bt-meta-val.g{color:var(--green)}.bt-meta-val.a{color:var(--accent2)}
.rec-list{display:flex;flex-direction:column;gap:.65rem}
.rec-item{padding:.85rem 1.1rem;border-radius:8px;border-left:3px solid;display:grid;
  grid-template-columns:auto 1fr;gap:.5rem 1rem;align-items:start}
.rec-item.WARNING{background:rgba(239,68,68,.07);border-color:var(--red)}
.rec-item.STRENGTH{background:rgba(34,197,94,.07);border-color:var(--green)}
.rec-item.INFO{background:rgba(59,130,246,.07);border-color:var(--blue)}
.rec-icon{font-size:1rem;line-height:1.4}
.rec-body{display:flex;flex-direction:column;gap:.25rem}
.rec-title{font-weight:700;font-size:.85rem;color:var(--text)}
.rec-detail{font-size:.78rem;color:var(--muted)}
.rec-action{font-size:.78rem;color:var(--accent2);font-weight:600;
  background:rgba(124,58,237,.1);border-radius:3px;padding:.2rem .5rem;display:inline-block;margin-top:.2rem}
.rec-area{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
  padding:.15rem .45rem;border-radius:3px;display:inline-block;margin-bottom:.2rem}
.rec-area.WARNING{background:rgba(239,68,68,.15);color:var(--red)}
.rec-area.STRENGTH{background:rgba(34,197,94,.15);color:var(--green)}
.rec-area.INFO{background:rgba(59,130,246,.15);color:var(--blue)}
.hist-run{display:flex;align-items:center;gap:1rem;padding:.6rem 1rem;
  border-radius:6px;background:var(--bg3);border:1px solid var(--border);
  margin-bottom:.5rem;cursor:pointer;transition:border-color .2s}
.hist-run:hover{border-color:var(--accent)}
.hist-run-date{font-size:.82rem;color:var(--muted);min-width:130px}
.hist-run-stats{display:flex;gap:1rem;flex:1;flex-wrap:wrap}
.hist-stat{font-size:.82rem;font-weight:600}

/* TUNE PANEL */
.tune-panel{background:var(--bg2);border:1px solid var(--accent);border-radius:10px;
  padding:1.25rem 1.5rem;margin-top:1.25rem}
.tune-panel-title{font-family:'Inter',sans-serif;font-size:.82rem;font-weight:700;
  text-transform:uppercase;letter-spacing:.08em;color:var(--accent2);margin-bottom:1rem;
  display:flex;align-items:center;gap:.6rem}
.tune-item{border:1px solid var(--border);border-radius:8px;padding:.85rem 1rem;
  margin-bottom:.65rem;border-left:3px solid var(--accent2)}
.tune-param{font-family:'JetBrains Mono',monospace;font-size:.85rem;font-weight:700;
  color:var(--accent2);margin-bottom:.35rem;display:flex;align-items:center;gap:.5rem}
.tune-delta{font-size:.75rem;font-weight:700;padding:.12rem .45rem;border-radius:3px;
  background:rgba(168,85,247,.18);color:var(--accent2)}
.tune-vals{font-size:.83rem;margin-bottom:.4rem;color:var(--text)}
.tune-old{font-family:'JetBrains Mono',monospace;color:var(--muted);text-decoration:line-through}
.tune-new{font-family:'JetBrains Mono',monospace;color:var(--green);font-weight:700}
.tune-weight-changes{margin:.35rem 0 .4rem;display:flex;flex-direction:column;gap:.22rem}
.tune-weight-row{font-family:'JetBrains Mono',monospace;font-size:.76rem;color:var(--text);
  padding:.15rem .5rem;background:var(--dim);border-radius:3px}
.tune-reason{font-size:.76rem;color:var(--muted);font-style:italic;
  padding:.3rem .5rem;border-radius:3px;background:rgba(148,163,184,.05)}
.tune-footer{display:flex;gap:.85rem;margin-top:1.1rem;align-items:center;flex-wrap:wrap}
.btn-apply{background:var(--green);color:#000;border:none;padding:.55rem 1.5rem;
  border-radius:6px;font-family:'Inter',sans-serif;font-size:.88rem;font-weight:800;
  cursor:pointer;letter-spacing:.04em;transition:all .2s}
.btn-apply:hover{opacity:.9;transform:translateY(-1px)}
.btn-apply:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-cancel{background:transparent;color:var(--muted);border:1px solid var(--border);
  padding:.55rem 1.1rem;border-radius:6px;font-family:'Inter',sans-serif;
  font-size:.88rem;font-weight:600;cursor:pointer;transition:all .2s}
.btn-cancel:hover{border-color:var(--accent2);color:var(--accent2)}
.tune-success{background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.25);
  border-radius:8px;padding:1.25rem 1.5rem;line-height:1.9;font-size:.88rem;color:var(--text)}
.tune-none{color:var(--muted);font-size:.85rem;font-style:italic;padding:.5rem 0}
/* PAGINATION */
.pg-bar{display:flex;align-items:center;justify-content:center;gap:1rem;
  padding:1rem 0;border-top:1px solid var(--border);margin-top:.25rem}
.pg-btn{background:var(--bg2);color:var(--text);border:1px solid var(--border);
  padding:.38rem 1rem;border-radius:6px;font-family:'Inter',sans-serif;
  font-size:.82rem;font-weight:600;cursor:pointer;transition:all .2s}
.pg-btn:hover:not(:disabled){border-color:var(--accent2);color:var(--accent2)}
.pg-btn:disabled{opacity:.35;cursor:not-allowed}
.pg-info{font-size:.82rem;color:var(--muted);min-width:200px;text-align:center}
/* TOKEN FILTER PILLS */
.tok-filter{display:flex;flex-wrap:wrap;gap:.45rem;padding:.5rem 0 .9rem}
.tok-pill{background:var(--bg3);color:var(--muted);border:1px solid var(--border);
  padding:.25rem .75rem;border-radius:20px;font-size:.76rem;font-weight:600;
  cursor:pointer;transition:all .18s}
.tok-pill:hover{border-color:var(--accent2);color:var(--accent2)}
.tok-pill.active{background:rgba(124,58,237,.18);border-color:var(--accent2);color:var(--accent2)}
/* SORTABLE TABLE HEADERS */
.sortable{cursor:pointer;user-select:none;white-space:nowrap}
.sortable:hover{color:var(--accent2)}
.sort-ico{font-size:.62rem;color:var(--muted);margin-left:.15rem;opacity:.4;transition:opacity .15s}
.sort-ico.on{opacity:1;color:var(--accent2)}
/* AUTO-REFRESH ACTIVE STATE */
.btn.ar-on{background:rgba(34,197,94,.12);border-color:var(--green);color:var(--green)}

/* MANUAL CLOSE BUTTON (on cards) */
.close-card-btn{background:rgba(124,58,237,.12);border:1px solid rgba(124,58,237,.3);
  color:var(--accent2);border-radius:4px;padding:.22rem .65rem;font-size:.72rem;
  font-weight:700;cursor:pointer;transition:all .18s;font-family:'Inter',sans-serif;
  letter-spacing:.04em;text-transform:uppercase;white-space:nowrap;margin-left:.5rem}
.close-card-btn:hover{background:rgba(124,58,237,.28);border-color:var(--accent2);
  transform:translateY(-1px)}

/* CLOSE POSITION MODAL */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:9999;
  display:flex;align-items:center;justify-content:center;backdrop-filter:blur(6px)}
.modal-box{background:var(--bg2);border:1px solid var(--border);border-radius:14px;
  padding:2rem;width:440px;max-width:92vw;position:relative;
  box-shadow:0 24px 80px rgba(0,0,0,.6)}
.modal-box::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;
  border-radius:14px 14px 0 0;
  background:linear-gradient(90deg,var(--accent),var(--accent2))}
.modal-x{position:absolute;top:1rem;right:1rem;background:transparent;border:none;
  color:var(--muted);cursor:pointer;font-size:1.1rem;padding:.25rem .45rem;
  border-radius:5px;line-height:1;transition:all .15s}
.modal-x:hover{color:#fff;background:var(--dim)}
.modal-h{font-family:'Inter',sans-serif;font-size:1rem;font-weight:700;
  color:#fff;margin-bottom:.3rem}
/* FAQ modal — wide, scrollable, for detailed panel docs */
.modal-box.faq{width:900px;max-width:95vw;max-height:85vh;overflow-y:auto;padding:1.5rem 1.8rem}
.modal-box.faq h3{font-size:1rem;color:var(--accent);margin:1.6rem 0 .55rem 0;
  padding-bottom:.35rem;border-bottom:1px solid var(--border)}
.modal-box.faq h3:first-of-type{margin-top:.5rem}
.modal-box.faq h4{font-size:.86rem;color:#e6e6e6;margin:1rem 0 .4rem 0;font-weight:600}
.modal-box.faq p{font-size:.85rem;line-height:1.6;color:#d0d0d0;margin:.4rem 0 .8rem 0}
.modal-box.faq ul, .modal-box.faq ol{font-size:.85rem;line-height:1.65;color:#d0d0d0;
  margin:.4rem 0 .8rem 0;padding-left:1.4rem}
.modal-box.faq li{margin-bottom:.3rem}
.modal-box.faq code{background:var(--bg);padding:1px 6px;border-radius:3px;
  font-family:'JetBrains Mono',monospace;font-size:.78rem;color:#9ad6ff}
.modal-box.faq strong{color:#fff;font-weight:600}
.modal-box.faq table{width:100%;border-collapse:collapse;font-size:.8rem;margin:.4rem 0 .9rem 0}
.modal-box.faq th{text-align:left;padding:.4rem .55rem;color:var(--muted);
  border-bottom:1px solid var(--border);font-weight:600;font-size:.75rem}
.modal-box.faq td{padding:.4rem .55rem;border-bottom:1px solid rgba(148,163,184,.07);
  color:#d0d0d0;vertical-align:top}
.faq-tip{background:rgba(34,197,94,.08);border-left:3px solid #22c55e;
  padding:.6rem .85rem;border-radius:4px;margin:.6rem 0;font-size:.82rem;line-height:1.55}
.faq-warn{background:rgba(245,158,11,.08);border-left:3px solid #f59e0b;
  padding:.6rem .85rem;border-radius:4px;margin:.6rem 0;font-size:.82rem;line-height:1.55}
.faq-danger{background:rgba(239,68,68,.08);border-left:3px solid #ef4444;
  padding:.6rem .85rem;border-radius:4px;margin:.6rem 0;font-size:.82rem;line-height:1.55}
.faq-tip strong, .faq-warn strong, .faq-danger strong{color:#fff}
.faq-learn-btn{display:inline-block;margin-top:.55rem;background:var(--accent);
  color:#fff;padding:.4rem .8rem;border-radius:5px;text-decoration:none;
  font-size:.75rem;font-weight:600;border:none;cursor:pointer;transition:all .15s}
.faq-learn-btn:hover{filter:brightness(1.15);transform:translateY(-1px)}
.modal-sub{font-size:.78rem;color:var(--muted);margin-bottom:1.4rem;font-weight:500}
.modal-sig-row{display:flex;gap:.6rem;margin-bottom:1.25rem;flex-wrap:wrap}
.modal-sig-chip{background:var(--dim);border:1px solid var(--border);border-radius:6px;
  padding:.35rem .75rem;font-size:.75rem;color:var(--muted);font-weight:500}
.modal-sig-chip strong{color:var(--text);font-family:'JetBrains Mono',monospace}
.modal-label{font-size:.7rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;font-weight:600;margin-bottom:.4rem;display:block}
.modal-input{width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:7px;padding:.65rem .9rem;color:#fff;
  font-family:'JetBrains Mono',monospace;font-size:1.05rem;font-weight:600;
  outline:none;transition:border-color .2s;margin-bottom:1.1rem}
.modal-input:focus{border-color:var(--accent2)}
.modal-preview{background:var(--dim);border-radius:8px;padding:.9rem 1rem;
  margin-bottom:1.25rem;display:grid;grid-template-columns:1fr 1fr;gap:.5rem .75rem}
.mprow{display:flex;flex-direction:column;gap:.15rem}
.mprow-label{font-size:.67rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.07em;font-weight:600}
.mprow-val{font-family:'JetBrains Mono',monospace;font-size:.9rem;font-weight:700}
.modal-actions{display:flex;gap:.75rem;margin-top:.25rem}
.btn-confirm-close{flex:1;background:var(--green);color:#000;border:none;
  padding:.7rem;border-radius:7px;font-family:'Inter',sans-serif;
  font-size:.92rem;font-weight:800;cursor:pointer;letter-spacing:.03em;
  transition:all .2s;text-transform:uppercase}
.btn-confirm-close:hover:not(:disabled){opacity:.88;transform:translateY(-1px)}
.btn-confirm-close:disabled{opacity:.35;cursor:not-allowed;transform:none}
.btn-confirm-close.is-loss{background:var(--red);color:#fff}
.btn-modal-cancel{background:transparent;border:1px solid var(--border);color:var(--muted);
  padding:.7rem 1.1rem;border-radius:7px;cursor:pointer;font-size:.9rem;
  font-weight:600;transition:all .2s;font-family:'Inter',sans-serif}
.btn-modal-cancel:hover{border-color:var(--accent2);color:var(--accent2)}

/* ── ADAPTIVE LEARNING TAB ─────────────────────────────────── */
.adap-gauge-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
@media(max-width:1100px){.adap-gauge-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){.adap-gauge-grid{grid-template-columns:1fr}}
.adap-gauge-card{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:.85rem 1rem}
.adap-gauge-header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.5rem}
.adap-gauge-label{font-size:.75rem;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.adap-gauge-val{font-family:'JetBrains Mono',monospace;font-size:.9rem;font-weight:700;color:var(--text)}
.port-bar{height:8px;border-radius:4px;background:var(--dim);overflow:hidden;margin-bottom:.1rem}
.port-bar-fill{height:100%;border-radius:4px;transition:width .4s ease;background:var(--accent)}
.port-bar-fill.full{background:var(--red)}.port-bar-fill.warn{background:var(--yellow)}
.port-bar-fill.ok{background:var(--green)}
.wt-token-block{margin-bottom:1.1rem;padding-bottom:1rem;border-bottom:1px solid var(--border)}
.wt-token-block:last-child{border-bottom:none;margin-bottom:0;padding-bottom:0}
.wt-token-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:.6rem}
.wt-token-name{font-weight:700;font-size:.95rem;color:#fff}
.wt-token-meta{font-size:.72rem;color:var(--muted)}
.wt-token-meta .n-val{color:var(--accent2);font-weight:600}
.wt-feat-row{display:flex;align-items:center;gap:.5rem;margin-bottom:.35rem}
.wt-feat-label{font-size:.72rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;min-width:62px;font-weight:600}
.wt-bar-bg{flex:1;height:7px;border-radius:4px;background:var(--dim);overflow:hidden;position:relative}
.wt-bar-fill{height:100%;border-radius:4px;transition:width .4s ease}
.wt-bar-fill.above{background:var(--green)}.wt-bar-fill.below{background:var(--muted)}
.wt-bar-default{position:absolute;top:0;bottom:0;left:33.4%;width:1px;background:var(--accent2);opacity:.5}
.wt-val{font-family:'JetBrains Mono',monospace;font-size:.75rem;color:var(--text);min-width:46px;text-align:right}
.wt-wr-row{font-size:.72rem;margin-top:.5rem;padding-top:.4rem;border-top:1px solid var(--border);font-weight:600}
.wt-wr-row.muted{color:var(--muted);font-weight:400}
.drift-token-block{margin-bottom:.8rem;padding:.75rem;background:var(--bg3);
  border-radius:8px;border:1px solid var(--border)}
.drift-token-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:.5rem}
.drift-token-name{font-weight:700;font-size:.9rem;color:#fff}
.drift-badge{font-size:.68rem;font-weight:700;padding:.15rem .5rem;border-radius:8px;
  text-transform:uppercase;letter-spacing:.04em}
.drift-badge.active{background:rgba(124,58,237,.2);color:var(--accent2);border:1px solid var(--accent)}
.drift-badge.learning{background:var(--dim);color:var(--muted);border:1px solid var(--border)}
.drift-thresholds{display:flex;gap:1rem;flex-wrap:wrap}
.drift-thr{text-align:center}
.drift-thr-label{font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:.2rem}
.drift-thr-val{font-family:'JetBrains Mono',monospace;font-size:.88rem;font-weight:700;color:#fff}
.drift-thr-default{font-size:.68rem;color:var(--muted)}
.adap-stale{font-size:.72rem;color:var(--yellow);margin-top:.5rem}
.adap-empty{color:var(--muted);font-size:.85rem;padding:.5rem 0}
.bot-active-dot{display:inline-block;width:8px;height:8px;border-radius:50%;
  margin-right:.4rem;vertical-align:middle}
.bot-active-dot.on{background:var(--green);box-shadow:0 0 6px var(--green)}
.bot-active-dot.off{background:var(--muted)}

/* HONEST METRICS TAB (Sprint 3 + FIX 1 Part 2 surfaces) */
.honest-status-row{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-bottom:1.5rem}
@media(max-width:1100px){.honest-status-row{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){.honest-status-row{grid-template-columns:1fr}}
.honest-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:1rem}
.honest-card.honest-status{text-align:center}
.honest-label{color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;font-weight:600;margin-bottom:.4rem}
.honest-value{font-size:1.6rem;font-weight:700;color:var(--accent);margin-bottom:.2rem;line-height:1.1}
.honest-value.ok{color:var(--green)}
.honest-value.warn{color:#ffb84d}
.honest-value.crit{color:#ff4444}
.honest-sub{color:var(--muted);font-size:.78rem}
.honest-section{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:1.1rem 1.3rem;margin-bottom:1.5rem}
.honest-section-title{color:var(--accent);font-size:.9rem;font-weight:600;margin-bottom:.9rem;border-bottom:1px solid var(--border);padding-bottom:.5rem}
.honest-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
@media(max-width:900px){.honest-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:560px){.honest-grid{grid-template-columns:1fr}}
.honest-cell{background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:.85rem 1rem;position:relative}
.honest-cell.honest-highlight{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.honest-cell-label{color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;margin-bottom:.35rem}
.honest-cell-value{font-size:1.35rem;font-weight:700;color:#fff;margin-bottom:.2rem;line-height:1.1}
.honest-cell-sub{color:var(--muted);font-size:.7rem}
.honest-verdict-row{display:flex;align-items:center;gap:.7rem;margin-top:1rem;padding:.65rem 1rem;background:var(--bg3);border:1px solid var(--border);border-radius:6px}
.honest-verdict-label{color:var(--muted);font-size:.85rem;font-weight:600}
.honest-verdict-value{font-size:1.1rem;font-weight:700;letter-spacing:.5px}
.honest-verdict-value.pass{color:var(--green)}
.honest-verdict-value.marginal{color:#ffb84d}
.honest-verdict-value.fail{color:#ff4444}
.honest-progress-wrap{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:.9rem 1.1rem}
.honest-progress-header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.5rem;color:#fff;font-weight:600}
.honest-progress-bar{background:var(--bg);border-radius:6px;overflow:hidden;height:14px;border:1px solid var(--border)}
.honest-progress-fill{background:linear-gradient(90deg,var(--accent),var(--green));height:100%;transition:width .4s ease}

/* Plain-English descriptions for non-experts */
.honest-desc{color:var(--muted);font-size:.72rem;line-height:1.4;margin-top:.55rem;padding-top:.5rem;border-top:1px dashed var(--border);font-style:italic;text-align:left}
.honest-status .honest-desc{text-align:center}
.honest-section-intro{color:var(--muted);font-size:.82rem;line-height:1.5;margin:-.4rem 0 1rem 0;padding:.65rem .85rem;background:var(--bg);border-left:3px solid var(--accent);border-radius:4px}
.honest-section-intro b{color:#eaeaea;font-weight:600}
.honest-cell-desc{color:var(--muted);font-size:.7rem;line-height:1.4;margin-top:.5rem;padding-top:.45rem;border-top:1px dashed var(--border);font-style:italic}
.honest-cell-desc code{background:var(--bg);padding:1px 5px;border-radius:3px;font-size:.95em}

/* Verdict legend (below the verdict row) */
.honest-verdict-legend{display:flex;flex-direction:column;gap:.35rem;margin-top:.8rem;padding:.7rem 1rem;background:var(--bg);border:1px dashed var(--border);border-radius:6px;font-size:.78rem;color:var(--muted)}
.honest-verdict-legend b{color:#eaeaea}
.honest-legend-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:.4rem;vertical-align:middle}
.honest-legend-dot.pass{background:var(--green)}
.honest-legend-dot.marginal{background:#ffb84d}
.honest-legend-dot.fail{background:#ff4444}
</style>
</head>
<body>
<header>
  <div class="logo">
    <div class="pulse"></div>
    <h1>Crypto <span>Signal</span> Tracker</h1>
  </div>
  <div class="hdr-right">
    <span id="dbStatus" class="db-ok">DB OK</span>
    <span id="lastUpdated">Loading...</span>
    <button class="btn" onclick="loadAll()">&#8635; Refresh</button>
    <button class="btn" id="autoRefBtn" onclick="toggleAutoRefresh(this)" style="font-size:.75rem;padding:.35rem .85rem">Auto Off</button>
  </div>
</header>
<main>
  <div id="errBanner" class="err-banner"></div>

  <!-- STATS -->
  <div class="stats">
    <div class="stat"><div class="stat-label">Total Signals</div><div class="stat-val a" id="s-total">—</div></div>
    <div class="stat"><div class="stat-label">Win Rate</div><div class="stat-val g" id="s-wr">—</div></div>
    <div class="stat"><div class="stat-label">Wins</div><div class="stat-val g" id="s-wins">—</div></div>
    <div class="stat"><div class="stat-label">Losses</div><div class="stat-val r" id="s-losses">—</div></div>
    <div class="stat"><div class="stat-label">Open</div><div class="stat-val" id="s-open">—</div></div>
    <div class="stat"><div class="stat-label">Avg R:R</div><div class="stat-val a" id="s-rr">—</div></div>
    <div class="stat"><div class="stat-label">Best Trade</div><div class="stat-val g" id="s-best">—</div></div>
  </div>

  <!-- MAIN TABS -->
  <div class="main-tabs">
    <button class="main-tab active" id="tabBtnOpen" onclick="showTab('open',this)">
      Open Positions <span class="tab-count" id="openCount">0</span>
    </button>
    <button class="main-tab" id="tabBtnHistory" onclick="showTab('history',this)">
      Signal History <span class="tab-count" id="histCount">0</span>
    </button>
    <button class="main-tab" id="tabBtnIntelligence" onclick="showTab('intelligence',this)">
      AI Intelligence <span class="tab-count">&#9889;</span>
    </button>
    <button class="main-tab" id="tabBtnBacktest" onclick="showTab('backtest',this);loadBacktest();loadBaselinePin()">
      &#128202; Backtest <span class="tab-count" id="btRunCount">—</span>
    </button>
    <button class="main-tab" id="tabBtnAdaptive" onclick="showTab('adaptive',this);loadAdaptive()">
      &#129504; Adaptive <span class="tab-count" id="adaptCount">&#9679;</span>
    </button>
    <button class="main-tab" id="tabBtnHonest" onclick="showTab('honest',this);loadHonestMetrics()">
      &#128205; Honest Metrics <span class="tab-count" id="honestPill">&middot;</span>
    </button>
    <!-- QuantStats tab HIDDEN 2026-05-24:
         Re-enable when LIVE trading starts AND closed signals start producing
         real P&L. Until then, the panel mostly shows zero/empty cards (paper
         signals are absent, backtest tearsheet is a useful but secondary view).
         Backend routes /api/quantstats and /api/quantstats/tearsheet remain
         active — only the tab visibility is suppressed.
         To re-enable: remove style="display:none" from the button below. -->
    <button class="main-tab" id="tabBtnQuantStats" style="display:none"
            onclick="showTab('quantstats',this);loadQuantStats()">
      &#128201; QuantStats <span class="tab-count" id="qsPill">&middot;</span>
    </button>
    <button class="main-tab" id="tabBtnExplorer" onclick="showTab('explorer',this);loadExplorer()">
      &#129302; Auto-Explorer <span class="tab-count" id="explorerPill">&middot;</span>
    </button>
  </div>

  <!-- OPEN POSITIONS PANEL -->
  <div id="panelOpen" class="tab-panel active">
    <div class="honest-section-intro" style="margin:0 0 1rem 0">
      <b>What is this tab?</b> Your <b>live action board</b>. Shows every signal that is still in-progress
      (not yet hit TP1 / TP2 / SL / expiry) and the cumulative P&amp;L equity curve from all closed signals.
      <br><br>
      Each card is one active position with its entry, stop loss, take-profit ladder, real-time MFE/MAE,
      and a manual close button (for when you exit before TP/SL fires &mdash; the bot will recompute the P&amp;L from your exit price).
      The equity curve appears below once the first signal closes; toggle 30d / 90d / 1y to zoom.
      <br><br>
      <b>Tip:</b> "Open" count in the page header should match this tab's card count. If they diverge,
      something fired but didn't render &mdash; check <b>Signal History</b> with the "Open" filter.
      <br>
      <button class="faq-learn-btn" onclick="openFAQ('open')">&#128214; Learn more &rarr;</button>
    </div>
    <!-- C1 (2026-05-22 tracker audit): Equity curve — cumulative P&L over closed signals.
         Hidden until first data point arrives. -->
    <div id="equityCurveWrap" class="equity-wrap" style="display:none">
      <div class="equity-hdr">
        <div class="equity-titles">
          <div class="sec-title">Equity Curve</div>
          <div class="equity-sub" id="equitySummary">—</div>
        </div>
        <div class="equity-range">
          <button class="ftab eq-range active" data-days="30" onclick="setEquityRange(30,this)">30d</button>
          <button class="ftab eq-range" data-days="90" onclick="setEquityRange(90,this)">90d</button>
          <button class="ftab eq-range" data-days="365" onclick="setEquityRange(365,this)">1y</button>
        </div>
      </div>
      <div class="equity-canvas-wrap"><canvas id="equityChart"></canvas></div>
    </div>
    <div id="openList"></div>
    <div class="pg-bar" id="openPgBar" style="display:none">
      <button class="pg-btn" id="openPrevBtn" onclick="openChangePage(-1)">&#8249; Prev</button>
      <span class="pg-info" id="openPgInfo"></span>
      <button class="pg-btn" id="openNextBtn" onclick="openChangePage(1)">Next &#8250;</button>
    </div>
  </div>

  <!-- AI INTELLIGENCE PANEL -->
  <div id="panelIntelligence" class="tab-panel">
    <div id="intelError" style="display:none" class="err-banner"></div>

    <div class="honest-section-intro" style="margin:0 0 1rem 0">
      <b>What is this tab?</b> The <b>AI Intelligence</b> view is the bot's <b>signal-quality scorecard</b>.
      It answers: <em>is the strategy picking good setups, and when does it perform best?</em>
      Cards here aggregate every signal the bot has fired (paper + live) and slice the results
      by confidence level, time of day, day of week, and token.
      Use it to spot which conditions to trust and which to avoid.
      <br><br>
      <b>Different from Adaptive tab:</b> Adaptive shows how the bot is <em>learning</em> (weights, gates, exposure).
      AI Intelligence shows <em>what the bot has produced</em> so far.
      <br>
      <button class="faq-learn-btn" onclick="openFAQ('intelligence')">&#128214; Learn more &rarr;</button>
    </div>

    <!-- BOT HEALTH SCORE -->
    <div class="bot-score-wrap" id="botScoreWrap">
      <div class="intel-sec-title">Bot Health Score</div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        Single composite number out of 100. <b>Win Rate</b> (40 pts), <b>Avg R:R</b> (20 pts),
        <b>Hi-Conf Win Rate</b> (20 pts), <b>Selectivity</b> (20 pts). 70+ is healthy.
      </div>
      <div class="bot-score-layout">
        <div class="bot-score-left">
          <div class="bot-score-num" id="botScoreNum">—</div>
          <div class="bot-score-denom">/ 100</div>
          <div class="bot-score-status" id="botScoreStatus">No Data</div>
        </div>
        <div class="bot-score-right">
          <div class="bot-bar-wrap"><div class="bot-bar-fill" id="botBarFill" style="width:0%"></div></div>
          <div class="bot-parts">
            <div class="bot-part">
              <div class="bot-part-label">Win Rate</div>
              <div class="bot-part-val"><span id="bpWr">0</span><span class="bot-part-max">/40</span></div>
            </div>
            <div class="bot-part">
              <div class="bot-part-label">Avg R:R</div>
              <div class="bot-part-val"><span id="bpRr">0</span><span class="bot-part-max">/20</span></div>
            </div>
            <div class="bot-part">
              <div class="bot-part-label">Hi-Conf WR</div>
              <div class="bot-part-val"><span id="bpHc">0</span><span class="bot-part-max">/20</span></div>
            </div>
            <div class="bot-part">
              <div class="bot-part-label">Selectivity</div>
              <div class="bot-part-val"><span id="bpSel">0</span><span class="bot-part-max">/20</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ADAPTIVE GATE STATUS CARDS -->
    <div class="intel-sec">
      <div class="intel-sec-title">Active Adaptive Gates</div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        Real-time view of the filters the bot is currently applying. If <b>Conf Floor</b> rises, the bot
        is being stricter (only firing high-conviction signals). <b>Tokens w/ Floor↑</b> = tokens whose
        recent WR dropped below 35% and now have a tighter floor applied. Empty = no filters tightened.
      </div>
      <div class="intel-cards">
        <div class="icard">
          <div class="icard-label">Conf Floor</div>
          <div class="icard-val a" id="iaConfFloor">—</div>
          <div class="icard-sub">min confidence to fire</div>
        </div>
        <div class="icard">
          <div class="icard-label">RANGING Floor</div>
          <div class="icard-val" id="iaRangingFloor">—</div>
          <div class="icard-sub" id="iaRangingFloorSub">threshold adj effect</div>
        </div>
        <div class="icard">
          <div class="icard-label">Tokens w/ Floor↑</div>
          <div class="icard-val" id="iaTokensGated">—</div>
          <div class="icard-sub" id="iaTokensGatedSub">WR&lt;35%: floor +1 &nbsp;·&nbsp; WR&lt;25%: floor +2</div>
        </div>
        <div class="icard">
          <div class="icard-label">OGD Active</div>
          <div class="icard-val" id="iaOgdActive">—</div>
          <div class="icard-sub" id="iaOgdActiveSub">tokens with blend applied</div>
        </div>
      </div>
    </div>

    <!-- CONFIDENCE ANALYTICS CARDS -->
    <div class="intel-sec">
      <div class="intel-sec-title">Confidence Analytics</div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        Does the bot's confidence score actually predict win rate? Healthy strategy: <b>Hi-Conf WR</b>
        (conf 7–10) should be noticeably higher than <b>Lo-Conf WR</b> (conf 1–4). If they're equal,
        the confidence number isn't doing its job and needs recalibration.
      </div>
      <div class="intel-cards">
        <div class="icard">
          <div class="icard-label">Avg Confidence</div>
          <div class="icard-val a" id="iaAvgConf">—</div>
          <div class="icard-sub">across all signals</div>
        </div>
        <div class="icard">
          <div class="icard-label">Hi-Conf Win Rate</div>
          <div class="icard-val g" id="iaHiWr">—</div>
          <div class="icard-sub" id="iaHiSub">conf 7-10</div>
        </div>
        <div class="icard">
          <div class="icard-label">Lo-Conf Win Rate</div>
          <div class="icard-val r" id="iaLoWr">—</div>
          <div class="icard-sub" id="iaLoSub">conf 1-4</div>
        </div>
        <div class="icard">
          <div class="icard-label">Best Conf Level</div>
          <div class="icard-val a" id="iaBestConf">—</div>
          <div class="icard-sub" id="iaBestSub">min 2 closed trades</div>
        </div>
      </div>
    </div>

    <!-- CONFIDENCE LEVEL BREAKDOWN (C4 stacked bar, 2026-05-22) -->
    <div class="intel-sec">
      <div class="intel-sec-title">
        Confidence Level Breakdown
        <span class="badge" style="font-size:.7rem;text-transform:none;letter-spacing:0;font-weight:400">
          Stacked: <span style="color:var(--green)">WIN</span> &nbsp;·&nbsp;
          <span style="color:#06b6d4">PARTIAL</span> &nbsp;·&nbsp;
          <span style="color:var(--red)">LOSS</span> &nbsp;·&nbsp;
          <span style="color:var(--muted)">EXPIRED</span>
        </span>
      </div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        How outcomes are distributed at each confidence level (1 to 10). Bars stack WIN / PARTIAL / LOSS / EXPIRED.
        Should slope toward more green as confidence rises. Flat slope = signals are equally good (or bad)
        regardless of the conf score &mdash; a red flag.
      </div>
      <div id="confBreakdown" class="conf-stack-wrap">
        <div class="empty">No closed signals yet</div>
      </div>
    </div>

    <!-- HOUR × DAY HEATMAP (C2, 2026-05-22) -->
    <div class="intel-sec">
      <div class="intel-sec-title">
        Win Rate by Hour × Day
        <span class="badge" id="hmBadge" style="font-size:.7rem;text-transform:none;letter-spacing:0;font-weight:400">
          UTC hours &nbsp;·&nbsp; min n=2 colored
        </span>
      </div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        Win rate by hour-of-day (UTC) and day-of-week. Reveals timing edges. ICT killzones
        (London 7&ndash;10 UTC, NY AM 12&ndash;15 UTC) typically show the strongest cells.
        Cells with fewer than 2 signals are uncolored to avoid false confidence.
      </div>
      <div id="hourDayHeatmap" class="hm-wrap">
        <div class="empty">No closed signals yet — heatmap populates after first signal closes</div>
      </div>
    </div>

    <!-- TOKEN PERFORMANCE (C5 chart + table, 2026-05-22) -->
    <div class="intel-sec">
      <div class="intel-sec-title">
        Token Performance
        <span class="badge" style="font-size:.7rem;text-transform:none;letter-spacing:0;font-weight:400">
          Bar = WR &nbsp;·&nbsp; whisker = Wilson 95% CI &nbsp;·&nbsp; sorted by WR
        </span>
      </div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        Per-token win rate with <b>Wilson 95% confidence interval</b> whiskers &mdash; honest about
        small-sample uncertainty (a 100% WR on 3 trades has a huge whisker). The <b>Adaptive</b>
        column shows the bot's current per-token weight blend (matches the Adaptive tab's matrix).
      </div>
      <div id="tokenWrChart" class="tok-wr-chart">
        <div class="empty">No closed signals yet</div>
      </div>
      <div class="tbl-wrap" style="margin-top:1rem">
        <table>
          <thead><tr>
            <th>Token</th><th>Signals</th><th>W / L</th>
            <th>Win Rate</th><th>Avg Conf</th><th>Avg R:R</th><th>Rating</th>
            <th>Adaptive</th>
          </tr></thead>
          <tbody id="tokPerfBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- SIGNAL HISTORY PANEL -->
  <div id="panelHistory" class="tab-panel">
    <div class="honest-section-intro" style="margin:0 0 1rem 0">
      <b>What is this tab?</b> The <b>full audit log</b> of every signal the bot has ever fired
      &mdash; closed and open, winners and losers. This is your forensic view.
      <br><br>
      Filter chips above the table let you slice by <b>outcome</b> (Wins / Losses / Partial / Open / Expired)
      and by <b>token</b>. Click any column header to sort. Click a row to expand the full signal context
      (FVG quality, MSS quality, sweep type, session, ICT structure, OGD weights at fire-time, template match, etc.).
      <br><br>
      <b>Tip:</b> Use this when investigating why a specific trade lost &mdash; the expanded row shows
      every feature value at signal-fire time, so you can spot patterns (e.g. "all my SELL losses were
      during NY_AM_KZ with weak SMT confirmation").
      <br>
      <button class="faq-learn-btn" onclick="openFAQ('history')">&#128214; Learn more &rarr;</button>
    </div>
    <div class="sec-hdr">
      <div class="sec-title">Signal History</div>
      <div class="filter-tabs">
        <button class="ftab active" onclick="setFilter('ALL',this)">All</button>
        <button class="ftab" onclick="setFilter('WIN',this)">Wins</button>
        <button class="ftab" onclick="setFilter('LOSS',this)">Losses</button>
        <button class="ftab" onclick="setFilter('PARTIAL',this)">Partial</button>
        <button class="ftab" onclick="setFilter('OPEN',this)">Open</button>
        <button class="ftab" onclick="setFilter('EXPIRED',this)">Expired</button>
      </div>
    </div>
    <div class="tok-filter" id="tokFilterBar">
      <button class="tok-pill active" onclick="setTokenFilter('ALL',this)">All Tokens</button>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th class="sortable" onclick="histSetSort('id')">ID <span class="sort-ico on" id="sh-id">&#9660;</span></th>
          <th class="sortable" onclick="histSetSort('token')">Token <span class="sort-ico" id="sh-token"></span></th>
          <th class="sortable" onclick="histSetSort('signal')">Signal <span class="sort-ico" id="sh-signal"></span></th>
          <th>Entry</th><th>SL</th><th>TP1</th><th>TP2</th><th>TP3</th>
          <th class="sortable" onclick="histSetSort('rr1')">R:R <span class="sort-ico" id="sh-rr1"></span></th>
          <th class="sortable" onclick="histSetSort('confidence')">Conf <span class="sort-ico" id="sh-confidence"></span></th>
          <th>MTF</th><th>RSI</th><th>4H</th><th>1H</th><th>5M</th>
          <th>Session</th><th>Sweep</th><th>EV</th>
          <th class="sortable" onclick="histSetSort('outcome')">Result <span class="sort-ico" id="sh-outcome"></span></th>
          <th class="sortable" onclick="histSetSort('profit_pct')">P&amp;L <span class="sort-ico" id="sh-profit_pct"></span></th>
          <th class="sortable" onclick="histSetSort('timestamp')">Time <span class="sort-ico" id="sh-timestamp"></span></th>
        </tr></thead>
        <tbody id="histBody"></tbody>
      </table>
    </div>
    <div class="pg-bar" id="histPgBar" style="display:none">
      <button class="pg-btn" id="histPrevBtn" onclick="histChangePage(-1)">&#8249; Prev</button>
      <span class="pg-info" id="histPgInfo"></span>
      <button class="pg-btn" id="histNextBtn" onclick="histChangePage(1)">Next &#8250;</button>
    </div>
  </div>
  <!-- BACKTEST PANEL -->
  <div id="panelBacktest" class="tab-panel">

    <div class="honest-section-intro" style="margin:0 0 1rem 0">
      <b>What is this tab?</b> The <b>strategy validation</b> view. Runs the exact same ICT signal logic
      that fires live signals, but over the last 365 days of historical data. Tells you whether
      the strategy <em>would have worked</em> across many market conditions.
      <br><br>
      Click <b>Run Backtest</b> to execute (VPN required &mdash; Binance is the data source; ~15&ndash;30 min on 5M candles).
      Results break down by token, regime, hour, day-of-week, sweep type, confluence template, and more.
      The <b>Walk-Forward</b> section shows out-of-sample (OOS) vs in-sample (IS) win rates &mdash; a small or negative
      overfit gap (IS &le; OOS) is a strong signal the edge is real.
      <br><br>
      <b>Tip:</b> Backtest WR is the <em>headline</em> number (easy to overfit). For LIVE-readiness,
      cross-check the <b>Honest Metrics</b> tab (CPCV + DSR) and <b>QuantStats</b> (Sharpe, Sortino, Calmar, drawdown).
      <br>
      <button class="faq-learn-btn" onclick="openFAQ('backtest')">&#128214; Learn more &rarr;</button>
    </div>

    <!-- BASELINE PIN BANNER -->
    <div id="baselinePinWrap" style="display:none;margin-bottom:1rem;border-radius:6px;padding:.85rem 1rem;font-size:.85rem;line-height:1.5">
      <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.4rem">
        <span id="baselinePinIcon" style="font-size:1.1rem">&#128204;</span>
        <span style="font-weight:600">Canonical Baseline:</span>
        <span id="baselinePinId" style="color:var(--accent);font-weight:600">&mdash;</span>
        <span id="baselinePinLabel" style="color:var(--muted);font-size:.78rem">&mdash;</span>
      </div>
      <div id="baselinePinMsg" style="color:var(--muted);font-size:.78rem">&mdash;</div>
      <div id="baselinePinExpected" style="color:var(--muted);font-size:.75rem;margin-top:.35rem">&mdash;</div>
    </div>

    <!-- Run Controls -->
    <div class="bt-controls">
      <button class="btn-run" id="btRunBtn" onclick="runBacktest()">&#9654; Run Backtest</button>
      <button class="btn" id="btTuneBtn" onclick="openTune()" style="display:none">&#9881; Tune Bot</button>
      <div class="bt-status-pill">
        <div class="bt-dot idle" id="btDot"></div>
        <span id="btStatusTxt">Idle</span>
      </div>
      <div class="bt-progress-wrap">
        <div class="bt-progress-bar"><div class="bt-progress-fill" id="btProgressFill" style="width:0%"></div></div>
        <div class="bt-progress-msg" id="btProgressMsg">Ready</div>
      </div>
      <small style="color:var(--muted)">&#9888; VPN required &nbsp;&#183;&nbsp; ~15-30 min (5M resolution) &nbsp;&#183;&nbsp; auto-saves to DB</small>
    </div>
    <div id="btErrorLog" style="display:none;margin-top:10px;background:#1a0a0a;border:1px solid #ff4444;border-radius:8px;padding:12px;">
      <div style="color:#ff6666;font-size:11px;font-weight:600;margin-bottom:6px;">ERROR LOG</div>
      <pre id="btErrorLogTxt" style="color:#ffaaaa;font-size:11px;white-space:pre-wrap;margin:0;max-height:200px;overflow-y:auto;"></pre>
    </div>

    <!-- Results (hidden until first run) -->
    <div id="btResults" style="display:none">

      <!-- Meta bar -->
      <div class="bt-meta-bar" id="btMetaBar"></div>

      <!-- Token Performance -->
      <div class="intel-sec">
        <div class="intel-sec-title">Performance by Token</div>
        <div class="tbl-wrap">
          <table>
            <thead><tr>
              <th>Token</th><th>Signals</th><th>Win</th><th>Partial</th>
              <th>Loss</th><th>Expired</th><th>Win Rate</th><th>Avg R:R</th><th>Avg Conf</th>
            </tr></thead>
            <tbody id="btTokenBody"></tbody>
          </table>
        </div>
      </div>

      <!-- By Regime -->
      <div class="intel-sec">
        <div class="intel-sec-title">Win Rate by Regime</div>
        <div class="conf-breakdown" id="btRegimeList"></div>
      </div>

      <!-- By Confidence -->
      <div class="intel-sec">
        <div class="intel-sec-title">Win Rate by Confidence Level</div>
        <div class="conf-breakdown" id="btConfList"></div>
      </div>

      <!-- BUY vs SELL -->
      <div class="intel-sec">
        <div class="intel-sec-title">BUY vs SELL</div>
        <div class="conf-breakdown" id="btDirList"></div>
      </div>

      <!-- ICT Kill Zone Session -->
      <div class="intel-sec">
        <div class="intel-sec-title">Win Rate by ICT Kill Zone Session</div>
        <div class="conf-breakdown" id="btSessionList"></div>
      </div>

      <!-- Rolling Walk-Forward (C6, 2026-05-22) -->
      <div class="intel-sec">
        <div class="intel-sec-title">
          Rolling Walk-Forward (90d train / 30d test)
          <span class="badge" id="wfBadge" style="font-size:.7rem;text-transform:none;letter-spacing:0;font-weight:400">
            <span style="color:var(--blue)">train WR</span> &nbsp;·&nbsp;
            <span style="color:var(--accent2)">test WR</span> &nbsp;·&nbsp;
            55% target line
          </span>
        </div>
        <div id="wfChartWrap" class="wf-wrap">
          <div class="empty">Run a backtest to populate rolling walk-forward</div>
        </div>
        <div id="wfSummary" class="wf-summary"></div>
      </div>

      <!-- Recommendations -->
      <div class="intel-sec">
        <div class="intel-sec-title">AI Recommendations</div>
        <div class="rec-list" id="btRecsList"></div>
      </div>

    </div>

    <!-- History -->
    <div class="intel-sec" id="btHistSec" style="display:none">
      <div class="intel-sec-title">Backtest History <small style="font-weight:400;font-size:.75rem;color:var(--muted)">(run monthly)</small></div>
      <div id="btHistList"></div>
      <div class="pg-bar" id="btHistPgBar" style="display:none">
        <button class="pg-btn" id="btHistPrevBtn" onclick="btHistChangePage(-1)">&#8249; Prev</button>
        <span class="pg-info" id="btHistPgInfo"></span>
        <button class="pg-btn" id="btHistNextBtn" onclick="btHistChangePage(1)">Next &#8250;</button>
      </div>
    </div>

    <!-- Tune Panel (hidden until opened) -->
    <div id="btTunePanel" class="tune-panel" style="display:none">
      <div class="tune-panel-title">&#9881; Auto-Tune Preview
        <small style="font-weight:400;font-size:.75rem;color:var(--muted);text-transform:none;letter-spacing:0">— review before applying</small>
      </div>
      <div id="tuneAdjList"></div>
      <div id="tuneGateInfo" style="font-size:.74rem;color:var(--muted);margin:.5rem 0 .3rem;padding:.3rem .6rem;background:rgba(148,163,184,.06);border-radius:4px;display:none"></div>
      <div class="tune-footer">
        <button class="btn-apply" id="tuneApplyBtn" onclick="confirmTune()">&#9654; Review &amp; Apply</button>
        <button class="btn-cancel" onclick="closeTune()">Cancel</button>
        <small style="color:var(--muted)">&#128190; Timestamped backup saved to backups/ &nbsp;&#183;&nbsp; restart bot after applying</small>
      </div>
    </div>

    <!-- Tune Confirmation Overlay -->
    <div id="tuneConfirmOverlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:999;display:none;align-items:center;justify-content:center">
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;max-width:520px;width:95%;padding:1.5rem 1.75rem;box-shadow:0 8px 32px rgba(0,0,0,.45)">
        <div style="font-size:1rem;font-weight:700;letter-spacing:.04em;color:var(--fg);margin-bottom:1rem">&#9888; Confirm Tune Bot Changes</div>
        <div id="tuneConfirmSummary" style="font-size:.82rem;color:var(--muted);margin-bottom:1rem;max-height:220px;overflow-y:auto"></div>
        <div id="tuneConfirmWfWarn" style="display:none;background:rgba(234,179,8,.12);border:1px solid rgba(234,179,8,.4);border-radius:5px;padding:.55rem .8rem;font-size:.78rem;color:#fbbf24;margin-bottom:.65rem"></div>
        <div id="tuneConfirmOgdNote" style="display:none;background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.3);border-radius:5px;padding:.5rem .75rem;font-size:.76rem;color:var(--muted);margin-bottom:1rem"></div>
        <label style="display:flex;align-items:flex-start;gap:.6rem;font-size:.8rem;color:var(--fg);cursor:pointer;margin-bottom:1.1rem">
          <input type="checkbox" id="tuneConfirmCheck" style="margin-top:.15rem;accent-color:var(--accent)">
          <span>I have reviewed the changes above and understand they will modify <code>strategy_engine.py</code>. The bot must be restarted to apply them.</span>
        </label>
        <div style="display:flex;gap:.75rem">
          <button class="btn-apply" id="tuneConfirmApplyBtn" onclick="executeTuneApply()" style="opacity:.45;cursor:not-allowed" disabled>&#10003; Confirm &amp; Apply</button>
          <button class="btn-cancel" onclick="closeConfirm()">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Tune History Section -->
    <div id="tuneHistorySec" class="intel-sec" style="display:none;margin-top:.5rem">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:.75rem;margin-bottom:.9rem">
        <div>
          <div class="intel-sec-title" style="margin-bottom:.3rem">Tune Bot History
            <small style="font-weight:400;font-size:.75rem;color:var(--muted)">— applied changes &amp; rollback</small>
          </div>
          <div id="tuneHistSummary" style="font-size:.74rem;color:var(--muted)"></div>
        </div>
        <input id="tuneHistSearch" type="text" placeholder="Filter by param..."
          style="background:var(--bg3);border:1px solid var(--border);border-radius:5px;
                 color:var(--text);padding:.32rem .75rem;font-size:.78rem;outline:none;
                 min-width:160px;transition:border-color .2s"
          onfocus="this.style.borderColor='var(--accent2)'"
          onblur="this.style.borderColor='var(--border)'"
          oninput="tuneHistPage=1;_renderTuneHistory()">
      </div>
      <div id="tuneHistoryBody"></div>
      <div class="pg-bar" id="tuneHistPgBar" style="display:none">
        <button class="pg-btn" id="tuneHistPrevBtn" onclick="tuneHistChangePage(-1)">&#8249; Prev</button>
        <span class="pg-info" id="tuneHistPgInfo"></span>
        <button class="pg-btn" id="tuneHistNextBtn" onclick="tuneHistChangePage(1)">Next &#8250;</button>
      </div>
    </div>

    <div id="btEmpty" class="empty" style="padding:3rem">No backtest data yet — click Run to start the first backtest</div>
  </div>

  <!-- ADAPTIVE LEARNING PANEL -->
  <div id="panelAdaptive" class="tab-panel">
  <div id="adaptError" style="display:none" class="err-banner"></div>

  <div class="honest-section-intro" style="margin:0 0 1rem 0">
    <b>What is this tab?</b> The <b>Adaptive</b> view is the bot's <b>learning &amp; risk-control</b> dashboard.
    It shows three things that auto-adjust as the bot trades:
    <br>&nbsp;&nbsp;1. <b>OGD weights</b> &mdash; per-token, per-feature importance (FVG quality, MSS quality, session, etc.)
    learned via online gradient descent after each closed signal.
    <br>&nbsp;&nbsp;2. <b>Adaptive gates</b> &mdash; signal-floor adjustments (e.g. a token that loses 3 in a row gets a stricter confidence floor).
    <br>&nbsp;&nbsp;3. <b>Portfolio exposure</b> &mdash; live position/risk gauges with hard caps.
    <br><br>
    <b>OFFLINE status is normal early on.</b> Adaptive learning activates only after 10 closed signals per token.
    Until then, the bot uses bootstrap defaults from backtesting.
    <br>
    <button class="faq-learn-btn" onclick="openFAQ('adaptive')">&#128214; Learn more &rarr;</button>
  </div>

  <!-- ROW 1: Bot State Summary Cards -->
  <div class="intel-sec">
    <div class="intel-sec-title">
      Bot Adaptive State
      <span class="pill dim" id="adaptBotStatus" style="margin-left:.5rem;font-size:.7rem;padding:.15rem .55rem;border-radius:10px;text-transform:uppercase;letter-spacing:.04em">OFFLINE</span>
    </div>
    <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
      Snapshot of the four live state variables the strategy uses to decide whether to fire a signal.
      <b>Threshold Adj.</b> shifts the base score gate (43); positive = stricter. <b>Confidence Floor</b>
      is the minimum signal confidence (1&ndash;10) required.
    </div>
    <div class="intel-cards">
      <div class="icard">
        <div class="icard-label">Threshold Adj.</div>
        <div class="icard-val" id="adaptThreshAdj">—</div>
        <div class="icard-sub" id="adaptThreshAdjSub">offset on base 43</div>
      </div>
      <div class="icard">
        <div class="icard-label">Confidence Floor</div>
        <div class="icard-val a" id="adaptConfFloor">—</div>
        <div class="icard-sub">min conf to fire signal</div>
      </div>
      <div class="icard">
        <div class="icard-label">Last Signal</div>
        <div class="icard-val" id="adaptLastSig" style="font-size:1rem">—</div>
        <div class="icard-sub">most recent fired</div>
      </div>
      <div class="icard">
        <div class="icard-label">SL Exposure</div>
        <div class="icard-val" id="adaptRiskCard">—</div>
        <div class="icard-sub" id="adaptRiskCardSub">% capital at risk</div>
      </div>
    </div>
  </div>

  <!-- ROW 2: Portfolio Exposure Gauges -->
  <div class="intel-sec">
    <div class="intel-sec-title">Portfolio Exposure</div>
    <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
      Hard caps that block new signals when filled. <b>Open Positions</b> = total slots in use.
      <b>BUY/SELL Slots</b> prevent directional over-exposure. <b>Capital at Risk</b> = sum of all open SL distances &times; position size.
      When a bar turns red, the bot will skip new signals in that direction until a position closes.
    </div>
    <div class="adap-gauge-grid">

      <div class="adap-gauge-card">
        <div class="adap-gauge-header">
          <span class="adap-gauge-label">Open Positions</span>
          <span class="adap-gauge-val" id="portOpenText">0 / 3</span>
        </div>
        <div class="port-bar"><div class="port-bar-fill ok" id="portOpenFill" style="width:0%"></div></div>
      </div>

      <div class="adap-gauge-card">
        <div class="adap-gauge-header">
          <span class="adap-gauge-label">BUY Slots</span>
          <span class="adap-gauge-val" id="portBuyText">0 / 2</span>
        </div>
        <div class="port-bar"><div class="port-bar-fill ok" id="portBuyFill" style="width:0%"></div></div>
      </div>

      <div class="adap-gauge-card">
        <div class="adap-gauge-header">
          <span class="adap-gauge-label">SELL Slots</span>
          <span class="adap-gauge-val" id="portSellText">0 / 2</span>
        </div>
        <div class="port-bar"><div class="port-bar-fill ok" id="portSellFill" style="width:0%"></div></div>
      </div>

      <div class="adap-gauge-card">
        <div class="adap-gauge-header">
          <span class="adap-gauge-label">Capital at Risk</span>
          <span class="adap-gauge-val" id="portRiskText">0.00% / 15%</span>
        </div>
        <div class="port-bar"><div class="port-bar-fill ok" id="portRiskFill" style="width:0%"></div></div>
      </div>

    </div>
    <div id="portSlotMsg" style="font-size:.8rem;font-weight:600;margin-top:.75rem"></div>
  </div>

  <!-- ROW 3: Per-Token OGD Weight Matrix -->
  <div class="intel-sec">
    <div class="intel-sec-title">
      Per-Token OGD Weight Matrix
      <span class="badge" style="font-size:.7rem;text-transform:none;letter-spacing:0;font-weight:400">
        Vertical mark = default 16.7% &nbsp;·&nbsp; Green = above default &nbsp;·&nbsp; Updates on signal close
      </span>
    </div>
    <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
      For each token, six features (FVG quality, MSS quality, session, confidence, trend strength, DR location)
      have a weight that sums to 100%. The dotted line marks the default 16.7% (equal weight).
      Above default = the feature is currently a stronger predictor for that token; below = weaker.
      Weights update only when a signal closes &mdash; expect long periods of stability.
      A token pinned to all-floor weights signals <em>degeneration</em> (flagged in red).
    </div>
    <div id="adaptWeightsBody">
      <div class="empty">No OGD data yet — weights populate after first signal closes</div>
    </div>
  </div>

  <!-- ROW 4: Concept Drift Baselines -->
  <div class="intel-sec">
    <div class="intel-sec-title">
      Concept Drift Baselines
      <span class="badge" style="font-size:.7rem;text-transform:none;letter-spacing:0;font-weight:400">
        Active after 20+ bars &nbsp;·&nbsp; ADX threshold = 85% rolling mean &nbsp;·&nbsp; RSI extremes widen in high ATR
      </span>
    </div>
    <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
      Per-token rolling baselines for ADX, ATR, and RSI extremes. Once a token has 20+ bars of live data,
      its <b>Learning</b> badge flips to <b>Active</b> and the bot starts using these dynamic thresholds
      instead of static defaults &mdash; so a low-vol coin like USDC isn't gated the same way as a high-vol coin like SOL.
    </div>
    <div id="adaptDriftBody">
      <div class="empty">No drift baselines yet — accumulates during live trading cycles</div>
    </div>
    <div id="adaptCacheAge" class="adap-stale" style="display:none"></div>
  </div>

  <!-- ROW 5: R10 Per-Token Forensic Panel (master audit 2026-05-26) -->
  <div class="intel-sec">
    <div class="intel-sec-title">
      Per-Token Adaptive Forensic Panel
      <span class="badge" style="font-size:.7rem;text-transform:none;letter-spacing:0;font-weight:400">
        Last update detail · health flags · regime label · reward / gradient_l1
      </span>
    </div>
    <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
      For each token: current weight top-feature, n_updates, the latest OGD update's
      <b>reward</b> + <b>gradient_l1</b> + <b>regime</b> + <b>profit_pct</b>
      (R4 + R7 forensic columns from <code>weight_history</code>), plus health flags
      (<span class="badge warn">FLOOR-PINNED</span> <span class="badge crit">DEGENERATE</span>
      <span class="badge crit">FROZEN</span> <span class="badge warn">STALE</span>).
      Global DSR-gate verdict + freeze state shown in the header strip.
      Updates after each closed signal.
    </div>
    <div id="adaptForensicHeader" style="margin-bottom:.6rem;font-size:.85rem;color:var(--muted)"></div>
    <div id="adaptForensicBody">
      <div class="empty">No forensic data yet — populates after first signal closes</div>
    </div>
  </div>

  </div><!-- /panelAdaptive -->

  <!-- HONEST METRICS PANEL (Sprint 3 + FIX 1 Part 2 surfaces) -->
  <div id="panelHonest" class="tab-panel">
    <div class="honest-section-intro" style="margin:0 0 1rem 0">
      <b>What is this tab?</b> The <b>"is it really working?" view</b>. Most trading dashboards show
      cherry-picked numbers. This tab shows the <em>honest</em> ones &mdash; the metrics that survive proper
      statistical correction for the fact that we've tested many parameter configurations.
      <br><br>
      Key concepts:
      <br>&nbsp;&nbsp;&bull; <b>CPCV</b> (Combinatorial Purged K-Fold) &mdash; splits the data into many train/test combinations
      so a lucky single split can't fool us. Reports mean &amp; spread of OOS win rate.
      <br>&nbsp;&nbsp;&bull; <b>DSR</b> (Deflated Sharpe Ratio) &mdash; corrects the Sharpe ratio for the number of
      configs tested. Without DSR, testing 100 configs will produce a 99th-percentile "winner" by pure luck.
      <br>&nbsp;&nbsp;&bull; <b>Cross-config std</b> &mdash; how much performance varies across all the variants we've tried.
      Tight clustering = robust edge. Wide spread = brittle / overfit.
      <br><br>
      <b>LIVE gate:</b> CPCV mean WR &ge; 60% AND DSR &ge; 95% AND &ge;30 closed paper signals.
      <br>
      <button class="faq-learn-btn" onclick="openFAQ('honest')">&#128214; Learn more &rarr;</button>
    </div>
    <div id="honestLoading" style="color:var(--muted);text-align:center;padding:40px">Loading honest metrics...</div>
    <div id="honestContent" style="display:none">

      <!-- Top status row -->
      <div class="honest-status-row">
        <div class="honest-card honest-status">
          <div class="honest-label">Bot Version</div>
          <div class="honest-value" id="hmBotVersion">—</div>
          <div class="honest-sub" id="hmExecutionMode">—</div>
          <div class="honest-desc">Current strategy variant. PAPER mode = signals only, no auto-trades.</div>
        </div>
        <div class="honest-card honest-status">
          <div class="honest-label">Latest Audit Score</div>
          <div class="honest-value" id="hmAuditScore">—</div>
          <div class="honest-sub" id="hmAuditDate">—</div>
          <div class="honest-desc">Out of 10 — combined verdict of 11 specialist code audits (ICT logic, risk, statistics, etc.). ≥9 is enterprise-grade.</div>
        </div>
        <div class="honest-card honest-status">
          <div class="honest-label">OGD Health</div>
          <div class="honest-value" id="hmOgdAlert">—</div>
          <div class="honest-sub" id="hmOgdDetail">—</div>
          <div class="honest-desc">Online Gradient Descent — the bot's adaptive weight learning. OK = healthy, WARN = cosmetic issue, CRIT = collapsed (block LIVE).</div>
        </div>
        <div class="honest-card honest-status">
          <div class="honest-label">Macro Filter</div>
          <div class="honest-value" id="hmMacroValue">—</div>
          <div class="honest-sub" id="hmMacroDetail">—</div>
          <div class="honest-desc">Skips trades during news shocks (FOMC, CPI, NFP). OFF = always trade; ADVISORY = log near events; BLOCKING = suppress signals.</div>
        </div>
      </div>

      <!-- Paper trading progress -->
      <div class="honest-section">
        <div class="honest-section-title">&#9201; Paper Trading Progress</div>
        <div class="honest-section-intro">Each closed paper signal is one real-world test of the strategy's edge. We need at least 30 closed signals before we can honestly decide if the strategy works with real money. This bar fills as signals close.</div>
        <div class="honest-progress-wrap">
          <div class="honest-progress-header">
            <span id="hmPaperLabel">0 / 30 closed signals</span>
            <span id="hmPaperEta" class="honest-sub">ETA: — months</span>
          </div>
          <div class="honest-progress-bar"><div class="honest-progress-fill" id="hmPaperFill" style="width:0%"></div></div>
          <div class="honest-sub" style="margin-top:6px">LIVE switch requires N&ge;30 closed paper signals. Tracking real OOS validation.</div>
          <div id="hmPaperRateDetail" class="honest-sub" style="margin-top:4px;font-size:.78rem;color:var(--muted)">
            Rate basis: &mdash;
          </div>
        </div>
      </div>

      <!-- Latest backtest honest metrics -->
      <div class="honest-section">
        <div class="honest-section-title">&#129504; Latest Backtest &mdash; Honest Metrics</div>
        <div class="honest-section-intro">How the strategy performed on historical data. The <b>Headline WR</b> is the single-split number (easy to overfit). The <b>CPCV</b> and <b>DSR</b> numbers are the honest ones &mdash; they correct for the temptation to test 100 configs and pick the lucky winner. Gold-bordered cells are the metrics that decide LIVE-readiness.</div>
        <div class="honest-grid">
          <div class="honest-cell">
            <div class="honest-cell-label">Latest Run</div>
            <div class="honest-cell-value" id="hmRunId">—</div>
            <div class="honest-cell-sub" id="hmRunDate">—</div>
            <div class="honest-cell-desc">The most recent backtest # in the DB. Each click of "Run Backtest" creates a new one.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">Signals (n)</div>
            <div class="honest-cell-value" id="hmRunN">—</div>
            <div class="honest-cell-sub">Trades found in 365 days</div>
            <div class="honest-cell-desc">How many trade setups the strategy identified across all 10 tokens in the last year of data. Higher = more opportunities.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">Headline WR</div>
            <div class="honest-cell-value" id="hmRunWr">—</div>
            <div class="honest-cell-sub">Single split &mdash; can be inflated</div>
            <div class="honest-cell-desc">Win rate from one walk-forward split. Marketing number &mdash; can look great by luck. Use CPCV mean instead for honest read.</div>
          </div>
          <div class="honest-cell honest-highlight">
            <div class="honest-cell-label">CPCV mean WR &#11088;</div>
            <div class="honest-cell-value" id="hmCpcvWr">—</div>
            <div class="honest-cell-sub">Honest average (target &ge;58%)</div>
            <div class="honest-cell-desc">Average win rate across 10 different time slices of the data. Resists overfitting. This is the WR you should actually trust.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">CPCV q05</div>
            <div class="honest-cell-value" id="hmCpcvQ05">—</div>
            <div class="honest-cell-sub">Worst slice floor</div>
            <div class="honest-cell-desc">The 5th-percentile slice &mdash; almost the worst result among the 10 slices. If this drops below 50%, the strategy is fragile in some market conditions.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">CPCV std</div>
            <div class="honest-cell-value" id="hmCpcvStd">—</div>
            <div class="honest-cell-sub">Lower = more consistent</div>
            <div class="honest-cell-desc">How much win rate varies across the 10 slices. Lower std means the edge is stable; high std means it depends on which window you test.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">Overall Sharpe</div>
            <div class="honest-cell-value" id="hmSharpe">—</div>
            <div class="honest-cell-sub">Return / risk ratio</div>
            <div class="honest-cell-desc">How much return you get per unit of risk. >1 is good, >2 is excellent. Doesn't yet correct for selection bias &mdash; PSR/DSR do that.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">PSR (OOS)</div>
            <div class="honest-cell-value" id="hmPsr">—</div>
            <div class="honest-cell-sub">Real-edge probability</div>
            <div class="honest-cell-desc">Probabilistic Sharpe Ratio &mdash; statistical confidence that the strategy has a real edge (vs being lucky). >95% = high confidence.</div>
          </div>
          <div class="honest-cell honest-highlight">
            <div class="honest-cell-label">DSR (multi-test) &#11088;</div>
            <div class="honest-cell-value" id="hmDsr">—</div>
            <div class="honest-cell-sub" id="hmDsrNote">Honest (target &ge;95%)</div>
            <div class="honest-cell-desc">Deflated Sharpe Ratio &mdash; corrects for the fact that we've tested many configs. The gold standard for LIVE-readiness. ≥95% required before switching to LIVE.</div>
          </div>
        </div>
        <div class="honest-verdict-row">
          <span class="honest-verdict-label">Phase A Verdict:</span>
          <span class="honest-verdict-value" id="hmVerdict">—</span>
        </div>
        <div class="honest-verdict-legend">
          <span><span class="honest-legend-dot pass"></span> <b>PASS</b> = CPCV &ge;58% AND DSR &ge;95%. LIVE-ready.</span>
          <span><span class="honest-legend-dot marginal"></span> <b>MARGINAL</b> = CPCV &ge;55% AND DSR &ge;95%. Acceptable, but not ideal.</span>
          <span><span class="honest-legend-dot fail"></span> <b>FAIL</b> = below either threshold. NOT ready for LIVE.</span>
        </div>
      </div>

      <!-- Cross-config sr_trial_std -->
      <div class="honest-section">
        <div class="honest-section-title">&#128202; Cross-Config Trial Std (FIX 1 Part 2)</div>
        <div class="honest-section-intro">When we test many parameter combinations, the "best" result can look great just by luck. This section measures how much the strategy's performance varies <b>across all the different configs we've tried</b>. Used to compute the honest DSR &mdash; tight clustering means the edge is robust, not lucky.</div>
        <div class="honest-grid">
          <div class="honest-cell">
            <div class="honest-cell-label">Value (std)</div>
            <div class="honest-cell-value" id="hmStdValue">—</div>
            <div class="honest-cell-sub">Spread of Sharpes</div>
            <div class="honest-cell-desc">Standard deviation of OOS Sharpe across all configs tested. Lower = configs cluster tightly = edge is robust across the parameter space.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">N distinct configs</div>
            <div class="honest-cell-value" id="hmStdN">—</div>
            <div class="honest-cell-sub">Tested across history</div>
            <div class="honest-cell-desc">How many different parameter combinations we've actually backtested. More = wider exploration of the strategy space.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">Mean OOS Sharpe</div>
            <div class="honest-cell-value" id="hmStdMean">—</div>
            <div class="honest-cell-sub">Avg across configs</div>
            <div class="honest-cell-desc">Average out-of-sample Sharpe across all configs. Tells you the "typical" performance, not just the best one we cherry-picked.</div>
          </div>
          <div class="honest-cell">
            <div class="honest-cell-label">Computed at</div>
            <div class="honest-cell-value" id="hmStdComputed" style="font-size:.9rem">—</div>
            <div class="honest-cell-sub">Last snapshot timestamp</div>
            <div class="honest-cell-desc">When this number was last calculated. Re-run <code>scripts/compute_cross_config_sr_std.py</code> after every optimizer cycle to keep it fresh.</div>
          </div>
        </div>
        <div class="honest-sub" style="margin-top:8px" id="hmStdNote">—</div>
      </div>

    </div><!-- /honestContent -->
    <div id="honestError" style="display:none;color:#ff6666;padding:20px;text-align:center"></div>
  </div><!-- /panelHonest -->

  <!-- QUANTSTATS PANEL -->
  <div id="panelQuantstats" class="tab-panel">
    <div class="honest-section-intro" style="margin:0 0 1rem 0">
      <b>What is this tab?</b> The <b>professional risk tearsheet</b>. While the AI Intelligence tab
      shows operational stats (signal quality, timing), QuantStats shows the <b>portfolio-level risk metrics</b>
      that institutional traders use to evaluate a strategy.
      <br><br>
      Computed by <a href="https://github.com/ranaroussi/quantstats" target="_blank" style="color:var(--accent)">QuantStats</a>
      (Apache 2.0) &mdash; the same library used by quant funds. Includes <b>Sharpe / Sortino / Calmar / Omega</b> ratios,
      <b>VaR / CVaR</b>, <b>drawdown</b> details, <b>Kelly criterion</b>, distribution stats (skew, kurtosis, tail ratio),
      monthly heatmap, rolling Sharpe, and the full HTML report embedded below.
      <br><br>
      <b>Annualization is auto-scaled</b> to your actual trade frequency, not the default 252-day assumption &mdash; so the
      Sharpe number is honest for sparse ICT signals.
      <br><br>
      <b>Tip:</b> Toggle source between <b>Backtest</b> (historical validation) and <b>Paper</b> (live signals as they accumulate).
    </div>
    <div class="honest-section">

      <div style="display:flex;gap:12px;align-items:center;margin:14px 0 18px 0;flex-wrap:wrap">
        <label style="color:var(--muted);font-size:13px">Data source:</label>
        <select id="qsSource" onchange="loadQuantStats()" style="background:#1a1f2e;color:#fff;border:1px solid #2a3a4a;padding:6px 10px;border-radius:4px;font-size:13px">
          <option value="backtest">Backtest (latest run)</option>
          <option value="paper">Paper Trading (live signals)</option>
        </select>
        <span id="qsMeta" style="color:var(--muted);font-size:12px"></span>
        <a id="qsTearLink" href="/api/quantstats/tearsheet?source=backtest" target="_blank"
           style="margin-left:auto;background:#2a3a4a;color:#fff;padding:8px 14px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:500">
          Open in new tab &#8599;
        </a>
      </div>

      <div id="qsLoading" style="color:var(--muted);text-align:center;padding:30px">Loading...</div>
      <div id="qsEmpty" style="display:none;color:var(--muted);text-align:center;padding:30px">
        No closed signals yet for this source.
      </div>

      <div id="qsContent" style="display:none">
        <div class="honest-grid">
          <div class="honest-cell"><div class="honest-cell-label">Sharpe Ratio</div><div class="honest-cell-value" id="qsSharpe">—</div>
            <div class="honest-cell-desc">Risk-adjusted return per unit of total volatility. &gt;1 good, &gt;2 strong, &gt;3 elite.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Sortino Ratio</div><div class="honest-cell-value" id="qsSortino">—</div>
            <div class="honest-cell-desc">Like Sharpe but only penalizes <em>downside</em> volatility. Better for asymmetric strategies.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Calmar Ratio</div><div class="honest-cell-value" id="qsCalmar">—</div>
            <div class="honest-cell-desc">Annualized return ÷ max drawdown. Compares reward to worst-case pain. &gt;3 strong.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">CAGR</div><div class="honest-cell-value" id="qsCagr">—</div>
            <div class="honest-cell-desc">Compound annual growth rate (scaled to actual trade frequency).</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Max Drawdown</div><div class="honest-cell-value" id="qsMaxDd">—</div>
            <div class="honest-cell-desc">Worst peak-to-trough capital loss in the sample.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Profit Factor</div><div class="honest-cell-value" id="qsPf">—</div>
            <div class="honest-cell-desc">Σ wins ÷ |Σ losses|. &gt;1.5 acceptable, &gt;2 strong, &gt;3 rare.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Kelly %</div><div class="honest-cell-value" id="qsKelly">—</div>
            <div class="honest-cell-desc">Optimal fraction of capital to risk per trade. Half-Kelly is the conservative rule.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Win Rate</div><div class="honest-cell-value" id="qsWr">—</div>
            <div class="honest-cell-desc">% of trade-days that were net positive.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Avg Win / Loss</div><div class="honest-cell-value" id="qsAvgWl">—</div>
            <div class="honest-cell-desc">Mean P&amp;L on winning trade-days vs losing trade-days.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Best / Worst Day</div><div class="honest-cell-value" id="qsBw">—</div>
            <div class="honest-cell-desc">Extreme single-day outcomes.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Volatility (ann)</div><div class="honest-cell-value" id="qsVol">—</div>
            <div class="honest-cell-desc">Annualized standard deviation of trade-day returns.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Value-at-Risk (95%)</div><div class="honest-cell-value" id="qsVar">—</div>
            <div class="honest-cell-desc">5th-percentile single-day loss. CVaR is the average loss beyond the VaR threshold.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Omega Ratio</div><div class="honest-cell-value" id="qsOmega">—</div>
            <div class="honest-cell-desc">Probability-weighted ratio of gains to losses. Captures full distribution shape.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Tail Ratio</div><div class="honest-cell-value" id="qsTail">—</div>
            <div class="honest-cell-desc">95th-pct gain ÷ |5th-pct loss|. &gt;1 means upside tails dominate downside.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Skew / Kurtosis</div><div class="honest-cell-value" id="qsSk">—</div>
            <div class="honest-cell-desc">Positive skew = larger gains than losses. High kurtosis = fat tails.</div></div>
          <div class="honest-cell"><div class="honest-cell-label">Cumulative Return</div><div class="honest-cell-value" id="qsCum">—</div>
            <div class="honest-cell-desc">Total compounded return over the full sample period.</div></div>
        </div>

        <div class="honest-section-title" style="margin-top:28px">&#128196; Full Interactive Tearsheet</div>
        <div class="honest-section-intro" style="margin-bottom:10px">
          QuantStats HTML report rendered inline below — equity curve, monthly heatmap, rolling Sharpe, drawdown periods, EOY returns, distribution plots, and metrics table.
        </div>
        <div style="position:relative;width:100%;background:#0c1118;border:1px solid #2a3a4a;border-radius:6px;overflow:hidden">
          <iframe id="qsTearFrame" src="about:blank" loading="lazy"
                  style="width:100%;height:1400px;border:0;background:#fff;display:block">
          </iframe>
        </div>
      </div>
      <div id="qsError" style="display:none;color:#ff6666;padding:20px;text-align:center"></div>
    </div>
  </div><!-- /panelQuantstats -->

  <!-- AUTO-EXPLORER PANEL -->
  <div id="panelExplorer" class="tab-panel">
    <div class="honest-section-intro" style="margin:0 0 1rem 0">
      <b>What is this tab?</b> The <b>autonomous R&amp;D</b> view. Shows what the
      <a href="https://github.com/optuna/optuna" target="_blank" style="color:var(--accent)">Optuna</a>-driven
      explorer has discovered while running in the background. Every trial uses the same honest CPCV+DSR validation
      gates as manual backtests; auto-promoted winners (Pareto-improving + reproducible) become the new baseline pin
      automatically. <strong>Never auto-flips LIVE</strong> &mdash; that decision stays operator-deliberate.
      <br><br>
      Start a session manually with <code style="background:var(--bg);padding:1px 5px;border-radius:3px">python scripts/autonomous_explorer.py --trials 30</code>.
      Each trial = ~11 min. Status updates here every 15s while running.
      <br>
      <button class="faq-learn-btn" onclick="openFAQ('explorer')">&#128214; Learn more &rarr;</button>
    </div>

    <!-- Session status banner -->
    <div id="explSessionWrap" style="display:none;margin-bottom:1rem;border-radius:6px;padding:.85rem 1rem;font-size:.85rem;line-height:1.5">
      <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.4rem;flex-wrap:wrap">
        <span id="explStateIcon" style="font-size:1.1rem">&#129302;</span>
        <span style="font-weight:600">Explorer:</span>
        <span id="explStateText" style="font-weight:600">&mdash;</span>
        <span id="explStudyName" style="color:var(--muted);font-size:.78rem">&mdash;</span>
        <span id="explLastUpdate" style="color:var(--muted);font-size:.74rem;margin-left:auto">&mdash;</span>
      </div>
      <div id="explSessionDetail" style="color:var(--muted);font-size:.78rem">&mdash;</div>
    </div>
    <div id="explNoSession" style="display:none;color:var(--muted);text-align:center;padding:30px">
      No explorer session yet. Start one with <code style="background:var(--bg);padding:1px 5px;border-radius:3px">python scripts/autonomous_explorer.py --trials 30</code>
    </div>

    <!-- Summary cards row -->
    <div class="honest-status-row" style="margin-top:1rem">
      <div class="honest-card honest-status">
        <div class="honest-label">Trials Total</div>
        <div class="honest-value" id="explTotalTrials">&mdash;</div>
        <div class="honest-sub" id="explStudiesCount">&mdash;</div>
        <div class="honest-desc">All trials ever run across all explorer sessions.</div>
      </div>
      <div class="honest-card honest-status">
        <div class="honest-label">PASS / FAIL / ERROR</div>
        <div class="honest-value" id="explVerdictRatio" style="font-size:1.2rem">&mdash;</div>
        <div class="honest-sub" id="explPassPct">&mdash;</div>
        <div class="honest-desc">PASS = cleared all 4 honest gates (n&ge;30, CPCV mean&ge;60%, q05&ge;50%, DSR&ge;95%).</div>
      </div>
      <div class="honest-card honest-status">
        <div class="honest-label">Auto-Promotions Today</div>
        <div class="honest-value" id="explPromosToday">&mdash;</div>
        <div class="honest-sub" id="explSoakHours">&mdash;</div>
        <div class="honest-desc">Hard cap: 2/day. 24h soak required between promotions to observe each one's effect.</div>
      </div>
      <div class="honest-card honest-status">
        <div class="honest-label">Pareto Archive</div>
        <div class="honest-value" id="explParetoSize">&mdash;</div>
        <div class="honest-sub">non-dominated configs</div>
        <div class="honest-desc">Top configs that aren't beaten on every metric by any other tested config.</div>
      </div>
    </div>

    <!-- Pareto archive table -->
    <div class="honest-section">
      <div class="honest-section-title">&#127942; Pareto Archive (top non-dominated configs)</div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        Each row is a config no other tested config dominates on all four dimensions (CPCV mean &uarr;, CPCV std &darr;, Sharpe &uarr;, n &uarr;).
        The baseline pin is typically in here. Candidates that don't quite meet promotion criteria still appear so the operator can review.
      </div>
      <div class="tbl-wrap">
        <table style="width:100%;border-collapse:collapse;font-size:.78rem">
          <thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border)">
            <th style="padding:.35rem .5rem">Trial</th>
            <th style="padding:.35rem .5rem">Study</th>
            <th style="padding:.35rem .5rem">n</th>
            <th style="padding:.35rem .5rem">WR</th>
            <th style="padding:.35rem .5rem">CPCV mean</th>
            <th style="padding:.35rem .5rem">CPCV std</th>
            <th style="padding:.35rem .5rem">Sharpe</th>
            <th style="padding:.35rem .5rem">DSR</th>
            <th style="padding:.35rem .5rem">Params</th>
          </tr></thead>
          <tbody id="explParetoBody">
            <tr><td colspan="9" class="empty" style="padding:1rem">No Pareto candidates yet</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Auto-promotion history -->
    <div class="honest-section">
      <div class="honest-section-title">&#9889; Recent Auto-Promotions</div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        Every entry here passed the strict 8-criteria gate AND a reproducibility re-run with matching config_hash.
        Rollback any auto-promotion via <code style="background:var(--bg);padding:1px 5px;border-radius:3px">python scripts/promote_baseline.py --rollback-to-run &lt;N&gt;</code>.
      </div>
      <div class="tbl-wrap">
        <table style="width:100%;border-collapse:collapse;font-size:.78rem">
          <thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border)">
            <th style="padding:.35rem .5rem">Promoted</th>
            <th style="padding:.35rem .5rem">Trial</th>
            <th style="padding:.35rem .5rem">Run</th>
            <th style="padding:.35rem .5rem">CPCV (run1 / repro)</th>
            <th style="padding:.35rem .5rem">DSR</th>
            <th style="padding:.35rem .5rem">Sharpe</th>
          </tr></thead>
          <tbody id="explPromoBody">
            <tr><td colspan="6" class="empty" style="padding:1rem">No auto-promotions yet</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Recent trials -->
    <div class="honest-section">
      <div class="honest-section-title">&#128202; Recent Trials (last 20)</div>
      <div class="honest-section-intro" style="margin:.4rem 0 .8rem 0;border-left-color:#06b6d4">
        Latest trials with verdicts and reject reasons. <span style="color:var(--green)">PASS</span> trials cleared
        every honest gate. <span style="color:var(--red)">FAIL</span> shows the first failing gate.
        <span style="color:var(--muted)">ERROR</span> = timeout / crash / DB issue.
      </div>
      <div class="tbl-wrap">
        <table style="width:100%;border-collapse:collapse;font-size:.78rem">
          <thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border)">
            <th style="padding:.35rem .5rem">#</th>
            <th style="padding:.35rem .5rem">Study</th>
            <th style="padding:.35rem .5rem">Verdict</th>
            <th style="padding:.35rem .5rem">n</th>
            <th style="padding:.35rem .5rem">WR</th>
            <th style="padding:.35rem .5rem">CPCV</th>
            <th style="padding:.35rem .5rem">DSR</th>
            <th style="padding:.35rem .5rem">Wall</th>
            <th style="padding:.35rem .5rem">Reason / Status</th>
          </tr></thead>
          <tbody id="explTrialsBody">
            <tr><td colspan="9" class="empty" style="padding:1rem">No trials yet</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div><!-- /panelExplorer -->

</main>

<!-- FAQ MODAL — opened from every tab's "Learn more" button -->
<div id="faqModal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closeFAQ()">
  <div class="modal-box faq">
    <button class="modal-x" onclick="closeFAQ()">&#10005;</button>
    <div class="modal-h" id="faqTitle">FAQ</div>
    <div id="faqBody"></div>
  </div>
</div>

<!-- FAQ CONTENT TEMPLATES (hidden, copied into faqBody on demand) -->
<div id="faqTemplates" style="display:none">

  <div id="faq_open">
    <h3>What is this panel?</h3>
    <p>The <strong>Open Positions</strong> tab is your <strong>live action board</strong>. It shows every signal the bot has fired that is still in-progress &mdash; meaning it has not yet hit TP1, TP2, TP3, the stop loss, or expired. It also displays the cumulative P&amp;L equity curve from all closed signals over the selected window.</p>
    <h3>Why it exists</h3>
    <p>You need a single screen to answer: <em>"What real money am I exposed to right now?"</em> Every open card represents a trade the bot wants you to execute manually. Closing one early or letting it ride affects your real outcomes &mdash; this tab is where you make those decisions.</p>
    <h3>Section-by-section</h3>
    <h4>Open signal cards</h4>
    <p>Each card represents one in-flight signal with: token, direction (BUY/SELL), entry price, stop loss, take-profit ladder (TP1 / TP2 / TP3), R:R ratios, confidence (1&ndash;10), live MFE/MAE, and a manual close button.</p>
    <h4>Equity curve</h4>
    <p>Hidden until the first signal closes. Plots cumulative P&amp;L over closed trades. Annotated with peak equity and max drawdown. Range selector: 30d / 90d / 1y.</p>
    <h3>When to check it</h3>
    <ul>
      <li>Every time a Telegram alert fires &mdash; verify the signal is in the table</li>
      <li>Before going to bed &mdash; review what's open overnight</li>
      <li>After a market move &mdash; see if any positions are near TP/SL</li>
      <li>When considering a manual close &mdash; check the MFE/MAE to see if the trade already moved against you</li>
    </ul>
    <h3>What to do when you see X</h3>
    <table>
      <thead><tr><th>Observation</th><th>Suggested action</th></tr></thead>
      <tbody>
        <tr><td>Position near TP1 with low momentum</td><td>Consider manual close at current price to lock in partial</td></tr>
        <tr><td>Position near SL with adverse news</td><td>Consider manual close to limit loss below the bot's structural SL</td></tr>
        <tr><td>Multiple opens in same direction</td><td>Verify portfolio risk in Adaptive tab &mdash; LIVE mode caps at 2 same-direction</td></tr>
        <tr><td>Position count doesn't match page header</td><td>Check Signal History with "Open" filter &mdash; something fired but didn't render</td></tr>
      </tbody>
    </table>
    <h3>Common scenarios</h3>
    <div class="faq-tip"><strong>Scenario A:</strong> Telegram pings at 3am with a BUY on AVAX. You wake at 7am, check Open Positions, see AVAX up 2% (already past TP1). You manually close at +2% via the modal &mdash; the bot logs this as a manual exit and computes P&amp;L from your exit price, not the bot's TP target.</div>
    <div class="faq-warn"><strong>Scenario B:</strong> You see 4 open positions but only have time to execute 2. Adaptive tab shows MAX_OPEN_POSITIONS limit (20 in PAPER, 4 in LIVE) so the bot would have allowed all 4. Pick the 2 with highest confidence + best R:R from the cards.</div>
    <h3>Glossary</h3>
    <ul>
      <li><strong>MFE (Maximum Favorable Excursion):</strong> the peak profit the position reached before reversing &mdash; how good it briefly looked</li>
      <li><strong>MAE (Maximum Adverse Excursion):</strong> the worst loss the position touched before recovering &mdash; how bad it briefly looked</li>
      <li><strong>R:R (Risk:Reward):</strong> ratio of profit target distance to stop loss distance, e.g. 1:2 = risk 1% to make 2%</li>
      <li><strong>Equity curve:</strong> cumulative P&amp;L over time. Healthy = upward-sloping with shallow drawdowns</li>
    </ul>
  </div>

  <div id="faq_history">
    <h3>What is this panel?</h3>
    <p>The <strong>Signal History</strong> tab is the <strong>full audit log</strong> of every signal the bot has ever fired &mdash; closed and open, winners and losers. Every row is one signal with its complete context (entry, SL, TPs, confidence, regime, ICT structure, OGD weights at fire-time, template match, etc.).</p>
    <h3>Why it exists</h3>
    <p>When something goes wrong (or surprisingly well), you need to investigate <em>why</em>. The history table lets you slice and dice by outcome, token, time, and feature. It's your forensic tool for finding patterns the dashboards don't surface automatically.</p>
    <h3>Section-by-section</h3>
    <h4>Filter chips (top)</h4>
    <p>Slice by outcome: <strong>All / Wins / Losses / Partial / Open / Expired</strong>. Stacked with the per-token filter below.</p>
    <h4>Token filter bar</h4>
    <p>One pill per token in your universe + "All Tokens". Click to filter the table.</p>
    <h4>Main table</h4>
    <p>Sortable columns: ID, token, signal direction, entry, SL, TP1/2/3, R:R, confidence, timestamp, status. Click any column header to sort.</p>
    <h4>Row expansion</h4>
    <p>Click a row to reveal the full feature snapshot at signal-fire time: market regime, sweep type, session, dealing-range location, MSS quality, FVG quality, SMT type, entry type, EV score, ICT bias, template match, OGD weights, and more.</p>
    <h3>When to check it</h3>
    <ul>
      <li>After a losing streak &mdash; filter by "Losses" + token to find common patterns</li>
      <li>After a winning streak &mdash; verify the wins aren't lucky (different regimes / sessions / setups)</li>
      <li>When auditing a specific Telegram alert you remember &mdash; search by token + time</li>
      <li>Before changing a strategy parameter &mdash; understand what current signals look like</li>
    </ul>
    <h3>What to do when you see X</h3>
    <table>
      <thead><tr><th>Observation</th><th>Suggested action</th></tr></thead>
      <tbody>
        <tr><td>All recent losses share a session (e.g., OVERNIGHT)</td><td>Cross-check AI Intelligence hour&times;day heatmap, consider blocking that session</td></tr>
        <tr><td>All recent losses have low SMT confirmation</td><td>Tighten SMT gate in config (operator decision)</td></tr>
        <tr><td>One token underperforming all others</td><td>Run D-pilot (backtest that token alone), consider removing from universe</td></tr>
        <tr><td>EXPIRED count rising</td><td>Entry window may be too narrow OR confidence floor too strict</td></tr>
      </tbody>
    </table>
    <h3>Common scenarios</h3>
    <div class="faq-tip"><strong>Scenario A:</strong> "I've had 3 losses today on SELL signals." Filter Losses + sort by timestamp DESC. Expand each row: do they all share the same regime (e.g., RANGING)? Same session? Same MSS quality? Pattern emerges &mdash; route the finding to the operator for a backtest experiment.</div>
    <div class="faq-warn"><strong>Scenario B:</strong> "Bot fired but I didn't get the Telegram." Filter by Open (or by token) + check the timestamp matches what you saw. If the row exists but Telegram failed, the issue is in the alert delivery, not the bot. Logs would have a [TG FAILED] line.</div>
    <h3>Glossary</h3>
    <ul>
      <li><strong>OPEN:</strong> signal fired, in-flight, not yet TP/SL/expired</li>
      <li><strong>WIN:</strong> hit TP3 fully (max profit)</li>
      <li><strong>PARTIAL / PARTIAL_TP1 / PARTIAL_TP2:</strong> hit TP1 (and/or TP2), then reversed before TP3 &mdash; still counts as a winner in WR math</li>
      <li><strong>LOSS:</strong> hit SL before any TP</li>
      <li><strong>EXPIRED:</strong> entry window passed without hitting either TP or SL</li>
      <li><strong>Sweep type:</strong> BSL (buy-side liquidity, used for SELL setup) or SSL (sell-side liquidity, used for BUY setup)</li>
      <li><strong>EV score:</strong> expected value rank (template-specific quality bonus)</li>
    </ul>
  </div>

  <div id="faq_intelligence">
    <h3>What is this panel?</h3>
    <p>The <strong>AI Intelligence</strong> tab is the bot's <strong>signal-quality scorecard</strong>. It aggregates every signal the bot has fired and slices the results by confidence level, time of day, day of week, and token. It answers: <em>is the strategy picking good setups, and when does it perform best?</em></p>
    <h3>Why it exists</h3>
    <p>The bot's edge isn't uniform &mdash; it works better in some regimes, hours, sessions, and on some tokens than others. This panel surfaces those edges (and weaknesses) so you can either trust the bot more during high-edge conditions, or eventually filter out low-edge conditions in code.</p>
    <p><strong>Different from Adaptive tab:</strong> Adaptive shows how the bot is <em>learning</em> (weights, gates, exposure). AI Intelligence shows <em>what the bot has produced</em> so far.</p>
    <h3>Section-by-section</h3>
    <h4>Bot Health Score</h4>
    <p>Single composite number out of 100. Composition:</p>
    <ul>
      <li><strong>Win Rate (40 pts max):</strong> overall WR scaled 0-100</li>
      <li><strong>Avg R:R (20 pts max):</strong> reward-to-risk ratio across all signals</li>
      <li><strong>Hi-Conf WR (20 pts max):</strong> WR among conf 7-10 signals (should be highest)</li>
      <li><strong>Selectivity (20 pts max):</strong> fewer-but-better signals score higher than many-but-noisy</li>
    </ul>
    <p>70+ is healthy. Below 50 = the strategy is not earning its keep.</p>
    <h4>Active Adaptive Gates</h4>
    <p>Real-time view of what filters the bot is currently applying.</p>
    <ul>
      <li><strong>Conf Floor:</strong> minimum signal confidence required to fire (default 1)</li>
      <li><strong>RANGING Floor:</strong> stricter floor in RANGING regimes (where edge is weakest)</li>
      <li><strong>Tokens w/ Floor&uarr;:</strong> tokens whose recent WR dropped below 35% and now have +1 or +2 added to their conf floor</li>
      <li><strong>OGD Active:</strong> tokens whose OGD weights have learned enough to be applied (vs bootstrap defaults)</li>
    </ul>
    <h4>Confidence Analytics</h4>
    <p>Sanity check: does the bot's confidence score actually predict WR?</p>
    <ul>
      <li><strong>Hi-Conf WR (conf 7-10):</strong> should be noticeably HIGHER than Lo-Conf WR</li>
      <li><strong>Lo-Conf WR (conf 1-4):</strong> can be lower; if equal to Hi-Conf, the score isn't doing its job</li>
      <li><strong>Best Conf Level:</strong> the conf bucket with the strongest WR (min 2 trades)</li>
    </ul>
    <h4>Confidence Level Breakdown</h4>
    <p>Stacked bar per confidence level (1-10) showing WIN / PARTIAL / LOSS / EXPIRED distribution. Should slope GREEN as confidence rises. Flat slope = red flag (confidence not predictive).</p>
    <h4>Win Rate by Hour &times; Day</h4>
    <p>Heatmap of WR by hour-of-day (UTC) and day-of-week. ICT killzones (London 7-10 UTC, NY AM 12-15 UTC) typically show the strongest cells. Cells with &lt;2 signals are uncolored (avoiding false confidence).</p>
    <h4>Token Performance</h4>
    <p>Per-token WR with <strong>Wilson 95% confidence interval</strong> whiskers &mdash; honest about small-sample uncertainty. A 100% WR on 3 trades has a huge whisker. The "Adaptive" column shows the bot's current per-token weight blend.</p>
    <h3>When to check it</h3>
    <ul>
      <li>Weekly &mdash; trend check on Bot Health Score</li>
      <li>After a losing day &mdash; see if losses cluster in a specific hour/session/token</li>
      <li>Before tuning strategy &mdash; understand current weak/strong points</li>
      <li>When confidence calibration feels off (Hi-Conf losing more than Lo-Conf)</li>
    </ul>
    <h3>What to do when you see X</h3>
    <table>
      <thead><tr><th>Observation</th><th>Suggested action</th></tr></thead>
      <tbody>
        <tr><td>Bot Health Score drops &gt;10 in a week</td><td>Run AI Intelligence diagnostics &mdash; find which dimension dropped</td></tr>
        <tr><td>Hi-Conf WR &le; Lo-Conf WR</td><td>Confidence scoring needs recalibration; flag for operator</td></tr>
        <tr><td>One hour is dark red (WR &lt; 40%)</td><td>Consider blocking that hour in <code>config.py</code></td></tr>
        <tr><td>One token Wilson lower bound is below 50%</td><td>Run D-pilot backtest, consider removal</td></tr>
      </tbody>
    </table>
    <h3>Common scenarios</h3>
    <div class="faq-tip"><strong>Scenario A:</strong> "All my losses this week were on Mondays during OVERNIGHT session." Heatmap confirms: Monday OVERNIGHT = WR 30%. Decision: block that cell in config (operator task), expect overall WR to lift.</div>
    <div class="faq-warn"><strong>Scenario B:</strong> "Token X has WR 100% (3 trades)." Wilson CI shows [29%, 100%]. The true WR could be anywhere in that range. Don't celebrate yet &mdash; need 10+ trades before treating it as a real edge.</div>
    <h3>Glossary</h3>
    <ul>
      <li><strong>Wilson 95% CI:</strong> a conservative confidence interval for proportions, accounts for small sample. Better than naive ±std on percentages</li>
      <li><strong>Killzone:</strong> ICT term for high-edge hour windows. London 7-10 UTC, NY AM 12-15 UTC</li>
      <li><strong>Conf floor:</strong> minimum confidence required to fire; raised dynamically when token loses streak</li>
      <li><strong>Selectivity:</strong> low frequency + high quality &gt; high frequency + average quality</li>
    </ul>
  </div>

  <div id="faq_backtest">
    <h3>What is this panel?</h3>
    <p>The <strong>Backtest</strong> tab is the <strong>strategy validation</strong> view. It runs the same ICT signal logic that fires live, but over historical data (last 365 days of 5M Binance candles). Tells you whether the strategy <em>would have worked</em> across many market conditions.</p>
    <h3>Why it exists</h3>
    <p>Live trading data accumulates slowly (3-5 signals/month). Backtest fills the gap by simulating the strategy over a year of historical data in ~11 minutes. It gives you statistical power (n=40+) for decisions that would otherwise wait 8+ months of paper trading.</p>
    <p><strong>Important nuance:</strong> backtest WR is the <em>headline</em> number (easy to overfit). For LIVE-readiness, cross-check the <strong>Honest Metrics</strong> tab (CPCV + DSR).</p>
    <h3>Section-by-section</h3>
    <h4>Baseline pin banner</h4>
    <p>Top of the tab. Shows which Run is the canonical baseline (e.g., Run-168). Color-coded:</p>
    <ul>
      <li>&#x2705; <strong>OK:</strong> latest backtest matches pinned baseline</li>
      <li>&#x26A0;&#xFE0F; <strong>Drift:</strong> latest is newer than pin (an experiment was run but not promoted)</li>
      <li>&#x26D4; <strong>Mismatch:</strong> latest differs from pin &mdash; investigate</li>
    </ul>
    <h4>Run Controls</h4>
    <p>Click <strong>Run Backtest</strong> to execute. VPN required (Binance blocked in PH). Cached candle data makes re-runs ~3-5 min. Auto-saves to DB.</p>
    <h4>Meta bar</h4>
    <p>Run date, period, resolution, total signals, headline WR, avg R:R, cost model (slippage + fee).</p>
    <h4>Performance by Token</h4>
    <p>Breakdown table: signals / wins / partial / losses / expired / WR / avg R:R / avg conf per token.</p>
    <h4>Win Rate by Regime / Session / Day / Hour</h4>
    <p>Same breakdowns as AI Intelligence but for backtest data instead of live.</p>
    <h4>Walk-Forward</h4>
    <p>Shows out-of-sample (OOS) vs in-sample (IS) WR. A small or NEGATIVE overfit gap (IS &le; OOS) is a strong signal the edge is real, not curve-fit.</p>
    <h4>Tune Bot History</h4>
    <p>Audit trail of every strategy parameter change ever applied. Includes Run-X labels showing which backtest captured each change. Rollback button per row.</p>
    <h3>When to check it</h3>
    <ul>
      <li>After applying a parameter change &mdash; verify it didn't break things</li>
      <li>Before flipping to LIVE &mdash; sanity check current strategy on historical data</li>
      <li>Weekly &mdash; rerun to capture latest week of data (rolling 365d window)</li>
      <li>When evaluating an experiment hypothesis</li>
    </ul>
    <h3>What to do when you see X</h3>
    <table>
      <thead><tr><th>Observation</th><th>Suggested action</th></tr></thead>
      <tbody>
        <tr><td>Headline WR &lt; 60%</td><td>Strategy not LIVE-ready. Tune via backtest-explorer agent</td></tr>
        <tr><td>Overfit gap &gt; +10pp (IS &gt;&gt; OOS)</td><td>Strategy is over-fit to past data; will likely degrade live</td></tr>
        <tr><td>n &lt; 30 signals over 365 days</td><td>Too selective; statistical power too low</td></tr>
        <tr><td>One token contributes 50%+ losses</td><td>Re-evaluate that token's inclusion</td></tr>
        <tr><td>Baseline pin shows "drift"</td><td>Either promote latest run or investigate why it's there</td></tr>
      </tbody>
    </table>
    <h3>Common scenarios</h3>
    <div class="faq-tip"><strong>Scenario A:</strong> You applied a config change manually. Run Backtest. Headline WR went from 77% to 81% (+4pp). But Honest Metrics tab shows CPCV mean only +0.5pp. The "lift" is mostly within statistical noise &mdash; don't promote yet.</div>
    <div class="faq-warn"><strong>Scenario B:</strong> Backtest takes &gt;15 min. Check log &mdash; probably Binance fetch issue (no VPN, rate-limited). Cache may be stale. Try again later.</div>
    <h3>Glossary</h3>
    <ul>
      <li><strong>OOS (Out-of-sample):</strong> data the strategy has NOT seen during tuning &mdash; the honest test</li>
      <li><strong>IS (In-sample):</strong> data the strategy WAS tuned on &mdash; easy to overfit</li>
      <li><strong>Overfit gap:</strong> IS WR &minus; OOS WR. Large positive = bad. Negative = strategy edge is real</li>
      <li><strong>Cost model:</strong> realistic slippage (0.05%/side) + exchange fee (0.10%/side) deducted from every trade</li>
      <li><strong>Walk-forward:</strong> simulates trading with only past data available at each point, then tests on next chunk</li>
    </ul>
  </div>

  <div id="faq_adaptive">
    <h3>What is this panel?</h3>
    <p>The <strong>Adaptive</strong> tab is the bot's <strong>learning &amp; risk-control</strong> dashboard. It shows three things that auto-adjust as the bot trades:</p>
    <ol>
      <li><strong>OGD weights</strong> &mdash; per-token, per-feature importance learned via online gradient descent after each closed signal</li>
      <li><strong>Adaptive gates</strong> &mdash; signal-floor adjustments (e.g., a token that loses 3 in a row gets a stricter conf floor)</li>
      <li><strong>Portfolio exposure</strong> &mdash; live position / risk gauges with hard caps</li>
    </ol>
    <h3>Why it exists</h3>
    <p>A static strategy decays over time as markets change. OGD makes per-token features (FVG quality, MSS quality, session, etc.) adapt their importance based on real outcomes. Portfolio gates prevent runaway losses regardless of how the strategy feels.</p>
    <p><strong>OFFLINE status is normal early on.</strong> Adaptive learning activates only after 10 closed signals per token. Until then, the bot uses bootstrap defaults from backtesting.</p>
    <h3>Section-by-section</h3>
    <h4>Bot Adaptive State</h4>
    <p>Snapshot of the 4 live state variables:</p>
    <ul>
      <li><strong>Threshold Adj.:</strong> offset on the base score gate (default 43). Positive = stricter</li>
      <li><strong>Confidence Floor:</strong> minimum signal confidence required (1-10)</li>
      <li><strong>Last Signal:</strong> most recent fired signal token/time</li>
      <li><strong>SL Exposure:</strong> total % capital at risk across all open positions</li>
    </ul>
    <h4>Portfolio Exposure</h4>
    <p>Hard caps that block new signals when filled:</p>
    <table>
      <thead><tr><th>Gate</th><th>PAPER</th><th>LIVE</th></tr></thead>
      <tbody>
        <tr><td>Open Positions</td><td>20</td><td>4</td></tr>
        <tr><td>Same Direction (BUY or SELL)</td><td>10</td><td>2</td></tr>
        <tr><td>Capital at Risk</td><td>100%</td><td>3%</td></tr>
        <tr><td>Drawdown Halt</td><td>20%</td><td>10%</td></tr>
      </tbody>
    </table>
    <p>When a bar turns red, the bot skips new signals in that direction until a position closes.</p>
    <h4>Per-Token OGD Weight Matrix</h4>
    <p>For each token, 6 features have a weight summing to 100%:</p>
    <ul>
      <li>FVG quality, MSS quality, session, confidence, trend strength, DR location</li>
    </ul>
    <p>Dotted vertical line marks the default 16.7% (equal weight). Green = above default (stronger predictor for that token). Below = weaker. Weights update only on signal close. A token pinned to all-floor weights signals <em>degeneration</em> (flagged red).</p>
    <h4>Concept Drift Baselines</h4>
    <p>Per-token rolling baselines for ADX, ATR, and RSI extremes. Once a token has 20+ bars of live data, its <strong>Learning</strong> badge flips to <strong>Active</strong> and the bot starts using dynamic thresholds instead of static defaults.</p>
    <h3>When to check it</h3>
    <ul>
      <li>Daily &mdash; quick scan for portfolio caps turning red</li>
      <li>After a losing streak &mdash; check if conf floor auto-raised correctly</li>
      <li>Weekly &mdash; review OGD weight matrix for degeneration patterns</li>
      <li>Before flipping LIVE &mdash; understand which portfolio caps activate</li>
    </ul>
    <h3>What to do when you see X</h3>
    <table>
      <thead><tr><th>Observation</th><th>Suggested action</th></tr></thead>
      <tbody>
        <tr><td>Token shows all-floor OGD weights (degeneration)</td><td>Don't trust signals from this token until OGD recovers (10+ wins)</td></tr>
        <tr><td>Capital at Risk near cap</td><td>Wait for positions to close before expecting new alerts</td></tr>
        <tr><td>Drift baseline shows "Learning (5/20)"</td><td>Normal &mdash; token needs more bars before adaptive thresholds activate</td></tr>
        <tr><td>Threshold Adj &gt; +5</td><td>Bot is being unusually strict; recent performance probably weak</td></tr>
      </tbody>
    </table>
    <h3>Common scenarios</h3>
    <div class="faq-tip"><strong>Scenario A:</strong> "I haven't gotten signals for 2 days." Check Adaptive: Threshold Adj = +8, Conf Floor = 7. Bot tightened after a recent loss streak. Will relax automatically as new wins land. Don't manually override.</div>
    <div class="faq-warn"><strong>Scenario B:</strong> "Token X has weight matrix all at floor (red)." This is OGD <em>degeneration</em> &mdash; the learning algorithm collapsed for this token. Either ignore signals from it or wait for monitoring.py to auto-reset.</div>
    <div class="faq-danger"><strong>Scenario C:</strong> Portfolio Risk hits 3% in LIVE mode. New signals will be silently blocked. Either close a position manually or wait. The bot is correctly protecting capital.</div>
    <h3>Glossary</h3>
    <ul>
      <li><strong>OGD (Online Gradient Descent):</strong> incremental machine learning that updates weights after each new data point, without retraining from scratch</li>
      <li><strong>Bootstrap weights:</strong> initial 16.7% equal weights used until OGD has enough data (10+ closes per token)</li>
      <li><strong>Concept drift:</strong> when the statistical properties of market data change over time. Drift detector adjusts thresholds dynamically</li>
      <li><strong>Threshold adjustment:</strong> dynamic offset applied to the signal score gate based on recent performance</li>
      <li><strong>Degeneration:</strong> when OGD weights collapse to the floor (all 5% min). Indicates the learning failed for that token</li>
    </ul>
  </div>

  <div id="faq_honest">
    <h3>What is this panel?</h3>
    <p>The <strong>Honest Metrics</strong> tab is the <strong>"is it really working?"</strong> view. Most trading dashboards show cherry-picked numbers (best-case backtest WR). This tab shows the <em>honest</em> ones &mdash; metrics that survive proper statistical correction for the fact that we've tested many parameter configurations.</p>
    <h3>Why it exists</h3>
    <p>The biggest trap in algorithmic trading is <strong>selection bias</strong>: test 100 configs, pick the best one, it looks great by luck alone. CPCV and DSR are the industry-standard corrections. Without them, your backtest is theater.</p>
    <h3>Key concepts</h3>
    <h4>CPCV (Combinatorial Purged K-Fold Cross-Validation)</h4>
    <p>Splits historical data into many train/test combinations (not just one). Reports mean &amp; spread of OOS win rate across all combinations. A lucky single split can't fool this.</p>
    <ul>
      <li><strong>CPCV mean:</strong> average WR across all OOS folds &mdash; this is the honest WR</li>
      <li><strong>CPCV std:</strong> spread of WRs. Tight = robust. Wide = brittle</li>
      <li><strong>CPCV q05:</strong> 5th percentile WR &mdash; worst-case fold. Should still be &ge; 50%</li>
    </ul>
    <h4>DSR (Deflated Sharpe Ratio)</h4>
    <p>Corrects the Sharpe ratio for the number of configs tested. Testing 100 configs and picking the best one gives a Sharpe inflated by selection bias. DSR deflates that.</p>
    <ul>
      <li>DSR &ge; 95% = high confidence the edge is real</li>
      <li>DSR &lt; 50% = probably overfitting to one lucky config</li>
    </ul>
    <h4>Cross-config std</h4>
    <p>Standard deviation of OOS Sharpe across all distinct configs you've tested. Used as the deflation input. Smaller = configs cluster tightly = robust edge.</p>
    <h3>Section-by-section</h3>
    <h4>Top status row</h4>
    <p>4 cards: Bot Version, Latest Audit Score, OGD Health (OK/WARN/CRIT), Macro Filter status.</p>
    <h4>Paper Trading Progress</h4>
    <p>Bar: closed paper signals / 30 (LIVE threshold). ETA based on actual fire rate. Source label tells you whether the rate comes from live data, backtest, or default.</p>
    <h4>Latest Backtest &mdash; Honest Metrics</h4>
    <p>Headline numbers from the most recent run. Gold-bordered cells are the metrics that decide LIVE-readiness:</p>
    <ul>
      <li><strong>CPCV WR mean:</strong> &ge; 60% required</li>
      <li><strong>DSR:</strong> &ge; 95% required</li>
    </ul>
    <h4>Honest Cross-Config Statistics</h4>
    <p>Spread of Sharpes across all configs ever tested. Used to compute honest DSR.</p>
    <h3>When to check it</h3>
    <ul>
      <li>Before any LIVE-mode decision</li>
      <li>After running a new backtest &mdash; verify honest metrics, not just headline</li>
      <li>Weekly &mdash; confirm strategy hasn't drifted off the honest gate</li>
      <li>When evaluating an experiment &mdash; look at delta CPCV mean, not delta headline WR</li>
    </ul>
    <h3>What to do when you see X</h3>
    <table>
      <thead><tr><th>Observation</th><th>Suggested action</th></tr></thead>
      <tbody>
        <tr><td>Headline WR &gt; CPCV mean by 10pp+</td><td>Strategy is over-fit to one split. Distrust the headline</td></tr>
        <tr><td>DSR drops below 95% after a new config tested</td><td>Selection bias eating your edge. Stop testing more configs</td></tr>
        <tr><td>CPCV std widens significantly</td><td>Edge is becoming brittle &mdash; recent config not as robust</td></tr>
        <tr><td>q05 below 50%</td><td>Worst-case fold is coin flip &mdash; strategy not consistent enough</td></tr>
      </tbody>
    </table>
    <h3>LIVE gate</h3>
    <div class="faq-warn"><strong>All 3 must pass to clear LIVE:</strong>
      <ul style="margin-top:.4rem">
        <li>CPCV mean WR &ge; 60%</li>
        <li>DSR &ge; 95%</li>
        <li>&ge; 30 closed paper signals (real OOS validation)</li>
      </ul>
    </div>
    <h3>Glossary</h3>
    <ul>
      <li><strong>OOS (Out-of-sample):</strong> data the strategy was not tuned on &mdash; the honest test</li>
      <li><strong>Selection bias:</strong> picking the best of N tests inflates the apparent edge by chance alone</li>
      <li><strong>Lopez de Prado:</strong> the academic source for CPCV (2018) and DSR (Bailey-LdP 2014). Industry gold standards</li>
      <li><strong>Multiple testing correction:</strong> statistical adjustment for testing many hypotheses (configs)</li>
      <li><strong>Within-fold proxy:</strong> the wrong way to estimate cross-trial std (uses one run's internal variance). We use the honest cross-config std instead</li>
    </ul>
  </div>

  <div id="faq_explorer">
    <h3>What is this panel?</h3>
    <p>The <strong>Auto-Explorer</strong> tab is your <strong>autonomous R&amp;D</strong> view. It shows what the Optuna-driven explorer has discovered while running in the background. Every trial uses the same honest CPCV+DSR validation gates as manual backtests; auto-promoted winners (Pareto-improving + reproducible) become the new baseline pin automatically.</p>
    <p><strong>Never auto-flips LIVE</strong> &mdash; that decision stays operator-deliberate.</p>
    <h3>Why it exists</h3>
    <p>Manual backtest exploration is slow and biased toward hypotheses the operator can think of. Optuna's Bayesian search efficiently maps the parameter space, finds Pareto-optimal corners, and runs while you sleep. Honest gates prevent it from promoting noise. The two-promotion-per-day cap + 24h soak prevent runaway promotion chains.</p>
    <h3>Section-by-section</h3>
    <h4>Session status banner</h4>
    <p>Color-coded by state:</p>
    <ul>
      <li>&#x1F7E2; <strong>RUNNING:</strong> explorer is actively executing trials right now</li>
      <li>&#x1F535; <strong>FINISHED:</strong> session completed normally</li>
      <li>&#x1F7E1; <strong>PAUSED:</strong> anti-overfit guard tripped or operator interrupted</li>
    </ul>
    <h4>Summary cards (4)</h4>
    <ul>
      <li><strong>Trials Total:</strong> all trials ever run across all studies</li>
      <li><strong>PASS/FAIL/ERROR:</strong> verdict ratio + PASS rate %</li>
      <li><strong>Auto-Promotions Today:</strong> count vs daily cap (2/day) + soak hours</li>
      <li><strong>Pareto Archive size:</strong> non-dominated configs</li>
    </ul>
    <h4>Pareto Archive</h4>
    <p>Top configs that aren't beaten on every metric by any other tested config. Dimensions: CPCV mean &uarr;, CPCV std &darr;, Sharpe &uarr;, n &uarr;. The baseline pin is typically in here.</p>
    <h4>Recent Auto-Promotions</h4>
    <p>Every entry here passed the strict 8-criteria gate AND a reproducibility re-run with matching config_hash. Rollback any auto-promotion via <code>python scripts/promote_baseline.py --rollback-to-run &lt;N&gt;</code>.</p>
    <h4>Recent Trials</h4>
    <p>Last 20 trials with verdict, metrics, walltime, reject reason. <strong>PASS</strong> trials cleared every honest gate. <strong>FAIL</strong> shows the first failing gate. <strong>ERROR</strong> = timeout/crash/DB issue.</p>
    <h3>When to check it</h3>
    <ul>
      <li>Morning after an overnight session &mdash; review what was found</li>
      <li>Anytime to monitor live progress (auto-refreshes every 15s)</li>
      <li>Before flipping LIVE &mdash; verify baseline pin still matches and no concerning trends</li>
      <li>After expanding the search space &mdash; new study should appear</li>
    </ul>
    <h3>What to do when you see X</h3>
    <table>
      <thead><tr><th>Observation</th><th>Suggested action</th></tr></thead>
      <tbody>
        <tr><td>Session shows PAUSED with "basin_lost"</td><td>50 trials in a row FAILed. Investigate search space or relax gates</td></tr>
        <tr><td>Auto-promotion happened overnight</td><td>Verify on Backtest tab; rollback if concerning</td></tr>
        <tr><td>Pareto archive shows a challenger near baseline</td><td>Wait for more trials &mdash; if reproducible, it'll auto-promote</td></tr>
        <tr><td>PASS rate &lt; 5% after 30+ trials</td><td>Search space mostly explores noise. Tighten ranges or anti-pattern lockouts</td></tr>
      </tbody>
    </table>
    <h3>Operator commands</h3>
    <table>
      <thead><tr><th>Command</th><th>What it does</th></tr></thead>
      <tbody>
        <tr><td><code>--trials 30</code></td><td>Run 30 trials (~5.5 hours)</td></tr>
        <tr><td><code>--study-name &lt;name&gt;</code></td><td>Optuna study label (same name = Bayesian continuity)</td></tr>
        <tr><td><code>--status</code></td><td>Print current session state + Pareto top-5</td></tr>
        <tr><td><code>--digest [hours]</code></td><td>Compact operator summary for last N hours (default 24)</td></tr>
        <tr><td><code>--best</code></td><td>Top-10 PASS trials across all studies</td></tr>
        <tr><td><code>--list-recent N</code></td><td>Print last N trials</td></tr>
        <tr><td><code>--skip-precache</code></td><td>Skip the cache-warm step (saves ~11 min if cache is fresh)</td></tr>
      </tbody>
    </table>
    <h3>Common scenarios</h3>
    <div class="faq-tip"><strong>Scenario A:</strong> Started 30-trial session before bed. Wake up: dashboard shows 28 trials done (2 ERROR from timeouts), 5 PASS, no auto-promotions. PASS trials match baseline closely (no Pareto improvement). Run <code>--digest 12</code> for summary. No action needed.</div>
    <div class="faq-warn"><strong>Scenario B:</strong> Dashboard shows AUTO_PROMOTED row from 03:14am. New baseline is Run-X. Check Backtest tab &mdash; pin banner shows OK status with new Run-X. Review trial details; if happy, do nothing. If concerned, rollback via CLI.</div>
    <div class="faq-danger"><strong>Scenario C:</strong> Session paused with "code_drift" reason. You edited <code>ict_engine.py</code> or <code>backtest.py</code> while explorer was running. Restart the session after your edits are complete.</div>
    <h3>Glossary</h3>
    <ul>
      <li><strong>Optuna:</strong> Bayesian hyperparameter search library. TPE sampler learns from prior trials to pick smart next ones</li>
      <li><strong>TPE (Tree-structured Parzen Estimator):</strong> the sampling algorithm Optuna uses by default. Needs ~25-50 trials before its prior is meaningful</li>
      <li><strong>Pareto front:</strong> set of configs where no single config beats another on every metric. Multi-objective optimization output</li>
      <li><strong>Dominance:</strong> config A dominates B if A &ge; B on every dim AND A &gt; B on at least one</li>
      <li><strong>Reproducibility check:</strong> running the same params twice and verifying matching config_hash + metrics within tolerance. Prevents promoting lucky single runs</li>
      <li><strong>Daily cap / Soak:</strong> max 2 auto-promotions per UTC day, 24h between each &mdash; observe first promotion's effects before next stacks</li>
    </ul>
  </div>

</div>

<!-- MANUAL CLOSE POSITION MODAL -->
<div id="closePosModal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closePositionModal()">
  <div class="modal-box">
    <button class="modal-x" onclick="closePositionModal()">&#10005;</button>
    <div class="modal-h" id="closePosTitle">Close Position</div>
    <div class="modal-sub">Enter your actual exit price — P&L calculated automatically.</div>

    <div class="modal-sig-row" id="closePosChips"></div>

    <label class="modal-label" for="closePosInput">Exit Price (USD)</label>
    <input class="modal-input" id="closePosInput" type="number" step="any" min="0"
      placeholder="e.g. 9.3500" oninput="_updateClosePnl(this.value)"
      onkeydown="if(event.key==='Enter')confirmClosePosition()">

    <div class="modal-preview">
      <div class="mprow">
        <div class="mprow-label">Float P&amp;L</div>
        <div class="mprow-val" id="closePnlVal" style="color:var(--muted)">—</div>
      </div>
      <div class="mprow">
        <div class="mprow-label">Result</div>
        <div class="mprow-val" id="closeResultVal" style="color:var(--muted)">—</div>
      </div>
      <div class="mprow">
        <div class="mprow-label">vs TP1</div>
        <div class="mprow-val" id="closeVsTp1" style="color:var(--muted)">—</div>
      </div>
      <div class="mprow">
        <div class="mprow-label">Close Type</div>
        <div class="mprow-val" style="color:var(--accent2);font-size:.78rem">MANUAL</div>
      </div>
    </div>

    <div class="modal-actions">
      <button class="btn-confirm-close" id="closePosConfirmBtn" onclick="confirmClosePosition()" disabled>
        Confirm Close
      </button>
      <button class="btn-modal-cancel" onclick="closePositionModal()">Cancel</button>
    </div>
  </div>
</div>

<script>
let allSigs=[], curFilter='ALL', curToken='ALL';
let histPage=1, HIST_PAGE_SIZE=25, histSort={col:'id',dir:'desc'};
let allOpen=[], openPage=1, OPEN_PAGE_SIZE=8;
let _tuneHistData=[], tuneHistPage=1;
const TUNE_HIST_PAGE_SIZE=10;
let _btHistData=[], btHistPage=1;
const BT_HIST_PAGE_SIZE=10;

// ── Manual Close Position Modal ─────────────────────────
let _cm = {sigId:null, direction:'', entry:0, tp1:0, tp2:0, tp3:0, sl:0,
           tp1Pct:0, tp2Pct:0, slPct:0};

function openCloseModalById(sigId){
  const r = allOpen.find(s => String(s.id) === String(sigId));
  if(!r){ showErr('Signal not found in open list — refresh the page'); return; }
  openCloseModal(r.id, r.token, r.signal, r.entry_price,
                 r.tp1, r.tp2, r.tp3, r.sl,
                 r.tp1_pct||0, r.tp2_pct||0, r.sl_pct||0);
}

function openCloseModal(sigId, token, direction, entry, tp1, tp2, tp3, sl,
                        tp1Pct, tp2Pct, slPct){
  _cm = {sigId, direction, entry, tp1, tp2, tp3, sl, tp1Pct, tp2Pct, slPct};

  document.getElementById('closePosTitle').textContent =
    'Close ' + token + ' ' + direction + ' #' + sigId;

  // Populate info chips
  const dir = direction === 'BUY' ? '&#9650; BUY' : '&#9660; SELL';
  const col = direction === 'BUY' ? 'var(--green)' : 'var(--red)';
  document.getElementById('closePosChips').innerHTML =
    '<div class="modal-sig-chip">'+dir+' <strong style="color:'+col+'">'+token+'</strong></div>'
   +'<div class="modal-sig-chip">Entry <strong>$'+Number(entry).toFixed(4)+'</strong></div>'
   +'<div class="modal-sig-chip">TP1 <strong>$'+Number(tp1).toFixed(4)+'</strong> (+'+Number(tp1Pct).toFixed(1)+'%)</div>'
   +'<div class="modal-sig-chip">TP2 <strong>$'+Number(tp2).toFixed(4)+'</strong> (+'+Number(tp2Pct).toFixed(1)+'%)</div>'
   +'<div class="modal-sig-chip">SL <strong style="color:var(--red)">$'+Number(sl).toFixed(4)+'</strong></div>';

  // Reset inputs and preview
  document.getElementById('closePosInput').value = '';
  _updateClosePnl('');
  document.getElementById('closePosModal').style.display = 'flex';
  setTimeout(() => document.getElementById('closePosInput').focus(), 60);
}

function closePositionModal(){
  document.getElementById('closePosModal').style.display = 'none';
}

function _updateClosePnl(val){
  const ep  = parseFloat(val);
  const btn = document.getElementById('closePosConfirmBtn');
  const pnlEl    = document.getElementById('closePnlVal');
  const resultEl = document.getElementById('closeResultVal');
  const vsTp1El  = document.getElementById('closeVsTp1');

  if(!ep || ep <= 0 || isNaN(ep)){
    pnlEl.textContent = resultEl.textContent = vsTp1El.textContent = '—';
    pnlEl.style.color = resultEl.style.color = vsTp1El.style.color = 'var(--muted)';
    btn.disabled = true;
    btn.textContent = 'Confirm Close';
    btn.className = 'btn-confirm-close';
    return;
  }

  let pnl;
  if(_cm.direction === 'BUY'){
    pnl = (ep - _cm.entry) / _cm.entry * 100;
  } else {
    pnl = (_cm.entry - ep) / _cm.entry * 100;
  }

  // P&L display
  const pnlStr = (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + '%';
  pnlEl.textContent = pnlStr;
  pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';

  // Result classification (mirrors backend logic)
  let result, rCol;
  if(pnl >= _cm.tp1Pct){
    result = 'WIN'; rCol = 'var(--green)';
  } else if(pnl > 0){
    result = 'PARTIAL'; rCol = 'var(--yellow)';
  } else {
    result = 'LOSS'; rCol = 'var(--red)';
  }
  resultEl.textContent = result;
  resultEl.style.color = rCol;

  // vs TP1 remaining
  const remaining = _cm.tp1Pct - pnl;
  if(remaining <= 0){
    vsTp1El.textContent = 'AT/PAST TP1';
    vsTp1El.style.color = 'var(--green)';
  } else {
    vsTp1El.textContent = remaining.toFixed(2) + '% short';
    vsTp1El.style.color = 'var(--muted)';
  }

  // Button state
  btn.disabled = false;
  if(pnl < 0){
    btn.className = 'btn-confirm-close is-loss';
    btn.textContent = 'Confirm Close (LOSS)';
  } else {
    btn.className = 'btn-confirm-close';
    btn.textContent = 'Confirm Close (' + result + ')';
  }
}

async function confirmClosePosition(){
  const exitPrice = parseFloat(document.getElementById('closePosInput').value);
  if(!exitPrice || exitPrice <= 0 || isNaN(exitPrice)){
    showErr('Enter a valid exit price'); return;
  }
  const btn = document.getElementById('closePosConfirmBtn');
  btn.disabled = true;
  btn.textContent = 'Closing...';

  try{
    const r = await fetch('/api/close_position', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({signal_id: _cm.sigId, exit_price: exitPrice})
    });
    const d = await r.json();
    if(d.ok){
      closePositionModal();
      await loadAll();   // refresh all panels so stats + history update immediately
    } else {
      showErr('Close failed: ' + (d.error || 'unknown error'));
      btn.disabled = false;
    }
  } catch(e){
    showErr('Close failed: ' + e.message);
    btn.disabled = false;
  }
}
let _autoRefresh=null;

function showErr(msg){
  const b=document.getElementById('errBanner');
  b.textContent=msg; b.style.display='block';
  setTimeout(()=>b.style.display='none',8000);
}

function showTab(tab, btn){
  document.querySelectorAll('.main-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel'+tab.charAt(0).toUpperCase()+tab.slice(1)).classList.add('active');
}

async function loadAll(){
  document.getElementById('lastUpdated').textContent='Updating...';
  try{
    const h=await fetch('/api/health');
    const hd=await h.json();
    const dbEl=document.getElementById('dbStatus');
    if(hd.db_exists){
      dbEl.textContent='DB OK'; dbEl.className='db-ok';
    } else {
      dbEl.textContent='DB MISSING'; dbEl.className='db-err';
      showErr('signals.db not found — run crypto_alert.py first');
    }
  }catch(e){console.error('health',e)}

  await Promise.all([loadStats(), loadOpen(), loadHistory(), loadIntelligence(), loadEquityCurve(), loadHourDayHeatmap()]);
  document.getElementById('lastUpdated').textContent=
    'Updated: '+new Date().toLocaleTimeString();
}

// ── C6 ROLLING WALK-FORWARD CHART (2026-05-22) ────────────────────────────────
let _wfChart = null;
async function loadRollingWf(){
  const wrap = document.getElementById('wfChartWrap');
  const sumEl = document.getElementById('wfSummary');
  if(!wrap) return;
  try{
    const r = await fetch('/api/rolling-wf');
    const d = await r.json();
    if(!d.ok || !d.windows || d.windows.length === 0){
      wrap.innerHTML = '<div class="empty">No walk-forward data yet</div>';
      if(sumEl) sumEl.textContent = '';
      return;
    }
    // Replace wrap content with canvas if not already
    if(!wrap.querySelector('canvas')){
      wrap.innerHTML = '<canvas id="wfChart"></canvas>';
    }
    const labels = d.windows.map(w => w.train_end_ts);
    const trainData = d.windows.map(w => w.train_n >= 3 ? w.train_wr : null);
    const testData  = d.windows.map(w => w.test_n  >= 3 ? w.test_wr  : null);
    const targetLine = labels.map(() => 55);
    const ctx = document.getElementById('wfChart').getContext('2d');
    const datasets = [
      {
        label: 'Train WR',
        data: trainData,
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59,130,246,0.10)',
        borderWidth: 2,
        pointRadius: 3, pointHoverRadius: 5,
        spanGaps: true, fill: false, tension: 0.18,
      },
      {
        label: 'Test (OOS) WR',
        data: testData,
        borderColor: '#a855f7',
        backgroundColor: 'rgba(168,85,247,0.15)',
        borderWidth: 2,
        pointRadius: 3, pointHoverRadius: 5,
        spanGaps: true, fill: false, tension: 0.18,
      },
      {
        label: 'Target 55%',
        data: targetLine,
        borderColor: 'rgba(148,163,184,0.45)',
        borderWidth: 1, borderDash: [4, 4],
        pointRadius: 0, fill: false, tension: 0,
      }
    ];
    if(_wfChart){
      _wfChart.data.labels = labels;
      _wfChart.data.datasets = datasets;
      _wfChart.update('none');
    } else {
      _wfChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {mode: 'index', intersect: false},
          plugins: {
            legend: {labels: {color: '#94a3b8', font: {size: 11}, boxWidth: 14}},
            tooltip: {
              backgroundColor: 'rgba(18,18,29,0.96)',
              borderColor: '#252538', borderWidth: 1,
              titleColor: '#f1f5f9', bodyColor: '#f1f5f9', padding: 10,
              callbacks: {
                afterBody: (items) => {
                  if(!items.length) return '';
                  const w = d.windows[items[0].dataIndex];
                  return ['n_train=' + w.train_n, 'n_test=' + w.test_n];
                }
              }
            }
          },
          scales: {
            x: {
              grid: {color: 'rgba(37,37,56,0.4)'},
              ticks: {color: '#94a3b8', maxRotation: 30, autoSkip: true, maxTicksLimit: 10, font: {size: 10}}
            },
            y: {
              grid: {color: 'rgba(37,37,56,0.4)'},
              ticks: {color: '#94a3b8', font: {size: 10}, callback: (v) => v + '%'},
              suggestedMin: 0, suggestedMax: 100,
            }
          }
        }
      });
    }
    // Summary line
    const s = d.summary || {};
    const gapColor = (s.mean_gap || 0) >= -5 ? 'var(--green)' : (s.mean_gap || 0) >= -15 ? 'var(--yellow)' : 'var(--red)';
    const consistRatio = s.n_windows > 0 ? Math.round((s.consistent || 0) / s.n_windows * 100) : 0;
    if(sumEl){
      sumEl.innerHTML =
        'Run #' + (d.run_id || '—')
        + ' &nbsp;·&nbsp; ' + (s.n_windows || 0) + ' folds'
        + ' &nbsp;·&nbsp; mean test−train gap <span style="color:' + gapColor + '">'
          + ((s.mean_gap || 0) >= 0 ? '+' : '') + (s.mean_gap || 0).toFixed(1) + 'pp</span>'
        + ' &nbsp;·&nbsp; consistent (test ≥ 55%): ' + (s.consistent || 0) + ' / ' + (s.n_windows || 0)
          + ' (' + consistRatio + '%)';
    }
  }catch(e){
    console.error('rolling-wf', e);
    wrap.innerHTML = '<div class="empty">Failed to load walk-forward data</div>';
  }
}

// ── C3 OGD WEIGHT SPARKLINES (2026-05-22) ─────────────────────────────────────
// Hand-rolled canvas sparklines (one per token block, 6 colored lines per token).
// Avoids spawning N Chart.js instances for a per-token repeated micro-chart.
const _OGD_FEATURE_COLORS = {
  'fvg_quality':    '#22c55e',
  'mss_quality':    '#3b82f6',
  'session':        '#a855f7',
  'confidence':     '#eab308',
  'trend_strength': '#06b6d4',
  'dr_location':    '#ef4444',
};
const _OGD_WEIGHT_MIN = 0.05;
const _OGD_WEIGHT_MAX = 0.50;
const _OGD_DEFAULT_W  = 1.0 / 6.0;
let _ogdHistoryCache = null;
async function _fetchOgdHistory(force){
  if(_ogdHistoryCache && !force) return _ogdHistoryCache;
  try{
    const r = await fetch('/api/ogd-weight-history');
    const d = await r.json();
    _ogdHistoryCache = (d && d.ok && d.series) ? d.series : {};
  }catch(e){
    console.error('ogd-history', e);
    _ogdHistoryCache = {};
  }
  return _ogdHistoryCache;
}
async function renderOgdSparklines(){
  const series = await _fetchOgdHistory(true);
  document.querySelectorAll('canvas.wt-spark').forEach(canvas => {
    const tok = canvas.dataset.token;
    const tokSeries = series[tok];
    if(!tokSeries){
      _drawEmptySparkline(canvas, 'no history');
      _renderSparkLegend(tok, []);
      return;
    }
    const feats = Object.keys(tokSeries);
    _drawSparklineMulti(canvas, tokSeries);
    _renderSparkLegend(tok, feats);
  });
}
function _renderSparkLegend(tok, feats){
  const el = document.getElementById('wtSparkLegend_' + tok);
  if(!el) return;
  if(!feats.length){
    el.innerHTML = '<span>No trajectory yet</span>';
    return;
  }
  el.innerHTML = feats.map(f => {
    const c = _OGD_FEATURE_COLORS[f] || '#94a3b8';
    return '<span class="wt-leg-item">'
      + '<span class="wt-leg-dot" style="background:' + c + '"></span>'
      + f.replace('_', ' ')
      + '</span>';
  }).join('') + '<span style="margin-left:auto;color:var(--muted)">'
    + '─ default ' + (_OGD_DEFAULT_W*100).toFixed(1) + '%</span>';
}
function _drawEmptySparkline(canvas, msg){
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 600, h = canvas.clientHeight || 56;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.fillStyle = '#1a1a28';
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = '#475569';
  ctx.font = '11px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(msg, w / 2, h / 2 + 4);
}
function _drawSparklineMulti(canvas, tokSeries){
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 600, h = canvas.clientHeight || 56;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  // Background
  ctx.fillStyle = '#0a0a0f';
  ctx.fillRect(0, 0, w, h);
  // Padding for axes
  const padL = 4, padR = 4, padT = 4, padB = 4;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  // Y-scale: clamp to [WEIGHT_MIN, WEIGHT_MAX]
  const yMin = _OGD_WEIGHT_MIN, yMax = _OGD_WEIGHT_MAX;
  const yToPx = (y) => padT + (1 - (y - yMin) / (yMax - yMin)) * plotH;
  // Reference horizontal line at default weight
  ctx.strokeStyle = 'rgba(148,163,184,0.35)';
  ctx.setLineDash([2, 3]);
  ctx.lineWidth = 1;
  ctx.beginPath();
  const defY = yToPx(_OGD_DEFAULT_W);
  ctx.moveTo(padL, defY); ctx.lineTo(padL + plotW, defY); ctx.stroke();
  ctx.setLineDash([]);
  // Max points across features for x-scaling (each feature has its own length)
  let maxPts = 0;
  for(const f in tokSeries){ maxPts = Math.max(maxPts, tokSeries[f].length); }
  if(maxPts < 2){
    _drawEmptySparkline(canvas, 'need ≥2 snapshots');
    return;
  }
  // Draw each feature line
  for(const feat in tokSeries){
    const pts = tokSeries[feat];
    if(pts.length < 2) continue;
    const color = _OGD_FEATURE_COLORS[feat] || '#94a3b8';
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    pts.forEach((p, i) => {
      const x = padL + (i / Math.max(1, pts.length - 1)) * plotW;
      const y = yToPx(Math.max(yMin, Math.min(yMax, p.w)));
      if(i === 0) ctx.moveTo(x, y);
      else        ctx.lineTo(x, y);
    });
    ctx.stroke();
    // End-point dot
    const last = pts[pts.length - 1];
    const lx = padL + plotW, ly = yToPx(Math.max(yMin, Math.min(yMax, last.w)));
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(lx, ly, 2.2, 0, Math.PI * 2); ctx.fill();
  }
}

// ── C2 HOUR × DAY HEATMAP (2026-05-22) ────────────────────────────────────────
const _DOW_LABELS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
function _hmColor(wr){
  // Diverging scale centered on 50%. Red below, green above, neutral mid.
  if(wr >= 70) return '#16a34a';     // strong green
  if(wr >= 60) return '#4ade80';     // green
  if(wr >= 50) return '#a3e635';     // lime
  if(wr >= 40) return '#fbbf24';     // amber
  if(wr >= 30) return '#fb923c';     // orange
  return '#ef4444';                   // red
}
async function loadHourDayHeatmap(){
  const wrap = document.getElementById('hourDayHeatmap');
  if(!wrap) return;
  try{
    const r = await fetch('/api/hour-day-heatmap');
    const d = await r.json();
    if(!d.ok || !d.cells || Object.keys(d.cells).length === 0){
      wrap.innerHTML = '<div class="empty">No closed signals yet — heatmap populates after first signal closes</div>';
      return;
    }
    // Build 7×24 grid markup
    let cells = ['<div class="hm-grid">'];
    // Header row: blank corner + 24 hour labels
    cells.push('<div class="hm-row-label"></div>');
    for(let h = 0; h < 24; h++){
      cells.push('<div class="hm-col-label">' + (h%3===0 ? String(h).padStart(2,'0') : '') + '</div>');
    }
    // 7 rows for days
    for(let dow = 0; dow < 7; dow++){
      cells.push('<div class="hm-row-label">' + _DOW_LABELS[dow] + '</div>');
      for(let h = 0; h < 24; h++){
        const c = d.cells[dow + '_' + h];
        if(!c){
          cells.push('<div class="hm-cell empty" title="' + _DOW_LABELS[dow] + ' ' + String(h).padStart(2,'0') + ':00 UTC — no signals"></div>');
          continue;
        }
        const color = c.n >= 2 ? _hmColor(c.wr) : null;
        const cls   = c.n >= 2 ? '' : ' lown';
        const style = color ? ('background:' + color + ';color:#0a0a0f') : '';
        const txt   = c.n >= 2 ? (c.wr | 0) : c.n;
        const title = _DOW_LABELS[dow] + ' ' + String(h).padStart(2,'0') + ':00 UTC — '
                     + c.wr + '% WR (n=' + c.n
                     + ': ' + c.wins + 'W/' + c.partial + 'P/' + c.losses + 'L/' + c.expired + 'E)';
        cells.push('<div class="hm-cell' + cls + '" style="' + style + '" title="' + title + '">' + txt + '</div>');
      }
    }
    cells.push('</div>');
    // Legend + summary
    const s = d.summary || {};
    const bestStr  = s.best  ? _DOW_LABELS[s.best.dow]  + ' ' + String(s.best.hour).padStart(2,'0')  + 'h ' + s.best.wr + '% (n=' + s.best.n + ')' : '—';
    const worstStr = s.worst ? _DOW_LABELS[s.worst.dow] + ' ' + String(s.worst.hour).padStart(2,'0') + 'h ' + s.worst.wr + '% (n=' + s.worst.n + ')' : '—';
    cells.push(
      '<div class="hm-legend">'
      + '<span>0%</span>'
      + '<div class="hm-legend-bar">'
      +   '<div style="background:#ef4444"></div>'
      +   '<div style="background:#fb923c"></div>'
      +   '<div style="background:#fbbf24"></div>'
      +   '<div style="background:#a3e635"></div>'
      +   '<div style="background:#4ade80"></div>'
      +   '<div style="background:#16a34a"></div>'
      + '</div>'
      + '<span>100%</span>'
      + '<span style="margin-left:auto">'+(s.n_cells_usable||0)+' cells with n≥2</span>'
      + '</div>'
      + '<div class="hm-summary">★ Best: <span style="color:var(--green)">' + bestStr + '</span>'
      + ' &nbsp;·&nbsp; ☠ Worst: <span style="color:var(--red)">' + worstStr + '</span></div>'
    );
    wrap.innerHTML = cells.join('');
  }catch(e){
    console.error('hour-day-heatmap', e);
    wrap.innerHTML = '<div class="empty">Failed to load heatmap</div>';
  }
}

// ── C5 TOKEN WR HORIZONTAL BAR WITH WILSON CI (2026-05-22) ────────────────────
function renderTokenWrChart(toks){
  const el = document.getElementById('tokenWrChart');
  if(!el) return;
  const eligible = (toks||[]).filter(t => (t.closed || 0) >= 1);
  if(!eligible.length){
    el.innerHTML = '<div class="empty">No closed signals yet</div>';
    return;
  }
  // Sort by WR descending; tokens with more closed signals tie-break higher
  eligible.sort((a, b) => (b.wr - a.wr) || (b.closed - a.closed));
  el.innerHTML = eligible.map(t => {
    const wr = t.wr || 0;
    const lo = (t.wr_lo != null) ? t.wr_lo : 0;
    const hi = (t.wr_hi != null) ? t.wr_hi : 100;
    const cls = wr >= 65 ? 'g' : wr >= 45 ? 'y' : 'r';
    const wrCls = wr >= 60 ? ' g' : wr < 40 ? ' r' : '';
    const ciWidth = Math.max(0, hi - lo);
    const ciTitle = 'Wilson 95% CI: ' + lo.toFixed(1) + '% – ' + hi.toFixed(1) + '%';
    return '<div class="tok-wr-row">'
      + '<div class="tok-wr-label">' + t.token + '</div>'
      + '<div class="tok-wr-track" title="' + ciTitle + '">'
      +   '<div class="tok-wr-fill ' + cls + '" style="width:' + wr + '%"></div>'
      +   '<div class="tok-wr-ci" style="left:' + lo + '%;width:' + ciWidth + '%"></div>'
      +   '<div class="tok-wr-50"></div>'
      + '</div>'
      + '<div class="tok-wr-stats">'
      +   '<div><span class="wr-pct' + wrCls + '">' + wr + '%</span></div>'
      +   '<div>n=' + (t.closed || 0) + ' [' + lo.toFixed(0) + '-' + hi.toFixed(0) + '%]</div>'
      + '</div>'
      + '</div>';
  }).join('');
}

// ── C4 STACKED CONFIDENCE BARS (2026-05-22 tracker audit) ─────────────────────
function renderConfStackedBar(levels, bestConf){
  const el = document.getElementById('confBreakdown');
  if(!el) return;
  if(!levels.length){
    el.innerHTML = '<div class="empty">No closed signals yet</div>';
    return;
  }
  const bestLvl = bestConf ? bestConf.level : null;
  // Find max total per level for proportional bar width
  const maxClosed = Math.max(1, ...levels.map(l => l.closed || 0));
  el.innerHTML = levels.map(l => {
    const w = l.wins||0, p = l.partial||0, lo = l.losses||0, e = l.expired||0;
    const total = w + p + lo + e;
    if(total === 0){
      return '<div class="conf-stack-row">'
        +'<div class="conf-stack-label'+(l.level===bestLvl?' best':'')+'">Conf '+l.level+'</div>'
        +'<div class="conf-stack-bar" title="no closed signals"></div>'
        +'<div class="conf-stack-meta"><span class="wr-pct">—</span>'
        +'<span>0 closed / '+(l.count||0)+' fired</span></div>'
        +'</div>';
    }
    // Bar fills proportionally to its closed-count vs the largest level.
    const rowWidthPct = (l.closed / maxClosed) * 100;
    const segs = [
      {cls:'win', n:w,  lbl:'WIN'},
      {cls:'par', n:p,  lbl:'PARTIAL'},
      {cls:'los', n:lo, lbl:'LOSS'},
      {cls:'exp', n:e,  lbl:'EXPIRED'},
    ];
    const segsHtml = segs.filter(s => s.n > 0).map(s => {
      const pctOfTotal = (s.n / total) * 100;
      return '<div class="conf-stack-seg '+s.cls+'" '
        +'style="width:'+pctOfTotal+'%" '
        +'title="'+s.lbl+': '+s.n+' ('+pctOfTotal.toFixed(0)+'%)"></div>';
    }).join('');
    const wrClass = l.wr >= 60 ? ' g' : l.wr < 40 ? ' r' : '';
    return '<div class="conf-stack-row">'
      +'<div class="conf-stack-label'+(l.level===bestLvl?' best':'')+'">Conf '+l.level
        +(l.level===bestLvl?' ★':'')+'</div>'
      +'<div class="conf-stack-bar" style="width:'+rowWidthPct+'%">'+segsHtml+'</div>'
      +'<div class="conf-stack-meta">'
      +  '<span class="wr-pct'+wrClass+'">'+l.wr+'% WR</span>'
      +  '<span>'+l.closed+' closed / '+(l.count||0)+' fired</span>'
      +'</div>'
      +'</div>';
  }).join('');
}

// ── C1 EQUITY CURVE (2026-05-22 tracker audit) ────────────────────────────────
let _equityChart = null;
let _equityRangeDays = 30;
function setEquityRange(days, btn){
  _equityRangeDays = days;
  document.querySelectorAll('.eq-range').forEach(b => b.classList.remove('active'));
  if(btn) btn.classList.add('active');
  loadEquityCurve();
}
async function loadEquityCurve(){
  const wrap = document.getElementById('equityCurveWrap');
  const sub  = document.getElementById('equitySummary');
  if(!wrap) return;
  try{
    const r = await fetch('/api/equity-curve?days='+_equityRangeDays);
    const d = await r.json();
    if(!d.ok || !Array.isArray(d.points) || d.points.length === 0){
      wrap.style.display = 'none';
      return;
    }
    wrap.style.display = 'block';
    const labels = d.points.map(p => p.ts.substring(5, 16));   // MM-DD HH:MM
    const data   = d.points.map(p => p.cum_pnl);
    const s = d.summary || {};
    const finalSign = (s.final||0) >= 0 ? '+' : '';
    const ddSign    = (s.max_dd||0) <= 0 ? '' : '+';
    sub.innerHTML =
      '<span style="color:'+((s.final||0)>=0?'var(--green)':'var(--red)')+'">'
      + finalSign + (s.final||0).toFixed(2) + '%</span>'
      + ' &nbsp;·&nbsp; n=' + (s.n||0)
      + ' &nbsp;·&nbsp; peak ' + ((s.peak||0)>=0?'+':'') + (s.peak||0).toFixed(2) + '%'
      + ' &nbsp;·&nbsp; max DD <span style="color:var(--red)">' + ddSign + (s.max_dd||0).toFixed(2) + '%</span>';

    const ctx = document.getElementById('equityChart').getContext('2d');
    const lineColor = (s.final||0) >= 0 ? '#22c55e' : '#ef4444';
    if(_equityChart){
      _equityChart.data.labels = labels;
      _equityChart.data.datasets[0].data = data;
      _equityChart.data.datasets[0].borderColor = lineColor;
      _equityChart.data.datasets[0].backgroundColor = lineColor + '22';
      _equityChart.update('none');
      return;
    }
    _equityChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Cumulative P&L %',
          data: data,
          borderColor: lineColor,
          backgroundColor: lineColor + '22',
          borderWidth: 2,
          fill: true,
          tension: 0.18,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: lineColor,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {mode: 'index', intersect: false},
        plugins: {
          legend: {display: false},
          tooltip: {
            backgroundColor: 'rgba(18,18,29,0.96)',
            borderColor: '#252538',
            borderWidth: 1,
            titleColor: '#f1f5f9',
            bodyColor: '#f1f5f9',
            padding: 10,
            callbacks: {
              label: (ctx) => {
                const v = ctx.parsed.y;
                return 'Cum P&L: ' + (v>=0?'+':'') + v.toFixed(2) + '%';
              }
            }
          }
        },
        scales: {
          x: {
            grid: {color: 'rgba(37,37,56,0.4)'},
            ticks: {color: '#94a3b8', maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: {size: 10}}
          },
          y: {
            grid: {color: 'rgba(37,37,56,0.4)'},
            ticks: {color: '#94a3b8', font: {size: 10},
                    callback: (v) => (v>=0?'+':'') + v.toFixed(1) + '%'},
            beginAtZero: false,
          }
        }
      }
    });
  }catch(e){
    console.error('equity-curve', e);
    wrap.style.display = 'none';
  }
}

async function loadStats(){
  try{
    const r=await fetch('/api/stats');
    if(!r.ok) throw new Error('stats '+r.status);
    const s=await r.json();
    if(!s.db_ok) showErr('Database error — check terminal for details');
    document.getElementById('s-total').textContent=s.total||'0';
    document.getElementById('s-wr').textContent=(s.win_rate||0)+'%';
    document.getElementById('s-wins').textContent=s.wins||'0';
    document.getElementById('s-losses').textContent=s.losses||'0';
    document.getElementById('s-open').textContent=s.opens||'0';
    document.getElementById('s-rr').textContent='1:'+(s.avg_rr||'—');
    document.getElementById('s-best').textContent=s.best_trade?'+'+s.best_trade+'%':'—';
  }catch(e){showErr('Failed to load stats: '+e.message)}
}

function trendClass(t){
  if(!t) return 'neutral';
  const l=t.toLowerCase();
  if(l==='strong_bull') return 'strong-bull';
  if(l==='bull') return 'bull';
  if(l==='strong_bear') return 'strong-bear';
  if(l==='bear') return 'bear';
  return 'neutral';
}

function _expiryLabel(expiresAt){
  if(!expiresAt) return '<span style="color:var(--muted);font-size:.75rem">No expiry</span>';
  const exp=new Date(expiresAt.replace(' ','T')+'Z');
  const now=new Date();
  const diffMs=exp-now;
  if(diffMs<=0) return '<span style="color:var(--red);font-size:.75rem">EXPIRED</span>';
  const h=Math.floor(diffMs/3600000);
  const m=Math.floor((diffMs%3600000)/60000);
  const col=h<2?'var(--red)':h<6?'var(--yellow)':'var(--muted)';
  return '<span style="color:'+col+';font-size:.75rem">Exp: '+h+'h '+m+'m</span>';
}

function _openCardHtml(r){
  const sig=r.signal.toLowerCase();
  const profit=r.profit_pct>0
    ?'<span class="pnl-p">+'+Number(r.profit_pct).toFixed(2)+'%</span>'
    :r.profit_pct<0
    ?'<span class="pnl-n">'+Number(r.profit_pct).toFixed(2)+'%</span>'
    :'<span style="color:var(--muted)">—</span>';

  return '<div class="card '+sig+'">'
    +'<div class="sig-badge '+sig+'">'+r.signal+'</div>'
    +'<div class="card-info">'
    +'<div class="card-token" style="display:flex;align-items:center;gap:.5rem">'
    +r.token+' <small style="color:var(--muted);font-size:.75rem;font-weight:500">#'+r.id+'</small>'
    +'<button class="close-card-btn" data-sig-id="'+r.id+'" onclick="openCloseModalById(this.dataset.sigId)">&#10005; Close</button>'
    +'</div>'
    +'<div class="card-sub">Entry: <span style="font-family:JetBrains Mono,monospace;color:var(--text)">$'+Number(r.entry_price).toFixed(4)+'</span>'
    +' &nbsp;|&nbsp; RSI: <strong style="color:var(--text)">'+(r.rsi||'—')+'</strong>'
    +' &nbsp;|&nbsp; MTF: <strong style="color:var(--text)">'+(r.mtf_bias||'—')+' '+(r.mtf_conf||0)+'%</strong></div>'
    +'<div class="card-sub">4H: <strong style="color:var(--text)">'+(r.trend_4h||'—')+'</strong>'
    +' &rarr; 1H: <strong style="color:var(--text)">'+(r.trend_1h||'—')+'</strong>'
    +' &rarr; 5M: <strong style="color:var(--text)">'+(r.trend_5m||'—')+'</strong>'
    +' &nbsp;|&nbsp; '+_expiryLabel(r.expires_at)+'</div>'
    +'<div class="card-sub" style="font-size:.76rem">'
    +'Sweep: <strong style="color:var(--text)">'+(r.sweep_type||'—')+'</strong>'
    +' &nbsp;|&nbsp; MSS: <strong style="color:var(--text)">'+(r.mss_quality||'—')+'</strong>'
    +' &nbsp;|&nbsp; FVG: <strong style="color:var(--text)">'+(r.fvg_quality||'—')+'</strong>'
    +' &nbsp;|&nbsp; DR: <strong style="color:var(--text)">'+(r.dr_location||'—')+'</strong>'
    +' &nbsp;|&nbsp; EV: <strong style="color:var(--text)">'+(r.ev_status||'—')+'</strong>'+(r.ev_score!=null?' ('+Number(r.ev_score).toFixed(1)+'%)':'')+'</div>'
    +'<div class="dots">'
    +'<div class="dot-tp'+(r.tp1_hit?' hit':'')+'" title="TP1"></div>'
    +'<div class="dot-tp'+(r.tp2_hit?' hit':'')+'" title="TP2"></div>'
    +'<div class="dot-tp'+(r.tp3_hit?' hit':'')+'" title="TP3"></div>'
    +'<div style="width:8px"></div>'
    +'<div class="dot-sl'+(r.sl_hit?' hit':'')+'" title="SL"></div>'
    +'</div>'
    +'</div>'
    +'<div class="card-levels">'
    +'<div class="lrow"><span class="llbl" style="color:var(--muted)">TP3</span>'
    +'<span class="lval'+(r.tp3_hit?' lhit':'')+'">$'+Number(r.tp3).toFixed(4)+'</span>'
    +'<small style="color:var(--muted)">+'+Number(r.tp3_pct||0).toFixed(1)+'%</small></div>'
    +'<div class="lrow"><span class="llbl" style="color:var(--muted)">TP2</span>'
    +'<span class="lval'+(r.tp2_hit?' lhit':'')+'">$'+Number(r.tp2).toFixed(4)+'</span>'
    +'<small style="color:var(--muted)">+'+Number(r.tp2_pct||0).toFixed(1)+'%</small></div>'
    +'<div class="lrow"><span class="llbl" style="color:var(--muted)">TP1</span>'
    +'<span class="lval'+(r.tp1_hit?' lhit':'')+'">$'+Number(r.tp1).toFixed(4)+'</span>'
    +'<small style="color:var(--muted)">+'+Number(r.tp1_pct||0).toFixed(1)+'%</small></div>'
    +'<div class="lrow"><span class="llbl" style="color:var(--red)">SL</span>'
    +'<span class="lval">$'+Number(r.sl).toFixed(4)+'</span>'
    +'<small style="color:var(--muted)">'+Number(r.sl_pct||0).toFixed(1)+'%</small></div>'
    +'<div class="lrow" style="margin-top:.3rem">'+profit+'</div>'
    +'</div>'
    +'</div>';
}

function renderOpenPage(){
  const el=document.getElementById('openList');
  const pgBar=document.getElementById('openPgBar');
  if(!allOpen.length){
    el.innerHTML='<div class="empty">No open positions</div>';
    pgBar.style.display='none'; return;
  }
  const totalPages=Math.max(1,Math.ceil(allOpen.length/OPEN_PAGE_SIZE));
  openPage=Math.max(1,Math.min(openPage,totalPages));
  const start=(openPage-1)*OPEN_PAGE_SIZE;
  const slice=allOpen.slice(start,start+OPEN_PAGE_SIZE);
  el.innerHTML=slice.map(_openCardHtml).join('');
  if(totalPages>1){
    pgBar.style.display='flex';
    document.getElementById('openPrevBtn').disabled=(openPage===1);
    document.getElementById('openNextBtn').disabled=(openPage===totalPages);
    document.getElementById('openPgInfo').textContent=
      'Page '+openPage+' of '+totalPages+' ('+allOpen.length+' positions)';
  } else { pgBar.style.display='none'; }
}

function openChangePage(delta){
  openPage+=delta; renderOpenPage();
  document.getElementById('panelOpen').scrollTop=0;
}

async function loadOpen(){
  try{
    const r=await fetch('/api/open');
    if(!r.ok) throw new Error('open '+r.status);
    allOpen=await r.json();
    document.getElementById('openCount').textContent=allOpen.length;
    renderOpenPage();
  }catch(e){showErr('Failed to load open positions: '+e.message)}
}

async function loadHistory(){
  try{
    const r=await fetch('/api/signals');
    if(!r.ok) throw new Error('signals '+r.status);
    allSigs=await r.json();
    document.getElementById('histCount').textContent=allSigs.length;
    // build token filter pills from data
    const tokens=[...new Set(allSigs.map(s=>s.token))].sort();
    const bar=document.getElementById('tokFilterBar');
    bar.innerHTML='<button class="tok-pill'+(curToken==='ALL'?' active':'')+'" data-tok="ALL" onclick="setTokenFilter(this.dataset.tok,this)">All Tokens</button>'
      +tokens.map(t=>'<button class="tok-pill'+(curToken===t?' active':'')+'" data-tok="'+t+'" onclick="setTokenFilter(this.dataset.tok,this)">'+t+'</button>').join('');
    renderTable();
  }catch(e){showErr('Failed to load signal history: '+e.message)}
}

function setFilter(f,btn){
  curFilter=f; histPage=1;
  document.querySelectorAll('.ftab').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  renderTable();
}

function setTokenFilter(tok,btn){
  curToken=tok; histPage=1;
  document.querySelectorAll('.tok-pill').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  renderTable();
}

function histSetSort(col){
  if(histSort.col===col) histSort.dir=histSort.dir==='asc'?'desc':'asc';
  else { histSort.col=col; histSort.dir='desc'; }
  document.querySelectorAll('.sort-ico').forEach(el=>{el.textContent='';el.classList.remove('on');});
  const ico=document.getElementById('sh-'+col);
  if(ico){ ico.textContent=histSort.dir==='desc'?'▼':'▲'; ico.classList.add('on'); }
  histPage=1; renderTable();
}

function histChangePage(delta){
  histPage+=delta; renderTable();
  document.getElementById('panelHistory').scrollTop=0;
}

function toggleAutoRefresh(btn){
  if(_autoRefresh){
    clearInterval(_autoRefresh); _autoRefresh=null;
    btn.textContent='Auto Off'; btn.classList.remove('ar-on');
  } else {
    _autoRefresh=setInterval(()=>{loadOpen();loadStats();},30000);
    btn.textContent='Auto On'; btn.classList.add('ar-on');
  }
}

function renderTable(){
  let rows=allSigs;
  // token filter
  if(curToken!=='ALL') rows=rows.filter(r=>r.token===curToken);
  // result filter
  if(curFilter==='OPEN') rows=rows.filter(r=>r.status==='OPEN');
  else if(curFilter==='EXPIRED') rows=rows.filter(r=>(r.outcome||'OPEN')==='EXPIRED');
  else if(curFilter!=='ALL') rows=rows.filter(r=>(r.outcome||'OPEN')===curFilter);
  // sort
  const col=histSort.col, dir=histSort.dir;
  rows=[...rows].sort((a,b)=>{
    let va=a[col]??'', vb=b[col]??'';
    if(typeof va==='string'){va=va.toLowerCase();vb=vb.toLowerCase();}
    if(va<vb) return dir==='asc'?-1:1;
    if(va>vb) return dir==='asc'?1:-1;
    return 0;
  });
  const total=rows.length;
  const totalPages=Math.max(1,Math.ceil(total/HIST_PAGE_SIZE));
  histPage=Math.max(1,Math.min(histPage,totalPages));
  const start=(histPage-1)*HIST_PAGE_SIZE;
  const pageRows=rows.slice(start,start+HIST_PAGE_SIZE);

  const body=document.getElementById('histBody');
  const pgBar=document.getElementById('histPgBar');
  if(!total){
    body.innerHTML='<tr><td colspan="21" class="empty">'
      +(allSigs.length===0
        ?'No signals yet — bot will save signals here once running'
        :'No signals matching this filter')
      +'</td></tr>';
    pgBar.style.display='none'; return;
  }
  body.innerHTML=pageRows.map(r=>{
    const out=r.outcome||'OPEN';
    const pnl=r.profit_pct!=null?Number(r.profit_pct):0;
    const pnlHtml=pnl>0?'<span class="pnl-p">+'+pnl.toFixed(2)+'%</span>'
      :pnl<0?'<span class="pnl-n">'+pnl.toFixed(2)+'%</span>':'<span style="color:var(--muted)">—</span>';
    const conf=r.confidence||0;
    const segs=Array.from({length:5},(_,i)=>
      '<div class="cseg'+(i<Math.round(conf/2)?' on':'')+'"></div>').join('');
    const sigC=r.signal==='BUY'?'var(--green)':'var(--red)';
    const ts=r.timestamp?r.timestamp.slice(0,16):'—';
    const t4h=r.trend_4h||'—'; const t1h=r.trend_1h||'—'; const t5m=r.trend_5m||'—';
    return '<tr>'
      +'<td style="color:var(--muted);font-size:.75rem">'+r.id+'</td>'
      +'<td class="tok">'+r.token+'</td>'
      +'<td><span style="color:'+sigC+';font-weight:700;font-size:.82rem">'+r.signal+'</span></td>'
      +'<td class="mono">$'+Number(r.entry_price||0).toFixed(4)+'</td>'
      +'<td class="mono" style="color:var(--red)">$'+Number(r.sl||0).toFixed(4)+'</td>'
      +'<td class="mono" style="color:'+(r.tp1_hit?'var(--green)':'var(--text)')+'">$'+Number(r.tp1||0).toFixed(4)+'</td>'
      +'<td class="mono" style="color:'+(r.tp2_hit?'var(--green)':'var(--text)')+'">$'+Number(r.tp2||0).toFixed(4)+'</td>'
      +'<td class="mono" style="color:'+(r.tp3_hit?'var(--green)':'var(--text)')+'">$'+Number(r.tp3||0).toFixed(4)+'</td>'
      +'<td class="mono">1:'+(r.rr1||'—')+'</td>'
      +'<td><div class="conf-bar">'+segs+'</div> <span style="font-size:.78rem">'+conf+'</span></td>'
      +'<td><span class="mtf '+(r.mtf_bias||'NEUTRAL')+'">'+(r.mtf_bias||'—')+'</span></td>'
      +'<td class="mono">'+(r.rsi?Number(r.rsi).toFixed(1):'—')+'</td>'
      +'<td><span class="trend '+trendClass(t4h)+'">'+t4h+'</span></td>'
      +'<td><span class="trend '+trendClass(t1h)+'">'+t1h+'</span></td>'
      +'<td><span class="trend '+trendClass(t5m)+'">'+t5m+'</span></td>'
      +'<td style="font-size:.72rem;color:var(--muted)">'+(r.session||'—').replace('_KZ','')+'</td>'
      +'<td style="font-size:.72rem;color:var(--muted)">'+(r.sweep_type||'—')+'</td>'
      +'<td style="font-size:.72rem;color:'+(r.ev_status==='POSITIVE'?'var(--green)':r.ev_status==='NEGATIVE'?'var(--red)':r.ev_status?'var(--yellow)':'var(--muted)')+'">'+(r.ev_status||'—')+(r.ev_score!=null?' '+Number(r.ev_score).toFixed(0)+'%':'')+'</td>'
      +'<td><span class="out '+out+'">'+out+'</span></td>'
      +'<td>'+pnlHtml+'</td>'
      +'<td style="color:var(--muted);white-space:nowrap;font-size:.78rem">'+ts+'</td>'
      +'</tr>';
  }).join('');
  // pagination bar
  pgBar.style.display='flex';
  document.getElementById('histPrevBtn').disabled=(histPage===1);
  document.getElementById('histNextBtn').disabled=(histPage===totalPages);
  document.getElementById('histPgInfo').textContent=
    'Showing '+(start+1)+'–'+Math.min(start+HIST_PAGE_SIZE,total)+' of '+total+' signals';
}

async function loadIntelligence(){
  try{
    const r=await fetch('/api/intelligence');
    if(!r.ok) throw new Error('intelligence '+r.status);
    const d=await r.json();
    if(!d.ok) throw new Error('DB error in intelligence');

    // Bot Health Score — when no signals have closed yet, render an awaiting
    // state instead of the misleading 10/Weak that the formula produces from
    // default sel_score=10 on empty data.
    const score=d.bot_score||0;
    const totalClosed=d.total_closed||0;
    const statusEl=document.getElementById('botScoreStatus');
    if(totalClosed===0){
      document.getElementById('botScoreNum').textContent='—';
      document.getElementById('botBarFill').style.width='0%';
      statusEl.textContent='Awaiting first closed signal';
      statusEl.className='bot-score-status status-awaiting';
    } else {
      document.getElementById('botScoreNum').textContent=score;
      document.getElementById('botBarFill').style.width=score+'%';
      if(score>=70){statusEl.textContent='Excellent';statusEl.className='bot-score-status status-excellent';}
      else if(score>=45){statusEl.textContent='Average';statusEl.className='bot-score-status status-average';}
      else{statusEl.textContent='Weak';statusEl.className='bot-score-status status-weak';}
    }
    const bp=d.bot_parts||{};
    document.getElementById('bpWr').textContent=totalClosed===0?'—':(bp.wr||0);
    document.getElementById('bpRr').textContent=totalClosed===0?'—':(bp.rr||0);
    document.getElementById('bpHc').textContent=totalClosed===0?'—':(bp.hc||0);
    document.getElementById('bpSel').textContent=totalClosed===0?'—':(bp.sel||0);

    // ── Adaptive Gate Status Cards ──
    const confFloorEl = document.getElementById('iaConfFloor');
    if(confFloorEl) confFloorEl.textContent = d.conf_floor != null ? d.conf_floor : '—';

    const rfVal = d.ranging_floor_raise || 0;
    const rfEl  = document.getElementById('iaRangingFloor');
    const rfSub = document.getElementById('iaRangingFloorSub');
    if(rfEl){
      rfEl.textContent  = rfVal > 0 ? '+'+rfVal : '0';
      rfEl.className    = 'icard-val ' + (rfVal > 0 ? 'r' : '');
    }
    if(rfSub){
      const adjV = d.threshold_adj || 0;
      rfSub.textContent = rfVal > 0
        ? 'conf floor raised in RANGING/UNKNOWN (adj='+adjV+')'
        : adjV > 0
        ? 'adj='+adjV+' active — needs ≥3 for floor raise'
        : 'threshold at baseline';
    }

    const toks_arr = d.tokens || [];
    const gatedCount = toks_arr.filter(t => t.recent_wr != null && t.recent_wr < 0.35).length;
    const gatedEl  = document.getElementById('iaTokensGated');
    const gatedSub = document.getElementById('iaTokensGatedSub');
    if(gatedEl){
      gatedEl.textContent = gatedCount + ' / ' + toks_arr.length;
      gatedEl.className   = 'icard-val ' + (gatedCount > 0 ? 'r' : 'g');
    }
    if(gatedSub){
      gatedSub.textContent = gatedCount > 0
        ? gatedCount + ' token(s) with conf floor raised'
        : 'all tokens within normal range';
    }

    const ogdActive = toks_arr.filter(t => t.blend_pct > 0).length;
    const ogdEl  = document.getElementById('iaOgdActive');
    const ogdSub = document.getElementById('iaOgdActiveSub');
    if(ogdEl){
      ogdEl.textContent = ogdActive + ' / ' + toks_arr.length;
      ogdEl.className   = 'icard-val ' + (ogdActive > 0 ? 'g' : '');
    }
    if(ogdSub){
      ogdSub.textContent = ogdActive > 0
        ? 'OGD weights blended into scoring'
        : 'accumulating — need 30 closed trades/token';
    }

    // Confidence analytics cards
    document.getElementById('iaAvgConf').textContent=d.avg_conf||'—';
    document.getElementById('iaHiWr').textContent=(d.hi_total>0)?d.hi_wr+'%':'—';
    document.getElementById('iaHiSub').textContent=(d.hi_total>0)?'from '+d.hi_total+' closed (conf 7-10)':'no data yet';
    document.getElementById('iaLoWr').textContent=(d.lo_total>0)?d.lo_wr+'%':'—';
    document.getElementById('iaLoSub').textContent=(d.lo_total>0)?'from '+d.lo_total+' closed (conf 1-4)':'no data yet';
    if(d.best_conf){
      document.getElementById('iaBestConf').textContent='Level '+d.best_conf.level;
      document.getElementById('iaBestSub').textContent=d.best_conf.wr+'% WR ('+d.best_conf.closed+' closed)';
    } else {
      document.getElementById('iaBestConf').textContent='—';
      document.getElementById('iaBestSub').textContent='min 2 closed trades';
    }

    // C4 (2026-05-22 tracker audit): Confidence level breakdown as stacked
    // horizontal bar (WIN / PARTIAL / LOSS / EXPIRED per level).
    renderConfStackedBar(d.conf_levels || [], d.best_conf);

    // Token performance — C5 chart on top + existing detail table below
    const toks=d.tokens||[];
    renderTokenWrChart(toks);
    const tb=document.getElementById('tokPerfBody');
    if(!toks.length){
      tb.innerHTML='<tr><td colspan="7" class="empty">No signal data yet</td></tr>';
    } else {
      tb.innerHTML=toks.map(t=>{
        const wrBarColor=t.wr>=65?'var(--green)':t.wr>=45?'var(--yellow)':'var(--red)';
        const wrHtml='<div class="wr-bar-wrap">'
          +'<div class="wr-mini-bar"><div class="wr-mini-fill" style="width:'+t.wr+'%;background:'+wrBarColor+'"></div></div>'
          +'<span class="mono" style="font-size:.78rem">'+t.wr+'%</span></div>';
        let ratingClass='nodata', ratingTxt='No Data';
        if(t.closed>=2){
          if(t.wr>=65){ratingClass='strong';ratingTxt='Strong';}
          else if(t.wr>=45){ratingClass='average';ratingTxt='Average';}
          else{ratingClass='weak';ratingTxt='Weak';}
        }
        // Fix 1 & Fix 3: Adaptive column — OGD blend and per-token WR gate
        let adaptHtml = '';
        const wr30 = t.recent_wr;
        const blend = t.blend_pct || 0;
        if(wr30 != null && wr30 < 0.35){
          const floorExtra = wr30 < 0.25 ? 2 : 1;
          const gColor = wr30 < 0.25 ? 'var(--red)' : 'var(--accent2)';
          adaptHtml += '<div style="font-size:.7rem;color:'+gColor+';font-weight:600">&#128683; floor +'+floorExtra+'</div>';
        }
        if(blend > 0){
          adaptHtml += '<div style="font-size:.7rem;color:var(--green)">&#9889; OGD '+blend+'%</div>';
        } else if(t.ogd_n > 0){
          adaptHtml += '<div style="font-size:.7rem;color:var(--muted)">&#9203; '+t.ogd_n+'/30</div>';
        } else {
          adaptHtml += '<div style="font-size:.7rem;color:var(--muted)">—</div>';
        }
        return '<tr>'
          +'<td class="tok">'+t.token+'</td>'
          +'<td class="mono">'+t.signals+'</td>'
          +'<td class="mono"><span style="color:var(--green)">'+t.wins+'</span>'
          +' / <span style="color:var(--red)">'+t.losses+'</span></td>'
          +'<td>'+wrHtml+'</td>'
          +'<td class="mono">'+(t.avg_conf||'—')+'</td>'
          +'<td class="mono">'+(t.avg_rr?'1:'+t.avg_rr:'—')+'</td>'
          +'<td><span class="tok-rating '+ratingClass+'">'+ratingTxt+'</span></td>'
          +'<td>'+adaptHtml+'</td>'
          +'</tr>';
      }).join('');
    }
  }catch(e){
    console.error('intelligence',e);
    const el=document.getElementById('intelError');
    if(el){el.textContent='Failed to load intelligence: '+e.message;el.style.display='block';}
  }
}

// ── BACKTEST ───────────────────────────────────────────────
let _btPollTimer = null;

async function runBacktest(){
  const btn=document.getElementById('btRunBtn');
  btn.disabled=true;
  try{
    const r=await fetch('/api/backtest/run',{method:'POST'});
    const d=await r.json();
    if(!d.ok){showErr('Backtest error: '+(d.error||'unknown'));btn.disabled=false;return;}
    _startBtPoll();
  }catch(e){showErr('Cannot start backtest: '+e.message);btn.disabled=false;}
}

function _startBtPoll(){
  if(_btPollTimer) clearInterval(_btPollTimer);
  _btPollTimer=setInterval(_pollBtStatus,2500);
  _pollBtStatus();
}

async function _pollBtStatus(){
  try{
    const r=await fetch('/api/backtest/status');
    const d=await r.json();
    const dot=document.getElementById('btDot');
    const txt=document.getElementById('btStatusTxt');
    const fill=document.getElementById('btProgressFill');
    const msg=document.getElementById('btProgressMsg');
    const btn=document.getElementById('btRunBtn');
    fill.style.width=(d.progress||0)+'%';
    msg.textContent=d.message||'';
    const errPanel=document.getElementById('btErrorLog');
    const errTxt=document.getElementById('btErrorLogTxt');
    if(d.status==='RUNNING'){
      dot.className='bt-dot running'; txt.textContent='Running...'; btn.disabled=true;
      errPanel.style.display='none';
    } else if(d.status==='DONE'){
      dot.className='bt-dot done'; txt.textContent='Done'; btn.disabled=false;
      errPanel.style.display='none';
      clearInterval(_btPollTimer); _btPollTimer=null;
      await loadBacktest();
    } else if(d.status==='FAILED'){
      dot.className='bt-dot failed'; txt.textContent='Failed'; btn.disabled=false;
      clearInterval(_btPollTimer); _btPollTimer=null;
      if(d.error_log){
        errTxt.textContent=d.error_log;
        errPanel.style.display='block';
      }
    } else {
      dot.className='bt-dot idle'; txt.textContent='Idle'; btn.disabled=false;
      errPanel.style.display='none';
    }
  }catch(e){console.error('bt poll',e);}
}

async function loadBacktest(){
  try{
    const [rr, rh]=await Promise.all([
      fetch('/api/backtest/results').then(r=>r.json()),
      fetch('/api/backtest/history').then(r=>r.json())
    ]);
    // C6 (2026-05-22 tracker audit): rolling walk-forward chart — fire and forget,
    // it has its own error handling and renders independently.
    loadRollingWf();

    // History section
    const histSec=document.getElementById('btHistSec');
    const histList=document.getElementById('btHistList');
    const runs=(rh.runs||[]);
    document.getElementById('btRunCount').textContent=runs.length||'0';
    if(runs.length){
      histSec.style.display='block';
      _btHistData = runs;
      btHistPage = 1;
      _renderBtHistory();
    }

    if(!rr.ok){
      document.getElementById('btEmpty').style.display='block';
      document.getElementById('btResults').style.display='none';
      return;
    }

    document.getElementById('btEmpty').style.display='none';
    document.getElementById('btResults').style.display='block';
    document.getElementById('btTuneBtn').style.display='inline-block';

    // Meta bar
    const wr=rr.overall_wr||0;
    const wrC=wr>=65?'g':wr>=50?'a':'r';
    const cm=(rr.summary||{}).cost_model||null;
    const cmHtml=cm
      ?'<div class="bt-meta-item"><div class="bt-meta-label">Cost Model</div>'
        +'<div class="bt-meta-val" style="font-size:.78rem;color:var(--muted);line-height:1.5">'
        +cm.slippage_pct+'% slip<br>'+(cm.rt_total_pct)+'% RT fee</div></div>'
      :'<div class="bt-meta-item"><div class="bt-meta-label">Cost Model</div>'
        +'<div class="bt-meta-val" style="font-size:.75rem;color:var(--red)">None — WR<br>overstated</div></div>';
    const tfHtml=cm
      ?'<div class="bt-meta-item"><div class="bt-meta-label">Resolution</div>'
        +'<div class="bt-meta-val a" style="font-size:.95rem">'+cm.timeframe.toUpperCase()+'</div></div>'
      :'';
    document.getElementById('btMetaBar').innerHTML=
      '<div class="bt-meta-item"><div class="bt-meta-label">Run Date</div><div class="bt-meta-val" style="font-size:.95rem;color:var(--muted)">'+rr.run_date.slice(0,16)+'</div></div>'
      +'<div class="bt-meta-item"><div class="bt-meta-label">Period</div><div class="bt-meta-val a">'+rr.days+'d</div></div>'
      +tfHtml
      +'<div class="bt-meta-item"><div class="bt-meta-label">Total Signals</div><div class="bt-meta-val a">'+rr.total_signals+'</div></div>'
      +'<div class="bt-meta-item"><div class="bt-meta-label">Win Rate</div><div class="bt-meta-val '+wrC+'">'+wr+'%</div></div>'
      +'<div class="bt-meta-item"><div class="bt-meta-label">Avg R:R</div><div class="bt-meta-val g">1:'+rr.avg_rr+'</div></div>'
      +cmHtml;

    const sum=rr.summary||{};

    // Token table
    const toks=Object.entries(sum.by_token||{}).sort((a,b)=>b[1].wr-a[1].wr);
    const tokBody=document.getElementById('btTokenBody');
    tokBody.innerHTML=toks.length?toks.map(([tok,d])=>{
      const wc=d.wr>=65?'var(--green)':d.wr>=50?'var(--yellow)':'var(--red)';
      return '<tr><td class="tok">'+tok+'</td><td class="mono">'+d.signals+'</td>'
        +'<td class="mono" style="color:var(--green)">'+d.wins+'</td>'
        +'<td class="mono" style="color:var(--yellow)">'+d.partial+'</td>'
        +'<td class="mono" style="color:var(--red)">'+d.losses+'</td>'
        +'<td class="mono" style="color:var(--muted)">'+d.expired+'</td>'
        +'<td><div class="wr-bar-wrap"><div class="wr-mini-bar"><div class="wr-mini-fill" style="width:'+d.wr+'%;background:'+wc+'"></div></div>'
        +'<span class="mono" style="font-size:.78rem">'+d.wr+'%</span></div></td>'
        +'<td class="mono">1:'+d.avg_rr+'</td>'
        +'<td class="mono">'+d.avg_conf+'</td></tr>';
    }).join(''):'<tr><td colspan="9" class="empty">No data</td></tr>';

    // Regime bars
    const regimes=Object.entries(sum.by_regime||{}).sort((a,b)=>b[1].wr-a[1].wr);
    document.getElementById('btRegimeList').innerHTML=regimes.length?regimes.map(([reg,d])=>{
      const c=d.wr>=65?'var(--green)':d.wr>=50?'var(--yellow)':'var(--red)';
      return '<div class="clrow"><div class="cl-label" style="width:140px;font-size:.72rem">'+reg+'</div>'
        +'<div class="cl-bar-wrap"><div class="cl-bar-fill" style="width:'+d.wr+'%;background:'+c+'"></div></div>'
        +'<div class="cl-stats">'+d.wr+'% WR</div>'
        +'<div class="cl-count">'+d.signals+' sigs</div></div>';
    }).join(''):'<div class="empty">No data</div>';

    // Confidence bars
    const confs=Object.entries(sum.by_conf||{}).sort((a,b)=>+a[0]-+b[0]);
    document.getElementById('btConfList').innerHTML=confs.length?confs.map(([c,d])=>{
      const col=d.wr>=65?'var(--green)':d.wr>=50?'var(--yellow)':'var(--red)';
      return '<div class="clrow"><div class="cl-label">Conf '+c+'</div>'
        +'<div class="cl-bar-wrap"><div class="cl-bar-fill" style="width:'+d.wr+'%;background:'+col+'"></div></div>'
        +'<div class="cl-stats">'+d.wr+'% WR</div>'
        +'<div class="cl-count">'+d.signals+' sigs</div></div>';
    }).join(''):'<div class="empty">No data</div>';

    // BUY vs SELL
    const dirs=Object.entries(sum.by_dir||{});
    document.getElementById('btDirList').innerHTML=dirs.length?dirs.map(([dir,d])=>{
      const c=dir==='BUY'?'var(--green)':'var(--red)';
      return '<div class="clrow"><div class="cl-label" style="color:'+c+'">'+dir+'</div>'
        +'<div class="cl-bar-wrap"><div class="cl-bar-fill" style="width:'+d.wr+'%;background:'+c+'"></div></div>'
        +'<div class="cl-stats">'+d.wr+'% WR</div>'
        +'<div class="cl-count">'+d.signals+' sigs</div></div>';
    }).join(''):'<div class="empty">No data</div>';

    // ICT Kill Zone Session breakdown
    const sessOrder=['ASIA_KZ','LONDON_KZ','NY_AM_KZ','OVERNIGHT'];
    const sessLabel={'ASIA_KZ':'Asia KZ (20-23 UTC)','LONDON_KZ':'London KZ (02-04 UTC)',
                     'NY_AM_KZ':'NY AM KZ (13-15 UTC)','OVERNIGHT':'Overnight (dead)'};
    const sessData=sum.by_session||{};
    const sessEntries=sessOrder.filter(k=>sessData[k]).map(k=>[k,sessData[k]]);
    document.getElementById('btSessionList').innerHTML=sessEntries.length?sessEntries.map(([sess,d])=>{
      const c=d.wr>=65?'var(--green)':d.wr>=50?'var(--yellow)':'var(--red)';
      const lbl=sessLabel[sess]||sess;
      return '<div class="clrow"><div class="cl-label" style="width:180px;font-size:.72rem">'+lbl+'</div>'
        +'<div class="cl-bar-wrap"><div class="cl-bar-fill" style="width:'+d.wr+'%;background:'+c+'"></div></div>'
        +'<div class="cl-stats">'+d.wr+'% WR</div>'
        +'<div class="cl-count">'+d.signals+' sigs</div></div>';
    }).join(''):'<div class="empty">No session data yet — run backtest to populate</div>';

    // Recommendations
    const recs=rr.recommendations||[];
    const icons={WARNING:'⚠️',STRENGTH:'✅',INFO:'ℹ️'};
    document.getElementById('btRecsList').innerHTML=recs.length?recs.map(rec=>
      '<div class="rec-item '+rec.type+'">'
      +'<div class="rec-icon">'+icons[rec.type]+'</div>'
      +'<div class="rec-body">'
      +'<div><span class="rec-area '+rec.type+'">'+rec.area+'</span></div>'
      +'<div class="rec-title">'+rec.title+'</div>'
      +'<div class="rec-detail">'+rec.detail+'</div>'
      +'<div class="rec-action">&#8594; '+rec.action+'</div>'
      +'</div></div>'
    ).join(''):'<div class="empty">No recommendations generated</div>';

  }catch(e){console.error('loadBacktest',e);}
}

// ── TUNE ───────────────────────────────────────────────────
let _tuneData = null;

async function openTune(){
  const panel = document.getElementById('btTunePanel');
  if(panel.style.display !== 'none'){ closeTune(); return; }
  document.getElementById('tuneAdjList').innerHTML = '<div class="empty">Loading preview...</div>';
  document.getElementById('tuneApplyBtn').style.display = 'none';
  panel.style.display = 'block';
  panel.scrollIntoView({behavior:'smooth', block:'start'});
  try{
    const [r, rs] = await Promise.all([
      fetch('/api/backtest/tune-preview'),
      fetch('/api/tune/status').catch(() => null)
    ]);
    const d = await r.json();
    const gateData = rs ? await rs.json().catch(() => null) : null;
    if(!d.ok){ document.getElementById('tuneAdjList').innerHTML='<div class="tune-none">Error: '+(d.error||'unknown')+'</div>'; return; }
    _tuneData = d;
    renderTunePreview(d, gateData);
  }catch(e){ document.getElementById('tuneAdjList').innerHTML='<div class="tune-none">Failed: '+e.message+'</div>'; }
}

function closeTune(){
  document.getElementById('btTunePanel').style.display='none';
  _tuneData = null;
}

function renderTunePreview(d, gateData){
  const adjs  = d.adjustments    || [];
  const notes = d.validation_notes || [];
  const applyBtn = document.getElementById('tuneApplyBtn');

  // P3-5: Walk-forward gap warning banner
  const wfGap = d.walk_forward_gap;
  const wfWarnHtml = (wfGap != null && wfGap > 15)
    ? '<div style="background:rgba(234,179,8,.1);border:1px solid rgba(234,179,8,.35);border-radius:5px;'
      +'padding:.55rem .8rem;font-size:.78rem;color:#fbbf24;margin-bottom:.75rem">'
      +'&#9888; <strong>Walk-forward gap: '+d.train_wr+'% train vs '+d.test_wr+'% test (gap='+wfGap+'pp)</strong>'
      +' — possible overfitting. Treat adjustments below with extra caution.</div>'
    : '';

  // Always show validation notes (train/test split info, rejected changes)
  const notesHtml = notes.length
    ? '<div style="margin-bottom:.85rem;display:flex;flex-direction:column;gap:.4rem">'
      + notes.map(n =>
          '<div style="font-size:.76rem;color:var(--muted);background:rgba(148,163,184,.06);'
          +'border-left:2px solid var(--accent);padding:.35rem .65rem;border-radius:0 4px 4px 0">'
          +'&#128202; '+n+'</div>'
        ).join('')
      + '</div>'
    : '';

  // P3-4: Frequency gate indicator
  const gateEl = document.getElementById('tuneGateInfo');
  if(gateEl && gateData){
    const fg = gateData.frequency_gate || {};
    if(fg.passed === false){
      gateEl.style.display = 'block';
      const nd = fg.need_days || 0; const ns = fg.need_signals || 0;
      gateEl.innerHTML = '&#128274; Frequency gate: need '+(ns > 0 ? ns+' more signals' : '')+
        (nd > 0 && ns > 0 ? ' OR ' : '')+(nd > 0 ? nd+' more days' : '')+' since last tune';
    } else if(fg.note || fg.passed === true){
      gateEl.style.display = 'block';
      const nSig = fg.new_signals != null ? ' ('+fg.new_signals+' new signals, '+fg.days_since_apply+' days)' : '';
      gateEl.innerHTML = '&#9989; Frequency gate passed'+nSig;
    } else {
      gateEl.style.display = 'none';
    }
  }

  if(!adjs.length){
    document.getElementById('tuneAdjList').innerHTML =
      wfWarnHtml + notesHtml
      +'<div class="tune-none">&#10003; No adjustments needed — current settings already optimal for this backtest result ('+d.backtest_wr+'% WR)</div>';
    applyBtn.style.display='none'; return;
  }
  applyBtn.style.display='block';
  document.getElementById('tuneAdjList').innerHTML = wfWarnHtml + notesHtml + adjs.map(adj => {
    const isW = adj.param === 'WEIGHTS';
    const deltaHtml = adj.delta ? `<span class="tune-delta">${adj.delta}</span>` : '';
    const valsHtml = isW
      ? '<div class="tune-weight-changes">'+( adj.changes_desc||[]).map(s=>'<div class="tune-weight-row">'+s+'</div>').join('')+'</div>'
      : `<div class="tune-vals"><span class="tune-old">${adj.old_val}</span> &rarr; <span class="tune-new">${adj.new_val}</span></div>`;
    return `<div class="tune-item">
      <div class="tune-param">${adj.param} ${deltaHtml}</div>
      ${valsHtml}
      <div class="tune-reason">&#128202; ${adj.reason}</div>
    </div>`;
  }).join('');
}

function confirmTune(){
  if(!_tuneData || !_tuneData.adjustments || !_tuneData.adjustments.length) return;
  const overlay = document.getElementById('tuneConfirmOverlay');
  const adjs    = _tuneData.adjustments;
  // Build summary
  const summaryHtml = adjs.map(a =>
    '<div style="padding:.35rem .5rem;border-bottom:1px solid var(--border)">'
    +'<strong style="color:var(--fg)">' + a.param + '</strong>'
    +(a.delta ? ' <span style="color:var(--accent2)">'+a.delta+'</span>' : '')
    +'<div style="color:var(--muted);font-size:.76rem;margin-top:.2rem">' + a.reason + '</div>'
    +'</div>'
  ).join('');
  document.getElementById('tuneConfirmSummary').innerHTML = summaryHtml;
  // Walk-forward warning
  const wfWarnEl = document.getElementById('tuneConfirmWfWarn');
  const wfGap = _tuneData.walk_forward_gap;
  if(wfGap != null && wfGap > 15){
    wfWarnEl.style.display = 'block';
    wfWarnEl.innerHTML = '&#9888; Walk-forward gap ' + wfGap + 'pp — significant overfitting risk. Apply only if you accept the model may not generalise.';
  } else {
    wfWarnEl.style.display = 'none';
  }
  // OGD health note
  const ogdEl = document.getElementById('tuneConfirmOgdNote');
  if(ogdEl){
    ogdEl.style.display = 'block';
    ogdEl.innerHTML = '&#128295; OGD adaptive weights will be re-bootstrapped from the updated backtest configuration after apply. Any in-progress live learning will be overwritten.';
  }
  // Reset checkbox + button
  const chk = document.getElementById('tuneConfirmCheck');
  const applyBtn = document.getElementById('tuneConfirmApplyBtn');
  chk.checked = false;
  applyBtn.disabled = true; applyBtn.style.opacity = '.45'; applyBtn.style.cursor = 'not-allowed';
  chk.onchange = () => {
    applyBtn.disabled = !chk.checked;
    applyBtn.style.opacity = chk.checked ? '1' : '.45';
    applyBtn.style.cursor  = chk.checked ? 'pointer' : 'not-allowed';
  };
  overlay.style.display = 'flex';
}

function closeConfirm(){
  document.getElementById('tuneConfirmOverlay').style.display = 'none';
}

async function executeTuneApply(){
  if(!_tuneData || !_tuneData.adjustments || !_tuneData.adjustments.length) return;
  const applyBtn = document.getElementById('tuneConfirmApplyBtn');
  applyBtn.disabled = true; applyBtn.textContent = 'Applying...';
  closeConfirm();
  const footerBtn = document.getElementById('tuneApplyBtn');
  if(footerBtn){ footerBtn.disabled=true; footerBtn.textContent='Applying...'; }
  try{
    const r = await fetch('/api/backtest/tune-apply',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        adjustments: _tuneData.adjustments,
        train_wr:    _tuneData.train_wr,
        test_wr:     _tuneData.test_wr,
      })
    });
    const d = await r.json();
    if(d.ok){
      document.getElementById('btTunePanel').innerHTML =
        '<div class="tune-success">'
        +'<strong>&#10003; '+d.applied_count+' change'+(d.applied_count!==1?'s':'')+' applied</strong><br>'
        +(d.backup ? 'Backup saved as <code>'+d.backup+'</code><br><br>' : '')
        +'&#9888; <strong>Restart the bot (crypto_alert.py) to reload strategy_engine.py</strong><br>'
        +'<small style="color:var(--muted)">To revert: use the Tune History rollback button below</small>'
        +'</div>';
      loadTuneHistory();
    } else {
      showErr('Apply failed: '+(d.error||'unknown'));
      if(footerBtn){ footerBtn.disabled=false; footerBtn.textContent='&#9654; Review & Apply'; }
    }
  }catch(e){
    showErr('Apply error: '+e.message);
    if(footerBtn){ footerBtn.disabled=false; footerBtn.textContent='&#9654; Review & Apply'; }
  }
}

// ── TUNE HISTORY ─────────────────────────────────────────────────────────────
async function loadTuneHistory(){
  try{
    const r = await fetch('/api/backtest/tune-history');
    const d = await r.json();
    const sec = document.getElementById('tuneHistorySec');
    if(!d.ok || !d.history || !d.history.length){ if(sec) sec.style.display='none'; return; }
    if(sec) sec.style.display='block';
    _tuneHistData = d.history;
    tuneHistPage = 1;
    _renderTuneHistory();
  }catch(e){ console.warn('loadTuneHistory error:', e); }
}

function _tuneHistFiltered(){
  const q = (document.getElementById('tuneHistSearch')?.value||'').trim().toLowerCase();
  return q ? _tuneHistData.filter(h => (h.param||'').toLowerCase().includes(q)) : _tuneHistData;
}

function _renderTuneHistory(){
  const body   = document.getElementById('tuneHistoryBody');
  const pgBar  = document.getElementById('tuneHistPgBar');
  const data   = _tuneHistFiltered();
  const total  = data.length;
  const pages  = Math.max(1, Math.ceil(total / TUNE_HIST_PAGE_SIZE));
  if(tuneHistPage > pages) tuneHistPage = pages;
  const start  = (tuneHistPage - 1) * TUNE_HIST_PAGE_SIZE;
  const page   = data.slice(start, start + TUNE_HIST_PAGE_SIZE);

  // Status summary bar
  const cnt = {APPLIED:0,ROLLED_BACK:0,VERIFIED_BETTER:0,VERIFIED_WORSE:0};
  _tuneHistData.forEach(h => { if(cnt[h.status]!==undefined) cnt[h.status]++; });
  const summEl = document.getElementById('tuneHistSummary');
  if(summEl){
    const parts = [];
    if(cnt.APPLIED)         parts.push('<span style="color:var(--accent2)">'+cnt.APPLIED+' Applied</span>');
    if(cnt.VERIFIED_BETTER) parts.push('<span style="color:var(--green)">'+cnt.VERIFIED_BETTER+' Verified Better</span>');
    if(cnt.VERIFIED_WORSE)  parts.push('<span style="color:var(--red)">'+cnt.VERIFIED_WORSE+' Verified Worse</span>');
    if(cnt.ROLLED_BACK)     parts.push('<span style="color:var(--muted)">'+cnt.ROLLED_BACK+' Rolled Back</span>');
    const filterNote = total < _tuneHistData.length
      ? ' &nbsp;<span style="color:var(--muted)">(filtered: '+total+' / '+_tuneHistData.length+')</span>' : '';
    summEl.innerHTML = parts.join(' &nbsp;·&nbsp; ') + filterNote;
  }

  // Pagination controls
  if(pgBar){
    pgBar.style.display = pages > 1 ? 'flex' : 'none';
    document.getElementById('tuneHistPrevBtn').disabled = tuneHistPage <= 1;
    document.getElementById('tuneHistNextBtn').disabled = tuneHistPage >= pages;
    document.getElementById('tuneHistPgInfo').textContent =
      'Page ' + tuneHistPage + ' of ' + pages + '  (' + total + ' record' + (total!==1?'s':'') + ')';
  }

  if(!page.length){ body.innerHTML='<div class="empty" style="padding:1.5rem">No matching records</div>'; return; }

  const sColor = s => s==='APPLIED'?'var(--accent2)':s==='ROLLED_BACK'?'var(--muted)':s==='VERIFIED_BETTER'?'var(--green)':'var(--red)';
  body.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:.78rem">'
    +'<thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border)">'
    +'<th style="padding:.35rem .5rem">Date</th>'
    +'<th style="padding:.35rem .5rem" title="Backtest Run that captured this change">Run</th>'
    +'<th style="padding:.35rem .5rem">Param</th>'
    +'<th style="padding:.35rem .5rem">Change</th>'
    +'<th style="padding:.35rem .5rem">Train WR</th>'
    +'<th style="padding:.35rem .5rem">Test WR</th>'
    +'<th style="padding:.35rem .5rem" title="Win rate on signals closed after this tune was applied">Post WR</th>'
    +'<th style="padding:.35rem .5rem">Status</th>'
    +'<th style="padding:.35rem .5rem"></th>'
    +'</tr></thead><tbody>'
    + page.map(h => {
        const canRollback = h.status==='APPLIED'||h.status==='VERIFIED_BETTER'||h.status==='VERIFIED_WORSE';
        const rollBtn = canRollback
          ? '<button onclick="rollbackTune('+h.id+')" style="font-size:.7rem;padding:.2rem .55rem;background:rgba(239,68,68,.12);color:#f87171;border:1px solid rgba(239,68,68,.3);border-radius:4px;cursor:pointer;white-space:nowrap">Rollback</button>'
          : '<span style="color:var(--muted);font-size:.7rem">—</span>';
        const postWr = h.post_apply_wr != null
          ? h.post_apply_wr+'% <span style="color:var(--muted);font-size:.68rem">(n='+h.post_apply_n+')</span>'
          : '<span style="color:var(--muted)">—</span>';
        const hasExtra = h.notes || h.backup_file || h.signals_at_apply != null || h.backtest_run_id != null;
        const expandBtn = hasExtra
          ? ' <button onclick="toggleTuneRow(this,'+h.id+')" title="Details" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:.72rem;padding:.1rem .25rem;line-height:1;vertical-align:middle">&#9660;</button>'
          : '';
        const extraRow = hasExtra
          ? '<tr id="txr'+h.id+'" style="display:none">'
            +'<td colspan="9" style="padding:.4rem .5rem .7rem 1.4rem;background:rgba(37,37,56,.3)">'
            +'<div style="display:flex;flex-wrap:wrap;gap:.5rem 2rem;font-size:.74rem">'
            +(h.signals_at_apply!=null ? '<span><span style="color:var(--muted)">Signals at apply:</span> '+h.signals_at_apply+'</span>' : '')
            +(h.backtest_run_id !=null ? '<span><span style="color:var(--muted)">Backtest run:</span> #'+h.backtest_run_id+'</span>' : '')
            +(h.backup_file ? '<span><span style="color:var(--muted)">Backup:</span> <code style="font-size:.71rem;color:var(--muted)">'+h.backup_file+'</code></span>' : '')
            +(h.notes ? '<span style="width:100%;color:var(--muted);font-style:italic">&#8220;'+h.notes+'&#8221;</span>' : '')
            +'</div></td></tr>'
          : '';
        const runCell = h.backtest_run_id != null
          ? '<span style="color:var(--accent);font-weight:600">Run-'+h.backtest_run_id+'</span>'
          : '<span style="color:var(--muted)">—</span>';
        return '<tr style="border-bottom:1px solid rgba(148,163,184,.07)">'
          +'<td style="padding:.35rem .5rem;color:var(--muted)">'+(h.applied_at||'').slice(0,16)+'</td>'
          +'<td style="padding:.35rem .5rem">'+runCell+'</td>'
          +'<td style="padding:.35rem .5rem;font-weight:600">'+h.param+expandBtn+'</td>'
          +'<td style="padding:.35rem .5rem;color:var(--accent2);font-family:JetBrains Mono,monospace;font-size:.74rem">'+(h.old_val||'')+'&nbsp;&rarr;&nbsp;'+(h.new_val||'')+'</td>'
          +'<td style="padding:.35rem .5rem">'+(h.train_wr!=null?h.train_wr+'%':'—')+'</td>'
          +'<td style="padding:.35rem .5rem">'+(h.test_wr!=null?h.test_wr+'%':'—')+'</td>'
          +'<td style="padding:.35rem .5rem">'+postWr+'</td>'
          +'<td style="padding:.35rem .5rem;font-weight:600;color:'+sColor(h.status)+'">'+h.status+'</td>'
          +'<td style="padding:.35rem .5rem">'+rollBtn+'</td>'
          +'</tr>'+extraRow;
      }).join('')
    +'</tbody></table>';
}

function toggleTuneRow(btn, id){
  const row = document.getElementById('txr'+id);
  if(!row) return;
  const open = row.style.display==='none';
  row.style.display = open ? 'table-row' : 'none';
  btn.innerHTML = open ? '&#9650;' : '&#9660;';
  btn.style.color = open ? 'var(--accent2)' : 'var(--muted)';
}

function tuneHistChangePage(delta){
  const pages = Math.max(1, Math.ceil(_tuneHistFiltered().length / TUNE_HIST_PAGE_SIZE));
  tuneHistPage = Math.max(1, Math.min(pages, tuneHistPage + delta));
  _renderTuneHistory();
}

// ── BACKTEST HISTORY RENDERER ─────────────────────────────────────────────────
function _renderBtHistory(){
  const list  = document.getElementById('btHistList');
  const pgBar = document.getElementById('btHistPgBar');
  const total = _btHistData.length;
  const pages = Math.max(1, Math.ceil(total / BT_HIST_PAGE_SIZE));
  if(btHistPage > pages) btHistPage = pages;
  const start = (btHistPage - 1) * BT_HIST_PAGE_SIZE;
  const page  = _btHistData.slice(start, start + BT_HIST_PAGE_SIZE);
  list.innerHTML = page.map(r =>
    '<div class="hist-run">'
    +'<div class="hist-run-date">'+r.run_date.slice(0,16)+'</div>'
    +'<div class="hist-run-stats">'
    +'<span class="hist-stat">'+r.total_signals+' signals</span>'
    +'<span class="hist-stat" style="color:var(--green)">WR: '+r.overall_wr+'%</span>'
    +'<span class="hist-stat" style="color:var(--accent2)">R:R: 1:'+r.avg_rr+'</span>'
    +'<span class="hist-stat" style="color:var(--muted)">'+r.days+'d</span>'
    +'</div></div>'
  ).join('');
  if(pgBar){
    pgBar.style.display = pages > 1 ? 'flex' : 'none';
    document.getElementById('btHistPrevBtn').disabled = btHistPage <= 1;
    document.getElementById('btHistNextBtn').disabled = btHistPage >= pages;
    document.getElementById('btHistPgInfo').textContent =
      'Page '+btHistPage+' of '+pages+'  ('+total+' run'+(total!==1?'s':'')+')';
  }
}

function btHistChangePage(delta){
  const pages = Math.max(1, Math.ceil(_btHistData.length / BT_HIST_PAGE_SIZE));
  btHistPage = Math.max(1, Math.min(pages, btHistPage + delta));
  _renderBtHistory();
}

async function rollbackTune(tuneId){
  if(!confirm('Roll back tune adjustment #'+tuneId+'? This will restore the previous value in strategy_engine.py.')) return;
  try{
    const r = await fetch('/api/backtest/tune-rollback',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({tune_history_id: tuneId})
    });
    const d = await r.json();
    if(d.ok){
      showErr = () => {};  // suppress — success
      alert('Rolled back #'+tuneId+'. Restart the bot to apply.');
      loadTuneHistory();
    } else {
      alert('Rollback failed: '+(d.error||'unknown'));
    }
  }catch(e){ alert('Rollback error: '+e.message); }
}

// Poll status on load in case a backtest is already running
_pollBtStatus();
loadTuneHistory();

// ── ADAPTIVE LEARNING TAB ─────────────────────────────────────────────────────
let _adaptiveVisible = false;
let _adaptivePollTimer = null;
const _FEAT_LABELS = {fvg_quality:'FVG Quality', mss_quality:'MSS Quality', session:'Session', confidence:'Confidence', trend_strength:'Trend Str', dr_location:'DR Location'};

function _fillGauge(fillId, textId, used, max, label){
  const pct = Math.min(100, Math.round((used / max) * 100));
  const fillEl = document.getElementById(fillId);
  const textEl = document.getElementById(textId);
  if(fillEl){
    fillEl.style.width = pct + '%';
    fillEl.className = 'port-bar-fill ' + (pct >= 100 ? 'full' : pct >= 67 ? 'warn' : 'ok');
  }
  if(textEl) textEl.textContent = label;
}

// ──────────────────────────────────────────────────────────
// HONEST METRICS TAB (Sprint 3 + FIX 1 Part 2 surfaces)
// ──────────────────────────────────────────────────────────
async function loadHonestMetrics(){
  const loading = document.getElementById('honestLoading');
  const content = document.getElementById('honestContent');
  const err     = document.getElementById('honestError');
  loading.style.display = 'block';
  content.style.display = 'none';
  err.style.display     = 'none';
  try {
    const r = await fetch('/api/honest-metrics');
    if(!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || 'endpoint returned !ok');

    // ─── Top status row ─────────────────────────────────────
    document.getElementById('hmBotVersion').textContent = d.bot_version || '—';
    // C-3 fix (tracker audit 2026-05-26 cycle-6): read execution_mode from
    // the API instead of hardcoding "PAPER mode". A future LIVE flip is now
    // reflected in the dashboard within one poll cycle. Suffix annotates
    // signal-only PAPER semantics so the operator still sees that context.
    const _mode = (d.execution_mode || 'UNKNOWN').toUpperCase();
    const _modeLabel = _mode === 'PAPER' ? 'PAPER mode (signal-only)'
                     : _mode === 'LIVE'  ? 'LIVE mode (real capital)'
                     : _mode === 'UNKNOWN' ? 'UNKNOWN mode (no heartbeat / env)'
                     : _mode + ' mode';
    document.getElementById('hmExecutionMode').textContent = _modeLabel;

    const auditScore = d.audit && d.audit.score !== null ? d.audit.score : null;
    const auditEl = document.getElementById('hmAuditScore');
    if(auditScore !== null) {
      auditEl.textContent = auditScore.toFixed(2) + '/10';
      auditEl.className = 'honest-value ' + (auditScore >= 9 ? 'ok' : auditScore >= 7 ? 'warn' : 'crit');
    } else {
      auditEl.textContent = '—';
    }
    document.getElementById('hmAuditDate').textContent = (d.audit && d.audit.date) || 'no audit yet';

    const ogd = d.ogd_health || {};
    const alertEl = document.getElementById('hmOgdAlert');
    alertEl.textContent = ogd.global_alert || 'UNKNOWN';
    alertEl.className = 'honest-value ' + (
      ogd.global_alert === 'OK' ? 'ok' :
      ogd.global_alert === 'WARN' ? 'warn' :
      ogd.global_alert === 'CRIT' ? 'crit' : ''
    );
    document.getElementById('hmOgdDetail').textContent =
      'tokens=' + (ogd.tokens || 0) + ', degen=' + (ogd.degenerate || 0) +
      ', pinned=' + (ogd.pinned || 0) + ', stale=' + (ogd.stale || 0);

    const mf = d.macro_filter || {};
    const mfEl = document.getElementById('hmMacroValue');
    if(mf.enabled === null || mf.enabled === undefined) {
      mfEl.textContent = '—';
    } else if(!mf.enabled) {
      mfEl.textContent = 'OFF';
      mfEl.className = 'honest-value';
    } else if(mf.advisory_only) {
      mfEl.textContent = 'ADVISORY';
      mfEl.className = 'honest-value warn';
    } else {
      mfEl.textContent = 'BLOCKING';
      mfEl.className = 'honest-value ok';
    }
    document.getElementById('hmMacroDetail').textContent =
      'event_calendar.py: FOMC/CPI/NFP windows';

    // ─── Paper trading progress ─────────────────────────────
    const pp = d.paper_progress || {};
    const pct = pp.pct || 0;
    document.getElementById('hmPaperLabel').textContent =
      (pp.closed || 0) + ' / ' + (pp.target || 30) + ' closed signals  (' + pct.toFixed(1) + '%)';
    document.getElementById('hmPaperEta').textContent =
      'ETA: ' + (pp.eta_months !== undefined ? pp.eta_months : '—') + ' months';
    document.getElementById('hmPaperFill').style.width = pct + '%';
    const rateEl = document.getElementById('hmPaperRateDetail');
    if(rateEl){
      const sourceLabel = ({
        'live_30d':            'live last-30d (real-time)',
        'backtest_run_latest': 'latest backtest (no live data yet)',
        'fallback_default':    'default 4/mo (no data available)'
      })[pp.rate_source] || pp.rate_source || '—';
      const remaining = pp.remaining !== undefined ? pp.remaining : '?';
      const rate = pp.rate_per_month !== undefined ? pp.rate_per_month : '?';
      rateEl.textContent = 'Rate basis: ' + rate + ' signals/month from ' + sourceLabel +
        '  ·  ' + remaining + ' to go';
    }

    // ─── Latest backtest honest metrics ─────────────────────
    const lr = d.latest_run || {};
    const hm = d.honest_metrics || {};
    document.getElementById('hmRunId').textContent =
      lr.id !== null ? 'Run-' + lr.id : '—';
    document.getElementById('hmRunDate').textContent = lr.date || '—';
    document.getElementById('hmRunN').textContent = lr.n !== null ? lr.n : '—';
    document.getElementById('hmRunWr').textContent =
      lr.wr !== null ? lr.wr.toFixed(1) + '%' : '—';
    document.getElementById('hmCpcvWr').textContent =
      hm.cpcv_wr_mean !== null ? hm.cpcv_wr_mean.toFixed(2) + '%' : '—';
    document.getElementById('hmCpcvQ05').textContent =
      hm.cpcv_wr_q05 !== null ? hm.cpcv_wr_q05.toFixed(1) + '%' : '—';
    document.getElementById('hmCpcvStd').textContent =
      hm.cpcv_wr_std !== null ? hm.cpcv_wr_std.toFixed(2) + '%' : '—';
    document.getElementById('hmSharpe').textContent =
      hm.overall_sharpe !== null ? hm.overall_sharpe.toFixed(3) : '—';
    document.getElementById('hmPsr').textContent =
      hm.psr_oos !== null ? hm.psr_oos.toFixed(1) + '%' : '—';
    document.getElementById('hmDsr').textContent =
      hm.dsr !== null ? hm.dsr.toFixed(1) + '%' : '—';
    document.getElementById('hmDsrNote').textContent =
      hm.dsr_proxy_used === false ? 'Honest cross-config (Bailey/LdP)' :
      hm.dsr_proxy_used === true  ? '⚠️ Within-fold proxy (anti-conservative)' :
      'Honest (target ≥95%)';

    const verdEl = document.getElementById('hmVerdict');
    verdEl.textContent = hm.verdict || '—';
    verdEl.className = 'honest-verdict-value ' + (
      hm.verdict === 'PASS' ? 'pass' :
      hm.verdict === 'MARGINAL' ? 'marginal' :
      hm.verdict === 'FAIL' ? 'fail' : ''
    );

    // ─── Cross-config sr_trial_std ──────────────────────────
    const cs = d.cross_config_std || {};
    document.getElementById('hmStdValue').textContent =
      cs.value !== null ? cs.value.toFixed(4) : '—';
    document.getElementById('hmStdN').textContent = cs.n_configs || '—';
    document.getElementById('hmStdMean').textContent =
      cs.mean_oos_sharpe !== null ? cs.mean_oos_sharpe.toFixed(4) : '—';
    document.getElementById('hmStdComputed').textContent = cs.computed_at || '—';
    document.getElementById('hmStdNote').textContent = cs.note || '—';

    // ─── Update tab pill with alert level ───────────────────
    const pill = document.getElementById('honestPill');
    if(ogd.global_alert === 'CRIT') pill.textContent = '!';
    else if(ogd.global_alert === 'WARN') pill.textContent = '⚠';
    else if(ogd.global_alert === 'OK') pill.textContent = '✓';
    else pill.textContent = '·';

    loading.style.display = 'none';
    content.style.display = 'block';
  } catch (e) {
    loading.style.display = 'none';
    err.style.display = 'block';
    err.textContent = 'Failed to load honest metrics: ' + e.message;
  }
}

async function loadAdaptive(){
  try{
    const [r, rh] = await Promise.all([
      fetch('/api/adaptive/summary'),
      fetch('/api/adaptive/health').catch(() => null)
    ]);
    if(!r.ok) throw new Error('adaptive ' + r.status);
    const d = await r.json();
    if(!d.ok) throw new Error('Adaptive endpoint error');
    const healthData = rh ? await rh.json().catch(() => null) : null;
    const healthTokens = (healthData && healthData.ok) ? (healthData.tokens || {}) : {};

    // ── Bot State ──
    const bs = d.bot_state || {};
    const adjVal = bs.threshold_adj || 0;
    const adjEl = document.getElementById('adaptThreshAdj');
    if(adjEl){
      adjEl.textContent = (adjVal > 0 ? '+' : '') + adjVal;
      adjEl.className = 'icard-val ' + (adjVal > 0 ? 'r' : adjVal < 0 ? 'g' : '');
    }
    // Fix 2: show what _signal_threshold_adj actually enforces now
    const adjSubEl = document.getElementById('adaptThreshAdjSub');
    if(adjSubEl){
      const floorRaise = Math.floor(Math.max(0, adjVal) / 3);
      if(adjVal > 0 && floorRaise > 0)
        adjSubEl.textContent = 'RANGING/UNKNOWN conf floor +' + floorRaise;
      else if(adjVal > 0)
        adjSubEl.textContent = 'active — needs adj≥3 for floor raise';
      else if(adjVal < 0)
        adjSubEl.textContent = 'threshold relaxed (good WR)';
      else
        adjSubEl.textContent = 'at baseline';
    }
    const cfEl = document.getElementById('adaptConfFloor');
    if(cfEl) cfEl.textContent = bs.conf_floor != null ? bs.conf_floor : '—';

    const lastSigEl = document.getElementById('adaptLastSig');
    if(lastSigEl) lastSigEl.textContent = bs.last_signal_ts ? bs.last_signal_ts.slice(0,16) : '—';

    const statusPill = document.getElementById('adaptBotStatus');
    if(statusPill){
      statusPill.textContent = bs.bot_active ? 'ACTIVE' : 'OFFLINE';
      statusPill.style.background = bs.bot_active ? 'rgba(34,197,94,.15)' : 'var(--dim)';
      statusPill.style.color = bs.bot_active ? 'var(--green)' : 'var(--muted)';
      statusPill.style.border = bs.bot_active ? '1px solid rgba(34,197,94,.3)' : '1px solid var(--border)';
    }

    // ── Portfolio Exposure ──
    const po = d.portfolio || {};
    _fillGauge('portOpenFill','portOpenText', po.open_count||0, po.max_open||3,
      (po.open_count||0)+' / '+(po.max_open||3));
    _fillGauge('portBuyFill','portBuyText', po.buy_count||0, po.max_same_dir||2,
      (po.buy_count||0)+' / '+(po.max_same_dir||2));
    _fillGauge('portSellFill','portSellText', po.sell_count||0, po.max_same_dir||2,
      (po.sell_count||0)+' / '+(po.max_same_dir||2));
    const riskPct = (po.risk_used_pct || 0) * 100;
    // Fix F1+F2 (2026-05-22 tracker audit): max_risk_pct from API, not hardcoded 15%.
    // LIVE caps at 3% (M18 fix); PAPER caps at 100%. Color thresholds are now
    // proportional to the cap rather than absolute percentage points.
    const maxRiskPct = (po.max_risk_pct != null ? po.max_risk_pct : 0.15) * 100;
    const maxRiskLabel = maxRiskPct.toFixed(maxRiskPct >= 10 ? 0 : 1) + '%';
    _fillGauge('portRiskFill','portRiskText', riskPct, maxRiskPct,
      riskPct.toFixed(2)+'% / '+maxRiskLabel);
    const riskCardEl = document.getElementById('adaptRiskCard');
    if(riskCardEl){
      riskCardEl.textContent = riskPct.toFixed(2) + '%';
      // Red at/above cap, amber at 66% of cap, green below.
      riskCardEl.className = 'icard-val ' + (
        riskPct >= maxRiskPct        ? 'r' :
        riskPct >= maxRiskPct * 0.66 ? ''  : 'g');
    }
    const riskCardSubEl = document.getElementById('adaptRiskCardSub');
    if(riskCardSubEl){
      riskCardSubEl.textContent = '% capital at risk / ' + maxRiskLabel + ' cap';
    }
    const slotEl = document.getElementById('portSlotMsg');
    if(slotEl){
      const sf = po.slots_free || 0;
      slotEl.textContent = sf > 0 ? sf + ' position slot' + (sf!==1?'s':'') + ' available' : 'Portfolio full — no new signals will fire';
      slotEl.style.color = sf > 0 ? 'var(--green)' : 'var(--red)';
    }

    // ── OGD Weights ──
    const wdata = d.weights || {};
    const wtokens = wdata.tokens || {};
    const feats = wdata.feature_order || ['rsi','trend','sr','mtf','volume','momentum'];
    const defW = wdata.default_weight || 0.1667;
    const ogdMin = wdata.ogd_min_samples || 30;
    const wbEl = document.getElementById('adaptWeightsBody');
    if(wbEl){
      const tkeys = Object.keys(wtokens);
      if(!tkeys.length){
        wbEl.innerHTML = '<div class="empty">No OGD data yet — weights populate after first signal closes</div>';
      } else {
        wbEl.innerHTML = tkeys.map(tok => {
          const tw = wtokens[tok];
          const nUpd = tw.n_updates || 0;
          const updAt = tw.updated_at ? tw.updated_at.slice(0,16) : '—';
          const blend = tw.blend_pct != null ? tw.blend_pct : 0;
          // Fix 1: reflect real OGD activation threshold (30) and current blend %
          const phase = nUpd === 0 ? 'Default weights'
            : nUpd < ogdMin ? 'Accumulating ('+nUpd+'/'+ogdMin+')'
            : blend > 0 ? 'Applied — '+blend+'% OGD / '+(100-blend)+'% static'
            : 'OGD Active — '+nUpd+' updates';
          const bars = feats.map(f => {
            const w = tw[f] || defW;
            const barPct = Math.round(w / 0.50 * 100);  // 0.50 = WEIGHT_MAX
            const above = w > defW + 0.005;
            return '<div class="wt-feat-row">'
              +'<div class="wt-feat-label">'+(_FEAT_LABELS[f]||f)+'</div>'
              +'<div class="wt-bar-bg">'
              +'<div class="wt-bar-fill '+(above?'above':'below')+'" style="width:'+barPct+'%"></div>'
              +'<div class="wt-bar-default"></div>'
              +'</div>'
              +'<div class="wt-val">'+(w*100).toFixed(1)+'%</div>'
              +'</div>';
          }).join('');
          // Fix 3: per-token WR gate status
          const wr = tw.recent_wr;
          const wrN = tw.wr_n || 0;
          let wrHtml = '';
          if(wr == null){
            wrHtml = '<div class="wt-wr-row muted">Token WR: insufficient data ('+wrN+'&lt;5 trades)</div>';
          } else {
            const wrPct = Math.round(wr * 100);
            const wrColor = wr < 0.25 ? 'var(--red)' : wr < 0.35 ? 'var(--accent2)' : 'var(--green)';
            const gateNote = wr < 0.25 ? ' — conf floor +2 (Fix 3 active)'
                           : wr < 0.35 ? ' — conf floor +1 (Fix 3 active)' : '';
            wrHtml = '<div class="wt-wr-row" style="color:'+wrColor+'">Token WR (last '+wrN+'): '+wrPct+'%'+gateNote+'</div>';
          }
          // P3-1: OGD health badge
          const hth = healthTokens[tok] || {};
          let badgeHtml = '';
          if(Object.keys(healthTokens).length){
            const isDegen = hth.is_degenerate;
            const maxW    = hth.max_weight   != null ? hth.max_weight   : null;
            const ent     = hth.weight_entropy != null ? hth.weight_entropy : null;
            const nH      = hth.n_updates     != null ? hth.n_updates   : nUpd;
            let badgeLabel, badgeStyle;
            if(isDegen){
              badgeLabel = 'DEGENERATE';
              badgeStyle = 'background:rgba(239,68,68,.18);color:#f87171;border:1px solid rgba(239,68,68,.35)';
            } else if(nH < ogdMin){
              badgeLabel = 'LEARNING';
              badgeStyle = 'background:rgba(148,163,184,.12);color:var(--muted);border:1px solid rgba(148,163,184,.2)';
            } else {
              badgeLabel = 'HEALTHY';
              badgeStyle = 'background:rgba(52,211,153,.12);color:#34d399;border:1px solid rgba(52,211,153,.25)';
            }
            const tooltip = maxW != null ? 'max_w='+maxW.toFixed(3)+(ent!=null?', entropy='+ent.toFixed(3):'') : '';
            badgeHtml = '<span title="'+tooltip+'" style="font-size:.68rem;padding:.12rem .45rem;border-radius:10px;letter-spacing:.05em;font-weight:700;'+badgeStyle+'">'+badgeLabel+'</span>';
          }
          // C-2 fix (tracker audit 2026-05-26 cycle-6): annotate the source.
          // Tokens without a live `token_weights` row fall back to the
          // bootstrap pool (`backtest_token_weights`). The BOOTSTRAP badge
          // tells the operator the weights are seeded priors, not the result
          // of any closed-signal OGD updates yet.
          if(tw.source === 'bootstrap'){
            badgeHtml += ' <span title="Seeded from backtest_token_weights; no live updates yet" '
              + 'style="font-size:.62rem;padding:.10rem .40rem;border-radius:10px;letter-spacing:.05em;font-weight:700;'
              + 'background:rgba(148,163,184,.12);color:var(--muted);border:1px solid rgba(148,163,184,.2);margin-left:.25rem">BOOTSTRAP</span>';
          }
          return '<div class="wt-token-block" data-token="'+tok+'">'
            +'<div class="wt-token-hdr">'
            +'<div class="wt-token-name">'+tok+' '+badgeHtml+'</div>'
            +'<div class="wt-token-meta"><span class="n-val">'+nUpd+'</span> updates &nbsp;·&nbsp; '+phase+' &nbsp;·&nbsp; Last: '+updAt+'</div>'
            +'</div>'
            +bars
            +wrHtml
            +'<div class="wt-spark-wrap" title="Weight trajectory across bootstrap + live updates (last 30 snapshots per feature)">'
            +  '<canvas class="wt-spark" data-token="'+tok+'" width="600" height="56"></canvas>'
            +  '<div class="wt-spark-legend" id="wtSparkLegend_'+tok+'"></div>'
            +'</div>'
            +'</div>';
        }).join('');
        // C3 (2026-05-22 tracker audit): populate sparklines after HTML is in DOM
        renderOgdSparklines();
      }
    }

    // ── Drift Baselines ──
    const ddata = d.drift || {};
    const dtoks = ddata.tokens || {};
    const dbEl = document.getElementById('adaptDriftBody');
    if(dbEl){
      const dkeys = Object.keys(dtoks);
      if(!dkeys.length){
        dbEl.innerHTML = '<div class="empty">No drift baselines yet — accumulates during live trading cycles</div>';
      } else {
        dbEl.innerHTML = dkeys.map(tok => {
          const dt = dtoks[tok];
          const active = dt.active;
          const n = dt.n_samples || 0;
          const updAt = dt.updated_at ? dt.updated_at.slice(0,16) : '—';
          return '<div class="drift-token-block">'
            +'<div class="drift-token-hdr">'
            +'<div class="drift-token-name">'+tok+'</div>'
            +'<span class="drift-badge '+(active?'active':'learning')+'">'
            +(active ? 'Active' : 'Learning ('+n+'/20)')+'</span>'
            +'</div>'
            +'<div class="drift-thresholds">'
            +'<div class="drift-thr"><div class="drift-thr-label">ADX Thresh</div>'
            +'<div class="drift-thr-val">'+(dt.adx_threshold||25)+'</div>'
            +'<div class="drift-thr-default">default 25.0</div></div>'
            +'<div class="drift-thr"><div class="drift-thr-label">RSI Oversold</div>'
            +'<div class="drift-thr-val">'+(dt.rsi_oversold||38)+'</div>'
            +'<div class="drift-thr-default">default 38.0</div></div>'
            +'<div class="drift-thr"><div class="drift-thr-label">RSI Overbought</div>'
            +'<div class="drift-thr-val">'+(dt.rsi_overbought||62)+'</div>'
            +'<div class="drift-thr-default">default 62.0</div></div>'
            +'<div class="drift-thr"><div class="drift-thr-label">ADX Mean</div>'
            +'<div class="drift-thr-val">'+(dt.adx_mean||'—')+'</div>'
            +'<div class="drift-thr-default">rolling baseline</div></div>'
            +'<div class="drift-thr"><div class="drift-thr-label">ATR Ratio Mean</div>'
            +'<div class="drift-thr-val">'+(dt.atr_ratio_mean||'—')+'</div>'
            +'<div class="drift-thr-default">rolling baseline</div></div>'
            +'<div class="drift-thr"><div class="drift-thr-label">Samples</div>'
            +'<div class="drift-thr-val">'+n+'</div>'
            +'<div class="drift-thr-default">/ 200 window</div></div>'
            +'</div>'
            +'<div style="font-size:.7rem;color:var(--muted);margin-top:.4rem">Last persisted: '+updAt+'</div>'
            +'</div>';
        }).join('');
      }
    }

    // Cache age indicator
    const cacheEl = document.getElementById('adaptCacheAge');
    if(cacheEl){
      const age = d.cache_age_sec || 0;
      if(age < 2){
        cacheEl.style.display = 'none';
      } else {
        cacheEl.textContent = 'Cached ' + age + 's ago — updates every 15s';
        cacheEl.style.display = 'block';
      }
    }

    document.getElementById('adaptCount').textContent = Object.keys(wtokens).length || '0';

    // ── R10 Per-Token Forensic Panel ───────────────────────────────────
    // Fetch + render the new R4 (reward, gradient_l1, profit_pct) +
    // R7 (regime) forensic columns from weight_history, plus R1
    // (DSR verdict) + R9 (freeze state) global health.
    try {
      const fr = await fetch('/api/adaptive/forensic');
      if (fr.ok) {
        const fd = await fr.json();
        renderAdaptiveForensicPanel(fd);
      }
    } catch (e) {
      console.warn('forensic panel', e);
    }

  } catch(e){
    console.error('adaptive', e);
    const el = document.getElementById('adaptError');
    if(el){ el.textContent = 'Failed to load adaptive data: ' + e.message; el.style.display = 'block'; }
  }
}

function renderAdaptiveForensicPanel(data) {
  const headerEl = document.getElementById('adaptForensicHeader');
  const bodyEl   = document.getElementById('adaptForensicBody');
  if (!bodyEl) return;
  if (!data || !data.ok) {
    bodyEl.innerHTML = '<div class="empty">forensic endpoint error</div>';
    return;
  }

  // Header strip: global verdict + freeze state
  const g = data.global || {};
  const verdict = (g.latest_cpcv_verdict || {}).verdict || '—';
  const verdictClass = verdict === 'PASS' ? 'g' :
                       verdict === 'MARGINAL' ? 'y' :
                       verdict === 'FAIL' ? 'r' : '';
  const fs = g.learning_freeze_state || {};
  const frozenLabel = fs.frozen ? '<span class="badge crit">FROZEN</span>' :
                      (fs.active_triggers && fs.active_triggers.length > 0) ?
                      '<span class="badge warn">SHADOW: ' + (fs.active_triggers||[]).join(', ') + '</span>' :
                      '<span class="badge ok">OK</span>';
  headerEl.innerHTML =
    '<b>Latest CPCV Verdict:</b> <span class="' + verdictClass + '">' + verdict + '</span>' +
    '  ·  <b>R9 freeze:</b> ' + frozenLabel +
    '  ·  <b>Updated:</b> ' + ((g.latest_cpcv_verdict||{}).updated_at || '—');

  const tokens = data.tokens || {};
  const sorted = Object.keys(tokens).sort();
  if (sorted.length === 0) {
    bodyEl.innerHTML = '<div class="empty">No forensic data yet</div>';
    return;
  }

  // Compact per-token rows
  const rows = sorted.map(tok => {
    const t = tokens[tok] || {};
    const cw = t.current_weights || {};
    let topFeat = '—', topVal = 0;
    Object.entries(cw).forEach(([f, v]) => { if (v > topVal) { topVal = v; topFeat = f; } });
    const flags = (t.health_flags || []).map(f => {
      const cls = f.startsWith('FROZEN') ? 'crit' :
                  f.startsWith('DEGENERATE') ? 'crit' :
                  f.startsWith('FLOOR-PINNED') ? 'warn' :
                  f.startsWith('STALE') ? 'warn' : '';
      return '<span class="badge ' + cls + '" style="margin-right:.2rem">' + f + '</span>';
    }).join('') || '<span style="color:var(--muted);font-size:.75rem">—</span>';

    const recent = (t.recent_updates || [])[0] || {};
    const reward = recent.reward != null ? recent.reward.toFixed(3) : '—';
    const grad   = recent.gradient_l1 != null ? recent.gradient_l1.toFixed(5) : '—';
    const regime = recent.regime || '—';
    const profit = recent.profit_pct != null ? (recent.profit_pct*100).toFixed(2) + '%' : '—';
    const lastTs = recent.ts || t.last_update_iso || '—';
    const rewardColor = recent.reward > 0 ? 'g' : recent.reward < 0 ? 'r' : '';

    return '<tr>' +
      '<td><b>' + tok + '</b></td>' +
      '<td style="text-align:center">' + (t.n_updates || 0) + '</td>' +
      '<td style="font-size:.8rem">' + topFeat + ':' + (topVal*100).toFixed(1) + '%</td>' +
      '<td class="' + rewardColor + '">' + reward + '</td>' +
      '<td>' + grad + '</td>' +
      '<td style="font-size:.8rem">' + regime + '</td>' +
      '<td>' + profit + '</td>' +
      '<td style="font-size:.7rem;color:var(--muted)">' + lastTs + '</td>' +
      '<td>' + flags + '</td>' +
      '</tr>';
  }).join('');

  bodyEl.innerHTML =
    '<table class="data-table" style="width:100%;font-size:.85rem">' +
      '<thead><tr>' +
        '<th>Token</th><th>n_updates</th><th>Top Feature</th>' +
        '<th>Last Reward</th><th>Grad L1</th><th>Regime</th>' +
        '<th>P&amp;L</th><th>Last Update</th><th>Flags</th>' +
      '</tr></thead>' +
      '<tbody>' + rows + '</tbody>' +
    '</table>';
}

function _startAdaptivePoll(){
  if(_adaptivePollTimer) return;
  _adaptivePollTimer = setInterval(() => {
    if(_adaptiveVisible) loadAdaptive();
  }, 60000);  // 60s — weights change only on signal close, drift persists every ~30min
}
_startAdaptivePoll();

// ── showTab — redefined here to track adaptive panel visibility ───────────────
function showTab(tab, btn){
  _adaptiveVisible = (tab === 'adaptive');
  _explorerVisible = (tab === 'explorer');
  document.querySelectorAll('.main-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel'+tab.charAt(0).toUpperCase()+tab.slice(1)).classList.add('active');
}

// Poll status on load in case a backtest is already running
_pollBtStatus();

// ── FAQ modal — opens detailed docs for each tab ──────────────────────────
const FAQ_TITLES = {
  open:         '📂 Open Positions — Full Guide',
  history:      '📜 Signal History — Full Guide',
  intelligence: '⚡ AI Intelligence — Full Guide',
  backtest:     '📊 Backtest — Full Guide',
  adaptive:     '🧠 Adaptive — Full Guide',
  honest:       '📍 Honest Metrics — Full Guide',
  explorer:     '🤖 Auto-Explorer — Full Guide',
};
function openFAQ(key){
  const tpl = document.getElementById('faq_' + key);
  if(!tpl) return;
  document.getElementById('faqTitle').textContent = FAQ_TITLES[key] || 'FAQ';
  document.getElementById('faqBody').innerHTML = tpl.innerHTML;
  document.getElementById('faqModal').style.display = 'flex';
  document.getElementById('faqModal').scrollTop = 0;
}
function closeFAQ(){
  document.getElementById('faqModal').style.display = 'none';
}
// ESC to close FAQ modal
document.addEventListener('keydown', e => {
  if(e.key === 'Escape' && document.getElementById('faqModal').style.display === 'flex'){
    closeFAQ();
  }
});

// ── Auto-Explorer tab ─────────────────────────────────────────────────────
async function loadExplorer(){
  try{
    const [statusR, paretoR, promoR, trialsR] = await Promise.all([
      fetch('/api/explorer/status').then(r=>r.json()),
      fetch('/api/explorer/pareto').then(r=>r.json()),
      fetch('/api/explorer/promotions').then(r=>r.json()),
      fetch('/api/explorer/trials?limit=20').then(r=>r.json()),
    ]);

    const sessWrap = document.getElementById('explSessionWrap');
    const noSess = document.getElementById('explNoSession');
    if(!statusR.ok || statusR.state === 'NO_SESSION' || !statusR.session){
      sessWrap.style.display = 'none';
      noSess.style.display = 'block';
    } else {
      noSess.style.display = 'none';
      sessWrap.style.display = 'block';
      const s = statusR.session;
      const stateColors = {
        RUNNING:  {bg:'#0e2616', border:'#1f8a4c', icon:'▶️'},
        FINISHED: {bg:'#0e1c2c', border:'#2a4a6a', icon:'✅'},
        PAUSED:   {bg:'#2c2410', border:'#a07b18', icon:'⏸️'},
        UNKNOWN:  {bg:'#1a1f2e', border:'#444',    icon:'❔'}
      };
      const sc = stateColors[statusR.state] || stateColors.UNKNOWN;
      sessWrap.style.background = sc.bg;
      sessWrap.style.border = '1px solid ' + sc.border;
      document.getElementById('explStateIcon').textContent = sc.icon;
      document.getElementById('explStateText').textContent = statusR.state;
      document.getElementById('explStudyName').textContent = s.study_name ? '(' + s.study_name + ')' : '';
      document.getElementById('explLastUpdate').textContent = s.last_updated ? 'last update: ' + s.last_updated : '';
      const c = s.counts || {};
      const detail = 'Trials ' + (s.trials_completed||0) + '/' + (s.trials_planned||0)
        + '  ·  PASS=' + (c.PASS||0)
        + '  FAIL=' + (c.FAIL||0)
        + '  ERROR=' + (c.ERROR||0)
        + (s.best_cpcv ? '  ·  best CPCV=' + s.best_cpcv + '  DSR=' + (s.best_dsr||'?') : '')
        + (s.pause_reason ? '  ·  pause: ' + s.pause_reason : '');
      document.getElementById('explSessionDetail').textContent = detail;
    }

    // Summary cards
    const trials = (trialsR.totals || {});
    const total = (trials.PASS||0) + (trials.FAIL||0) + (trials.ERROR||0);
    document.getElementById('explTotalTrials').textContent = total;
    document.getElementById('explStudiesCount').textContent = (trialsR.n_studies||0) + ' distinct studies';
    document.getElementById('explVerdictRatio').textContent =
      (trials.PASS||0) + ' / ' + (trials.FAIL||0) + ' / ' + (trials.ERROR||0);
    document.getElementById('explPassPct').textContent =
      total > 0 ? ((100 * (trials.PASS||0) / total).toFixed(1) + '% PASS rate') : '—';
    document.getElementById('explPromosToday').textContent = (promoR.promotions || []).filter(p => {
      const today = new Date().toISOString().slice(0,10);
      return (p.promoted_at_utc || '').startsWith(today);
    }).length;
    const lastPromoTs = ((promoR.promotions || []).slice(-1)[0] || {}).promoted_at_utc;
    if(lastPromoTs){
      const ago = (Date.now() - new Date(lastPromoTs).getTime()) / 3600000;
      document.getElementById('explSoakHours').textContent =
        ago < 24 ? ('soak: ' + ago.toFixed(1) + 'h since last') : 'free to promote';
    } else {
      document.getElementById('explSoakHours').textContent = 'no prior auto-promote';
    }
    document.getElementById('explParetoSize').textContent = (paretoR.archive || []).length;
    document.getElementById('explorerPill').textContent = total;

    // Pareto archive table
    const paretoBody = document.getElementById('explParetoBody');
    const pareto = paretoR.archive || [];
    if(pareto.length === 0){
      paretoBody.innerHTML = '<tr><td colspan="9" class="empty" style="padding:1rem">No Pareto candidates yet</td></tr>';
    } else {
      paretoBody.innerHTML = pareto.map(p => {
        const params = p.params ? Object.entries(p.params).map(([k,v]) => k.replace('BACKTEST_','').replace('ICT_','') + '=' + v).join('  ') : '';
        return '<tr style="border-bottom:1px solid rgba(148,163,184,.07)">'
          + '<td style="padding:.35rem .5rem">#' + (p.trial_id||'?') + '</td>'
          + '<td style="padding:.35rem .5rem;color:var(--muted)">' + (p.study_name||'') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (p.n||'—') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (p.wr!=null ? p.wr+'%' : '—') + '</td>'
          + '<td style="padding:.35rem .5rem;color:var(--green);font-weight:600">' + (p.cpcv_mean!=null ? p.cpcv_mean+'%' : '—') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (p.cpcv_std!=null ? p.cpcv_std : '—') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (p.sharpe!=null ? p.sharpe : '—') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (p.dsr!=null ? p.dsr+'%' : '—') + '</td>'
          + '<td style="padding:.35rem .5rem;color:var(--muted);font-family:JetBrains Mono,monospace;font-size:.7rem">' + params + '</td>'
          + '</tr>';
      }).join('');
    }

    // Promotions table
    const promoBody = document.getElementById('explPromoBody');
    const promos = (promoR.promotions || []).filter(p => p.kind === 'AUTO_PROMOTED').slice(-10).reverse();
    if(promos.length === 0){
      promoBody.innerHTML = '<tr><td colspan="6" class="empty" style="padding:1rem">No auto-promotions yet</td></tr>';
    } else {
      promoBody.innerHTML = promos.map(p => {
        const m1 = p.metrics_run1 || {};
        const m2 = p.metrics_run2 || {};
        return '<tr style="border-bottom:1px solid rgba(148,163,184,.07)">'
          + '<td style="padding:.35rem .5rem;color:var(--muted)">' + (p.promoted_at_utc||'').slice(0,16) + '</td>'
          + '<td style="padding:.35rem .5rem">#' + (p.trial_no||'?') + '</td>'
          + '<td style="padding:.35rem .5rem;color:var(--accent);font-weight:600">Run-' + (p.backtest_run_id||'?') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (m1.cpcv_mean||'—') + '% / ' + (m2.cpcv_mean||'—') + '%</td>'
          + '<td style="padding:.35rem .5rem">' + (m1.dsr||'—') + '%</td>'
          + '<td style="padding:.35rem .5rem">' + (m1.sharpe||'—') + '</td>'
          + '</tr>';
      }).join('');
    }

    // Recent trials table
    const trialsBody = document.getElementById('explTrialsBody');
    const trList = trialsR.trials || [];
    if(trList.length === 0){
      trialsBody.innerHTML = '<tr><td colspan="9" class="empty" style="padding:1rem">No trials yet</td></tr>';
    } else {
      trialsBody.innerHTML = trList.map(t => {
        const vcolor = {PASS:'var(--green)', FAIL:'var(--red)', ERROR:'var(--muted)'}[t.verdict] || 'var(--muted)';
        return '<tr style="border-bottom:1px solid rgba(148,163,184,.07)">'
          + '<td style="padding:.35rem .5rem">#' + t.trial_id + '</td>'
          + '<td style="padding:.35rem .5rem;color:var(--muted);font-size:.74rem;white-space:nowrap">' + (t.study_name||'') + '</td>'
          + '<td style="padding:.35rem .5rem;color:' + vcolor + ';font-weight:600">' + t.verdict + '</td>'
          + '<td style="padding:.35rem .5rem">' + (t.n||'—') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (t.wr!=null ? t.wr+'%' : '—') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (t.cpcv_mean!=null ? t.cpcv_mean+'%' : '—') + '</td>'
          + '<td style="padding:.35rem .5rem">' + (t.dsr!=null ? t.dsr+'%' : '—') + '</td>'
          + '<td style="padding:.35rem .5rem;color:var(--muted);font-size:.72rem">' + (t.walltime_s!=null ? Math.round(t.walltime_s)+'s' : '—') + '</td>'
          + '<td style="padding:.35rem .5rem;color:var(--muted);font-size:.72rem">' + (t.reject_reason || (t.verdict==='PASS' ? 'all gates clear' : '')) + '</td>'
          + '</tr>';
      }).join('');
    }
  } catch(e){
    console.error('loadExplorer', e);
  }
}

// Auto-refresh explorer panel every 15s while it's visible
let _explorerVisible = false;
setInterval(() => {
  if(_explorerVisible) loadExplorer();
}, 15000);

// ── Baseline pin banner (Backtest tab) ────────────────────────────────────
async function loadBaselinePin(){
  try{
    const r = await fetch('/api/baseline-pin');
    const d = await r.json();
    const wrap = document.getElementById('baselinePinWrap');
    if(!d.ok || !wrap) return;
    const pin = d.pin || {};
    const exp = pin.expected || {};
    const lat = d.latest || {};
    const status = d.status || 'ok';
    const palette = {
      ok:       {bg:'#0e2616', border:'#1f8a4c', icon:'✅'},
      drift:    {bg:'#2c2410', border:'#a07b18', icon:'⚠️'},
      mismatch: {bg:'#2c0e0e', border:'#a02d2d', icon:'⛔'}
    };
    const p = palette[status] || palette.ok;
    wrap.style.background = p.bg;
    wrap.style.border = '1px solid ' + p.border;
    wrap.style.display = 'block';
    document.getElementById('baselinePinIcon').textContent = p.icon;
    document.getElementById('baselinePinId').textContent = 'Run-' + (pin.run_id || '?');
    document.getElementById('baselinePinLabel').textContent =
      (pin.label ? '(' + pin.label + ')' : '') +
      (pin.promoted_at ? '  ·  promoted ' + pin.promoted_at : '');
    document.getElementById('baselinePinMsg').textContent = d.message || '';
    document.getElementById('baselinePinExpected').textContent =
      'Expected: n=' + (exp.n||'?') + '  ·  WR=' + (exp.wr_pct||'?') + '%' +
      '  ·  CPCV mean=' + (exp.cpcv_wr_mean_pct||'?') + '%' +
      '  ·  Sharpe=' + (exp.cpcv_sharpe_mean||'?') +
      '  ·  DSR=' + (exp.dsr_pct||'?') + '%' +
      '   |   Latest in DB: Run-' + (lat.id||'?') +
      ' (n=' + (lat.n||'?') + ', WR=' + (lat.wr||'?') + '%)';
  }catch(e){ /* silent */ }
}

// ── QuantStats tab ─────────────────────────────────────────────────────────
async function loadQuantStats(){
  const sel  = document.getElementById('qsSource');
  const src  = sel ? sel.value : 'backtest';
  const link = document.getElementById('qsTearLink');
  const frame = document.getElementById('qsTearFrame');
  const tearUrl = '/api/quantstats/tearsheet?source=' + src;
  if(link) link.href = tearUrl;
  if(frame && frame.dataset.loadedSrc !== src){
    frame.src = tearUrl;
    frame.dataset.loadedSrc = src;
  }

  const loading = document.getElementById('qsLoading');
  const empty   = document.getElementById('qsEmpty');
  const content = document.getElementById('qsContent');
  const errBox  = document.getElementById('qsError');
  loading.style.display = 'block'; empty.style.display = 'none';
  content.style.display = 'none'; errBox.style.display = 'none';

  try{
    const r = await fetch('/api/quantstats?source=' + src);
    const d = await r.json();
    loading.style.display = 'none';
    if(!d.ok){
      empty.style.display = 'block';
      empty.textContent = 'No closed signals yet for ' + src + '. Tearsheet will populate once trades close.';
      document.getElementById('qsPill').textContent = '0';
      return;
    }
    const m = d.metrics;
    const fmt   = (v, p=2) => (v===null||v===undefined) ? '—' : (typeof v==='number' ? v.toFixed(p) : v);
    const fmtPc = (v) => (v===null||v===undefined) ? '—' : (typeof v==='number' ? v.toFixed(2)+'%' : v);
    document.getElementById('qsSharpe').textContent  = fmt(m.sharpe);
    document.getElementById('qsSortino').textContent = fmt(m.sortino);
    document.getElementById('qsCalmar').textContent  = fmt(m.calmar);
    document.getElementById('qsCagr').textContent    = fmtPc(m.cagr_pct);
    document.getElementById('qsMaxDd').textContent   = fmtPc(m.max_drawdown_pct);
    document.getElementById('qsPf').textContent      = fmt(m.profit_factor);
    document.getElementById('qsKelly').textContent   = fmtPc((m.kelly_criterion||0)*100);
    document.getElementById('qsWr').textContent      = fmtPc(m.win_rate_pct);
    document.getElementById('qsAvgWl').textContent   = fmtPc(m.avg_win_pct) + ' / ' + fmtPc(m.avg_loss_pct);
    document.getElementById('qsBw').textContent      = fmtPc(m.best_day_pct) + ' / ' + fmtPc(m.worst_day_pct);
    document.getElementById('qsVol').textContent     = fmtPc(m.volatility_ann_pct);
    document.getElementById('qsVar').textContent     = fmtPc(m.value_at_risk_pct) + ' / ' + fmtPc(m.cvar_pct);
    document.getElementById('qsOmega').textContent   = fmt(m.omega);
    document.getElementById('qsTail').textContent    = fmt(m.tail_ratio);
    document.getElementById('qsSk').textContent      = fmt(m.skew) + ' / ' + fmt(m.kurtosis);
    document.getElementById('qsCum').textContent     = fmtPc(m.cumulative_return_pct);
    const metaParts = [d.n + ' trade-days'];
    if(m.periods_per_year) metaParts.push('~' + m.periods_per_year + ' trade-days/yr');
    if(d.first_ts) metaParts.push(d.first_ts.slice(0,10) + ' → ' + d.last_ts.slice(0,10));
    document.getElementById('qsMeta').textContent = '(' + metaParts.join(' · ') + ')';
    document.getElementById('qsPill').textContent = d.n;
    content.style.display = 'block';
  }catch(e){
    loading.style.display = 'none';
    errBox.style.display = 'block';
    errBox.textContent = 'QuantStats fetch failed: ' + e.message;
  }
}

setInterval(loadAll, 30000);
loadAll();
</script>
</body>
</html>"""
