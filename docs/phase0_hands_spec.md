# Spec: Phase 0 — Hand Separation

**Status**: metric + ground truth + baselines built and measured
(`score_hands.py`). **Algorithm deliberately not implemented** — this is
a design brief for an architect-level model, like
docs/meter_hierarchy_spec.md.

Written 2026-08-13. Everything below is measured on the 4 keyboard pairs
in `musicxmls/` (2435 notes), not assumed.

---

## 1. The proposal

Insert a new phase BEFORE Phase 1 that assigns every note a hand
(L / R) from raw MIDI alone:

```
MIDI ──► Phase 0  Hand Separation   → hand ∈ {L,R} per note
     ──► Phase 1  Harmonic Regimes  (can use hand as the bass-voice feed)
     ──► Phase 2  Voice Threading   (voices constrained WITHIN a hand)
     ──► Phase 3/4 Meter ──► Phase 5 Quantize + Notation
```

**Why it goes first.** Hands are a coarser, more physically constrained
partition than voices: a hand spans about an octave, hands rarely cross,
and a single hand routinely plays 2–3 voices. Getting hands right first
turns an unconstrained 4-way voice assignment into two smaller
constrained ones, and gives Phase 1 a real bass voice instead of the
lowest-note-in-keyframe proxy it uses today.

**The hard constraint this implies**: Phase 0 cannot consume Phase 1 or
Phase 2 output. It sees pitch, onset, duration, velocity — nothing else.
That is a genuinely different algorithm from the current threader, which
takes `regime_frames`. This is a redesign, not a reordering.

**Open architectural question, and the reason this is an architect
task, not a parameter task**: *does hand separation need harmony?* The
evidence is mixed and is laid out in §4.

## 2. Why this is the top priority

Downstream cascade, already measured on Clementi (docs/session-log.md,
2026-08-13):

- 18 notes assigned to the wrong hand → wrong Phase 5 staff.
- Voice-splitting across hands broke beaming so badly that a bar of
  continuous eighths beamed as *nothing* (78.5% → 97.2% after
  `merge_monophonic_voices` patched the symptom).
- Rhythm errors (88.0%) trace to Phase 5A monophony truncation, which
  fires because notes land in the wrong stream.

And it is piano-specific. Chorales and folk songs — 74 of the 87 corpus
pieces — have 4 real parts or 1; "hands" is a category error there, so
this work cannot be evaluated on the existing corpus. That is why the
metric below uses its own keyboard set.

## 3. The metric (built, run it)

```bash
python3 score_hands.py --emit-truth --all       # truth from musicxmls/
python3 score_hands.py --truth "corpus_runs/hands/<piece>.hands.json"
python3 score_hands.py --truth ... --pred my_hands.json --json report.json
```

- **Ground truth**: reference MusicXML part index (part 0 = RH, part 1 =
  LH), extracted at the repo's 120 BPM convention. Truth files live in
  `corpus_runs/hands/` (gitignored, regenerable).
- **Prediction format**: `[{"onset_ms":…, "pitch":…, "hand":"L"|"R"}]`
  or `{"notes":[…]}`. Unmatched notes count as wrong.
- **Reported**: overall accuracy, per-hand accuracy, **crossover-region
  accuracy**, and **hand switches inside a true hand** (the line-continuity
  failure mode, invisible to plain accuracy).

**The crossover region is the metric that matters.** It is the pitch band
where both hands are active — below it everything is LH, above it
everything is RH, and inside it pitch alone cannot decide. It is **43% of
all notes** across the four pieces. Headline accuracy is dominated by the
easy outer registers; report crossover accuracy or the number is theatre.

## 4. Baselines — what must be beaten, and what they reveal

| piece | notes | split@60 | oracle split | crossover (oracle) | crossover share |
|---|---|---|---|---|---|
| Burgmüller Arabesque | 444 | 60.8% | 98.4% (@68) | 97.5% | 64% |
| Burgmüller The Storm | 575 | 62.6% | 96.4% (@49) | 90.8% | 40% |
| Clementi Sonatina | 333 | 91.0% | 91.3% (@58) | 70.7% | 30% |
| Kuhlau Sonatina | 1083 | 77.6% | 92.8% (@66) | 82.5% | 41% |
| **all** | **2435** | **72.8%** | **94.5%** | **87.2%** | **43%** |

`split@60` = fixed threshold at middle C. `oracle split` = the best
single threshold **for that piece**, chosen with knowledge of the answer —
an upper bound on any pitch-only rule, and not achievable in practice.

