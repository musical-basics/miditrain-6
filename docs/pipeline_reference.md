# MidiTrain Pipeline Reference

**Purpose**: the complete logic of every pipeline phase in one document, so
a future AI (or human) can reason about the system without reading the
code. Contracts, algorithms, tuned parameters, measured accuracy, and file
map. Deeper theory lives in the pointed-to docs; this is the canonical map.

Last updated: 2026-07-08 (after channel-norm + weight retune, baseline
bus=863 / thermo=1147 / spike=1694 / heldout=27 / voices=90.57%;
per-tier bus: chorale 222 / essen 382 / piano 259).

---

## The big picture

MidiTrain turns raw MIDI into sheet music through five phases. Each phase
is a pure function that layers ONE annotation onto a canonical note
timeline (the plan-doc architecture: regime_id → voice_id → metrical
position → notation):

```
MIDI file
  │  Phase 1  Harmonic Regime Detection   → regimes + per-note chord color
  │  Phase 2  Voice Threading             → voice_tag per note
  │  Phase 3  Meter (thermo + spike)      → barline grids (two engines)
  │  Phase 4  Meter Evidence Bus          → barline grid (joint argmax over all cues)
  │  Phase 5  Quantize + Notation         → tick coordinates → VexFlow score
  ▼
sheet music (diagnostic display)
```

Phases 3 and 4 are three competing METER ENGINES (thermo, legacy spike,
bus); Phase 5 consumes whichever grid the user selects. All three are
scored continuously against corpus ground truth (see Evaluation).

**Design principles** (violate at your peril):
1. Phases communicate ONLY via JSON files with explicit contracts (below).
2. Each phase keeps its own ground truth and its own grid search; a tuned
   winner is adopted only after the cross-phase benchmark gate passes
   (docs/benchmarking.md).
3. Upgrades are selectable options (A/B), never overwrites, until the
   numbers pick a winner.
4. Notation is a diagnostic display: meter errors are global/catastrophic,
   voice errors local, spelling cosmetic. Priority follows that order.

**System-wide conventions**:
- All times in integer milliseconds. 120 BPM convention everywhere:
  quarter note = 500ms, `tick_to_ms = 500/tpq` regardless of MIDI tempo
  metadata. DO NOT change this (docs/final_v3.md "what not to change").
- Voices are named `"Voice 1"` (soprano) … `"Voice 4"` (bass),
  `"Overflow (Chord)"`, `"Unassigned"`.
- Pitch classes → interval names relative to C: 0="1", 1="b2", 2="2",
  3="b3", 4="3", 5="4", 6="#4", 7="5", 8="b6", 9="6", 10="b7", 11="7".

---

## The ETME JSON (the central data contract)

Written by `export_etme_data.py` to
`visualizer/public/etme_{base_key}_{angle_map}_{break_method}[_{jaccard}].json`.

```json
{
  "notes": [{
    "pitch": 60, "velocity": 65, "onset": 0, "duration": 500,
    "voice_tag": "Voice 1", "id_score": 0.0,              // Phase 2
    "hue": 317.5, "sat": 88.7, "lightness": 48.9,          // Phase 1 color
    "tonal_distance": 12.5, "regime_state": "Regime Locked",
    "debug": {"diff":0,"pmass":0,"rmass":0,"threshold":0.75,"particles":[...]}
  }],
  "regimes": [{"start_time":0,"end_time":4000,"state":"Stable",
               "hue":317.5,"saturation":88.7,"v_vec":[x,y]}],
  "stats": {"total_notes":N,"total_regimes":M,"voice_counts":{...},
            "relaxation": false}
}
```
Regime `state` ∈ {`Stable`, `Regime Locked`, `TRANSITION SPIKE!`,
`Silence`, `Undefined / Gray Void`}. `TRANSITION SPIKE!` start times ARE
the Phase 1 harmonic boundaries — everything downstream that says
"spikes" means these. Phase 2 fields are optional in old files; consumers
must tolerate their absence.

