# Technical Debt

Items noticed while working on something else. Documented here per operating
instructions; ask before fixing.

## Phase 2 hand-split: the biggest remaining notation error (2026-08-13)

Diagnosed against the Clementi pair (`/compare`). Hands 94.6% — **all 18
wrong-hand notes are Phase 2 voice-threading failures, not engraving.**
Measured, so we don't re-litigate it:

| voice | → ref RH | → ref LH |
|---|---|---|
| Voice 1 | 153 | 6 |
| Voice 2 | 66 | 4 |
| **Voice 3** | **6** | **12** |
| Voice 4 | 2 | 84 |

V1/V4 are 96–98% clean; the damage is entirely in the inner voices, and V3
is barely better than a coin flip. V3 also only fires 18× in the whole piece
(V1=159, V2=70, V4=86) — it is a dumping ground for whatever the cost
function can't place.

**Do NOT "fix" this in Phase 5C by assigning staves from pitch.** Measured on
this piece (333 notes): current fixed VOICE_MAP **315/333**, pure pitch≥C4
303/333, V1/V4 fixed + inner by pitch≥A3 317/333. Pitch models are a wash or
worse because the piece contains pitch-identical, hand-opposite textures —
m9's D4 is 5 semitones above the bass and is LH; m20's G4 is 2 semitones
above the bass and is RH. The discriminator is line continuity over time,
which only Phase 2 can see. (The +2 hybrid is piece-specific noise, not a
model.)

Three concrete Phase 2 leads, ranked, all needing the benchmark gate:

1. **Inner voices are penalized harder for register deviation than outer
   ones** — `voice_threader.py` register gravity uses weight 0.75 for inner
   vs 0.5 for V1/V4 (confirmed at the `W_REGISTER` block). Any note straying
   from `ideal_pitch` is therefore pushed OUT to V1 or V4. That is exactly
   m9/m11's LH D4 → V1 and m30's RH chord tones → V4. Equalizing or
   inverting that weight is the highest-leverage single change.
2. **Mid-line thread breaks**: m27 runs `D4 C4 B3 A3 G3` (one RH scale) but
   is threaded V1, V2, V2, **V3**, V1 — the cost function abandons a thread
   for one note and resumes it. `cost_elastic` (1.5/semitone) is too weak
   against the 30.0 affinity penalty. A continuation bonus for a thread
   active on an adjacent pitch within ~200ms would close 6 of the 18.
3. **`_stabilize_inner_voices` is too narrow** — it only smooths V2↔V3 at the
   same pitch. m9/m11's repeated D4 alternates V2 then V1, so the post-pass
   never sees it. Generalizing to any voice pair over a repeated-pitch run
   closes at least 2 and plausibly all 8 of the m9/m11 errors.

Related: the 40 rhythm errors (88.0%) are a single cause — Phase 5A's
monophony truncation writing eighths where the score holds quarters.

### Hand model: one voice per hand (2026-08-13)

The user's model — **one voice per hand, splitting to two only when a hand
genuinely holds a note while playing others** — matches the reference
exactly (38/38 measures single-voice on BOTH staves). We are now at 74/76
staff-measures single-voice. `reclaim_idle_hand` in `phase5_musicxml.py`
implements the safe half: when one hand has NOTHING in a measure and the
other holds a >= half-bar note that is the lowest sounding pitch with every
other note above it, that note goes back to the idle hand. Hands 94.6% →
95.2%, LH 90.6% → 92.5%, zero regressions; fires on **0 of 363 corpus
measures**, so it is tightly scoped to this texture.

**The m9/m11 offbeat case is NOT yet solvable from the exported data** — do
not keep trying heuristics on it, this is the record of what already failed:

| candidate rule | fix | break |
|---|---|---|
| offbeat interleaved with LH + within an octave | 8 | 8 |
| "fast hand" owns the offbeat (per-measure onset count) | 0 | 5 |
| move to whichever hand is closer in pitch | 3 | 24 |
| LH-pulse offbeat AND below the RH line | 8 | 8 |
| ... plus a proximity threshold (0 / 2 / 4 semitones) | 8/4/4 | 8/8/8 |

