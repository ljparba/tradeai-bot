"""
Tests for config.py (Phase A item #4 / Audit Adopt 3).

Coverage:
  • Default values match the post-A-9 Run-48 baseline (regression guard).
  • Env-var overrides flow through for int / float / bool / str / choice / list.
  • Invalid env values fail loud (don't silently fall back).
  • LIVE_CONFIG_KWARGS / BACKTEST_CONFIG_KWARGS produce StrategyConfig instances
    identical to the pre-refactor inline definitions.
  • crypto_alert top-level constants stay bound to the same objects config exports.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

# Ensure repo root on sys.path when running pytest from anywhere.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── helper: import config fresh after manipulating os.environ ────────────────
def _reload_config(env_overrides=None, env_unset=()):
    """Reload config.py with controlled os.environ state. Returns the module."""
    saved = {}
    try:
        if env_overrides:
            for k, v in env_overrides.items():
                saved[k] = os.environ.get(k)
                os.environ[k] = v
        for k in env_unset:
            saved[k] = os.environ.get(k)
            os.environ.pop(k, None)
        # Drop cached config so re-import re-runs module-level code.
        sys.modules.pop("config", None)
        import config  # noqa: F401  (re-execed)
        return importlib.import_module("config")
    finally:
        # Restore environment so other tests aren't affected.
        for k, original in saved.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        sys.modules.pop("config", None)


# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT-VALUE REGRESSION TESTS (Run-48 baseline)
# ══════════════════════════════════════════════════════════════════════════════
class TestDefaults:
    """Defaults must match Run-48 baseline. Any drift here breaks backtest WR=81.1%."""

    def test_execution_mode_default(self):
        cfg = _reload_config(env_unset=("EXECUTION_MODE",))
        assert cfg.EXECUTION_MODE == "PAPER"

    def test_signal_cadence_defaults(self):
        cfg = _reload_config(env_unset=(
            "CHECK_INTERVAL", "SIGNAL_COOLDOWN", "STALE_CANDLE_THRESHOLD",
        ))
        assert cfg.CHECK_INTERVAL == 90
        assert cfg.SIGNAL_COOLDOWN == 40
        assert cfg.STALE_CANDLE_THRESHOLD == 270  # CHECK_INTERVAL * 3

    def test_indicator_defaults(self):
        cfg = _reload_config(env_unset=(
            "RSI_PERIOD", "RSI_OVERSOLD", "RSI_OVERBOUGHT",
            "ATR_PERIOD", "ATR_SL_MULT", "ROC_PERIOD", "VOLUME_SPIKE",
        ))
        assert cfg.RSI_PERIOD == 14
        assert cfg.RSI_OVERSOLD == 45
        assert cfg.RSI_OVERBOUGHT == 55
        assert cfg.ATR_PERIOD == 14
        assert cfg.ATR_SL_MULT == 1.0
        assert cfg.ROC_PERIOD == 10
        assert cfg.VOLUME_SPIKE == 1.2

    def test_risk_defaults(self):
        cfg = _reload_config(env_unset=(
            "RISK_PER_TRADE_PCT", "MAX_POSITION_PCT",
            "MAX_DAILY_LOSS_PCT", "MAX_WEEKLY_LOSS_PCT",
            "MAX_DAILY_LOSSES", "MAX_CONSECUTIVE_LOSSES", "SYMBOL_LOSS_COOLDOWN_H",
        ))
        assert cfg.RISK_PER_TRADE_PCT == 0.01
        assert cfg.MAX_POSITION_PCT == 0.20
        assert cfg.MAX_DAILY_LOSS_PCT == 0.03
        assert cfg.MAX_WEEKLY_LOSS_PCT == 0.06
        assert cfg.MAX_DAILY_LOSSES == 3
        assert cfg.MAX_CONSECUTIVE_LOSSES == 3
        assert cfg.SYMBOL_LOSS_COOLDOWN_H == 2

    def test_template_safety_defaults(self):
        cfg = _reload_config(env_unset=(
            "TEMPLATE_MIN_SAMPLE", "CIRCUIT_BREAKER_LOOKBACK",
            "CIRCUIT_BREAKER_MIN_WR", "BLOCK_RANGING_LIVE",
        ))
        assert cfg.TEMPLATE_MIN_SAMPLE == 50
        assert cfg.CIRCUIT_BREAKER_LOOKBACK == 20
        assert cfg.CIRCUIT_BREAKER_MIN_WR == 0.55
        assert cfg.BLOCK_RANGING_LIVE is True
        # RISK-GAP-NEW-1 update (cycle-10 audit 2026-05-28): TIER_DAILY_LIVE_CAPS
        # extended with 4 CRT-tier IDs (CRT_A_FVG_ALIGNED / CRT_B_OB_HIGH_MSS /
        # CRT_B_FVG_RELAXED / CRT_C_OB_DEFAULT) so evaluate_template_status()
        # finds a cap for CRT signals instead of defaulting to 0 (silently
        # marking every CRT signal PAPER_ONLY). BLOCK_RANGING_TEMPLATES also
        # adds CRT mid-tier IDs for parity with 5M_SWEEP TIER_B.
        assert cfg.TIER_DAILY_LIVE_CAPS == {
            "TIER_A": 3, "TIER_B": 2, "TIER_C": 0, "NONE": 1,
            "CRT_A_FVG_ALIGNED": 3, "CRT_B_OB_HIGH_MSS": 2,
            "CRT_B_FVG_RELAXED": 2, "CRT_C_OB_DEFAULT": 0,
        }
        assert cfg.BLOCK_RANGING_TEMPLATES == {
            "TIER_B", "NONE", "CRT_B_OB_HIGH_MSS", "CRT_B_FVG_RELAXED",
        }

    def test_signal_threshold_default(self):
        cfg = _reload_config(env_unset=("SIGNAL_THRESHOLD",))
        assert cfg.SIGNAL_THRESHOLD == 35

    def test_weights_sum_to_one(self):
        cfg = _reload_config()
        assert sum(cfg.WEIGHTS.values()) == pytest.approx(1.0, abs=1e-9)

    def test_token_universe_locked(self):
        """SOL/DOT/NEAR/LTC are intentionally excluded — guard against re-adds."""
        cfg = _reload_config()
        assert set(cfg.BINANCE_TOKENS.keys()) == {
            "BTC", "ETH", "XRP", "HBAR", "AVAX", "LINK", "BNB", "ADA", "POL",
        }
        assert "SOL" not in cfg.BINANCE_TOKENS
        assert "DOT" not in cfg.BINANCE_TOKENS

    def test_live_config_kwargs_run48_baseline(self):
        """LIVE_CONFIG_KWARGS must produce the post-A-9 baseline StrategyConfig."""
        cfg = _reload_config(env_unset=(
            "LIVE_ENABLE_BUY", "LIVE_ENABLE_SELL", "LIVE_BIAS_4H_GATE",
            "LIVE_TREND_1H_GATE", "LIVE_DEALING_RANGE_GATE",
            "LIVE_MSS_MIN_QUALITY", "LIVE_FVG_MIN_QUALITY",
            "LIVE_SMT_GATE", "LIQUID_HOURS",
        ))
        live = cfg.LIVE_CONFIG_KWARGS
        assert live["enable_buy"] is True
        assert live["enable_sell"] is True
        assert live["bias_4h_gate"] == "none"
        assert live["trend_1h_gate"] == "loose"
        assert live["dealing_range_gate"] is True
        assert live["mss_min_quality"] == "LOW"
        assert live["fvg_min_quality"] == "HIGH"
        assert live["sell_allowed_regimes"] == {"TRENDING_BEAR"}
        assert live["smt_gate"] is False
        assert live["liquid_hours"] == list(range(24))
        # F-2 (2026-05-22 Session 3): Wed (2) unblocked — original block rested
        # on n=4-6 Wed signals from Run 68, below the 30-signal statistical
        # floor. Re-running backtest under current regime to gather meaningful
        # Wed data. If Wed WR proves >55% at n≥30, keep unblocked; else revert.
        # See config.py:279-281 and CROSS_REF.md row F-2.
        assert live["blocked_weekdays"] == (1, 5)

    def test_backtest_config_kwargs_run48_baseline(self):
        cfg = _reload_config(env_unset=(
            "BACKTEST_ENABLE_BUY", "BACKTEST_ENABLE_SELL", "BACKTEST_BIAS_4H_GATE",
            "BACKTEST_TREND_1H_GATE", "BACKTEST_DEALING_RANGE_GATE",
            "BACKTEST_MSS_MIN_QUALITY", "BACKTEST_FVG_MIN_QUALITY",
            "BACKTEST_SMT_GATE", "LIQUID_HOURS",
        ))
        bt = cfg.BACKTEST_CONFIG_KWARGS
        assert bt["enable_buy"] is True
        assert bt["enable_sell"] is True
        assert bt["bias_4h_gate"] == "none"
        assert bt["trend_1h_gate"] == "loose"
        assert bt["dealing_range_gate"] is False  # DR-1 disabled in backtest
        assert bt["mss_min_quality"] == "LOW"
        assert bt["fvg_min_quality"] == "HIGH"
        assert bt["sell_allowed_regimes"] == {"TRENDING_BEAR"}
        assert bt["smt_gate"] is False
        assert bt["liquid_hours"] == list(range(24))

    def test_regime_rules_intact(self):
        cfg = _reload_config()
        assert cfg.REGIME_RULES["CHOPPY"]["BUY"] == "BLOCK"
        assert cfg.REGIME_RULES["LIQUIDATION"]["SELL"] == "BLOCK"
        assert cfg.REGIME_RULES["TRENDING_BULL"]["min_confirms"] == 2

    def test_expiry_by_regime_intact(self):
        cfg = _reload_config()
        assert cfg.EXPIRY_BY_REGIME["TRENDING_BULL"] == 12
        assert cfg.EXPIRY_BY_REGIME["LIQUIDATION"] == 4
        assert cfg.EXPIRY_BY_REGIME["LOW_VOLATILITY_CHOP"] == 6


# ══════════════════════════════════════════════════════════════════════════════
# ENV-VAR OVERRIDE TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestEnvOverrides:
    def test_int_override(self):
        cfg = _reload_config({"SIGNAL_COOLDOWN": "15"})
        assert cfg.SIGNAL_COOLDOWN == 15

    def test_float_override(self):
        cfg = _reload_config({"RISK_PER_TRADE_PCT": "0.005"})
        assert cfg.RISK_PER_TRADE_PCT == 0.005

    def test_bool_override_truthy_variants(self):
        for raw in ("1", "true", "True", "yes", "Y", "on"):
            cfg = _reload_config({"BLOCK_RANGING_LIVE": raw})
            assert cfg.BLOCK_RANGING_LIVE is True, f"truthy variant {raw!r} failed"

    def test_bool_override_falsy_variants(self):
        for raw in ("0", "false", "False", "no", "N", "off"):
            cfg = _reload_config({"BLOCK_RANGING_LIVE": raw})
            assert cfg.BLOCK_RANGING_LIVE is False, f"falsy variant {raw!r} failed"

    def test_choice_override(self):
        cfg = _reload_config({"LIVE_FVG_MIN_QUALITY": "MEDIUM"})
        assert cfg.LIVE_CONFIG_KWARGS["fvg_min_quality"] == "MEDIUM"

    def test_liquid_hours_override(self):
        cfg = _reload_config({"LIQUID_HOURS": "13,14,15"})
        assert cfg.LIVE_CONFIG_KWARGS["liquid_hours"] == [13, 14, 15]
        assert cfg.BACKTEST_CONFIG_KWARGS["liquid_hours"] == [13, 14, 15]

    def test_liquid_hours_empty_means_all_24h(self):
        cfg = _reload_config({"LIQUID_HOURS": ""})
        assert cfg.LIVE_CONFIG_KWARGS["liquid_hours"] == list(range(24))

    def test_strategy_version_override(self):
        cfg = _reload_config({"STRATEGY_VERSION": "v3-test"})
        assert cfg.STRATEGY_VERSION == "v3-test"

    def test_stale_candle_threshold_responds_to_check_interval_default(self):
        """STALE_CANDLE_THRESHOLD defaults to CHECK_INTERVAL*3, so changing
        CHECK_INTERVAL should propagate when STALE_CANDLE_THRESHOLD itself is unset."""
        cfg = _reload_config({"CHECK_INTERVAL": "60"}, env_unset=("STALE_CANDLE_THRESHOLD",))
        assert cfg.CHECK_INTERVAL == 60
        assert cfg.STALE_CANDLE_THRESHOLD == 180

    def test_stale_candle_threshold_explicit_override(self):
        cfg = _reload_config({"STALE_CANDLE_THRESHOLD": "999"})
        assert cfg.STALE_CANDLE_THRESHOLD == 999


# ══════════════════════════════════════════════════════════════════════════════
# FAIL-LOUD VALIDATION TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestFailLoud:
    def test_invalid_int_raises(self):
        with pytest.raises(ValueError, match="SIGNAL_COOLDOWN"):
            _reload_config({"SIGNAL_COOLDOWN": "not-an-int"})

    def test_invalid_float_raises(self):
        with pytest.raises(ValueError, match="RISK_PER_TRADE_PCT"):
            _reload_config({"RISK_PER_TRADE_PCT": "not-a-float"})

    def test_invalid_bool_raises(self):
        with pytest.raises(ValueError, match="BLOCK_RANGING_LIVE"):
            _reload_config({"BLOCK_RANGING_LIVE": "maybe"})

    def test_invalid_choice_raises(self):
        with pytest.raises(ValueError, match="EXECUTION_MODE"):
            _reload_config({"EXECUTION_MODE": "TURBO"})

    def test_invalid_quality_choice_raises(self):
        with pytest.raises(ValueError, match="LIVE_FVG_MIN_QUALITY"):
            _reload_config({"LIVE_FVG_MIN_QUALITY": "GARBAGE"})

    def test_invalid_liquid_hours_non_int_raises(self):
        with pytest.raises(ValueError, match="LIQUID_HOURS"):
            _reload_config({"LIQUID_HOURS": "13,foo,15"})

    def test_invalid_liquid_hours_out_of_range_raises(self):
        with pytest.raises(ValueError, match="not in 0..23"):
            _reload_config({"LIQUID_HOURS": "13,99"})


# ══════════════════════════════════════════════════════════════════════════════
# DOWNSTREAM-CONSUMER WIRING TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestStrategyEngineWiring:
    def test_strategy_engine_consumes_kwargs(self):
        """strategy_engine.LIVE_CONFIG / BACKTEST_CONFIG must reflect config.py kwargs."""
        _reload_config()  # reset to defaults
        # re-import strategy_engine after config reset
        sys.modules.pop("strategy_engine", None)
        import strategy_engine as se
        assert se.LIVE_CONFIG.bias_4h_gate == "none"
        assert se.LIVE_CONFIG.fvg_min_quality == "HIGH"
        assert se.LIVE_CONFIG.dealing_range_gate is True
        assert se.BACKTEST_CONFIG.dealing_range_gate is False
        assert sorted(se.LIVE_CONFIG.liquid_hours) == list(range(24))


class TestCryptoAlertWiring:
    def test_crypto_alert_reexports_config(self):
        """crypto_alert.py must re-export config values for backtest.py compatibility."""
        sys.modules.pop("crypto_alert", None)
        sys.modules.pop("config", None)
        import config
        import crypto_alert as ca
        # Re-exported tunables share the SAME object identity as config defines them.
        assert ca.SIGNAL_COOLDOWN == config.SIGNAL_COOLDOWN
        assert ca.CHECK_INTERVAL == config.CHECK_INTERVAL
        assert ca.EXECUTION_MODE == config.EXECUTION_MODE
        assert ca.WEIGHTS is config.WEIGHTS
        assert ca.BINANCE_TOKENS is config.BINANCE_TOKENS
        assert ca.REGIME_RULES is config.REGIME_RULES
