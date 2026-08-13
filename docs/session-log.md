# Session Log

## 2026-08-13 — Phase 5C MusicXML export + score comparison GUI

Closes the loop the project was missing: MIDI in, **MusicXML out**, diffed
against a human-authored score. Everything this session is ADDITIVE — no
existing pipeline file was modified, so `benchmarks/baseline.json` is
untouched by construction and the gate was not re-run.

**New: Phase 5C (`phase5_musicxml.py`)**. The pipeline previously ended at
the DreamFlow `IntermediateScore` (VexFlow-shaped, with rests already
resolved and a chronological accidental filter). MusicXML needs absolute
`<divisions>`, explicit `<backup>` between voices, and unfiltered
accidentals — a different dialect, so 5C exports from the Phase 5A
quantized notes directly and reuses 5B's key detection + enharmonic
spelling as a library rather than translating one dialect into the other.
One part, two staves, Phase 5B's voice map (V1/V2 treble, V3/V4 bass).

**New tooling**:
- `compare_musicxml.py` — notes-only diff. Matches on (onset within tol,
  exact pitch), greedy nearest-onset and one-to-one (same no-double-counting
  discipline as the downbeat scorer). Spelling and duration agreement are
  reported as SEPARATE secondary stats, not note-identity errors.
- `musicxml_to_score.py` — reference MusicXML → IntermediateScore, so both
  scores render through the SAME VexFlow renderer and any visual difference
  is a real difference in the notes, not two renderers' conventions.
- `run_xml_compare.py` — one command for the whole loop; writes
  `visualizer/public/compare/<name>/`.
- GUI at **`/compare`** (`ScoreCompare.js` + `/api/compare-runs`): stacked
  staves with **synchronized horizontal scrolling**, a scorecard, and a
  note-by-note table. Generated notes are recoloured by comparison status
  (neutral = matches, amber = right note/wrong duration or spelling, red =
  not in the reference), with a toggle back to Phase 1 harmonic colour.

**Result on the user's Clementi Sonatina** (Op. 36 No. 1, 333 notes):
the bus engine gets **4/4 strict, F1 100%, 0 downbeat errors**, and the
back-propagated MusicXML is **100% note-accurate — precision, recall and
F1 all 1.000, exact at ZERO onset tolerance**, spelling 100%, key C major
correct. The only difference is **duration: 88% (40/333)**, and it is a
single systematic pattern — repeated notes the score holds a quarter, the
engine writes as an eighth. That is Phase 5A's documented monophony
truncation (it cuts a note at the next onset in the same voice), i.e. a
known silent distortion, now visible and measurable for the first time.
It is exactly the "duration accuracy vs GT" metric that pipeline_reference
open problem #4 asked for.

**Gotcha found and fixed** (would have bitten anyone reusing 5C): Phase 5A
measure numbering is **0-based on some grids and 1-based on others**, and
an anacrusis can push `abs_tick_start` negative. Anchoring a measure's tick
origin on `first_measure` therefore silently overflowed bars — a 6/8
Chopin mazurka produced 74 malformed measures while the 1-based Clementi
looked perfect. 5C now derives each measure's origin from the notes
actually in it. Verified: 4/4 Clementi and 6/8 mazurka (787 notes) both
export bar-exact, music21 parses both.

**Verification**: `npx tsc --noEmit` clean, `pnpm build` clean, both
scores render in a real browser (screenshotted), scroll-sync asserted in
Playwright, dev server killed.

## 2026-07-08 — Channel normalization: the largest single win

Roadmap item #1 (soft evidence + normalization) executed via the gated
loop:

- Built dense soft-evidence extraction (`phase4_make_votes.py`):
  Phase 1 per-keyframe salience from the already-persisted debug.diff
  (~1 vote/onset vs ~30 binary spikes) and thermo Δη+ from grid_sample.
- Built `normalize_channels` in the bus combiner (`channel_norm` flag):
  each channel's total vote mass scales to 1 before weighting.