The blocker: **m9 and m20 are identical on every extractable feature.**
Both have a repeated offbeat run alternating with the other hand's regular
pulse; in both, each hand fills 3 of 3 gaps; and m11 (dLH=2, belongs LH) vs
m20 (dLH=2, belongs RH) are indistinguishable by pitch distance. The only
real difference is *which hand owns the underlying figure* — m9's D4
continues the LH's broken-chord accompaniment, m20's G4 continues the RH's
own alternation. That is a Phase 2 line-continuity judgement; a Phase 5C
rule sees one measure and cannot make it. Any threshold that separates the
two is overfitting to this piece.

## From the Phase 3/4 port (2026-07-05)

- **`run_phase2.py` hardcodes the greedy threader** (`VoiceThreader`, line ~50).
  When the user selects "P2: Beam Search" in the UI and runs an
  `__optimized__:` dataset, the re-run still uses greedy. Fix: add a
  `--phase2_model` arg mirroring `export_etme_data.py`.
- ~~**Thermo meter output lacks `subdivision`**~~ — RESOLVED 2026-07-05:
  `phase3_thermo_meter.py` now estimates subdivision from note-onset IOIs and
  the thermo file is selectable as Phase 4's grid source ("Grid: Thermo" in
  the UI). Remaining weakness: when freeze events are sparse the thermo
  tactus degenerates to the measure length (e.g. Revolutionary chunk:
  tactus=measure=4000ms, ratio 33 → subdivision falls back to 1). The tactus
  estimator itself needs the corpus harness to tune.
- **`dreamflow` is a local file: dependency** (`visualizer/package.json`) on
  `/Users/lionelyu/Documents/UltimatePianist Repos/dreamflow`. Fresh clones on
  another machine will fail `pnpm install` unless that repo is present at the
  same relative path (or the dep is vendored/published).
- **Measure numbering restarts at 1 per chunk** (inherited miditrain-4 TODO):
  chunk 2 of a piece should continue from chunk 1's numbering.
- **Notation hover→tooltip mapping is loose**: miditrain-4's
  `handleNoteHover` matched notes by pitch + approximate tick-time with
  hardcoded 120 BPM assumptions; not ported to miditrain-6 (Phase 4B view has
  no note hover). Wire vfId → note identity properly if needed.


## Meter-change detection deferred (2026-08-13) — decision, with reasoning

User's call, and the data supports it: **do not add time-signature-change
logic until constant-meter accuracy is fixed.** Reasons, so this is not
re-litigated from the roadmap entry alone:

1. The error mass is not there. 59% of validation error is wrong
   metrical LEVEL on constant-meter pieces (docs/meter_hierarchy_spec.md);
   only 1 of 87 corpus pieces (chorale_010) even has a meter change.
2. It cannot be measured. A perfect implementation would move the
   aggregate by a rounding error and the gate would read PASS-identical —
   no signal to tune against.
3. Its switch penalty is untunable while the constant-meter error rate is
   this noisy: you cannot distinguish "penalty too loose" from "the engine
   was going to miss this piece anyway", and a penalty fitted to absorb
   unrelated failures is worse than no feature.

Piecewise DP remains valuable LATER as the rubato/live tracker (loosening
the switch penalty is the Large-Jones formulation) — but that is blocked
on ASAP performance data regardless, since corpus MIDI is quantized and
flat-velocity.


## Corpus scope: piano is primary, chorale/essen are secondary (2026-08-13)

User's decision after weighing full removal of the non-keyboard tiers:
**keep them, stop treating them as the target.** 74 of 87 corpus pieces
are chorales or folk songs — tuning aggregates on that mix optimizes for
the wrong domain ("a drug for monkeys when humans are the primary
consumer"). But deleting them would (a) destroy Phase 2's ONLY ground
truth, since SATB part labels are the voice-threading objective, (b)
shrink the corpus to ~13 pieces, below grid-search viability, and (c)
void every committed baseline.

Resolution: keep scoring them (regressions stay visible, Phase 2 keeps
its objective), report per-tier — already implemented in
run_benchmark.py — and treat the piano tier as the headline. Grow the
piano tier before trusting any piano-only number: `musicxmls/` is the
drop-in location, 4 pairs today.

Corollary already applied: the "hands" metric reads n/a on references
with more than 2 parts, instead of reporting a category error as a ~30%
failure.
