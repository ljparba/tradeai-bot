# SESSION_BREAKDOWN — descriptive, 720d (read-only)

**Bottom line: the NY session does NOT carry a real, OOS-robust, independent edge.** On primary
TF_B it is only +0.042 above the overall mean, **decays out-of-sample to ~the mean** (train
+0.425 → test +0.362), and the modest above-mean reading is **partly the inverted-volume effect
re-surfacing** — NY has the **lowest** MSS-bar volume of any session (mean vol_ratio 2.51,
%HIGH-vol 47% vs ~53–58% elsewhere), and we already know low volume → higher avg_R. The
genuinely strong session is **LONDON** (holds OOS); the genuinely weak one is **ASIAN** (holds
OOS, weakest in every regime) — not NY either way. And **every session is net-profitable.**
**Descriptive only — no filter proposed, no signal blocked, nothing changed.**

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B, in-memory (NO DB writes). Session
tagged from entry-ts UTC hour (no look-ahead — just the clock). Soaks A=515231, B=515230 +
fade=512666 alive and untouched.

Sessions (UTC): ASIAN 00–08 · LONDON 08–13 · LONDON_NY_OVERLAP 13–16 · NY 16–21 · LATE_US 21–24.

---

## 1. Per-session breakdown

### TF_B (5M/1H) — PRIMARY (n=12090, overall avg_R +0.3644)
| session | n | % | WR | avg_R | sum_R | outcome [WIN/PT2/PT2_T1/PT1/LOSS] | BUY / SELL |
|---------|----|----|-----|-------|-------|----|----|
| ASIAN | 3829 | 31.7% | 68.5% | **+0.2850** | +1091 | 1148/1/878/718/1078 | +0.236 / +0.347 |
| LONDON | 2287 | 18.9% | 71.8% | **+0.4208** | +962 | 693/3/505/445/637 | +0.407 / +0.436 |
| LDN_NY_OVL | 2033 | 16.8% | 72.3% | +0.4163 | +846 | 652/1/448/376/554 | +0.419 / +0.414 |
| **NY (16–21)** | 2632 | 21.8% | 71.5% | **+0.4059** | +1069 | 828/3/581/476/737 | +0.344 / +0.474 |
| LATE_US | 1309 | 10.8% | 70.4% | +0.3337 | +437 | 394/0/299/239/375 | +0.317 / +0.356 |

→ Ranking LONDON > LDN_NY_OVL > **NY** > overall > LATE_US > ASIAN. **NY is +0.042 above the mean
— decent but not the best** (London + overlap beat it). ASIAN is the weak spot (−0.079) yet still
+0.285 profitable.

### TF_A (5M/4H) (n=4744, overall avg_R +0.3376)
ASIAN **+0.2629** (33.9%) · LONDON +0.3951 (31.3%) · LDN_NY_OVL +0.3049 · **NY +0.3478** (26.0%) ·
LATE_US +0.5032 (n=182, tiny/noisy).
→ NY only **+0.010 above mean** (marginal). ASIAN weakest; LONDON strong.

**NY highlight:** above the overall mean on both TFs, but by a small, TF-dependent margin
(B +0.042, A +0.010) — not a standout. The best session is LONDON on both.

---

## 2. Confound checks

### Session × REGIME — ASIAN weakness is structural, not regime-driven
ASIAN is the weakest session **inside every regime** (B: BEAR +0.285 / BULL +0.262 / RANGE +0.310;
A: BEAR +0.214 / BULL +0.217 / RANGE +0.358) — well below the other sessions. So the session
ranking is not just one session catching a trending regime; ASIAN is genuinely weak across
regimes (still profitable). NY is mid-to-upper in every regime, no regime concentration.

### Session × VOLUME — the key confound: a "NY edge" is partly the inverted-volume effect
We already found **lower MSS-bar volume → higher avg_R** (VOLUME_BREAKDOWN.md). Mean vol_ratio /
%HIGH-vol per session:

| session | TF_B vol_ratio | TF_B %HIGH | TF_A vol_ratio | TF_A %HIGH |
|---------|----------------|------------|----------------|------------|
| ASIAN | 2.96 | 53.7% | 2.70 | 49.9% |
| LONDON | 2.93 | 54.7% | 2.95 | 50.4% |
| LDN_NY_OVL | 2.97 | 58.2% | **5.45** | **76.1%** |
| **NY** | **2.51** | **47.1%** | **2.29** | **43.9%** |
| LATE_US | 3.36 | 51.0% | 5.76 | 68.7% |