- `--soft` sweep (8 configs): **normalization alone: train 1270→817,
  val 1368→872 inline / 945 production**. Gate PASS, adopted. Bus is
  now the best meter engine (945 vs thermo 1147 vs spike 1694), and the
  per-tier breakdown (added this session) shows the win concentrated in
  the piano tier: 592→243 (−59%) — the product domain. Chorale −64,
  essen −13; thermo still leads the essen tier (200 vs 392).
- Dense channels at default weight: modest help without norm, slight
  HURT under norm — their weights need a dedicated sweep before
  adoption. The 872/945 inline-vs-production gap traces to the external
  channel weight (1.0 vs 1.8) — i.e. the weight knob is now live, and
  the re-run weight sweep (grid widened down to 0.5) is the follow-up.
  (First run of that sweep silently skipped normalization — the harness
  keyed norm off the sweep config, not the production default; fixed.)
- **Weight retune under norm (24 configs)**: the knob is live — spread
  807–1078 where the pre-norm sweep was flat. Winner: measure extra
  multiplier 2.2→1.0 + bass_cadence HALVED. Train 967→807, val 949→867,
  gate PASS. Chorales 310→222 (chorale_013 −31, two chorales to zero) —
  normalization unmasked the scaffold doc's one-beat-early bass
  diagnosis. Final baseline: **bus=863** (chorale 222 / essen 382 /
  piano 259) vs thermo 1147 vs spike 1694. One day's arc: 1371→863.
- **Dense-channel weight sweep: NEGATIVE.** Salience inert at every
  weight; Δη+ hurts ≥1.0. Dense-as-extracted adds nothing under norm —
  the harmonic-density path now runs through real per-beat labels
  (DCML), not re-weighted change salience. Roadmap #1 closed: norm
  adopted, dense channels measured out. docs/HANDOFF.md written.
- Also this session: `eval_pair.py` (user MIDI + MusicXML ad-hoc ground
  truth, alignment-checked) and tier-stratified benchmark reporting.

## 2026-07-07 (later) — Bus grid searches: weights inert, prior widths win

- **Channel-weight sweep (18 configs): INERT.** External-channel weights
  (1.8→4.5) and bass_cadence scaling flip ZERO train pieces — ~30 sparse
  harmonic votes can't move an argmax built from thousands of onset
  votes, at any scale. The corpus's answer to "tune the harmonic channel
  weight" is: the weight isn't the lever, vote density is. To make the
  harmonic channel decisive it needs richer votes (e.g. hierarchical
  freeze levels from energy_hierarchy, or per-beat harmonic-change
  scores), not a bigger multiplier.
