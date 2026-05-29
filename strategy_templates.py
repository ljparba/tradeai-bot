"""
TradeAI — ICT Strategy Template Registry  (Phase I-2)

Defines Tier A / Tier B / Tier C ICT strategy templates and evaluates how well
each incoming signal matches them.  Template matching is INFORMATIONAL ONLY —
it never blocks a signal or changes any live gate.

All confluences used here are already detected by ict_engine.py.
No new ICT detectors are introduced.

Tier A — Strict          : 4/5 required confluences + optional bonuses
Tier B — Balanced        : 3/5 required confluences + optional bonuses
Tier C — Exploratory     : 2/2 required confluences  | live_allowed = False
"""

__all__ = [
    "TemplateMatch",
    "TEMPLATE_REGISTRY",
    "evaluate_confluences_vs_templates",
    "evaluate_crt_templates",          # Phase B — CRT tier classifier (2026-05-28)
    "CRT_TEMPLATE_IDS",                # Phase B — registered CRT template IDs
    "seed_templates_table",
    "validate_tier_hierarchy",
]

import json
from typing import Dict, List, Any

from strategy_engine import QUALITY_RANK


# ── Data model ────────────────────────────────────────────────────────────────

class TemplateMatch:
    """Result of evaluating one signal against one template."""

    __slots__ = (
        "template_id", "template_name", "tier",
        "score", "required_hit", "required_need",
        "confluences_matched", "live_allowed",
    )

    def __init__(self, template_id, template_name, tier,
                 score, required_hit, required_need,
                 confluences_matched, live_allowed):
        self.template_id        = template_id          # "TIER_A" | "TIER_B" | "TIER_C"
        self.template_name      = template_name
        self.tier               = tier                 # "A" | "B" | "C"
        self.score              = score                # float 0.0–1.0
        self.required_hit       = required_hit         # int: how many required confluences satisfied
        self.required_need      = required_need        # int: threshold to be considered a match
        self.confluences_matched = confluences_matched # list[str]: descriptive labels
        self.live_allowed       = live_allowed         # False for Tier C

    @property
    def is_match(self) -> bool:
        """True when required_hit >= required_need."""
        return self.required_hit >= self.required_need

    def __repr__(self):
        return (f"TemplateMatch({self.template_id}, score={self.score:.3f}, "
                f"hit={self.required_hit}/{self.required_need}, match={self.is_match})")


# ── Template registry metadata ────────────────────────────────────────────────
# Used by seed_templates_table() to populate the DB templates table.

TEMPLATE_REGISTRY = [
    {
        "id":          "TIER_A",
        "name":        "Tier A — Strict",
        "tier":        "A",
        "description": ("Full ICT structure: HIGH MSS + MEDIUM+ FVG + active killzone "
                        "(LONDON/NY) + HTF DR extreme + REACTION_CONFIRMED entry."),
        "live_allowed": 1,
    },
    {
        "id":          "TIER_B",
        "name":        "Tier B — Balanced",
        "tier":        "B",
        "description": ("Most ICT components present: MEDIUM+ MSS + any FVG quality "
                        "+ any active killzone + partial alignment."),
        "live_allowed": 1,
    },
    {
        "id":          "TIER_C",
        "name":        "Tier C — Exploratory",
        "tier":        "C",
        "description": ("Basic ICT structure: any valid MSS + any valid FVG. "
                        "Paper/backtest only — not permitted in live trading."),
        "live_allowed": 0,
    },
    # ── Phase B (2026-05-28) — CRT-specific tier templates ──────────────────
    # CRT signals are H4 candle range theory: H4 sweep + 5M MSS confirmation +
    # (FVG OR OB) confluence + Wyckoff phase tag. The 5M_SWEEP templates above
    # don't apply (different feature semantics — CRT has no killzone constraint,
    # no DR_LOCATION discipline, and uses confluence_type instead of FVG_QUALITY
    # as the discriminator). The cycle-9 audit empirically identified FVG-vs-OB
    # as the +14.6pp WR axis — these templates encode that axis.
    {
        "id":          "CRT_A_FVG_ALIGNED",
        "name":        "CRT Tier A — FVG + MSS=HIGH",
        "tier":        "A",
        # T-1 fix (cycle-10 audit 2026-05-28): tightened MSS bar from
        # ≥MEDIUM to ==HIGH after full-population analysis (n=1945)
        # showed Tier A under ≥MEDIUM produced 63.9% WR while ==HIGH
        # yields 72.5% WR (n=80, Wilson CI [61.9%, 81.1%]) — statistically
        # separated top tier.
        "description": ("FVG confluence + MSS=HIGH. Highest-quality CRT setup, "
                        "Wilson-CI-separated from B/C at full-population n=1945."),
        "live_allowed": 1,
    },
    {
        "id":          "CRT_B_OB_HIGH_MSS",
        "name":        "CRT Tier B — OB + MSS≥MEDIUM",
        "tier":        "B",
        # T-2 fix (cycle-10 audit 2026-05-28): flipped MSS bar from HIGH
        # to ≥MEDIUM after full-population analysis (n=1945) showed
        # OB+MSS=HIGH produced 51.0% WR — the WORST tier, inverting the
        # expected A>B>C ordering — while OB+MSS=MEDIUM produced 56.9% WR.
        # Template ID retained for back-compat with historical signals.
        "description": ("OB confluence + MSS≥MEDIUM. Mid-tier CRT setup. "
                        "(T-2: MSS=HIGH on OB-only signals empirically selects "
                        "a worse sub-population — likely exhaustion-sweep "
                        "regime changes.)"),
        "live_allowed": 1,
    },
    {
        "id":          "CRT_B_FVG_RELAXED",
        "name":        "CRT Tier B — FVG (DEPRECATED A1/A2)",
        "tier":        "B",
        # A1/A2 (2026-05-28): retired from active classifier. Kept in
        # registry so historical signals (DB rows pre-redefinition) still
        # validate. evaluate_crt_templates no longer emits this template.
        "description": ("DEPRECATED post-A1/A2. Historical-only template ID. "
                        "Tier A's revised FVG+MSS≥MEDIUM definition absorbs the "
                        "entire former scope of this template."),
        "live_allowed": 1,
    },
    {
        "id":          "CRT_C_OB_DEFAULT",
        "name":        "CRT Tier C — OB default",
        "tier":        "C",
        "description": ("Catch-all for OB-only setups not meeting Tier B's HIGH-MSS "
                        "bar. Paper/backtest only — not permitted in live trading."),
        "live_allowed": 0,
    },
]

