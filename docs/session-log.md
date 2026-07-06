# Session Log

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
