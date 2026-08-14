# Session Log

## 2026-08-14 — Development moved to miditrain-7 (bottom-up rebuild)

User's call: the corpus here trained parameters on chorales/folk (not
the piano domain) and the phases are in the wrong hierarchical order.
**miditrain-7** (../miditrain-7, github.com/musical-basics/miditrain-7)
rebuilds bottom-up on clean 16-bar piano segments: hand separation
FIRST (96.6% overall / 94.7% crossover — beats the phase0 spec's oracle
bar on all metrics), downbeat inference SECOND (100% recall/precision,
10/10 segments strict), per-phase GUI. This repo's phase0_hands_spec
was the design brief; its meter-bus findings (channel norm, prior
sigmas, harmonic-vote density) were reused directly. miditrain-6 stays
as the reference implementation for phases not yet ported (quantize,
notation, engravers, benchmark gate).

## 2026-08-13 (later) — Phase 0 scaffolding; /compare covers the whole corpus

**User's call on corpus scope**, after considering and rejecting full
removal of chorale/essen: they stay (they are the ONLY Phase 2 voice
ground truth, and useful for harmonic inference), but they are not the
target domain — "optimizing a drug for monkeys when humans are the
primary consumer". Piano is primary. Recorded in docs/debt.md.

**Phase 0 (hand separation) proposed as a NEW FIRST phase**, before
harmonic regimes. Rationale: hands are a coarser, physically constrained
partition than voices, and getting them right first constrains Phase 2
and gives Phase 1 a real bass feed. Caveat surfaced and written into the
spec: Phase 0 cannot consume Phase 1/2 output, so it must work on raw
pitch/time alone — a different algorithm, not a reordering.

Built (scaffolding only, per user — implementation goes to an architect
model): `score_hands.py` — ground-truth extractor (MusicXML part index =
hand) + scorer + baselines. Measured over the 4 keyboard pairs now in
`musicxmls/` (Clementi, 2x Burgmüller, Kuhlau; 2435 notes):

| baseline | overall | crossover |
|---|---|---|
| fixed split @ middle C | 72.8% | 43.5% |
| oracle per-piece split | 94.5% | 87.2% |

Three findings that shape the spec: (1) the optimal fixed split moves
almost two octaves between pieces (49 for The Storm, 68 for the
Arabesque), so no global pitch constant is right; (2) **pitch alone
provably cannot solve this** — Clementi's oracle is 91.3% overall but
70.7% in the crossover, and no threshold beats it, because the piece has
pitch-identical hand-opposite textures; (3) line continuity is the
discriminator and is measurable — split@60 makes 130–139 hand switches
inside a single true hand, the oracle drops the Arabesque to 6. The
crossover region is 43% of all notes and is the metric that matters.

Spec: docs/phase0_hands_spec.md.

**/compare now covers the corpus, not just Clementi.** `run_compare_batch.py`
re-exports each corpus piece's music21 source as a reference MusicXML
(the factory built the corpus from those same sources) and runs the full
compare pipeline per piece: **80 runs built, 0 failed**. The run picker
gained a filter box, tier optgroups and prev/next stepping. The "hands"
stat now reads n/a on 4-part references instead of showing a false ~30%
failure — a 2-staff mapping is a category error for SATB.


## 2026-08-13 (end+1) — Idle-hand reclaim: the low-hanging fruit, taken

User's model: **one voice per hand, splitting to two only when a hand holds
a note while playing others.** Checked against the reference — it is exactly
right: the reference is single-voice on both staves in all 38 measures. We
were at 72/76 staff-measures; now 74/76.

**Shipped**: `reclaim_idle_hand` (phase5_musicxml.py). When one hand has
NOTHING in a measure and the other holds a >= half-bar note that is the
lowest sounding pitch with every other note above it, that note goes back to
the idle hand. Clementi m16/m17 are the case the user pointed at — the LH's
entire content is one whole note (F4 / Eb4) and Phase 2 gave it to the RH,
which engraved as the RH playing two voices while the LH rested.

- Hands **94.6% → 95.2%**, LH **90.6% → 92.5%**; downbeats/beaming/rhythm
  unchanged; bars still sum exactly; 6/8 mazurka unaffected.
- Fires on **0 of 363 corpus measures** across 12 pieces — tightly scoped,
  no collateral risk. Only `phase5_musicxml.py` changed, so the benchmark
  baseline is untouched by construction.