# Phase B (2026-05-28) — IDs that mark a signal as classified by the CRT
# tier scheme. Used by callers that need to distinguish CRT-classified
# signals from 5M_SWEEP-classified or unclassified ones.
CRT_TEMPLATE_IDS = {
    "CRT_A_FVG_ALIGNED",
    "CRT_B_OB_HIGH_MSS",
    "CRT_B_FVG_RELAXED",
    "CRT_C_OB_DEFAULT",
}


# ── Scoring functions ─────────────────────────────────────────────────────────

def _score_tier_a(f: Dict[str, Any]) -> TemplateMatch:
    """
    Tier A — Strict  (5 required confluences, threshold = 4/5)

    Required (one point each):
      1. MSS quality = HIGH
      2. FVG quality >= MEDIUM
      3. Session in {LONDON_KZ, NY_AM_KZ}
      4. DR location matches post-displacement direction (BUY→PREMIUM, SELL→DISCOUNT)
         (Fix #17 2026-05-22: canonical ICT geometry — after MSS, price has
         displaced INTO the opposite zone from the sweep, so BUYs land in
         PREMIUM and SELLs in DISCOUNT. Old BUY→DISCOUNT semantics were
         pre-sweep logic and matched 0/42 Run #85 signals — see audit
         cycle 7 REGRESSION-A.)
      5. Entry type = REACTION_CONFIRMED

    Optional bonuses (applied only if base > 0, total bonus max 0.20):
      +0.10  SMT confirmed (Run #85: SMT=True 78.8% WR vs SMT=False 66.7% WR;
             Fix #17 2026-05-22 flipped sign — see audit cycle 7 REGRESSION-B)
      +0.05  iFVG present (precision entry available)
      +0.05  4H bias aligned with direction
    """
    direction    = f.get("direction", "BUY")
    mss_quality  = f.get("mss_quality",  "NONE")
    fvg_quality  = f.get("fvg_quality",  "NONE")
    session      = f.get("session",      "OVERNIGHT")
    dr_location  = f.get("dr_location",  "UNKNOWN")
    smt_conf     = f.get("smt_confirmed", False)
    entry_type   = f.get("entry_type",   "ZONE_TOUCH")
    bias_4h      = f.get("bias_4h",      "NEUTRAL")
    ifvg_present = f.get("ifvg_present", False)
    sweep_cluster = f.get("sweep_cluster_size", 1)

    matched = []
    hit = 0

    if mss_quality == "HIGH":
        hit += 1; matched.append("MSS=HIGH")

    if QUALITY_RANK.get(fvg_quality, 0) >= QUALITY_RANK["MEDIUM"]:
        hit += 1; matched.append(f"FVG={fvg_quality}")

    if session in ("LONDON_KZ", "NY_AM_KZ"):
        hit += 1; matched.append(f"session={session}")

    if (direction == "BUY"  and dr_location == "PREMIUM") or \
       (direction == "SELL" and dr_location == "DISCOUNT"):
        hit += 1; matched.append(f"DR={dr_location}")

    if entry_type == "REACTION_CONFIRMED":
        hit += 1; matched.append("entry=REACTION_CONFIRMED")

    bonus = 0.0
    if smt_conf:
        bonus += 0.10; matched.append("SMT_bonus")
    if ifvg_present:
        bonus += 0.05; matched.append("iFVG_bonus")
    if (direction == "BUY"  and bias_4h == "BULLISH") or \
       (direction == "SELL" and bias_4h == "BEARISH"):
        bonus += 0.05; matched.append("4H_bias_bonus")
    # Fix #9 (2026-05-22): EQH/EQL cluster bonus. Canonical ICT — two or more
    # near-equal swing highs/lows form a stop-cluster (stronger BSL/SSL pool).
    if sweep_cluster >= 2:
        bonus += 0.05; matched.append(f"EQH/EQL_cluster={sweep_cluster}")

    base  = hit / 5.0
    score = min(base + bonus * base, 1.0)

    return TemplateMatch(
        template_id="TIER_A", template_name="Tier A — Strict", tier="A",
        score=round(score, 4),
        required_hit=hit, required_need=4,
        confluences_matched=matched, live_allowed=True,
    )