- **Structural sweep (8 configs): WIN.** tactus_prior_sigma_oct
  0.55→0.9 + measure_prior_sigma_oct 1.0→1.4: train 1359→1270 (−89),
  val 1385→1371 via the production path (the sweep's inline predictor said 1368; CLI barline int-rounding flips 3 boundary matches), gate PASS, adopted. The narrow van-Noorden prior — not
  the 1600ms search ceiling — was crushing slow-tactus pieces
  (MAX_PERIOD widening alone changed nothing). Movers: two Essen songs
  23→0 each, mozart_k155 −18; cost: op023 +37, chorale_009 0→9.
- New baseline: bus=1371, thermo=1147, spike=1694, heldout=27 (88.0),
  voices=90.57%.

## 2026-07-07 — Phase 4 = meter evidence bus; quantize/notation renumbered to Phase 5

**New phase map**: P1 harmonic regimes → P2 voice threading → P3 meter
(thermo + legacy spike) → **P4 meter evidence bus** → P5 quantize+notation.

- Installed the signal scaffold from `more miditrain files/` (canonical
  copies now at repo root; theory doc → docs/phase4_signal_scaffold.md):
  signals_common, accent_rhythm, parallelism, surprisal,
  melodic_attraction, energy_hierarchy, and the combiner as
  `phase4_meter_bus.py`. The bus does one joint (period, phase) argmax
  over literature channels (Povel-Essens, agogic, LBDM, IDyOM surprisal,
  Lerdahl attraction, gap-fill, bass cadence, GTTM parallelism) plus our
  engines as external vote channels (`phase4_make_votes.py` converts
  Phase 1 spikes + Phase 3 freezes).
- Bus meter block extended for the Phase 5 grid contract
  (beats_per_measure/denominator/subdivision + barline measure numbers);
  phase5_quantize/notation renamed from phase4_* and accept all three
  grid sources. Visualizer: Phase 4 view (bus barlines + channel-vote
  legend), "Grid: Meter Bus" option, 7-step runEngine, all Phase 5
  renames. tsc + build clean.
- Eval/benchmark now score the bus as a third engine
  (downbeat_errors_bus, severity 1).

**Measured results** (val split, ±50ms):

- bwv66.6 with harmonic votes: **F1 100%, strict 4/4** — the anacrusis
  piece both our engines scored 0% on. Phase handled by construction.
- Full val: bus=1385 vs thermo=1147 — but NOT comparable directly:
  thermo skips its 6 impossible pieces, bus scores all 43. On the 37
  shared pieces: bus 1272 vs thermo 1147, head-to-head 17-17-3. Bus
  covers thermo's failures at ~19 err/piece. Bus worst: mozart_k155
  (223), beethoven 9/8 (218), essen op003 (archaic 4/1 outside default
  240-1600ms period range — known limit). Bus weights are deliberately
  rough; weight tuning via --config sweeps is the next grid search.
- **Partial-discharge experiment REJECTED by the gate**: ported
  energy_hierarchy's partial discharge into thermo's Step 3.3 energy
  reset → thermo regressed (polonaises +32/+31, chorales +14/+10).
  Reverted. energy_hierarchy.py stays as a standalone annotator (its
  primary/secondary freeze labels can still feed the bus as votes).
  First candidate formally rejected by the benchmark gate — the process
  works in both directions.

## 2026-07-06 — Corpus expanded to 89 pieces; first gated grid search adopted

- Built `corpus files/corpus_full` with the factory (music21+mido in
  gitignored `corpus files/venv/`): demo 4 + 36 chorales + 40 Essen folk +
  piano tier (Clara Schumann polonaises ×4, Chopin mazurka 3/4, Mozart
  K545 exposition, CPE Bach h186) + 2 quartet movements (incl. 9/8
  Beethoven). 89 pieces, 0 skips, 87 metered.
- `make_corpus_split.py` → stratified deterministic 44 train / 43 val
  split, committed as benchmarks/corpus_split.json. run_benchmark.py now
  gates on the VAL split (+ held-out Pathétique); grid searches use train.
- Val-split baseline (old thermo defaults): thermo=1188 spike=1694
  heldout=27 voices=90.57% — thermo's win over spike generalizes beyond
  the chorale-heavy demo set.
- **First gated grid search** (`grid_search_thermo.py`, 27 configs,
  Phase 1+2 frozen): winner bass weight 3.0→4.0, melody 2.0→3.0
  (MIN_FREEZE_MS stays 50). Train 1323→1289, val 1278→1237, benchmark
  gate PASS (spike/voices/heldout exactly unchanged). Adopted as
  phase3_thermo_meter.py defaults; new baseline: **thermo=1147**.
  First parameter change in the project set by corpus evidence instead of
  intuition. Note the movers: the gain concentrates in chorales/folk;
  mozart_k155 and polonaise_op1n1 got slightly worse — texture-specific
  weighting is a future question.
- Six val pieces still produce no thermo meter (sparse freezes on short
  monophonic folk songs) — the tactus degeneracy remains the top thermo
  bug.

## 2026-07-05 (night) — Regression gate: run_benchmark.py + committed baseline

Built the cross-phase regression gate (see docs/benchmarking.md for the
full workflow). `run_corpus_eval.py` refactored to expose `evaluate()`;
new `run_benchmark.py` runs the full pipeline over the corpus AND the
held-out Pathétique chunk, producing one scorecard: downbeat errors for
both meter engines + held-out Phase 1 marker errors (severity 1), voice
accuracy (severity 2). Compares against committed
`benchmarks/baseline.json`; verdict PASS / TRADEOFF / REGRESSION
(exit codes 0/2/1), with per-piece movers.

Validation: held-out scoring reproduces the historical V3.1 optimizer
result exactly (27 errors, F1 88.0); identical re-run → PASS identical
(pipeline fully deterministic); beam-P2 candidate → TRADEOFF (meters
−41/−75 errors, voices −5.2pp), correctly not auto-adopted. Baseline
saved: thermo=729 spike=1113 heldout_P1=27 voices=92.26%.

Open: expand corpus with piano tier + train/validation split before grid
search; wire Phase 4 key/spelling into the scorecard.

## 2026-07-05 (evening) — Corpus harness wired in; first measured fights

**What arrived** (built externally, dropped into `corpus files/`):
`make_ground_truth.py` (music21/MusicXML → leak-free MIDI + ground-truth
JSON; needs `pip install music21 mido`), `score_against_truth.py` (pure
stdlib scorer: downbeats/meter/key/voices/spelling, format-sniffing,
diagnostics that name the failure mode), `corpus_harness.md` (the doc), and
`corpus_demo/` — 21 pre-rendered pieces (4 smoke, 12 chorales, 5 Essen folk
songs) with manifest. The zip duplicate is gitignored; `corpus_runs/`
(eval outputs) is gitignored.

**What was built here**: `run_corpus_eval.py` — runs the full pipeline
(export_analysis with the V3.1 rank-1 config loaded from
final_optimized_configs.json, then BOTH Phase 3 meter engines) over every
metered manifest row, scores each engine's barlines against ground truth
(±50ms), scores Phase 2 voices on polyphonic pieces, accumulates
corpus_runs/runs.csv, prints a summed-errors table. Flags: --pieces,
--phase2_model, --relaxation, --tag-suffix, --tol, --include-free-meter.
Thermo predictions are scored by flattening the file's meter block (scorer
sniffs top-level barlines).