→ **NY has the LOWEST MSS-bar volume of any session** (lowest mean vol_ratio AND lowest %HIGH-vol
on both TFs). Since low volume correlates with higher avg_R, **NY's modest above-mean avg_R is at
least partly the inverted-volume effect re-surfacing — not an independent "NY market edge."**
(Consistent: the high-volume LDN_NY_OVL on TF_A, vol 5.45 / 76% HIGH, has a *lower* avg_R +0.305.)

### Session × DIRECTION
No session is one-directional; BUY/SELL are reasonably mixed in each. SELL out-earns BUY in most
sessions (a general direction effect, not session-specific). NY's SELL (+0.474) carries its B
number more than its BUY (+0.344).

---

## 3. Stability (OOS 70/30)

### TF_B
| session | train avg_R | test avg_R |
|---------|-------------|------------|
| ASIAN | +0.3163 | **+0.2119** (drops, stays weakest) |
| LONDON | +0.4065 | **+0.4539** (rises, stays strongest) |
| LDN_NY_OVL | +0.4083 | +0.4351 (stable strong) |
| **NY** | +0.4250 | **+0.3616** (decays to ~overall mean) |
| LATE_US | +0.3444 | +0.3088 |

→ In the **test** split: LONDON (+0.454) > LDN_NY_OVL (+0.435) > **NY (+0.362)** > LATE_US > ASIAN
(+0.212). **NY decays to roughly the overall mean (~+0.36) OOS — its above-mean edge does not
hold.** LONDON and the overlap are the OOS-robust strong sessions; ASIAN the OOS-robust weak one.

### TF_A
ASIAN +0.260→+0.269 · LONDON +0.381→+0.428 · LDN_NY_OVL +0.283→+0.355 · **NY +0.338→+0.372** ·
LATE_US +0.523→+0.457 (n55). → NY mid-pack OOS; LONDON robust; ASIAN robustly weakest.

**Where session lands vs prior breakdowns:** MSS-quality flipped OOS (noise); volume held on both
(inverted); trend held on B only. **Session: ASIAN-weak / LONDON-strong holds OOS, but NY's
above-mean reading decays OOS — NY is not a robust edge.**

---

## 4. Interpretation (descriptive only — explicitly NOT a filter proposal)

**Does the NY session carry a real, OOS-robust edge?** No.
- NY is only modestly above mean (B +0.042, A +0.010), **decays OOS to ~the mean** on the primary
  TF, and is **not the best session** (London + overlap beat it).
- Its modest reading is **partly the inverted-volume effect in disguise** — NY has the lowest
  MSS-bar volume of any session, and low volume already predicts higher avg_R. So part of any
  "NY edge" is the volume signal re-surfacing, not an independent session effect.
- The robust, OOS-holding session facts are **ASIAN = structurally weakest** (every regime, holds
  OOS) and **LONDON = strongest** (holds OOS) — neither is NY. The forward-soak Asian −8→+7.32
  flip was burst/small-n; the 720d view shows Asian is simply the weakest (yet profitable) session.

**Heavy caveats (why this is orientation, not action):**
- (a) **NY's edge does not hold OOS;** session is largely noise/operational on the primary TF.
- (b) **Every session is net-profitable** (even weakest ASIAN +0.285). NY is only ~22% of signals.
  Filtering to NY-only would keep a slightly-better *avg_R* while discarding ~78% of signals and
  most *total profit* — the avg_R-vs-sum_R trap, same failure as the regime/volume filters (−28% sum_R).
- (c) **The operator's 9 pm-PH (NY) window is an OPERATIONAL fact, not a market edge** — it is when
  the operator is awake to execute manually. **If the bot is auto-traded on Bybit, session-of-day
  is irrelevant to it.**
- (d) **Acting would require a separate pre-registered OOS experiment** with its own decision rule
  — not a change inferred from this descriptive pass.

**No session filter is recommended or proposed.** Session carries some information (ASIAN weak,
LONDON strong — both OOS-robust), but **NY specifically is not a robust independent edge** (decays
OOS, partly the volume effect), and all sessions are profitable, so this is not a filtering case.
Reporting what the data shows; proposing nothing, blocking nothing.

---

**Isolation honored:** read-only descriptive bucketing; in-memory (0 DB rows written); both soaks
(A 515231, B 515230) + fade (512666) alive and untouched; signals.db + Run-3704 pin unchanged;
main untouched; branch not pushed. No filter, no change, no signal blocked. STOP.
