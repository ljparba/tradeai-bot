# ATOM_38_DIAGNOSIS — outcome-resolution check (Soak B, read-only)

**Trigger:** operator mapped ATOM #38 on TradingView and reported a contradiction —
"price did NOT hit TP1, then hit SL (should be a terminal LOSS/CLOSED), yet the
viewer shows it still OPEN and having hit TP2." Both cannot be true.

**Verdict up front: CASE (a) — operator misread TradingView. No bug.** The soak
resolution is correct, the viewer display is correct, and all four open positions are
legitimately OPEN under the soak's own BE-after-TP1 model. The bars prove TP1 *was*
hit (hours before TP2) and SL was *not* hit before TP1. The SL **price** the operator
saw was touched **after TP2** — a point at which the model has no stop. Severity: none
(informational). One model *characteristic* worth noting (no protective stop after
TP2) is flagged as an observation, not a bug — **no fix proposed.**

Read-only: `breakout-work/data/breakout.db` (`mode=ro`) + fresh Binance 5m klines.
Nothing written. Both soaks (A 486821, B 486822) + fade (393274) alive and untouched.

---

## 1. ATOM #38 — DB state (read-only)

| field | value |
|---|---|
| status | **OPEN** |
| results row | **NONE** (no row in `results` for signal_id=38) |
| tp1_hit / tp2_hit / tp3_hit / sl_hit / be_stopped | **all unset** (no results row exists) |
| realized_r | — (no results row) |
| entry / SL / TP1 / TP2 / TP3 | 1.865 / 1.851147 / 1.892706 / 1.906559 / 1.920412 |
| opened_ts | 2026-06-03 05:15:00 |
| expires_at | 2026-06-05 05:15:00 (not yet expired) |

**Key fact:** the DB has **no stored flags at all** for #38 — it does NOT claim TP2 was
hit. The "TP2 hit" the operator saw is the viewer's **live, on-the-fly** tier
computation (the open-position tier-coloring), not stored DB data. The DB simply says
"OPEN, unresolved." All four open positions likewise have no results row (DB-consistent).

---

## 2. ATOM #38 — forward price path (272 real 5m bars, entry+5min → now, 22.7h)