---

## Phase 1 — Harmonic Regime Detection ("ETME", Limbo V2.2 / Anchor Isolation)

**Question answered**: where does the harmony change, and what color is it?
**Full spec**: docs/final_v3.md (V3.1, includes the optimization journey).

**Input**: keyframes — note-onset groups within a 50ms window, each note a
tuple `(interval, octave, velocity, duration_ms[, is_bass])`.

**Core objects**:
- Each note becomes a *particle* with an angle on a 12-position wheel.
  Two angle maps: `dissonance` (default; consonant intervals cluster near
  0°, dissonant ones far) and `fifths` (circle of fifths, 30°/step).
- Particle mass = `(velocity/127) × dur_boost × register_boost`, where
  dur_boost = clamp(duration/1000, 0.5, 2.0) and register_boost =
  `1 + |octave−4|×0.15`. **Bass authority**: the bass note gets
  `mass × bass_multiplier` if it sits in octave ≤ 3. The bass note is the
  lowest note of the keyframe by default, or the note carrying the
  optional `is_bass` annotation (layered on by the P1↔P2 relaxation pass
  from Phase 2's Voice 4).
- A regime has an **anchor** — the establishing chord's particles, locked
  so passing notes can merge into the regime's color but can NOT drift the
  anchor centroid ("Anchor Isolation" — prevents centroid drift, the
  original failure mode).

**Break decision** (per keyframe vs the current anchor), method-dependent:
- `centroid`: angular divergence of pending centroid vs anchor > break_angle.
- `hybrid` (production): break if `diff > break_angle` OR
  `jaccard(anchor_pcs, pending_pcs) < jaccard_threshold`, gated by pending
  mass ≥ `min_break_mass`. Pitch-class sets drop trace particles below
  15% of max mass (capped at 0.25 absolute so an amplified bass can't
  erase inner voices). Subsets never break.
- `jaccard_only`: pure set overlap, no mass gate.
- `hybrid_v2`: Jaccard-primary with a scaled mass gate —
  `threshold = max(0.3, min_break_mass × jaccard / jaccard_threshold)`
  (strong harmonic evidence lowers the mass requirement).
- `*_split` variants split the pending queue.

**The Limbo state machine** (why it doesn't fire on ornaments): a
would-be break enters *probation* (pending spike frames) and must survive
`debounce_ms` before becoming a `TRANSITION SPIKE!`. Refinements (V3):
- *Mass resolution veto*: a resolution/merge is rejected if its mass is
  < `min_resolution_ratio` of the pending spike's mass (weak resolutions
  don't cancel strong evidence).
- *Anchor cap*: anchors hold at most `max_anchor_size` particles.
- *Maturity grace*: no break within `maturity_grace_ms` of regime start.
- *Limbo rescue*: gated on bass_multiplier > 1 — limbo frames revived as
  pending spikes when bass-driven breaks would otherwise strand them.

**Output**: per-frame regime states → consolidated `regimes[]`, plus
per-note 4D chord color (hue = mass-weighted centroid angle, sat =
vector magnitude, lightness = register, tonal_distance = distance to the
nearest 30° node) via a 50ms-lookahead rolling window that resets at
regime starts.

**Production config (V3.1 rank-1, in final_optimized_configs.json)**:
dissonance / hybrid, break_angle 35°, merge_angle 25°, min_break_mass
0.75, jaccard 0.375, debounce 100ms, min_resolution_ratio 0.6,
max_anchor_size 6, maturity_grace_ms 200, bass_multiplier 2.0.
**Accuracy**: P 90.8 / R 85.3 / F1 88.0 vs 116 hand markers on the
held-out Pathétique chunk (±100ms) — reproduced exactly by the benchmark.

**P1↔P2 relaxation** (optional, `--relaxation`): run P1 with the
lowest-note proxy → run P2 → re-run P1 with Voice 4 as the true bass feed
(`is_bass` annotations) → re-thread. Fixed two passes, deterministic.
Measured: +0.6 F1 on Pathétique, exactly neutral on the corpus (in SATB
texture the lowest note already IS the bass). Off by default.

---

## Phase 2 — Voice Threading

**Question answered**: which horizontal voice does each note belong to?
**Ground truth**: SATB part labels in the corpus chorales.

Two selectable models (`--phase2_model`), both max 4 voices + overflow:

- **Greedy** (`voice_threader.py`, production): left-to-right assignment
  minimizing an 8-term thermodynamic cost (pitch proximity, register
  affinity, crossing penalties, temporal gap, etc. — weights hand-tuned,
  never grid-searched), followed by post-processing patches including
  `_stabilize_inner_voices`. Sets `voice_tag` and `id_score`.
- **Beam** (`voice_threader_beam.py`): time-synchronous beam search
  (width 64), 5 weights, L2 pitch elasticity, no edge-case patches.

**Measured (corpus SATB, permutation-matched note accuracy)**:
greedy **92.3%**, beam **87.1%** — greedy wins on real ground truth,
despite beam being newer. But beam slightly improves BOTH downstream
meter engines (its bass line apparently suits them). Known greedy bugs:
voice splitting in 3→4 transitions, V1 instability in fast runs
(docs/voice_threading_issues.md) — these motivated beam.
`run_phase2.py` re-runs P2 on an existing ETME file (greedy only — known
debt).

---

## Phase 3 — Meter, first two engines

**Question answered**: where are the barlines, what is the time signature?
**Ground truth**: `downbeats_ms` in corpus ground-truth files (±50ms).

### 3a. Thermodynamic meter (`phase3_thermo_meter.py`) — canonical
**Theory**: docs/thermodynamic_meter_theory.md. Meter emerges from
tension/release, not note counting.

1. **Translate**: each note → particle with
   `mass = (vel/127) × min(dur_s, 4) × (1 + register_depth) × voice_weight`
   where register_depth = (128−pitch)/128 and voice weights are
   **Bass 4.0 / Soprano 3.0** / inner 1.0 / overflow 0.5 (corpus
   grid-searched 2026-07-06; were 3.0/2.0).
2. **Microcosm**: simulate on a 25ms grid —
   T (temperature) = activity_rate × Shannon entropy of same-voice pitch
   deltas ("patterned speed is cold, chaotic speed is hot");
   η (viscosity) = harmonic inertia (mass × saturation-stability ×
   convergence); P (pressure) = n·T/V with V = register span. An energy
   accumulator integrates T × dissonance.
3. **Phase detection**: per-bin phase from percentile-normalized
   thresholds (T_median, T_75, η_75) → frozen_solid / crystal / liquid /
   gas. A liquid/gas → solid transition lasting ≥ MIN_FREEZE_MS (50) is a
   **freezing event** with magnitude
   `Δη × (1 + P_before) × max(0.1, E_released) × tonic_bonus`
   (tonic_bonus rewards harmonic motion toward H_tonic — authentic
   cadences score, deceptive ones don't). Energy fully resets at each
   freeze. (A partial-discharge variant scaled by cadence strength was
   REJECTED by the benchmark gate 2026-07-07 — it regressed downbeats;
   `energy_hierarchy.py` survives as a standalone annotator.)
4. **Meter**: autocorrelate the magnitude-weighted freeze impulse train →
   measure_ms; tactus from inter-freeze IOI mode; time signature from
   measure/tactus ratio snapped to musical norms; barlines projected with
   rubber-band snapping to freezes, dead-reckoning between them, a
   **gas anti-anchor** rule (barlines never land in gas; slide out), and
   a consistency repair pass. Subdivision (ticks per beat, needed by
   Phase 5) estimated from note-onset IOI clustering vs the tactus,
   snapped to {1,2,3,4,6,8,12}.

**Known weakness**: with sparse freezes the tactus degenerates to the
measure length (6 corpus pieces produce no meter at all — they score as
failures). Output: `phase3_thermo_{base_key}.json` with
`thermodynamic_meta`, `phase_census`, `freezing_events[]`,
`meter{...}` (grid contract), `grid_sample[]`.

### 3b. Spike macro-meter (`phase3_spike_meter.py`) — legacy
Barlines anchor to Phase 1 spikes directly: tactus/sub-tactus from
hierarchical IOI clustering of onsets (10ms bins; tactus = strongest
cluster at 2/3/4/6× the sub-tactus); measure length from autocorrelation
of a spike-density envelope coherently weighted by Phase 2 voices
(bass ×3, melody ×1.5, squared); rubber-band barline snapping to spikes
(40%-of-tactus window, 0.5-measure min gap) with a two-pass
bass-coincidence veto. Output: `phase3_grid_{base_key}.json` (flat grid
contract, includes `spike_density[]` and `autocorr[]`).

**Measured (validation split)**: thermo 1147 errors (37/43 pieces) vs
spike 1694 (43/43). Head-to-head on shared pieces thermo wins decisively;
thermo IS the better engine of the two.

---

## Phase 4 — Meter Evidence Bus (`phase4_meter_bus.py`)

**Question answered**: same as Phase 3, but as ONE joint optimization
over every meter cue the literature validates plus our engines' outputs.
**Theory + channel map**: docs/phase4_signal_scaffold.md.

**Architecture**: every signal module emits *votes* —
time votes `{time_ms, weight}` ("something lands here") or period votes
`{lag_ms, anchor_ms, weight}` ("this material repeats at lag L"). The
combiner never knows what a signal means, only how strongly it votes.

**Channels** (signals_common / accent_rhythm / parallelism / surprisal /
melodic_attraction): onset_pulse (Temperley event rule), povel_essens
(1985 accent patterns), agogic (long notes on strong positions), lbdm
(Cambouropoulos boundary detection), velocity (dormant on corpus — flat
80), surprisal (n-gram information content, Pearce IDyOM), attraction
(Lerdahl/Larson magnetism — where resolution lands), gap_fill (Meyer),
bass_cadence (falling-fifth arrivals, agogically gated), parallelism
(GTTM MPR1 — repeats vote on period AND phase jointly). External
channels via `--votes name=path`: `phase4_make_votes.py` converts Phase 1
spikes (regimes `start_time`) and Phase 3 freezes (time_ms + magnitude)
into vote files; keys become `extra:harmonic`, `extra:freezes`.

**Combiner logic**:
1. *Tactus search*: for each period P (log-spaced 240–1600ms, then 0.1%
   fine refinement ±3% — a 1% period error smears phase over 30+ bars):
   `score(P) = prior(P) × best_folded_mass(all weighted votes, P)
   × (1 + w_par × parallelism_support(P))`. Prior = log-Gaussian around
   600ms, **σ 0.9 octaves** (corpus grid-searched 2026-07-07; was 0.55 —
   the narrow prior, not the search range, was crushing slow-tactus
   pieces). Best fold phase = tactus phase φ_t.
2. *Measure search*: grouping G ∈ {2,3,4} × bar-phase k·P over the
   structurally strong channels with measure-level multipliers,
   mass-per-grid-line normalized so different G compete fairly; measure
   prior σ 1.4 oct around 1900ms (grid-searched, was 1.0). *Parsimony*:
   G=4 must beat G=2 by margin 1.18 or the simpler level wins.
3. *Compound test*: top-line IOIs at P/3 vs P/2 → G×3/8 signatures.
4. Barlines projected rigidly from (measure_phase, M) — no rubato
   snapping (correct on quantized MIDI; for live MIDI feed this grid as a
   prior into a DP/rubber-band tracker).

**Anacrusis is free**: phase is a free variable, so pickups cost nothing
— bwv66.6 (both Phase 3 engines: F1 0%) scores **F1 100% strict 4/4**.

**Weight-tuning facts (measured, don't re-learn them)**:
- Channel-weight sweep was **INERT**: external-channel weight 1.8→4.5 and
  bass_cadence scaling flip ZERO train pieces. ~30 sparse harmonic votes
  cannot move an argmax built from thousands of onset votes. The lever is
  vote DENSITY (per-beat harmonic scores, hierarchical freeze levels),
  not weight scale.
- Structural sweep won: prior sigmas 0.55/1.0 → 0.9/1.4 (train
  1359→1270, val 1385→1371, gate PASS, adopted).

**Measured (validation)**: bus 863 on all 43 pieces — the best engine
overall by a wide margin since 2026-07-08's two adoptions: channel
normalization (`channel_norm: 1`, each channel's vote mass scaled to 1
before weighting — the project's largest single win, piano tier −59%)
and the weight retune it enabled (measure extra multiplier 1.0,
bass_cadence halved — fixing the chorale one-beat-early lock).
Thermo still leads the essen tier (200 vs 382). Worst failures: long dense movements
(mozart_k155 205, beethoven 9/8 218) and archaic meters — where denser
harmonic votes are the predicted fix (oracle test: perfect harmonic votes
lift bwv846 from 0.673 to 1.000).

**Output**: `phase4_bus_{base_key}.json` — top-level `barlines[]`
(+measure numbers), `meter{}` satisfying the Phase 5 grid contract
(beats_per_measure, denominator, subdivision, measure_ms, barlines),
`debug{}` with per-channel vote counts.

---

## Phase 5 — Quantize + Notation

**Question answered**: how does the analyzed music become a score?

### 5A Quantize (`phase5_quantize.py`)
Input: ETME notes + ONE grid (spike file, thermo file, or bus file — the
loader unwraps a nested `meter{}` block automatically).
`ticks_per_measure = beats_per_measure × subdivision`.
1. Global tick map by linear interpolation between barlines,
   extrapolated beyond first/last barline at the mean tick duration.
2. **Strike clusters**: notes within 45ms of a cluster's first note snap
   together (chords stay chords).
3. **Sequence preservation** per voice: a later note may not land on or
   before an earlier note's tick (forced to +1) unless same cluster.
4. Durations snap to nearest tick, min 1 tick; **monophony enforcement**
   truncates a note at the next note's start within the same voice.
5. Each note gains `quantized: {abs_tick_start, abs_tick_end,
   duration_ticks, measure, beat, sub_tick}`.
Output: `phase5_quantized_{...}.json` (full ETME data + quantized).

### 5B Notation (`phase5_notation.py`)
1. **Key detection**: velocity×duration-weighted pitch-class histogram,
   Pearson-correlated against Temperley CBMS (default) or
   Krumhansl-Schmuckler profiles, major+minor over all 12 tonics.
2. **Enharmonic spelling** on the line of fifths for the detected key,
   with a chronological accidental-memory pass dropping redundant
   accidentals within a measure.
3. **Score assembly**: voices→staves (V1/V2 treble, V3/V4 bass), rests
   filled, durations/dots/ties computed, emitted as the DreamFlow
   `IntermediateScore` JSON: measures → staves → voices → notes with
   `keys, duration, dots, accidentals, tiesToNext, beat, vfId`.
Output: `phase5_notation_{...}.json`, rendered by the visualizer's
VexFlow renderer (local `dreamflow` package — NOT OSMD, and NOT an npm
dep: `file:../../../UltimatePianist Repos/dreamflow`).

**Not yet scored**: corpus GT already carries key + per-note spelling;
the scorer auto-activates when Phase 5 emits `key` / `spelling` fields.
That wiring is the cheapest way to give Phase 5 numbers.

### 5C MusicXML export (`phase5_musicxml.py`)
The back-propagation endpoint: quantized notes → standard MusicXML 4.0, the
same interchange format a human-authored score uses. Exports from the 5A
quantized notes (NOT from 5B's output) and reuses 5B's key detection and
enharmonic spelling as a library — 5B emits the VexFlow dialect (rests
pre-resolved, accidentals chronologically filtered) while MusicXML wants
absolute `<divisions>`, explicit `<backup>` between voices, and unfiltered
accidentals. One part, two staves, 5B's voice map.

`divisions` (per quarter) is derived as `subdivision × denominator / 4`, so
one Phase 5A tick is one division whenever that is integral.

**Beaming is an engine output, not an engraving detail.** Beam groups follow
the meter the engine inferred, so they are a metrical assertion that can be
scored. `beam_group_ticks`: compound meters (6/8, 9/8, 12/8) beam by the
dotted-quarter group of three; **4/4 beams to the half-bar** (beaming to the
quarter was measured wrong — 40/40 of the initial disagreements against the
engraved Clementi); everything else beams to the beat. Only the primary
(8th-level) beam is emitted. Before this, NEITHER 5B nor 5C emitted beams —
the VexFlow renderer inferred them at draw time, so beaming was the
renderer's guess and was never the engine's claim.

**`merge_monophonic_voices` (architectural fix, not a patch)**: Phase 2
splits one melodic line across two voices (the 3→4 / fast-run instability in
docs/voice_threading_issues.md). Downstream, each voice sees gaps where the
other's notes are, so a bar of continuous eighths beamed as nothing at all.
5C merges same-staff voices whose notes never overlap in time — they were
one voice all along. Voices with genuinely overlapping spans are left alone,
so real polyphony cannot be flattened. Beaming 78.5% → 97.2%.

**Gotcha**: 5A measure numbering is 0-based on some grids and 1-based on
others, and an anacrusis can make `abs_tick_start` negative — so each
measure's tick origin is derived from the notes IN that measure, never from
the first measure number. Getting this wrong overflows bars silently
(6/8 mazurka: 74 malformed measures; the 1-based Clementi looked fine).
Output: `<name>.musicxml`.

### Comparing a generated score against a real one
`run_xml_compare.py --midi X.mid --xml X.musicxml [--name N] [--engine bus]`
runs the whole chain and writes `visualizer/public/compare/<N>/`
(manifest, both IntermediateScores, both MusicXMLs, comparison.json), then
the GUI at **`/compare`** shows them stacked with synchronized scrolling,
diff-coloured notes and a note-by-note table.

`compare_musicxml.py` is the scorer: NOTES ONLY (dynamics, articulations,
fingerings, slurs, ornaments and layout are out of scope by design). It
matches on (onset within `--tol` quarters, exact pitch), greedy
nearest-onset and one-to-one. Spelling and duration agreement are reported
separately as secondary stats — they are 5B/5A quality signals, not
note-identity errors.

**Note accuracy is NOT a result when the MIDI came from the score.** If the
MIDI is a render of the reference MusicXML (the usual case for an ad-hoc
pair), pitch+onset agreement is the identity function — it proves the
renderer round-trips, nothing about the pipeline. `compare_musicxml.py`
output is therefore an *alignment check*; the real scorecard is:

`score_notation.py -g gen.musicxml -r ref.musicxml --grid <grid>.json`

scores what the engine actually decides, taking truth from the reference's
own structure (part index = hand, measure offsets = downbeats, beam groups =
beaming):

- **hands (L/R)** — Phase 2 voices collapsed to staves vs the reference's
  parts, reported raw AND under the best global mapping (so a wholesale
  label swap reads as a swap, not as 0%), plus per-hand accuracy;
- **downbeats** — engine barlines vs measure starts, P/P/F1 at ±tol, same
  two-pointer 1:1 discipline as the corpus scorer, plus time signature;
- **beaming** — per adjacent pair of beamable notes, do both sides agree
  they are beamed together? (a metrical claim, see 5C below);
- **notated duration** and **stem direction** (engraving only).

**Measured (user's Clementi Sonatina, 333 notes, bus grid)**: downbeats
**F1 100%** / 0 errors / 4/4 strict · hands **94.6%** (RH 96.5, LH 90.6) ·
beaming **97.2%** · rhythm **88.0%**.

The residuals are both real engine leads, not export artifacts: the 18 hand
errors sit entirely in the D4–F4 crossover where Phase 2's pitch-proximity
threading fails, and the 40 rhythm errors are one systematic cause — Phase
5A's monophony truncation writing eighths where the score holds quarters.

---

## Evaluation infrastructure (how truth is decided)

- **Corpus**: `corpus files/corpus_full` — 89 pieces (36 Bach chorales,
  40 Essen folk songs, demo 4, piano tier: Clara Schumann polonaises ×4,
  Chopin mazurka, Mozart K545, CPE Bach, 2 quartet movements). Built by
  `make_ground_truth.py` (music21+mido in `corpus files/venv/`); MIDIs
  are leak-free (no TS/key metadata), 120 BPM convention, anacrusis
  encoded. Velocities are flat 80 — NEVER tune velocity weights here.
- **Split**: `benchmarks/corpus_split.json` — stratified 44 train / 43
  val. Grid searches use train only; the benchmark gates on val.
- **Held out forever**: Pathétique 64s chunk + 116 hand markers (the only
  Phase 1 ground truth and the only real-velocity data).
- **Scorer** (`corpus files/score_against_truth.py`, stdlib): downbeats
  (two-pointer 1:1 matching ±tol → P/R/F1, errors=FP+FN), meter
  strict/family, key, voices (best label permutation + fragmentation),
  spelling. Diagnostics name the failure: period_ratio (0.5 =
  half-measures, hierarchy error), phase_offset vs anacrusis_ms (phase
  bug), mean_abs_snap_err (jitter).
- **Runner** (`run_corpus_eval.py`): full pipeline → all three meter
  engines + voices scored per piece → runs.csv.
- **Gate** (`run_benchmark.py`): scorecard vs committed
  `benchmarks/baseline.json`. Severity 1 (downbeat errors ×3 engines,
  held-out P1 errors) / severity 2 (voice accuracy). Verdicts
  PASS(0)/REGRESSION(1)/TRADEOFF(2). Deterministic pipeline → no noise
  band. Full workflow: docs/benchmarking.md.
- **Grid searches**: `optimize_params.py` (Phase 1 vs markers),
  `grid_search_thermo.py`, `grid_search_bus.py`. Pattern: freeze
  upstream, sweep one phase, rank on train, confirm on val, gate, adopt
  + re-baseline in the same commit.
- **Ad-hoc pairs** (`eval_pair.py`): user MIDI + user MusicXML → the XML
  becomes ground truth via the factory, the MIDI runs the full pipeline,
  all engines + voices scored, with an onset-overlap alignment check.
- **Reporting is tier-stratified**: the benchmark prints per-tier
  downbeat errors (chorale / essen / mixed-piano) because 76/89 corpus
  pieces are chorales+folk and aggregates would mask piano regressions.

**Result history worth remembering**: thermo > spike (14/18 pieces);
greedy voices > beam (92.3 vs 87.1) yet beam slightly helps both meters;
relaxation corpus-neutral; thermo V4/V1 weights 4/3 adopted (+); partial
discharge REJECTED; bus channel weights INERT; bus prior sigmas 0.9/1.4
adopted (+).

---

## File map

| File | Phase | Reads → Writes |
|---|---|---|
| export_etme_data.py | 1+2 | MIDI → etme_*.json (has `--relaxation`, `--phase2_model`) |
| harmonic_regime_detector.py | 1 | (library) |
| voice_threader.py / voice_threader_beam.py | 2 | (libraries) |
| run_phase2.py | 2 | etme_*.json → same, voice tags added (greedy only) |
| phase3_thermo_meter.py | 3 | etme → phase3_thermo_{key}.json |
| phase3_spike_meter.py | 3 | etme → phase3_grid_{key}.json |
| phase4_make_votes.py | 4 | etme + thermo → phase4_votes_*_{key}.json |
| phase4_meter_bus.py | 4 | etme + votes → phase4_bus_{key}.json |
| signals_common / accent_rhythm / parallelism / surprisal / melodic_attraction | 4 | (signal libraries) |
| energy_hierarchy.py | 4 | standalone freeze annotator (primary/secondary) |
| phase5_quantize.py | 5 | etme + grid → phase5_quantized_*.json |
| phase5_notation.py | 5 | quantized + grid → phase5_notation_*.json |
| phase5_musicxml.py | 5 | quantized + grid → *.musicxml (Phase 5C) |
| musicxml_to_score.py | 5 | reference .musicxml → IntermediateScore (needs music21) |
| compare_musicxml.py | eval | two .musicxml → alignment check (needs music21) |
| score_notation.py | eval | two .musicxml + grid → hands/downbeats/beaming/rhythm scorecard (needs music21) |
| run_xml_compare.py | eval | MIDI + reference .musicxml → visualizer/public/compare/&lt;name&gt;/ |
| run_corpus_eval.py / run_benchmark.py / grid_search_*.py / make_corpus_split.py | eval | see Evaluation |
| visualizer/ (Next.js) | UI | runs the whole chain via /api/run-python; views per phase |

`{base_key}` = etme filename minus `etme_` prefix, split at the angle-map
token (`_dissonance`/`_fifths`).

---

## Open problems (ranked by expected payoff — 2026-07-07 review)

1. **Soft evidence + channel normalization** — DONE 2026-07-08 and
   CLOSED: normalization adopted (bus 1371→945), weight retune adopted
   (945→863). Dense channels (salience, Δη+) measured OUT: salience is
   inert at every weight (no phase information beyond onset_pulse), Δη+
   hurts. They remain available in phase4_make_votes.py for experiments.
   The harmonic-density path now requires per-beat harmonic QUALITY
   labels — see external data (DCML) below.
2. **Piecewise grids via DP with a switch penalty**: one (period, phase)
   per piece makes time-signature changes unwinnable by construction
   (chorale_010 is 4/4|3/4|4/4 in our own corpus) and long movements
   accumulate risk. Windowed DP with an inertia/switch cost is ONE
   mechanism that solves meter changes, the long-dense failures, AND
   becomes the rubato tracker for live MIDI when the penalty is loosened
   into phase correction (Large-Jones). Thermo degeneracy (open problem
   formerly #2) folds into this.
3. **External data**: the ASAP dataset (aligned scores + performance
   MIDI with downbeat labels) is the bridge to real velocities and
   rubato — the velocity channel is dormant on flat-80 corpus data. The
   DCML annotated corpora (Mozart sonatas, Beethoven quartets,
   When-in-Rome) carry beat-level harmony labels: corpus-scale Phase 1
   supervision instead of 116 hand markers, and real ground truth for
   the dense harmonic channel from (1).
4. **Phase 5 scoring**: wire key/spelling into the scorer (GT already
   captured) + add duration accuracy vs GT (min-1-tick snapping and
   monophony truncation are silent distortions only a metric catches).
   Then: regime-aware spelling (spell against the local tonicization,
   not the global key) and per-measure subdivision (a global value
   fails on duplet/triplet mixtures).
5. **Phase 2 weight search** — neither threader's cost weights have ever
   seen an optimizer; chorale SATB gives the objective (greedy 92.3 vs
   beam 87.1). Decompose costs, stratify per-voice metrics, encode the
   greedy post-patches as beam cost terms, then sweep.
6. **Engine consolidation** (after (1) passes the gate): retire spike
   (measured-worst), demote thermo to a freeze/salience channel
   generator, make the bus the sole meter decider. Three engines is A/B
   discipline, not a destination.
7. Rolling/corpus-calibrated thermo percentile thresholds (per-piece
   percentiles are unknowable mid-performance); measure numbering across
   chunks; `dreamflow` local-path dependency.

**Ad-hoc ground truth**: `eval_pair.py --midi X --xml Y` — the MusicXML
is the truth (120 BPM convention), the MIDI runs the full pipeline, every
decision is scored, alignment is sanity-checked first.
