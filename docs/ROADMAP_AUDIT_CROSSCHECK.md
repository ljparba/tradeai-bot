# ENTERPRISE_ROADMAP vs TRADINGAGENTS_AUDIT — Cross-Check

**Date:** 2026-05-22
**Purpose:** Determine whether the two documents can coexist or whether they conflict.

---

## TL;DR

**They are compatible — they operate at different layers and 90%+ of the surface area does not overlap.**

The roadmap focuses on **enterprise hardening + statistical validation + incremental confluence sources**. The audit focuses on **whether to import LLM patterns from an external repo** — and overwhelmingly says no.

Only **one genuine conflict** exists: the news/macro filter. Roadmap wants it as a **blocking gate**. Audit wants it as an **advisory tag only**. This is reconcilable by phasing — ship as advisory first, promote to gate only after data justifies it.

Two **soft overlaps** need a one-time design decision so we do not build the same thing twice:
- "Centralized config" (audit) vs "dotenv-vault" (roadmap) — different concerns, should be designed together.
- "Backtest checkpointing" (audit) is missing from the roadmap entirely — should be added there as a sub-item under CI/CD regression gate.

---

## Conflict Map

| Topic | Audit position | Roadmap position | Verdict |
|---|---|---|---|
| **News/macro filter** | ADVISORY tag only — never gate (§3.5 modified). Fear/Greed + CoinGecko status. | **BLOCKLIST** ADOPT, Phase A item #8 — "Additive confluence filter; gate behind `MACRO_FILTER_ENABLED`" | **REAL CONFLICT — RECONCILABLE** by phasing (see §3 below) |
| **LLM patterns in signal path** (bull/bear debate, LLM risk, final approver) | DROP entirely — break live-vs-backtest invariant | Not mentioned (roadmap is LLM-free) | No conflict — roadmap is silent, audit drops them |
| **Backtest checkpointing** | ADOPT NOW (saves dev time during optimizer runs) | Not mentioned | No conflict — gap in roadmap; add as sub-item |
| **Centralized config (`config.py`)** | ADOPT NOW — new module + env-var overrides | `dotenv-vault` ADOPT — Phase A, encrypted secrets | Compatible — config.py for tunables, dotenv-vault for secrets storage. Design together. |
| **Pydantic schemas** | DEFER until post-paper | `msgspec` DEFER ("not the bottleneck") | No conflict — both defer schema work |
| **Narrative memory + reflection** | DEFER until N≥30 closes | Not mentioned | No conflict — audit defers, roadmap is silent |
| **Risk management** | Drops LLM risk debate; endorses deterministic gates | Half-Kelly + ATR ADOPT (Phase B #7) — deterministic | Aligned |
| **Adaptive learning changes** | No changes proposed | river ADWIN ADOPT, Thompson Sampling PILOT, Kalman DEFER, weight-degeneration monitoring ADOPT | Compatible — audit's deferred "signal_memory.md" would need to coexist with ADWIN drift detection (both touch OGD; design boundary needed if both ship) |
| **Validation methodology** | Not addressed | CPCV + DSR + Monte Carlo bootstrap + OOS 20% holdout ADOPT (Phase A) | No conflict — orthogonal layers |
| **Operational hardening** | Not addressed | Dead-man's switch, supervisord, state persistence, CI gate ADOPT (Phase A) | No conflict — audit endorses any non-LLM hardening |
| **Live-vs-backtest invariant** | CRITICAL — must never be broken | Implicit (Red Flag #5: Pine-port lookahead = M24 class) | Aligned |
| **External feeds** | Free crypto-native sources only (Fear/Greed, CoinGecko) | Coinglass free ADOPT, Glassnode/Santiment DEFER, paid sources REJECT | Aligned |

---

## The One Real Conflict — News/Macro Filter

**Roadmap (Phase A #8):**
> News/macro blocklist — Additive confluence filter; gate behind config flag `MACRO_FILTER_ENABLED`.

**Audit (Adopt 2):**
> Crypto-native news/sentiment fetcher *as advisory tag only*. Attach `news_context` to result dict and DB column. **Do not use as a gate.** Acceptance test #1: "Run for 7 days with the fetcher attached → no signal count change vs prior 7 days (proves it is advisory only)."

### Why this is a real conflict

The roadmap intends to **REDUCE signal count** during macro events (FOMC, CPI windows). The audit says **DO NOT REDUCE signal count** because we are already at 37/yr ceiling and need N≥30 paper closes to validate LIVE. A blocking macro filter could rationally remove 2-5 signals/year — extending paper collection from 12 months to 14-16 months.

### Reconciliation

Ship as a single module with **two operating modes** controlled by `MACRO_FILTER_ENABLED`:

```
MACRO_FILTER_ENABLED=false  (default, audit's "advisory tag only")
  → Compute news_context, attach to result dict, log to DB
  → Signal fires regardless of news state
  → Tracker dashboard shows news_context badge per signal

MACRO_FILTER_ENABLED=true   (roadmap's "blocklist")
  → All of the above
  → AND signal is blocked if news_context.macro_event_within_2h == True
```

**Promotion criteria from advisory → gate** (must be met before flipping default):
1. ≥20 closed paper signals with `news_context` populated.
2. Statistical evidence that signals during macro windows underperform by ≥10pp WR.
3. Backtest replay over 365d with the gate enabled produces ≥30 sigs/year (does not violate frequency ceiling further).

**This satisfies both documents:**
- Roadmap Phase A #8 ships as planned (config flag exists, gating logic exists).
- Audit's "advisory only during paper" holds because default is `MACRO_FILTER_ENABLED=false`.
- Future promotion to gate is data-driven, not assumption-driven.

---

## Soft Overlaps That Need a One-Time Decision

### 1. `config.py` (audit) vs `dotenv-vault` (roadmap)

**Audit wants** `config.py` to centralize tunable CONSTANTS (`MAX_SL_PCT`, `ICT_SWING_N`, etc.) with env-var override.

**Roadmap wants** `dotenv-vault` for encrypted SECRET storage (`TELEGRAM_TOKEN`, `BINANCE_API_KEY` future, `ANTHROPIC_KEY` future).

These are different concerns:
- `config.py` — non-secret tunables, version-controlled defaults
- `dotenv-vault` — secrets, never in git

**Recommended design:** Ship them together as one task.
```
config.py        — defines all tunables with defaults; reads env vars on import
.env.vault       — encrypted secrets (dotenv-vault format)
env.bat          — local development env (gitignored)
env.example.bat  — template (committed)
```

`config.py` does not know which env vars are secret. dotenv-vault populates `os.environ` before `config.py` runs. Clean separation.

### 2. Backtest checkpointing (audit-only)

Audit's "Adopt 1" — per-token checkpoint in backtest.py for crash recovery during optimizer runs. This is a real gap in the roadmap. **Add as a sub-item under Phase A #4 (CI/CD backtest regression gate)** since the regression gate needs a fast, resumable backtest to run on every PR.

### 3. Audit's deferred "signal_memory.md" + roadmap's ADWIN drift detection

If both ship (audit's narrative memory after paper closes, roadmap's ADWIN in Phase C), they both touch the OGD layer. **Need a design boundary:**
- ADWIN → triggers numerical weight resets when drift exceeded
- signal_memory.md → reads-only context for an LLM reviewer (deferred)

They do not interact mechanically. But the AUDIT's HARD GUARDRAIL ("LLM never gates a signal") must hold even after ADWIN starts triggering resets. Document this in CROSS_REF.md when either ships.

---

## Items In Roadmap Not Mentioned by Audit (no conflict, just gaps in audit's scope)

All Phase A operational hardening items (dead-man's switch, supervisord, state persistence, CI gate, OOS holdout, Monte Carlo bootstrap, mlfinlab CPCV+DSR, dotenv-vault, smart-money-concepts oracle), all Phase B confluence items (Coinglass funding/OI/liq, pandas-ta, PDH/PDL/weekly-open, Prometheus, uvloop, Half-Kelly sizing), all Phase C adaptive items (ADWIN, Thompson Sampling, HMM, meta-labeling, skfolio ERC), all Phase D scale-out items.

**These are out of scope for the audit** — the audit was specifically tasked with reviewing a TradingAgents port proposal, not the broader roadmap.

---

## Items In Audit Not Mentioned by Roadmap

1. **LLM patterns explicitly DROPPED** — audit's main contribution. Roadmap is silent on LLMs; audit closes that door explicitly so future agents know not to re-propose.
2. **Backtest per-token checkpointing** — should be folded into roadmap Phase A as a sub-item.
3. **Crypto-native news SOURCES** (Fear/Greed, CoinGecko status) — roadmap says "news/macro blocklist" without naming sources. Audit specifies sources. Adopt the audit's source list inside the roadmap's item.
4. **The "advisory tag first, promote to gate later" pattern** — audit's modus operandi for any new filter. Roadmap should adopt this as a general red-flag: **no new gate ships in default-on state during paper collection.**

---

## Recommended Updates to ENTERPRISE_ROADMAP.md

To make the two documents consistent without breaking either:

1. **Phase A #8 (News/macro blocklist)** — clarify that `MACRO_FILTER_ENABLED` defaults to `false` until promotion criteria are met (data evidence + ≥20 closed signals with `news_context`). Add sources: Fear/Greed Index (alternative.me) + CoinGecko status updates.

2. **Phase A — Add sub-item:** "Backtest per-token checkpoint" (3-4h) under CI/CD regression gate. Required for the gate's runtime to stay reasonable as `BACKTEST_DAYS` grows.

3. **Add a Red Flag #13:** "Any new gate or filter ships with config flag in **default-off** state during paper collection. Promotion to default-on requires ≥20 closed signals showing the gate's correlation with outcome, AND a fresh backtest demonstrating the gate does not violate the 30-sig/yr frequency floor."

4. **Add reference in §1 (How agents/skills should use this document):** "Before proposing any LLM-based feature, also read `docs/TRADINGAGENTS_INVESTIGATION_AUDIT.md` — the LLM-in-signal-path patterns from TauricResearch/TradingAgents are explicitly dropped and do not need re-evaluation."

5. **Change Log entry:** "2026-05-22 — Cross-checked against TRADINGAGENTS_INVESTIGATION_AUDIT. News/macro filter clarified to advisory-first; backtest checkpointing added; LLM-in-loop patterns documented as dropped."

---

## Recommended Updates to TRADINGAGENTS_INVESTIGATION_AUDIT.md

Minor — the audit was written assuming the roadmap did not exist. One reference would close the loop:

1. **Add to §6 (Adoption Plan):** "Adopt 2 (news fetcher) — implemented as **advisory mode** of Roadmap Phase A #8 (news/macro blocklist). Default `MACRO_FILTER_ENABLED=false`; same code path, gating disabled."

2. **Add to §7 (Second-order findings):** "Cross-referenced against ENTERPRISE_ROADMAP.md — see ROADMAP_AUDIT_CROSSCHECK.md for the consolidated decision on each overlapping item."

---

## Final Verdict

**The two documents work together.** The audit was tasked with one specific question (port TradingAgents patterns?) and answered correctly. The roadmap covers the full enterprise pre-LIVE program. The single news-filter conflict resolves cleanly by making advisory the default and gating optional, controlled by the existing `MACRO_FILTER_ENABLED` flag the roadmap already specifies.

**No PR should be blocked by these documents being in disagreement.** Apply the five small edits above and they cite each other coherently.
