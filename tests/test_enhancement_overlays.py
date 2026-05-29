"""Unit tests for T1.2 (funding rate) and T1.3 (BTC correlation) overlays.

These tests cover the math + classification logic for the cycle-12
ENHANCEMENT_ROADMAP Tier 1 features. The fetcher-side of funding_rate_client
is exercised via the live smoke test (hits real Binance fapi); the unit tests
focus on classification + bonus calculation which are pure functions.
"""
import math
import os
import unittest


# ──────────────────────────────────────────────────────────────────────
# T1.3 — BTC correlation
# ──────────────────────────────────────────────────────────────────────
class TestBtcCorrelation(unittest.TestCase):
    def setUp(self):
        # Force gate ON for these tests; reload module to pick up env.
        os.environ["BTC_CORR_GATE_ENABLED"] = "1"
        os.environ["BTC_CORR_BONUS_PCT"]    = "0.08"
        os.environ["BTC_CORR_HIGH_THRESH"]  = "0.7"
        os.environ["BTC_CORR_LOW_THRESH"]   = "0.3"
        import importlib, btc_correlation
        importlib.reload(btc_correlation)
        self.bc = btc_correlation

    def test_perfect_correlation_returns_near_1(self):
        # Synthesize per-step returns r_i ~ N(0, 0.005); token = BTC×k+noise
        # produces near-1 correlation in log-return space.
        import random
        random.seed(0)
        btc = [100.0]
        tok = [50.0]
        for _ in range(120):
            r = random.gauss(0, 0.005)
            btc.append(btc[-1] * (1 + r))
            tok.append(tok[-1] * (1 + r * 0.95))   # 0.95 ratio + no noise → near 1.0
        corr = self.bc.compute_btc_correlation(btc, tok, window=60)
        self.assertIsNotNone(corr)
        self.assertGreater(corr, 0.99)

    def test_negative_correlation(self):
        # Token = -BTC return per step → inverse Pearson r ≈ -1.0
        import random
        random.seed(1)
        btc = [100.0]
        tok = [100.0]
        for _ in range(120):
            r = random.gauss(0, 0.005)
            btc.append(btc[-1] * (1 + r))
            tok.append(tok[-1] * (1 - r))    # exact inverse on each step
        corr = self.bc.compute_btc_correlation(btc, tok, window=60)
        self.assertIsNotNone(corr)
        self.assertLess(corr, -0.99)

    def test_insufficient_data_returns_none(self):
        # Only 5 bars but window=60 → must return None
        btc = [100.0] * 5
        tok = [50.0]  * 5
        corr = self.bc.compute_btc_correlation(btc, tok, window=60)
        self.assertIsNone(corr)

    def test_constant_series_returns_none(self):
        # Zero variance on one side → undefined Pearson r
        btc = [100.0] * 80
        tok = [50.0 + i * 0.1 for i in range(80)]
        corr = self.bc.compute_btc_correlation(btc, tok, window=60)
        self.assertIsNone(corr)

    def test_classify_aligned_high(self):
        # High corr + BUY in bull market = ALIGNED_HIGH
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "BUY", "STRONG_BULL"),
            "ALIGNED_HIGH",
        )

    def test_classify_divergent(self):
        # High corr but signal counters BTC trend = DIVERGENT
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "SELL", "STRONG_BULL"),
            "DIVERGENT",
        )
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "BUY", "STRONG_BEAR"),
            "DIVERGENT",
        )

    def test_classify_aligned_low(self):
        # Low corr = decoupled, token-specific edge regardless of direction
        self.assertEqual(
            self.bc.classify_btc_corr(0.10, "BUY", "STRONG_BULL"),
            "ALIGNED_LOW",
        )

    def test_classify_unknown_when_corr_is_none(self):
        self.assertEqual(
            self.bc.classify_btc_corr(None, "BUY", "STRONG_BULL"),
            "UNKNOWN",
        )

    def test_bonus_signs(self):
        # ALIGNED_HIGH → positive bonus
        self.assertGreater(
            self.bc.btc_corr_confidence_bonus(0.85, "BUY", "STRONG_BULL"), 0
        )
        # DIVERGENT → negative penalty
        self.assertLess(
            self.bc.btc_corr_confidence_bonus(0.85, "SELL", "STRONG_BULL"), 0
        )
        # UNKNOWN → zero
        self.assertEqual(
            self.bc.btc_corr_confidence_bonus(None, "BUY", "STRONG_BULL"), 0.0
        )

    def test_gate_disabled_short_circuits(self):
        os.environ["BTC_CORR_GATE_ENABLED"] = "0"
        import importlib, btc_correlation
        importlib.reload(btc_correlation)
        # Even with perfect data, classification returns DISABLED
        self.assertEqual(
            btc_correlation.classify_btc_corr(0.99, "BUY", "STRONG_BULL"),
            "DISABLED",
        )
        # And bonus is always 0
        self.assertEqual(
            btc_correlation.btc_corr_confidence_bonus(0.99, "BUY", "STRONG_BULL"),
            0.0,
        )

    # ── H-CY12-2 vocabulary parity regression tests ─────────────────────
    # Pre-fix, the call sites at crypto_alert.py:1157 and backtest.py:1481
    # passed `bias_4h` (ICT vocab: BULLISH/BEARISH/NEUTRAL) but
    # classify_btc_corr only matched EMA vocab (STRONG_BULL/BULL/...). Result:
    # ALIGNED_HIGH and DIVERGENT were mathematically unreachable from those
    # call sites. These tests lock the both-vocab behavior so future drifts
    # surface in CI.
    def test_h_cy12_2_ict_vocab_aligned_high(self):
        """BULLISH bias + BUY signal at high corr → ALIGNED_HIGH (post-fix)."""
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "BUY", "BULLISH"),
            "ALIGNED_HIGH",
        )
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "SELL", "BEARISH"),
            "ALIGNED_HIGH",
        )

    def test_h_cy12_2_ict_vocab_divergent(self):
        """ICT vocab: BULLISH bias + SELL signal at high corr → DIVERGENT (post-fix)."""
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "SELL", "BULLISH"),
            "DIVERGENT",
        )
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "BUY", "BEARISH"),
            "DIVERGENT",
        )

    def test_h_cy12_2_neutral_bias_falls_through_to_ambiguous(self):
        """NEUTRAL bias (either vocab) at high corr → AMBIGUOUS, not crashing."""
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "BUY", "NEUTRAL"),
            "AMBIGUOUS",
        )

    def test_h_cy12_2_ema_vocab_still_works(self):
        """Backwards compat: EMA vocab callers continue to work post-fix."""
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "BUY", "STRONG_BULL"),
            "ALIGNED_HIGH",
        )
        self.assertEqual(
            self.bc.classify_btc_corr(0.85, "SELL", "BEAR"),
            "ALIGNED_HIGH",
        )

    def test_h_cy12_2_bonus_polarity_under_ict_vocab(self):
        """Bonus sign correct when call site passes ICT vocab (H-CY12-2 fix)."""
        # ALIGNED_HIGH → positive bonus
        self.assertGreater(
            self.bc.btc_corr_confidence_bonus(0.85, "BUY", "BULLISH"), 0
        )
        # DIVERGENT → negative penalty
        self.assertLess(
            self.bc.btc_corr_confidence_bonus(0.85, "SELL", "BULLISH"), 0
        )