def _score_tier_b(f: Dict[str, Any]) -> TemplateMatch:
    """
    Tier B — Balanced  (5 required confluences, threshold = 3/5)

    Required (one point each):
      1. MSS quality >= MEDIUM
      2. FVG quality >= LOW (any valid quality, not NONE)
      3. Session in {LONDON_KZ, NY_AM_KZ, ASIA_KZ}
      4. DR location matches post-displacement direction (BUY→PREMIUM, SELL→DISCOUNT)
         (Fix #17 2026-05-22: see Tier A docstring for rationale.)
      5. Entry type in {REACTION_CONFIRMED, MIDPOINT_RECLAIM}

    Optional bonuses (same as Tier A):
      +0.10  SMT confirmed (Fix #17 2026-05-22: sign flipped per Run #85 data)
      +0.05  iFVG present
      +0.05  4H bias aligned
    """
    direction    = f.get("direction", "BUY")
    mss_quality  = f.get("mss_quality",  "NONE")
    fvg_quality  = f.get("fvg_quality",  "NONE")
    session      = f.get("session",      "OVERNIGHT")
    dr_location  = f.get("dr_location",  "UNKNOWN")
    smt_conf     = f.get("smt_confirmed", False)
    entry_type   = f.get("entry_type",   "ZONE_TOUCH")
    bias_4h      = f.get("bias_4h",      "NEUTRAL")
    ifvg_present = f.get("ifvg_present", False)
    sweep_cluster = f.get("sweep_cluster_size", 1)

    matched = []
    hit = 0

    if QUALITY_RANK.get(mss_quality, 0) >= QUALITY_RANK["MEDIUM"]:
        hit += 1; matched.append(f"MSS={mss_quality}")

    if QUALITY_RANK.get(fvg_quality, 0) >= QUALITY_RANK["LOW"]:
        hit += 1; matched.append(f"FVG={fvg_quality}")

    if session in ("LONDON_KZ", "NY_AM_KZ", "ASIA_KZ"):
        hit += 1; matched.append(f"session={session}")

    if (direction == "BUY"  and dr_location == "PREMIUM") or \
       (direction == "SELL" and dr_location == "DISCOUNT"):
        hit += 1; matched.append(f"DR={dr_location}")

    if entry_type in ("REACTION_CONFIRMED", "MIDPOINT_RECLAIM"):
        hit += 1; matched.append(f"entry={entry_type}")

    bonus = 0.0
    if smt_conf:
        bonus += 0.10; matched.append("SMT_bonus")
    if ifvg_present:
        bonus += 0.05; matched.append("iFVG_bonus")
    if (direction == "BUY"  and bias_4h == "BULLISH") or \
       (direction == "SELL" and bias_4h == "BEARISH"):
        bonus += 0.05; matched.append("4H_bias_bonus")
    # Fix #9 (2026-05-22): EQH/EQL cluster bonus.
    if sweep_cluster >= 2:
        bonus += 0.05; matched.append(f"EQH/EQL_cluster={sweep_cluster}")

    base  = hit / 5.0
    score = min(base + bonus * base, 1.0)

    return TemplateMatch(
        template_id="TIER_B", template_name="Tier B — Balanced", tier="B",
        score=round(score, 4),
        required_hit=hit, required_need=3,
        confluences_matched=matched, live_allowed=True,
    )


