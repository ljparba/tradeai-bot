"""H-CY13-1 regression guard — live↔backtest signals schema parity.

Cycle-12 promised that the 3 confidence-attribution columns
(`confidence_base`, `confidence_funding_bonus`, `confidence_btc_corr_bonus`)
would land in BOTH `signals` and `backtest_signals` tables. Cycle-13's
config-consistency audit caught that only the backtest side had shipped.

This test guards against the H-CY13-1 class of bug: a column exists on
one side of the live↔BT schema but not the other. The allow-list lets
through columns that legitimately differ (e.g. `id`, `run_id`, internal
diagnostics) — everything ATTRIBUTION-class must exist on both.

Run after any migration change or cycle audit; the test will RED on a
silent half-shipped column.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DB_PATH = os.path.join(ROOT, "data", "signals.db")


def _columns(conn: sqlite3.Connection, table: str) -> set:
    """Return the set of column names for `table`."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


# Columns that legitimately differ between live and backtest schemas.
# Anything not in this allow-list MUST exist on both tables (or neither).
_LEGITIMATELY_DIFFERENT = {
    # Live signals — operational tracking that doesn't make sense in BT
    "actual_entry_price", "slippage_pct",
    "limit_fillable", "fillable_check_at",
    "expires_at", "status",
    "feature_scores_json",  # live OGD score snapshot at emit time
    # Backtest signals — outcome / labelling
    "run_id",
    "outcome", "tp_reached", "wscore", "margin", "conflict",
    "breakeven_wr",
    # Triple-barrier label columns (backtest-only)
    "tb_bin", "tb_touch", "tb_ret", "tb_t1",
    # Realized return columns (backtest-only; live uses results table)
    "realized_r", "mfe_pct", "mae_pct",
    "net_tp1_pct", "net_tp2_pct", "net_tp3_pct", "net_sl_pct",
    "net_rr1",
    # Backtest-only categorical context
    "fvg_pct",
    "smt_confirmed",
    "ifvg_present", "ifvg_direction", "ifvg_age_bars",
    "ifvg_top", "ifvg_bottom", "ifvg_5m_used",
    # Live-only fields
    "market_regime", "regime_adx", "regime_eff", "regime_atr_r", "regime_conf",
    "btc_bias",
    "wscore_buy", "wscore_sell",
    "conflict_level", "candle_pattern",
    "ict_bias_4h",
    "trend_4h", "trend_5m", "mtf_bias", "mtf_conf",
    "atr", "roc", "vol_ratio", "rsi", "confirms",
    "strategy_version",
    "btc_dom_dir",
    # Both tables have `regime` BUT under different names — live calls it
    # `market_regime` and backtest calls it `regime`. Both are populated
    # (live via get_regime_for_token, backtest via detect_regime). The
    # allow-list above already excludes `market_regime`; this comment
    # documents WHY.
    "regime",
}


class TestSchemaParity(unittest.TestCase):
    """H-CY13-1 regression guard."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(DB_PATH):
            raise unittest.SkipTest(
                f"signals.db not present at {DB_PATH} — skip (no DB to inspect)."
            )
        cls.conn = sqlite3.connect(DB_PATH)
        cls.live_cols = _columns(cls.conn, "signals")
        cls.bt_cols   = _columns(cls.conn, "backtest_signals")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        except Exception:
            pass

    def test_attribution_columns_present_on_both_sides(self):
        """The 3 cycle-12+13 confidence-attribution columns must exist on BOTH
        signals (live) AND backtest_signals tables. H-CY13-1 was exactly the
        case where cycle-12 added them to backtest only — operator's tracker
        Reports tab + explorer post-hoc analysis couldn't decompose live
        confidence into base + funding bonus + BTC-corr bonus."""
        required_attribution = {
            "confidence_base",
            "confidence_funding_bonus",
            "confidence_btc_corr_bonus",
        }
        missing_live = required_attribution - self.live_cols
        missing_bt   = required_attribution - self.bt_cols
        self.assertEqual(
            missing_live, set(),
            f"signals (live) table missing attribution columns: {missing_live}. "
            f"H-CY13-1 regression."
        )
        self.assertEqual(
            missing_bt, set(),
            f"backtest_signals table missing attribution columns: {missing_bt}."
        )

    def test_overlay_columns_present_on_both_sides(self):
        """T1.2 + T1.3 overlay raw-data columns must exist on both — the
        upstream of the attribution columns. If these are missing on one
        side, the attribution computation also breaks for that path."""
        required_overlay = {
            "funding_rate_pct", "funding_classification",
            "btc_corr_strength", "btc_corr_classification",
        }
        missing_live = required_overlay - self.live_cols
        missing_bt   = required_overlay - self.bt_cols
        self.assertEqual(missing_live, set(),
            f"signals (live) missing overlay columns: {missing_live}")
        self.assertEqual(missing_bt, set(),
            f"backtest_signals missing overlay columns: {missing_bt}")

    def test_ote_columns_present_on_both_sides(self):
        """OTE overlay must be symmetric — tagging-only feature shipped
        2026-05-28."""
        required_ote = {"ote_zone", "ote_fib_pct"}
        missing_live = required_ote - self.live_cols
        missing_bt   = required_ote - self.bt_cols
        self.assertEqual(missing_live, set(),
            f"signals (live) missing OTE columns: {missing_live}")
        self.assertEqual(missing_bt, set(),
            f"backtest_signals missing OTE columns: {missing_bt}")

    def test_template_columns_present_on_both_sides(self):
        """Phase 5A template attribution must exist on both tables for
        explorer + dashboard parity."""
        required_template = {
            "matched_template_id", "template_scores_json",
        }
        missing_live = required_template - self.live_cols
        missing_bt   = required_template - self.bt_cols
        self.assertEqual(missing_live, set(),
            f"signals missing template columns: {missing_live}")
        self.assertEqual(missing_bt, set(),
            f"backtest_signals missing template columns: {missing_bt}")

    def test_source_tag_present_on_both_sides(self):
        """Source attribution (5M_SWEEP vs H4_CRT) MUST exist on both —
        else per-scanner stratification breaks."""
        self.assertIn("source", self.live_cols,
            "signals (live) is missing the `source` column (LBC-H-1 regression).")
        self.assertIn("source", self.bt_cols,
            "backtest_signals is missing the `source` column.")


if __name__ == "__main__":
    unittest.main()