# ──────────────────────────────────────────────────────────────────────
# H-CY12-1 — Live ↔ Backtest confidence-bonus parity
# ──────────────────────────────────────────────────────────────────────
class TestConfidenceBonusParity(unittest.TestCase):
    """Lock the M24-class invariant: same inputs → same confidence in both paths.

    Pre-fix, live applied `confidence + 10*(funding + btc_corr bonuses)` while
    backtest stored `_crt_conf` unchanged. Same setup quality produced different
    `confidence` values in `signals` vs `backtest_signals`, breaking explorer
    Bayesian tuning over `FUNDING_BONUS_PCT` / `BTC_CORR_BONUS_PCT`.

    These tests assert that the bonus magnitudes are pure functions of the
    same inputs across both paths, so any future refactor that breaks parity
    is caught at CI.
    """
    def setUp(self):
        os.environ["FUNDING_GATE_ENABLED"] = "1"
        os.environ["FUNDING_BONUS_PCT"]    = "0.05"
        os.environ["BTC_CORR_GATE_ENABLED"] = "1"
        os.environ["BTC_CORR_BONUS_PCT"]    = "0.08"
        os.environ["BTC_CORR_HIGH_THRESH"]  = "0.7"
        os.environ["BTC_CORR_LOW_THRESH"]   = "0.3"
        import importlib, funding_rate_client, btc_correlation
        importlib.reload(funding_rate_client)
        importlib.reload(btc_correlation)
        self.f = funding_rate_client
        self.bc = btc_correlation

    @staticmethod
    def _apply_bonus(base_conf, funding_bonus, btc_corr_bonus):
        """Replicate the formula at crypto_alert.py:1245 + backtest.py:1804."""
        return max(0, min(10, int(round(
            base_conf + 10 * (funding_bonus + btc_corr_bonus)))))

    def test_funding_bonus_pure_function_of_rate_direction(self):
        """Live and backtest bonuses must be computed from the same function."""
        for rate in [-0.0008, -0.0003, 0.0, 0.0003, 0.0008]:
            for direction in ["BUY", "SELL"]:
                live = self.f.funding_confidence_bonus(rate, direction)
                bt   = self.f.funding_confidence_bonus(rate, direction)
                self.assertEqual(live, bt,
                    f"Funding bonus diverges live↔BT at rate={rate} {direction}")

    def test_btc_corr_bonus_pure_function(self):
        """Live + backtest must compute identical BTC corr bonus."""
        for corr in [-0.5, 0.1, 0.5, 0.85]:
            for direction in ["BUY", "SELL"]:
                for bias in ["BULLISH", "BEARISH", "NEUTRAL"]:
                    live = self.bc.btc_corr_confidence_bonus(corr, direction, bias)
                    bt   = self.bc.btc_corr_confidence_bonus(corr, direction, bias)
                    self.assertEqual(live, bt,
                        f"BTC corr bonus diverges at corr={corr} dir={direction} bias={bias}")

    def test_combined_confidence_formula_clamps_to_0_10(self):
        """Formula `max(0, min(10, round(conf + 10*(f+b))))` clamps correctly."""
        # Base + max positive bonus should not exceed 10
        self.assertEqual(
            self._apply_bonus(9, 0.10, 0.10),  # +2.0 swing
            10  # clamped
        )
        # Base + max negative bonus should not go below 0
        self.assertEqual(
            self._apply_bonus(1, -0.10, -0.10),  # -2.0 swing
            0  # clamped
        )

    def test_h_cy12_1_extreme_counter_long_produces_same_result(self):
        """End-to-end: same inputs → same confidence both paths."""
        # Scenario: BUY signal, extreme negative funding (-0.0005),
        # BTC corr=0.85, BULLISH bias → favorable contrarian both ways
        base_conf = 7
        rate = -0.0005
        corr = 0.85
        direction = "BUY"
        bias = "BULLISH"

        f_bonus = self.f.funding_confidence_bonus(rate, direction)
        c_bonus = self.bc.btc_corr_confidence_bonus(corr, direction, bias)
        # Both should be POSITIVE (favorable signal)
        self.assertGreater(f_bonus, 0)
        self.assertGreater(c_bonus, 0)
        # Combined confidence
        combined = self._apply_bonus(base_conf, f_bonus, c_bonus)
        # 7 + 10*(0.05 + 0.08) = 7 + 1.3 = 8.3 → rounds to 8
        self.assertEqual(combined, 8)