Walked with the EXACT soak `resolve_open_signals` BE-after-TP1 logic
([breakout_paper_soak_B.py:294-317](breakout_paper_soak_B.py#L294)):

| event | bar (UTC) | price | note |
|---|---|---|---|
| **TP1 hit** (high ≥ 1.892706) | **06-03 08:54** | high 1.893 | TP1 reached ~3.6h after entry |
| **TP2 hit** (high ≥ 1.906559) | **06-03 11:14** | high 1.908 | TP2 reached, ~2.3h after TP1 |
| TP3 (high ≥ 1.920412) | NEVER | — | runner never reached TP3 |
| SL pre-TP1 (low ≤ 1.851147) | **NEVER** | — | SL was NOT touched before TP1 |
| — post-TP2 diagnostics — | | | |
| SL **price** touched AFTER TP2 | 06-03 20:59 | low 1.843 | *after* TP2 — model has no stop here |
| entry touched AFTER TP2 | 06-03 16:24 | low 1.86 | *after* TP2 — be-stop no longer active |
| current (last bar) | 06-04 03:59 | close 1.861 | drifting near entry |

**Walk flags:** tp1=1, tp2=1, tp3=0, sl_preTP1=**0**, be=0.
**Correct outcome under soak logic: STILL OPEN** (no terminal condition hit; not expired).

---

## 3. Resolving the contradiction → CASE (a)

The operator's two claims, tested against the bars:

1. *"Price did NOT hit TP1."* — **FALSE.** TP1 (1.892706) was hit at 06-03 08:54
   (high 1.893). TP2 (1.906559) was hit at 11:14 (high 1.908). TP1 was hit **2h20m
   before** TP2 — so the "TP2 without TP1" impossibility never occurred. TP1 came first,
   exactly as required.
2. *"Then hit the SL → should be LOSS/closed."* — The SL **price** (1.851147) was indeed
   touched — but at **06-03 20:59 (low 1.843)**, which is **~9.7h AFTER TP2 was already
   reached.** Under the BE-after-TP1 model the protective stop exists only **between TP1
   and TP2** (the be-stop at entry). **After TP2 there is no stop** — only TP3 or expiry
   closes the position. So a post-TP2 dip through the old SL price does **not** terminate it.

Therefore:
- **(a) operator misread TV — TRUE.** Most likely they read the later SL-price touch (or
  the current near-entry price) and concluded "SL hit, no TP1," not seeing that TP1→TP2
  fired hours earlier and that the model has no post-TP2 stop. A TV-not-in-UTC offset
  would equally explain landing in the wrong part of the path.
- **(b) viewer displaying wrong — FALSE.** The viewer's live tiers are tp1=1, tp2=1,
  tp3=0 — **identical** to the independent bar walk. It correctly shows "TP2 hit + OPEN,"
  which is a *valid* state (runner reached TP2, riding toward TP3, not yet terminal).
- **(c) soak resolution wrong — FALSE.** The soak correctly left #38 OPEN: no pre-TP1 SL,
  no be-stop (TP2 was reached first), no TP3, not expired. No mis-resolution, no DB
  corruption, no gate impact.

The "open + TP2-hit" combination only *looks* contradictory if you assume a stop exists
after TP2. It does not.

---

## 4. Why is ATOM #38 the only 05:15 cluster signal still open?

Genuinely, by the bars — not a stuck resolution. Siblings #32-37/#39 hit their SL
**before** any TP1 (terminal LOSS, closed within hours). ATOM #38 alone ran the other
way: it **hit TP1 (08:54) then TP2 (11:14)**, which under the model removes the stop and
holds the runner toward TP3 or expiry. Expiry is 06-05 05:15 (≈25h away) — **not past
expiry**. It is legitimately riding a TP2-locked runner. Barring a move to TP3 (1.920412),
it will resolve **PARTIAL_TP2** at expiry — i.e. #38 is a small *winner-in-waiting*
(books the TP2 partial), not a stuck loss. Nothing to flag.

---

## 5. The other 3 open positions — same check (all CONSISTENT, all legitimately OPEN)

| # | tok | dir | TP1 hit | TP2 hit | TP3 | SL pre-TP1 | post-TP2 SL touch | DB | viewer | correct? |
|---|---|---|---|---|---|---|---|---|---|---|
| 71 | ATOM | SELL | 06-04 02:04 | 06-04 02:09 | never | no | 03:34 (h 1.86) | OPEN, no result | tp1=1 tp2=1 | ✓ OPEN |
| 73 | HBAR | SELL | 06-04 02:04 | 06-04 02:09 | never | no | 02:49 (h 0.08474) | OPEN, no result | tp1=1 tp2=1 | ✓ OPEN |
| 76 | BNB | SELL | 06-04 02:04 | 06-04 02:09 | never | no | 03:04 (h 613.95) | OPEN, no result | tp1=1 tp2=1 | ✓ OPEN |

All three are the **same pattern as #38**: a fast spike (these are SELLs) blew through TP1
and TP2 within ~5 minutes (02:04→02:09), then reversed hard back up. Because TP2 was
locked, the model has no further stop, so they remain OPEN and offside (e.g. BNB now
618.75 vs entry 608.36, well past its old SL 613.54) until TP3 or expiry. DB flags match
the bars; viewer live tiers match the bars. **No display or resolution discrepancy on any
of the four.**

---

## 6. Bug-class assessment

- **Not a viewer bug (case b ruled out):** the live open-position tier computation
  ([breakout_viewer.py `_compute_open_tier_status`](breakout_viewer.py#L295)) returns the
  same (tp1=1, tp2=1, tp3=0) as the soak's own walk for all four. It is faithful.
- **Not a resolution bug (case c ruled out):** stored outcomes are uncorrupted — the four
  are correctly unresolved; closed siblings correctly closed on pre-TP1 SL. **No closed
  signal is at risk; the gate data is intact.**

### Observation worth surfacing (NOT a bug, no fix proposed)
The BE-after-TP1 model has **no protective stop after TP2** — only TP3 or expiry closes a
post-TP2 runner ([breakout_paper_soak_B.py:304-307](breakout_paper_soak_B.py#L304): the
be-stop carries `not tp2_hit`; there is no SL/BE branch once `tp2_hit`). Consequence: a
position that spikes to TP2 then fully reverses sits OPEN and offside until expiry, then
books **PARTIAL_TP2** regardless of where price ended. This is the current *intended*
RUNNER-EXIT model (scope of RUNNER_EXIT_GAP.md was BE-after-**TP1**), and it does not
corrupt outcomes — but it is the exact thing that confused the operator (four positions
showing "open + TP2-hit" while price sits back near/through the old SL). Whether to add a
post-TP2 trail/stop (e.g. SL→TP1 after TP2) is a **model design question** for later,
deliberately left as an observation here. **No change proposed.**

---

## VERDICT

**CASE (a): operator misread TradingView.** Bar evidence is decisive — ATOM #38 hit TP1
at 06-03 08:54 (before TP2 at 11:14), never touched SL before TP1, and the SL-price touch
the operator saw occurred at 20:59, **after** TP2, where the model intentionally has no
stop. The soak resolution and the viewer display are both correct and mutually consistent
with the bars. The other three opens (#71/#73/#76) are the same legitimate "TP2-locked
runner riding to expiry" state. **Severity: none.** No DB corruption, no display bug, no
resolution bug; the gate is unaffected. The only forward-looking note is the model's
**no-stop-after-TP2** behavior, recorded as an observation for a future design discussion.

**No fix proposed — reporting and waiting.**

**Isolation honored:** read-only; both soaks + fade alive and untouched; signals.db +
Run-3704 pin unchanged; main untouched; branch not pushed. STOP.