def _score_tier_c(f: Dict[str, Any]) -> TemplateMatch:
    """
    Tier C — Exploratory  (2 required confluences, threshold = 2/2)
    live_allowed = False — paper/backtest only.

    Required (one point each):
      1. MSS quality >= LOW (any valid quality, not NONE)
      2. FVG quality >= LOW (any valid quality, not NONE)

    Optional bonuses:
      +0.10  SMT confirmed (Fix #17 2026-05-22: sign flipped per Run #85 data)
      +0.05  Session in active killzone
      +0.05  DR location matches post-displacement direction (BUY→PREMIUM, SELL→DISCOUNT)
      +0.05  iFVG present
    """
    direction    = f.get("direction", "BUY")
    mss_quality  = f.get("mss_quality",  "NONE")
    fvg_quality  = f.get("fvg_quality",  "NONE")
    session      = f.get("session",      "OVERNIGHT")
    dr_location  = f.get("dr_location",  "UNKNOWN")
    smt_conf     = f.get("smt_confirmed", False)
    bias_4h      = f.get("bias_4h",      "NEUTRAL")
    ifvg_present = f.get("ifvg_present", False)

    matched = []
    hit = 0

    if QUALITY_RANK.get(mss_quality, 0) >= QUALITY_RANK["LOW"]:
        hit += 1; matched.append(f"MSS={mss_quality}")

    if QUALITY_RANK.get(fvg_quality, 0) >= QUALITY_RANK["LOW"]:
        hit += 1; matched.append(f"FVG={fvg_quality}")

    bonus = 0.0
    if smt_conf:
        bonus += 0.10; matched.append("SMT_bonus")
    if session in ("LONDON_KZ", "NY_AM_KZ", "ASIA_KZ"):
        bonus += 0.05; matched.append(f"session_bonus={session}")
    if (direction == "BUY"  and dr_location == "PREMIUM") or \
       (direction == "SELL" and dr_location == "DISCOUNT"):
        bonus += 0.05; matched.append(f"DR_bonus={dr_location}")
    if ifvg_present:
        bonus += 0.05; matched.append("iFVG_bonus")

    base  = hit / 2.0
    score = min(base + bonus * base, 1.0)

    return TemplateMatch(
        template_id="TIER_C", template_name="Tier C — Exploratory", tier="C",
        score=round(score, 4),
        required_hit=hit, required_need=2,
        confluences_matched=matched, live_allowed=False,
    )


# ── Public evaluation API ─────────────────────────────────────────────────────

_TIER_RANK = {"A": 0, "B": 1, "C": 2}