**First measured results** (19 metered pieces, errors = FP + FN):

| tag | downbeat errors | mean F1 | notes |
|---|---|---|---|
| spike (greedy) | 1113 | 0.143 | |
| thermo (greedy) | 729 | 0.201 | 1 failure (op004: too few freezes) |
| spike_beam | 1038 | | beam voices help meters a little |
| thermo_beam | 688 | | |
| spike_relax / thermo_relax | 1113 / 729 | | relaxation is a wash on corpus |

- **Thermo beats spike** on 14/18 head-to-head pieces. The freeze theory
  wins the first fight; both are weak in absolute terms (Pathétique-only
  tuning — that's what corpus grid search is for next).
- **Voices: greedy 92.3% vs beam 87.1%** mean note accuracy on SATB
  ground truth (16 polyphonic pieces). The newer beam threader LOSES to
  greedy on chorales — first hard evidence; the beam's cost weights were
  tuned by eye on Pathétique arpeggios.
- **Relaxation is corpus-neutral** (identical errors): in SATB texture the
  lowest-note proxy already IS the bass. It only pays on piano textures
  (Pathétique +0.6 F1). Keeps its off-by-default toggle.
- bwv66.6 diagnostics name distinct failure modes: spike finds
  half-measures (period_ratio 0.5), thermo finds a 1.5× period. Neither is
  the pure anacrusis-phase bug on that piece.

**Known limits respected**: corpus velocities are flat 80 — no
velocity-weight tuning on corpus tiers; free-meter Essen songs excluded by
default; Pathétique chunks stay held out.

**Next**: corpus grid search over meter params (existing optimize_params
pattern on top of runs.csv); beam-weight retune against chorale voice GT;
anacrusis-aware phase search in barline projection.

## 2026-07-05 (later) — Thermo grid source + P1↔P2 relaxation pass

**What was done**

1. **Thermo meter can now feed Phase 4** (plan-doc goal "thermodynamic meter
   IS Phase 3"):
   - `phase3_thermo_meter.py`: new `_estimate_subdivision()` — sub-tactus from
     note-onset IOI clustering (10ms bins), subdivision = freeze-tactus /
     sub-tactus snapped to the musical-norm ladder [1,2,3,4,6,8,12] with a 35%
     rejection tolerance. `meter{}` block now includes `subdivision` +
     `sub_tactus_ms`. Pathétique: 1000ms tactus / 80ms triplet-16ths → 12.
   - `phase4_quantize.py` / `phase4_notation.py` accept either grid shape:
     flat spike grid, or a thermo file with keys nested under `"meter"`.
   - Visualizer: "Grid: Spike (Legacy) | Thermo (Phase 3)" dropdown selects
     which meter's grid the Phase 4 steps consume; the Phase 4A view and
     legend render against the same `activeGrid`. Thermo step becomes fatal
     in runEngine when selected as grid source.

2. **P1↔P2 relaxation pass** (plan-doc item 1, fixed two passes, opt-in):
   - Keyframe note tuples gain an optional 5th element `is_bass`
     (contract: `(interval, octave, velocity[, duration_ms[, is_bass]])`).
     `HarmonicRegimeDetector._build_particles` uses the annotation when
     present, else falls back to the lowest-note-per-keyframe proxy. The
     octave ≤ 3 register gate is retained in both modes.
   - `export_etme_data.py`: `--relaxation` flag → pass 1 (P1 proxy → P2),
     then Voice 4 notes are layered back onto the keyframes via
     `annotate_keyframes_with_bass()` (pitch reconstructed from
     interval+octave, matched inside the 50ms grouping window), then pass 2
     (fresh P1 → fresh P2). Also added `--bass_multiplier` (default 1.0;
     V3.1-tuned value is 2.0) since relaxation is a no-op without bass
     authority. Inline regime-consolidation/frame-lookup code extracted into
     `consolidate_regimes()` / `build_frame_lookup()` so both passes share it.
   - `stats.relaxation` recorded in the export JSON.
   - Visualizer: "P1↔P2: Single Pass | Relaxation (Bass ×2)" dropdown; when
     on, runEngine passes `--relaxation --bass_multiplier 2.0`. Not available
     for `__optimized__:` datasets (Phase 1 is fixed there) — logged and
     skipped.

**Measured** (Pathétique 64s chunk, hybrid/J=0.375/mass=0.75/bass ×2,
100ms tolerance vs ground-truth markers): single pass P=80.0 R=79.3 F1=79.7;
relaxation P=81.4 R=79.3 F1=80.3 (two false positives removed, one spike
boundary moved 10625→10875ms). Voice assignments converged after pass 2
(identical voice counts) — consistent with the plan doc's "two passes
converge in practice".

**Verified**: A/B export runs deterministic; thermo-grid quantize works on
Pathétique (2/2, 12 subdivisions, 24 ticks/measure); module imports for
`optimize_params.py`/`run_phase2.py` unaffected; `tsc --noEmit` and
`pnpm build` clean.

**Left incomplete**

- Thermo tactus degenerates when freezes are sparse (Revolutionary:
  tactus=measure → subdivision 1). Needs corpus-harness tuning, not plumbing.
- Relaxation's bass ×2 in the UI is hardcoded to the V3.1 tuned value; a
  proper `bass_multiplier` control (or optimizer-driven value) is future work.
- Batch runner still runs single-pass/greedy only.

## 2026-07-05 — Phase 3 + Phase 4 ported from miditrain-4

**What was done**

Ported the downstream pipeline stages from miditrain-4 into this repo, with the
honest renumbering proposed in `plan for improvements.md` (thermodynamic meter
= Phase 3, quantize-and-notate = Phase 4; no more "Step 2.5"):

- `phase3_thermo_meter.py` (was miditrain-4 `thermodynamic_meter.py`, "Step 2.5")
  → writes `visualizer/public/phase3_thermo_{base_key}.json`
- `phase3_spike_meter.py` (was `phase3_meter.py`, "Phase 3A")
  → writes `visualizer/public/phase3_grid_{base_key}.json`
- `phase4_quantize.py` (was `phase3b_quantize.py`)
  → writes `visualizer/public/phase4_quantized_{...}.json`
- `phase4_notation.py` (was `phase3c_notation.py`; the misleading
  `osmd_ready` output prefix renamed to `phase4_notation_` — the renderer is
  VexFlow, not OSMD) → writes the DreamFlow IntermediateScore JSON
- All four are pure stdlib; no new entries in `requirements.txt`.

Visualizer:

- Added `dreamflow` local file dependency (`file:../../../UltimatePianist
  Repos/dreamflow` — the VexFlow fork; must exist at that path for
  `pnpm install`).
- Copied `app/components/dreamflow/` (VexFlowRenderer etc.) and
  `NotationView.js` from miditrain-4 (prop renamed `phase3cData` →
  `notationData`).
- New `Phase3Renderer.js` / `Phase4Renderer.js` following this repo's
  renderer-module pattern (extracted from miditrain-4's inline canvas code).
- `ETMEVisualizer.js`: four new views in a "Phase 3 / 4..." dropdown
  (`phase3` thermo overlay, `phase3_grid` barlines/density/ACF, `phase4a`
  quantized roll, `phase4b` VexFlow notation), fetches for the four new JSONs,
  runEngine extended to a 5-step chain (works for `__optimized__:` datasets
  too), key-algorithm select (Temperley/Krumhansl), notation layout toggle,
  quantized-coords tooltip. Header renamed to "ETME Pipeline Tester".
  Pre-edit backup in `_backup_files/ETMEVisualizer_pre_phase34_port.js`.

Docs ported: `docs/thermodynamic_meter_theory.md`,
`docs/phase3_spike_meter_history.md` (was phase3a_session_summary.md).

**Verified**: full Python chain ran end-to-end on
`etme_revolutionary_64s_chunk_dissonance_hybrid_0.5.json` (thermo → grid →
quantize → notation, detected key Eb); `tsc --noEmit` clean; `pnpm build`
clean; dev server served the page and all four new JSONs (all 200), then was
killed.

**Decisions made**

- Same wiring as miditrain-4: Phase 4 consumes the **spike grid**
  (`phase3_grid_*.json`), not the thermo meter's barlines. The thermo meter's
  `meter{}` block lacks `subdivision`, which the quantizer requires. Promoting
  thermo to grid source = add subdivision estimation to it (open decision).
- Kept both meter engines rather than replacing one (A/B testing rule): thermo
  is the canonical Phase 3 per the plan doc; the spike model is labeled
  "Legacy" in the UI.
- Did not port `test_temperley.py` (scratch test, hardcoded miditrain-3 path,
  duplicates `phase4_notation.py`'s detect_key).
- Test-generated Phase 3/4 JSONs for the revolutionary chunk left untracked,
  matching how the ETME datasets are currently handled.

**Left incomplete / known issues**

- Meter tuning is Pathétique-specific (miditrain-4 known issue): the
  Revolutionary chunk got 8/4 at questionable barlines. Expected — Phase 3 has
  no optimizer harness yet (the plan doc's "ground truth factory" is the fix).
- Measure numbering restarts per chunk (inherited TODO).
- The P1↔P2 relaxation loop (plan doc item 1: re-run P1 with V4 as true bass
  feed) is not implemented.
- See `docs/debt.md` for smaller inherited debts.