Three findings that should shape the design:

1. **A fixed middle-C split is useless (72.8%)**, and its optimum moves
   wildly per piece — 49 for The Storm, 68 for the Arabesque. Nearly
   *two octaves* apart. Any global pitch constant is the wrong model.
2. **Even the oracle split leaves 12.8% of crossover notes wrong.** The
   Clementi is the extreme case: its oracle is 91.3% overall but only
   **70.7% in the crossover**, and no threshold does better — the piece
   contains pitch-identical, hand-opposite textures (session log: m9's D4
   is LH, m20's G4 is RH). **Pitch alone provably cannot solve this.**
3. **Line continuity is the discriminator, and it is measurable.**
   split@60 produces 130–139 hand switches inside a single true hand on
   the two worst pieces; the oracle drops the Arabesque to 6. A model with
   any notion of stream continuity should crush this number — it is the
   most sensitive signal in the metric.

## 5. Objectives

**Primary**: crossover-region accuracy, with overall accuracy and switch
count reported alongside. A design that raises overall accuracy while
leaving crossover flat has optimized the easy 57%.

**Targets**: beat the oracle fixed split (94.5% overall / 87.2%
crossover). Beating the oracle is the bar because the oracle cheats —
matching it means the algorithm has learned nothing a per-piece constant
could not.

**Design properties wanted**:

1. **Causal-compatible if cheap.** The endgame is live transcription
   (docs/pipeline_reference.md). A model needing the whole piece is
   acceptable now, but an online/bounded-lookahead formulation is worth
   more. Do not contort the design for it.
2. **Continuity as a first-class term**, not a post-hoc smoother — see
   finding 3.
3. **Deterministic**, or seeded and reported. The gate requires it.
4. **Fails loudly, not silently.** A note the model is unsure about is
   more useful flagged than confidently misassigned; downstream phases
   can treat low-confidence hands differently.

**Non-objectives**:
- Voices. Phase 0 outputs 2 streams, not 4. Voice threading stays Phase 2
  and may then assume voices do not cross hands.
- Chorales / folk songs. Not keyboard music; hands are undefined there.
  Phase 0 runs only on piano input and the pipeline must tolerate its
  absence.

## 6. Integration constraints

- **Additive and selectable.** Phase 0 must be optional (a flag), because
  every existing baseline was produced without it. Repo rule 16.
- **The gate still applies.** `run_benchmark.py` must PASS: no severity-1
  regression (bus/thermo/spike downbeats, held-out Phase 1 errors),
  voices unchanged. Phase 0 changes Phase 1's bass feed, so it *can*
  move Phase 1 — that is the point, but it must be measured.
- **Where it plugs in**: `export_etme_data.py` builds keyframes and calls
  the detector; the `is_bass` annotation path (added for the P1↔P2
  relaxation pass, `harmonic_regime_detector._build_particles`) is the
  existing hook for feeding a real bass voice into Phase 1.
- **Phase 5 already assumes hands**: `phase5_musicxml.py:VOICE_MAP` maps
  V1/V2→treble, V3/V4→bass. A measured attempt to replace that with
  pitch rules **failed** (315/333 fixed vs 303/333 pitch-based, session
  log 2026-08-13) — because the real discriminator is line continuity,
  which Phase 5C cannot see. Phase 0 is where that information exists.

## 7. Corpus note

Four keyboard pairs is thin. `musicxmls/` is the tier (MIDI + MusicXML
side by side, same stem); adding more is drag-and-drop plus
`--emit-truth`. Before trusting any Phase 0 number as a general result,
grow this to ~15 pieces spanning textures: Alberti bass, hand-crossing
(Scarlatti), dense chorale-style keyboard writing, and at least one
piece with sustained hand overlap. ASAP (docs/HANDOFF.md next-moves)
would also supply real performance MIDI with hand labels.

## 8. Where to look

| what | where |
|---|---|
| Metric + baselines | `score_hands.py` |
| Truth files | `corpus_runs/hands/*.hands.json` (regenerable) |
| Keyboard pairs | `musicxmls/` (4 pairs, MIDI + MusicXML) |
| The cascade, measured | `docs/session-log.md` 2026-08-13 entries |
| Rejected Phase 5C pitch fix | same, "Rejected (measured, not assumed)" |
| Where Phase 1 takes a bass hint | `harmonic_regime_detector.py:_build_particles` |
| Voice→staff map | `phase5_musicxml.py:VOICE_MAP` |
| Gate rules | `docs/benchmarking.md`, `docs/HANDOFF.md` |