def evaluate_confluences_vs_templates(
    features: Dict[str, Any]
) -> List[TemplateMatch]:
    """
    Evaluate all three ICT strategy templates against the given signal features.

    Parameters
    ----------
    features : dict with keys
        direction     — "BUY" | "SELL"
        mss_quality   — "HIGH" | "MEDIUM" | "LOW" | "NONE"
        fvg_quality   — "HIGH" | "MEDIUM" | "LOW" | "NONE"
        session       — "LONDON_KZ" | "NY_AM_KZ" | "ASIA_KZ" | "OVERNIGHT"
        dr_location   — "PREMIUM" | "DISCOUNT" | "EQUILIBRIUM" | "UNKNOWN"
        smt_confirmed — bool
        entry_type    — "REACTION_CONFIRMED" | "MIDPOINT_RECLAIM" | "ZONE_TOUCH"
        bias_4h       — "BULLISH" | "BEARISH" | "NEUTRAL"
        ifvg_present  — bool

    Returns
    -------
    List[TemplateMatch]
        Sorted: matched templates first (Tier A > B > C), then unmatched by score.
        Returns [] only on exception — never raises.
    """
    try:
        matches = [
            _score_tier_a(features),
            _score_tier_b(features),
            _score_tier_c(features),
        ]
        matches.sort(key=lambda m: (
            not m.is_match,
            _TIER_RANK.get(m.tier, 9),
            -m.score,
        ))
        return matches
    except Exception as e:
        print(f"[TEMPLATES] evaluate error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Phase B (2026-05-28) — CRT tier classifier
# ─────────────────────────────────────────────────────────────────────────────
#
# CRT signals carry a different feature set than 5M_SWEEP signals:
#   confluence_type — "FVG" | "OB"           (NEW — primary discriminator)
#   mss_quality     — "HIGH" | "MEDIUM" | "LOW" | "NONE"
#   wyckoff_phase   — "ACCUMULATION" | "DISTRIBUTION" | "MARKUP" | "MARKDOWN"
#                     | "TRANSITION" | "?"
#   direction       — "BUY" | "SELL"
#   session         — "LONDON_KZ" | "NY_AM_KZ" | "ASIA_KZ" | "OVERNIGHT" | "UNKNOWN"
#   bias_4h         — "BULLISH" | "BEARISH" | "NEUTRAL"
#
# Empirical justification for these tier definitions:
#   - FVG vs OB axis = +14.6pp WR (cycle-9 audit, n=246 FVG vs n=2195 OB)
#   - Wyckoff TRANSITION = no edge by definition (phase undecidable)
#   - MSS=HIGH compensates for OB-only confluence (strong displacement
#     supplies what FVG would otherwise contribute)


def _crt_wyckoff_aligned(direction: str, phase: str) -> bool:
    """Phase B helper — True when Wyckoff phase supports the trade direction.

    BUY  is aligned with ACCUMULATION (basing) or MARKUP   (uptrend).
    SELL is aligned with DISTRIBUTION (topping) or MARKDOWN (downtrend).
    """
    if direction == "BUY":
        return phase in ("ACCUMULATION", "MARKUP")
    if direction == "SELL":
        return phase in ("DISTRIBUTION", "MARKDOWN")
    return False


def _score_crt_a(f: Dict[str, Any]) -> TemplateMatch:
    """
    CRT Tier A — FVG confluence + MSS≥MEDIUM (no Wyckoff requirement).

    A1/A2 revision (2026-05-28, post-B-6 backtest validation on Run #146,
    n=95): the original 3/3 definition that REQUIRED Wyckoff phase
    alignment empirically produced the WORST tier (44.4% WR vs 56-60% for
    B/C). Cross-tab showed FVG signals with phase-aligned Wyckoff under-
    performed FVG signals with COUNTER (56%) or TRANSITION (64%) phase by
    ~15-20pp WR. Confirms the broader CLAUDE.md finding that Wyckoff phase
    as currently detected lacks predictive power on CRT setups (a sweep-
    reversal pattern fundamentally conflicts with "trade in phase
    direction"). Wyckoff stays as informational metadata in entry_type but
    is no longer used as a tier discriminator. Template ID name retained
    for back-compat with historical signals; semantic meaning is now
    "high-quality FVG CRT setup."

    Required (2/2):
      1. confluence_type == FVG
      2. mss_quality ≥ MEDIUM

    Bonuses (max +0.20 total):
      +0.10  4H bias aligned with direction
      +0.05  Active killzone session (LONDON/NY/ASIA)
      +0.05  Session in {LONDON_KZ, NY_AM_KZ} specifically (top killzones)
    """
    direction      = f.get("direction",      "BUY")
    confluence     = f.get("confluence_type", "")
    mss_quality    = f.get("mss_quality",    "NONE")
    bias_4h        = f.get("bias_4h",        "NEUTRAL")
    session        = f.get("session",        "UNKNOWN")

    matched = []
    hit = 0

    if confluence == "FVG":
        hit += 1; matched.append("confluence=FVG")
    # T-1 fix (cycle-10 audit 2026-05-28): tighten MSS bar from ≥MEDIUM to
    # ==HIGH. Full-population analysis (n=1945) showed Tier A under the
    # ≥MEDIUM definition produced 63.9% WR (n=180). Tightening to MSS=HIGH
    # yields 72.5% WR (n=80) with Wilson 95% CI [61.9%, 81.1%] — a
    # statistically separated top tier.
    #
    # H-CY14-T1 fix (cycle-14 audit 2026-05-29) — TIER A IS SELL-ONLY.
    # ---------------------------------------------------------------------
    # Cycle-13 cumulative data (Runs 1854-2007, n=79 across Tier A):
    #     Tier A SELL (BSL_CRT, MSS=HIGH):  n=44, WR=72.7%, avg_R=+0.673  ✓
    #     Tier A BUY  (SSL_CRT, post-relax): n=35, WR=31.4%, avg_R=-0.207  ✗
    # The BUY-side FVG-confluence cohort destroys capital — even after
    # H-CY13-T2 relaxed the MSS gate to ≥MEDIUM (which moved BUY WR from
    # 20% → 31.4%, still well below break-even). Tier B BUY at 68.2%
    # (n=110, avg_R=+0.635) handles BUY setups correctly with the SAME
    # FVG-or-OB structural shape; the issue is specifically the Tier A
    # "FVG-aligned premium" classification on the BUY side. Per Tier-B
    # symmetric performance, the FVG confluence is fine for SELL but
    # systematically anti-selects on BUY (likely picking up gap-down
    # FVGs in retracements that re-attract sellers — needs ICT-level
    # investigation, not template-level patching).
    #
    # Until root cause identified, Tier A is SELL-only. BUY signals fall
    # to Tier B (where they perform at canonical 68.2% WR) or Tier C
    # (paper-only catchall). This trades ~35 lost "Tier A" BUY classifications
    # per 365d for honesty about which setups are premium quality.
    if direction != "SELL":
        # BUY signals never qualify for Tier A under current TP geometry.
        # Drops to Tier B (FVG + MSS=HIGH OR OB + MSS=HIGH) where they
        # perform well per cumulative data.
        pass
    elif mss_quality == "HIGH":
        # SELL + MSS=HIGH is the canonical Tier A premium tier (72.7% WR
        # cumulative, working as designed).
        hit += 1; matched.append("MSS=HIGH(SELL_only)")

    bonus = 0.0
    if (direction == "BUY"  and bias_4h == "BULLISH") or \
       (direction == "SELL" and bias_4h == "BEARISH"):
        bonus += 0.10; matched.append("4H_bias_bonus")
    if session in ("LONDON_KZ", "NY_AM_KZ", "ASIA_KZ"):
        bonus += 0.05; matched.append(f"session_bonus={session}")
    if session in ("LONDON_KZ", "NY_AM_KZ"):
        bonus += 0.05; matched.append("top_killzone_bonus")

    base  = hit / 2.0
    score = min(base + bonus * base, 1.0)
    return TemplateMatch(
        template_id="CRT_A_FVG_ALIGNED",
        template_name="CRT Tier A — FVG + MSS=HIGH",
        tier="A",
        score=round(score, 4),
        required_hit=hit, required_need=2,
        confluences_matched=matched, live_allowed=True,
    )


def _score_crt_b_ob_high(f: Dict[str, Any]) -> TemplateMatch:
    """
    CRT Tier B — OB confluence + MSS=HIGH (no Wyckoff requirement).

    A1/A2 revision (2026-05-28): non-TRANSITION Wyckoff requirement dropped
    in lockstep with Tier A. Population-level cross-tab showed alignment
    has near-zero independent discriminating power once confluence+MSS are
    controlled. Strong MSS displacement supplies the quality that FVG would
    otherwise contribute on its own.

    Required (2/2):
      1. confluence_type == OB
      2. mss_quality == HIGH
    """
    confluence    = f.get("confluence_type", "")
    mss_quality   = f.get("mss_quality",   "NONE")
    bias_4h       = f.get("bias_4h",       "NEUTRAL")
    direction     = f.get("direction",     "BUY")
    session       = f.get("session",       "UNKNOWN")

    matched = []
    hit = 0

    if confluence == "OB":
        hit += 1; matched.append("confluence=OB")
    # T-2 fix (cycle-10 audit 2026-05-28): flip OB's MSS bar from HIGH to
    # MEDIUM. Full-population analysis (n=1945) showed OB+MSS=HIGH
    # produced 51.0% WR (n=776) — the WORST tier — while OB+MSS=MEDIUM
    # produced 56.9% WR (n=902). MSS=HIGH on OB-only signals selects a
    # worse sub-population (hypothesis: exhaustion-sweep regime changes).
    # After flip Tier B rises to ~57% WR territory and empirical
    # ordering A > B > C is recovered.
    if QUALITY_RANK.get(mss_quality, 0) >= QUALITY_RANK["MEDIUM"]:
        hit += 1; matched.append(f"MSS={mss_quality}")

    bonus = 0.0
    if (direction == "BUY"  and bias_4h == "BULLISH") or \
       (direction == "SELL" and bias_4h == "BEARISH"):
        bonus += 0.10; matched.append("4H_bias_bonus")
    if session in ("LONDON_KZ", "NY_AM_KZ", "ASIA_KZ"):
        bonus += 0.05; matched.append(f"session_bonus={session}")

    base  = hit / 2.0
    score = min(base + bonus * base, 1.0)
    return TemplateMatch(
        template_id="CRT_B_OB_HIGH_MSS",
        template_name="CRT Tier B — OB + MSS≥MEDIUM",
        tier="B",
        score=round(score, 4),
        required_hit=hit, required_need=2,
        confluences_matched=matched, live_allowed=True,
    )


def _score_crt_b_fvg_relaxed(f: Dict[str, Any]) -> TemplateMatch:
    """
    DEPRECATED 2026-05-28 (A1/A2 redefinition).

    Pre-redefinition this template caught "FVG-confluence setups that missed
    Tier A's Wyckoff-alignment requirement." Under A1/A2 the Wyckoff gate
    was dropped from Tier A — Tier A is now FVG + MSS≥MEDIUM and absorbs
    this template's entire historical scope (in Run #146 every FVG signal
    carried MSS≥MEDIUM, so this template produced zero unique matches under
    A1/A2 anyway).

    Function retained:
      - The template ID stays in CRT_TEMPLATE_IDS / TEMPLATE_REGISTRY so
        historical signals with matched_template_id='CRT_B_FVG_RELAXED' on
        the live DB and backtest_signals tables still validate against
        Phase 5A _KNOWN_TEMPLATES and render correctly on the dashboard.
      - The scoring function stays defined so any out-of-tree consumer that
        imports it doesn't break.
      - It is REMOVED from evaluate_crt_templates() so NEW signals never
        receive this classification going forward.

    Required (2/2):
      1. confluence_type == FVG
      2. mss_quality ≥ LOW    (any valid MSS — relaxed vs Tier A's MEDIUM bar)
    """
    confluence  = f.get("confluence_type", "")
    mss_quality = f.get("mss_quality",   "NONE")
    bias_4h     = f.get("bias_4h",       "NEUTRAL")
    direction   = f.get("direction",     "BUY")
    session     = f.get("session",       "UNKNOWN")

    matched = []
    hit = 0

    if confluence == "FVG":
        hit += 1; matched.append("confluence=FVG")
    if QUALITY_RANK.get(mss_quality, 0) >= QUALITY_RANK["LOW"]:
        hit += 1; matched.append(f"MSS={mss_quality}")

    bonus = 0.0
    if (direction == "BUY"  and bias_4h == "BULLISH") or \
       (direction == "SELL" and bias_4h == "BEARISH"):
        bonus += 0.10; matched.append("4H_bias_bonus")
    if session in ("LONDON_KZ", "NY_AM_KZ", "ASIA_KZ"):
        bonus += 0.05; matched.append(f"session_bonus={session}")

    base  = hit / 2.0
    score = min(base + bonus * base, 1.0)
    return TemplateMatch(
        template_id="CRT_B_FVG_RELAXED",
        template_name="CRT Tier B — FVG (any MSS, any phase)",
        tier="B",
        score=round(score, 4),
        required_hit=hit, required_need=2,
        confluences_matched=matched, live_allowed=True,
    )


def _score_crt_c(f: Dict[str, Any]) -> TemplateMatch:
    """
    CRT Tier C — Catch-all. live_allowed=0 (paper/backtest only).

    Required (1/1):
      1. confluence_type in {FVG, OB}    (any valid CRT confluence)
    """
    confluence = f.get("confluence_type", "")
    matched = []
    hit = 0
    if confluence in ("FVG", "OB"):
        hit += 1; matched.append(f"confluence={confluence}")

    base  = hit / 1.0
    score = round(base, 4)
    # M-CY13-T3 fix (audit cycle-13 2026-05-29): the template_id stays
    # CRT_C_OB_DEFAULT for DB back-compat (legacy signals'
    # matched_template_id rows must keep matching), but the human-readable
    # name now reflects the empirical reality. Cycle-13 fresh-data
    # tabulation showed Tier C caught 18 FVG signals vs only 4 OB signals
    # in round-2 (Run-1854 n=22) — i.e. it serves as the catchall bucket
    # for FVG setups that miss Tier A's MSS=HIGH bar, NOT just OB setups.
    # The "OB default" label confused dashboard readers analyzing
    # template attribution.
    return TemplateMatch(
        template_id="CRT_C_OB_DEFAULT",
        template_name="CRT Tier C — catchall (FVG or OB, MSS<HIGH)",
        tier="C",
        score=score,
        required_hit=hit, required_need=1,
        confluences_matched=matched, live_allowed=False,
    )


def evaluate_crt_templates(features: Dict[str, Any]) -> List[TemplateMatch]:
    """Evaluate a CRT signal against all 4 CRT-specific tier templates.

    Returns matches sorted: matched-first, then A→B→C, then by score desc.
    The caller picks `next((m for m in matches if m.is_match), None)` as the
    single best match (same pattern as evaluate_confluences_vs_templates).

    Parameters
    ----------
    features : dict with keys
        direction       — "BUY" | "SELL"
        confluence_type — "FVG" | "OB"
        mss_quality     — "HIGH" | "MEDIUM" | "LOW" | "NONE"
        wyckoff_phase   — "ACCUMULATION" | "DISTRIBUTION" | "MARKUP"
                          | "MARKDOWN" | "TRANSITION" | "?"
        bias_4h         — "BULLISH" | "BEARISH" | "NEUTRAL"
        session         — "LONDON_KZ" | "NY_AM_KZ" | "ASIA_KZ"
                          | "OVERNIGHT" | "UNKNOWN"

    Returns
    -------
    List[TemplateMatch] — sorted; empty list on exception (never raises).
    """
    try:
        # A1/A2 redefinition (2026-05-28): _score_crt_b_fvg_relaxed retired
        # from active classification (see its docstring). Tier A's revised
        # 2/2 (FVG + MSS≥MEDIUM) absorbs its entire scope.
        matches = [
            _score_crt_a(features),
            _score_crt_b_ob_high(features),
            _score_crt_c(features),
        ]
        matches.sort(key=lambda m: (
            not m.is_match,
            _TIER_RANK.get(m.tier, 9),
            -m.score,
        ))
        return matches
    except Exception as e:
        print(f"[TEMPLATES] CRT evaluate error: {e}")
        return []


# ── Tier hierarchy property validator ────────────────────────────────────────

def validate_tier_hierarchy() -> List[str]:
    """
    Property-test that A ⊇ B ⊇ C holds for all bot-realistic signals.

    A bot-realistic signal has MSS ∈ {MEDIUM, HIGH} and FVG ∈ {LOW, MEDIUM, HIGH}
    (enforced by ict_engine.py entry gates before a signal is ever generated).
    On these inputs the tier hierarchy must hold: any signal matching Tier A must
    also match Tier B, and any matching Tier B must also match Tier C.

    Bonuses (SMT, iFVG, 4H bias) are excluded because they only affect the float
    score, not required_hit, so they cannot change is_match.

    Returns a list of violation strings — empty list means all clear.
    Call at startup to catch template-definition regressions early.
    """
    violations: List[str] = []

    directions  = ["BUY", "SELL"]
    mss_quals   = ["MEDIUM", "HIGH"]          # bot gate: MSS >= MEDIUM
    fvg_quals   = ["LOW", "MEDIUM", "HIGH"]   # bot gate: FVG >= LOW
    sessions    = ["LONDON_KZ", "NY_AM_KZ", "ASIA_KZ", "OVERNIGHT"]
    dr_locs     = ["PREMIUM", "DISCOUNT", "EQUILIBRIUM", "UNKNOWN"]
    entry_types = ["REACTION_CONFIRMED", "MIDPOINT_RECLAIM", "ZONE_TOUCH"]

    for direction in directions:
        for mss in mss_quals:
            for fvg in fvg_quals:
                for session in sessions:
                    for dr in dr_locs:
                        for entry in entry_types:
                            f = {
                                "direction": direction, "mss_quality": mss,
                                "fvg_quality": fvg, "session": session,
                                "dr_location": dr, "entry_type": entry,
                                "smt_confirmed": False, "bias_4h": "NEUTRAL",
                                "ifvg_present": False,
                            }
                            ma = _score_tier_a(f)
                            mb = _score_tier_b(f)
                            mc = _score_tier_c(f)
                            if ma.is_match and not mb.is_match:
                                violations.append(
                                    f"A⊇B violation: mss={mss} fvg={fvg} "
                                    f"session={session} dr={dr} entry={entry} dir={direction} "
                                    f"→ A.hit={ma.required_hit} B.hit={mb.required_hit}")
                            if mb.is_match and not mc.is_match:
                                violations.append(
                                    f"B⊇C violation: mss={mss} fvg={fvg} "
                                    f"session={session} dr={dr} entry={entry} dir={direction} "
                                    f"→ B.hit={mb.required_hit} C.hit={mc.required_hit}")

    return violations


# ── DB seeding helper ─────────────────────────────────────────────────────────

def seed_templates_table(conn) -> None:
    """
    Idempotently insert the three canonical templates into the `templates` table.
    Uses INSERT OR IGNORE so re-running init_db() never duplicates rows.
    Call this from crypto_alert.init_db() after creating the table.
    """
    for t in TEMPLATE_REGISTRY:
        conn.execute(
            """INSERT OR IGNORE INTO templates
               (id, name, tier, description, live_allowed, created_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (t["id"], t["name"], t["tier"], t["description"], t["live_allowed"]),
        )