**NOT shipped — m9/m11's offbeat D4.** The user's rhythmic-role reasoning is
sound ("the RH cannot bounce A5→D4→A5; that D4 is the LH's"), but it is not
yet decidable from the exported data. Five candidate rules were measured and
all break as much as they fix (table in docs/debt.md). The blocker is
concrete: **m9 and m20 are identical on every extractable feature** — both
are a repeated offbeat run alternating with the other hand's regular pulse,
both have each hand filling 3/3 gaps, and m11 (dLH=2, belongs LH) vs m20
(dLH=2, belongs RH) cannot be separated by pitch distance. The real
difference is which hand owns the underlying figure — m9's D4 continues the
LH's broken-chord accompaniment, m20's G4 continues the RH's own
alternation. That is Phase 2 line-continuity, not something a per-measure
Phase 5C rule can see. Recorded rather than fudged with a threshold that
would only fit this piece.

## 2026-08-13 (end) — Hand-split diagnosed: Phase 2, not engraving

Measure numbers added to all three `/compare` panes (bar-aligned across
renderers, so a number means the same bar everywhere). Verovio's own
`mnumInterval` stays silent on these files — they carry no
`<measure-numbering>` print hints and the SVG keeps no `n` attribute — so
numbers are drawn from the emitted `g.measure` sequence in document order,
sized off the staff bbox (Verovio's internal units make hard-coded font
sizes meaningless; a first attempt rendered a single 776-unit "1").

**Diagnosis of the 18 wrong-hand notes: all 18 are Phase 2 voice-threading
failures. None is an engraving problem.** Full evidence in docs/debt.md.
Headline: V1/V4 are 96–98% clean, V3 is 12/18 — a coin flip — and only fires
18× in the piece. The inner voices are where the split breaks.

**Rejected (measured, not assumed): fixing this in Phase 5C by assigning
staves from pitch.** Current fixed VOICE_MAP 315/333; pure pitch≥C4 303/333;
V1/V4 fixed + inner-by-pitch 317/333. Pitch models tie or lose because the
piece has pitch-identical, hand-opposite textures (m9's D4 sits 5 semitones
above the bass and is LH; m20's G4 sits 2 above and is RH). The real
discriminator is line continuity, which Phase 5C cannot see — it gets one
note at a time. The +2 hybrid is piece-specific noise. VOICE_MAP stays.

Three Phase 2 leads recorded, ranked, each verified against the source and
each requiring the benchmark gate before adoption: (1) inner voices carry a
HEAVIER register-gravity weight than outer ones (0.75 vs 0.5), which pushes
strays out to V1/V4 — the direct cause of m9/m11 and m30; (2) mid-line
thread breaks where one note of a scale defects to another voice; (3)
`_stabilize_inner_voices` only covers V2↔V3, so a V1↔V2 repeated-pitch
flip-flop is invisible to it. Not implemented — Phase 2 changes must be
gated, and per CLAUDE.md the decision is the user's.

## 2026-08-13 (later still) — Verovio as a second renderer; /compare in light mode

User's call, and the evidence backs it: **DreamFlow/VexFlow is a drawing
library, not an engraver.** Beam grouping, spacing and stem logic are whatever
the caller passes in or whatever its heuristics guess, so "is the beaming
right?" could not be answered while VexFlow was the only renderer — a bad beam
might be our data or might be the library.

- Added **Verovio 6.2** (`VerovioScore.js`). It is a real engraver: it applies
  notation rules to the MusicXML itself. Ships as self-contained WASM, so
  nothing is fetched from a CDN and the offline setup is preserved. The
  toolkit is ~7MB and single-instance, so it is created once and shared.
- **Three panes**: generated·Verovio, reference·Verovio, generated·VexFlow.
  Rendering the generated and the reference through the SAME engraver is the
  controlled comparison — any difference there is OURS. The VexFlow pane stays
  so renderer artefacts remain visible instead of being blamed on the data.
  A "Compare renderers" tab puts the same MusicXML through both side by side.
- **/compare is light mode now.** A score is read on paper and the page is
  about comparing engravings. This also fixed an invisible-ink bug: the diff
  recolouring painted its neutral as `rgba(232,232,240,.92)` (a dark-mode
  grey), which on white was white-on-white.
- **Reference markings stripped before engraving.** The file is an "All
  Markings Version"; its fingerings and dynamics are ~50% of the bytes and
  buried the notes. Stripped on the MusicXML (not by hiding SVG) so Verovio
  also reclaims the space they reserved. `<notations>` is deliberately NOT
  stripped — it holds ties and tuplets, which are rhythm.

**Two rendering bugs found and fixed:**

1. **VexFlow allocates a fixed 99999×11500 canvas** regardless of content, so
   the pane reported ~100k px of scroll for ~9.6k px of music and looked blank
   at almost every scroll position. `VexflowPane` measures the real content
   with `getBBox()` after render and crops. Both axes must be corrected AND
   agree with the viewBox — fixing width alone left `height=11500` against a
   361-tall viewBox, which scaled the music to near-invisibility.
2. **Scroll sync was pixel-based.** Verovio engraves this piece ~5.7k px wide,
   VexFlow ~9.6k — matching `scrollLeft` directly put the panes bars apart.
   Sync is now by FRACTION of scrollable extent, and rebinds when a pane's
   extent changes after render (the crop above changes it).

Verified in a real browser: 3 panes render, 0 console errors, all three hold
the same scroll fraction, dev server killed after.

## 2026-08-13 (later) — Scoring what the engine DECIDES, not the identity function

User's correction, and it was right: the Clementi MIDI is a **render of the
same MusicXML**, so comparing pitch+onset measures the identity function.
The 100% "note accuracy" reported earlier was tautological — it proved the
renderer round-trips, not that the pipeline works. It is now demoted to an
explicit *alignment check* everywhere (CLI, manifest, and a standing caveat
line in the GUI).

**New `score_notation.py`** scores the decisions that can actually be wrong,
using the reference's own structure as truth (part index = hand, measure
offsets = downbeats, beams = beam groups):

