#!/usr/bin/env bash
# Batch-run all TP-2 cells: 4H bias × 1H trend grid
# Baseline = bias=none × trend=loose (skip)
set -e
cd "C:/Users/User/Desktop/TradeAI"

declare -A CELLS=(
  [TP-2-a]="none none"
  [TP-2-b]="none strict"
  [TP-2-c]="loose none"
  [TP-2-d]="loose loose"
  [TP-2-e]="loose strict"
  [TP-2-f]="strict none"
  [TP-2-g]="strict loose"
  [TP-2-h]="strict strict"
)

for cell in TP-2-a TP-2-b TP-2-c TP-2-d TP-2-e TP-2-f TP-2-g TP-2-h; do
  read bias trend <<< "${CELLS[$cell]}"
  echo "==================== $cell: 4H=$bias 1H=$trend ===================="
  python backtest.py --clear-checkpoint > /dev/null 2>&1
  BACKTEST_BIAS_4H_GATE=$bias BACKTEST_TREND_1H_GATE=$trend python backtest.py > "/tmp/bt_${cell//-/_}.log" 2>&1
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
echo "ALL TP-2 CELLS DONE"