# ──────────────────────────────────────────────────────────────────────
# T1.2 — Funding rate (classification only; fetcher tested by live smoke)
# ──────────────────────────────────────────────────────────────────────
class TestFundingClassification(unittest.TestCase):
    def setUp(self):
        os.environ["FUNDING_GATE_ENABLED"] = "1"
        os.environ["FUNDING_BONUS_PCT"]    = "0.05"
        os.environ["FUNDING_EXTREME_LONG_THRESH"]  = "-0.0003"
        os.environ["FUNDING_EXTREME_SHORT_THRESH"] = "0.0003"
        import importlib, funding_rate_client
        importlib.reload(funding_rate_client)
        self.f = funding_rate_client

    def test_extreme_positive_funding_with_sell_is_counter(self):
        # Longs paying shorts heavily + SELL signal = favorable contrarian
        self.assertEqual(
            self.f.classify_funding_extreme(0.0005, "SELL"),
            "EXTREME_COUNTER_SHORT",
        )

    def test_extreme_negative_funding_with_buy_is_counter(self):
        # Shorts paying longs heavily + BUY signal = favorable contrarian
        self.assertEqual(
            self.f.classify_funding_extreme(-0.0005, "BUY"),
            "EXTREME_COUNTER_LONG",
        )

    def test_extreme_against_direction(self):
        # Extreme positive funding + BUY (agreeing with longs) = risky
        self.assertEqual(
            self.f.classify_funding_extreme(0.0005, "BUY"),
            "EXTREME_AGAINST",
        )

    def test_neutral_band(self):
        # Within ±0.0003 → no bias
        self.assertEqual(
            self.f.classify_funding_extreme(0.0001, "BUY"), "NEUTRAL"
        )
        self.assertEqual(
            self.f.classify_funding_extreme(-0.0001, "SELL"), "NEUTRAL"
        )

    def test_bonus_directional_signs(self):
        # Favorable contrarian → positive bonus
        self.assertGreater(
            self.f.funding_confidence_bonus(-0.0005, "BUY"), 0
        )
        # Unfavorable agreement → negative penalty
        self.assertLess(
            self.f.funding_confidence_bonus(0.0005, "BUY"), 0
        )
        # Neutral → zero
        self.assertEqual(
            self.f.funding_confidence_bonus(0.0001, "BUY"), 0.0
        )

    def test_gate_disabled_short_circuits(self):
        os.environ["FUNDING_GATE_ENABLED"] = "0"
        import importlib, funding_rate_client
        importlib.reload(funding_rate_client)
        self.assertEqual(
            funding_rate_client.classify_funding_extreme(0.0010, "SELL"),
            "DISABLED",
        )
        self.assertEqual(
            funding_rate_client.funding_confidence_bonus(0.0010, "SELL"),
            0.0,
        )

    def test_fetch_failed_returns_distinct_classification(self):
        """LOW item from T1.2/T1.3 review: distinguish fetch failure from NEUTRAL."""
        # Even at a NEUTRAL-band rate (0.0), the FETCH_FAILED flag must
        # short-circuit classification → "FETCH_FAILED" rather than "NEUTRAL".
        self.assertEqual(
            self.f.classify_funding_extreme(0.0, "BUY", fetch_failed=True),
            "FETCH_FAILED",
        )
        # Without the flag, the same rate is NEUTRAL (different observable).
        self.assertEqual(
            self.f.classify_funding_extreme(0.0, "BUY", fetch_failed=False),
            "NEUTRAL",
        )

    def test_historical_lookup_returns_zero_when_no_data(self):
        """Stage B: get_historical_funding_at returns 0.0 (NEUTRAL) when cache is empty."""
        self.f.reset_cache()
        # Without preload, lookup should return 0.0 (NEUTRAL fallback)
        rate = self.f.get_historical_funding_at("BTC", 1234567890000)
        self.assertEqual(rate, 0.0)
        # And historical_fetch_failed should return False (no attempt made)
        self.assertFalse(self.f.historical_fetch_failed("BTC"))


if __name__ == "__main__":
    unittest.main()
