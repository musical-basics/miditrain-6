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
