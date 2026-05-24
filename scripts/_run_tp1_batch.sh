#!/usr/bin/env bash
# Batch-run remaining TP-1 cells: TP-1-d, e, f, g, h
set -e
cd "C:/Users/User/Desktop/TradeAI"

declare -A CELLS=(
  [TP-1-d]="MEDIUM LOW"
  [TP-1-e]="MEDIUM MEDIUM"
  [TP-1-f]="MEDIUM HIGH"
  [TP-1-g]="HIGH MEDIUM"
  [TP-1-h]="HIGH HIGH"
)

for cell in TP-1-d TP-1-e TP-1-f TP-1-g TP-1-h; do
  read fvg mss <<< "${CELLS[$cell]}"
  echo "==================== $cell: FVG=$fvg MSS=$mss ===================="
  python backtest.py --clear-checkpoint > /dev/null 2>&1
  BACKTEST_FVG_MIN_QUALITY=$fvg BACKTEST_MSS_MIN_QUALITY=$mss python backtest.py > "/tmp/bt_${cell//-/_}.log" 2>&1
  python -c "
import sqlite3
con = sqlite3.connect('data/signals.db')
cur = con.cursor()
cur.execute('SELECT id, total_signals, overall_wr FROM backtest_runs ORDER BY id DESC LIMIT 1')
r = cur.fetchone()
print(f'  Run {r[0]}: n={r[1]} WR={r[2]}%')
"
  grep -E "WR \(CPCV\)|Sharpe \(CPCV\)|DSR \(multi|VERDICT" "/tmp/bt_${cell//-/_}.log" | head -4
  echo ""
done
echo "ALL TP-1 CELLS DONE"