| decision | Clementi | notes |
|---|---|---|
| downbeats | **F1 100%**, 0 errors, 4/4 strict | genuinely correct |
| hands (L/R) | **94.6%** (RH 96.5 / LH 90.6) | 18 real errors |
| beaming | **97.2%** | after two fixes below |
| rhythm | **88.0%** | 40 notes, one systematic cause |

**Two real bugs this exposed and fixed in Phase 5C:**

1. **Beaming did not exist as an engine output.** Neither 5B nor 5C emitted
   beams — the VexFlow renderer inferred them at draw time, so the "beaming"
   the UI showed was the renderer's guess, not the engine's claim. 5C now
   derives beam groups from the inferred meter (`beam_group_ticks`), which
   makes beaming a scoreable metrical assertion. Groups: compound meters
   beam by dotted-quarter, 4/4 beams to the **half-bar** (measured: beaming
   to the quarter caused 40/40 of the initial disagreements), others by beat.
   64% → 78.5%.
2. **Phase 2 voice-splitting was silently wrecking the engraving.** A bar of
   continuous eighths arrives split across Voice 1 and Voice 2 (alternating
   notes — the known 3→4 / fast-run instability in
   docs/voice_threading_issues.md). Each voice then sees gaps where the
   other's notes are, so *nothing beamed* — measure 7 came out as 8 unbeamed
   eighths. Fixed at the input, not in the beamer: `merge_monophonic_voices`
   merges same-staff voices whose notes never overlap in time. Genuine
   polyphony (overlapping spans) is untouched, so this cannot flatten a real
   two-voice texture. 78.5% → **97.2%**.

**Left as a finding, not patched**: the 18 hand errors are all in the D4–F4
crossover region (measures 9/11 repeated D4 → should be LH; 24–30 G3–D4 →
should be RH). That is Phase 2 pitch-proximity threading failing where the
hands meet, not an export artifact — a real Phase 2 lead. Likewise the 40
rhythm errors are one systematic cause: Phase 5A's monophony truncation
writing eighths where the score holds quarters.

**`run.sh` is now one command**: kills whatever holds the port (by port,
then by name), installs deps only when stale, boots, waits for the server to
actually answer, opens the browser, and traps Ctrl-C so it never orphans a
dev server. `PORT=xxxx ./run.sh` and `--no-open` supported. Verified by
running it twice in a row — second run detected PID, killed it, rebooted,
exactly one server left on the port.

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
