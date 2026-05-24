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
]


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
