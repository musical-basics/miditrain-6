# Benchmarking & Regression Gate

How to change weights/parameters in any phase without silently regressing
another phase. The core rule: **tune locally, accept globally.**

## The data tiers

| Tier | Data | Role |
|---|---|---|
| Smoke | `corpus files/corpus_demo` (21 pieces) | Quick checks. |
| Tuning (train) | `corpus files/corpus_full` — 87 metered pieces (36 chorales, 38 Essen folk, 13 mixed incl. a piano tier: Clara Schumann polonaises, Chopin mazurka, Mozart K545, CPE Bach, 2 quartet movements) split 44 train / 43 val in `benchmarks/corpus_split.json` (stratified by texture, committed, stable) | Grid searches run on **train only**. Flat velocity 80 — never tune velocity weights here. |
| Gate (val) | The 43-piece validation half | `run_benchmark.py` scores this split — the gate never sees training data. |
| Held out | Pathétique 64s chunk + hand markers | Integration test. **Never tune on it again.** Only place Phase 1 has ground truth, and the only real-velocity data. |
| Eyeball | Revolutionary chunk, Phase 4B notation view | No ground truth; sanity display. |

Corpus building needs music21+mido, installed in `corpus files/venv/`
(gitignored; recreate with `python3 -m venv "corpus files/venv" &&
"corpus files/venv/bin/pip" install music21 mido`). Example:
`"corpus files/venv/bin/python3" "corpus files/make_ground_truth.py" build
--preset chorales --limit 36 --out "corpus files/corpus_full"`. After
adding pieces, re-run `make_corpus_split.py` and review the split diff.

## The gate

```bash
python3 run_benchmark.py --save-baseline     # after adopting a change
python3 run_benchmark.py                     # verify: must be identical
python3 run_benchmark.py --phase2_model beam # gate any candidate change
```

Every run executes the FULL pipeline (so a Phase 2 change automatically
re-scores Phase 3) and produces one scorecard:

| metric | severity | phase |
|---|---|---|
| downbeat_errors_bus (corpus, ±50ms) | 1 — global | Phase 4 (evidence bus) |
| downbeat_errors_thermo / _spike (corpus, ±50ms) | 1 — global | Phase 3 |
| heldout_phase1_errors (markers, ±100ms) | 1 — global | Phase 1 |
| voices_mean_acc (SATB, permutation-matched) | 2 — local | Phase 2 |
| key / spelling (reserved — activates when pipeline emits fields) | 3 — cosmetic | Phase 5 |

Caveat when comparing engines to each other (not to their own baseline):
`downbeat_errors_*` sums only pieces where the engine produced barlines.
Thermo skips pieces with too few freezes (they count as `failed`, not as
errors), while spike and bus always predict. Head-to-head engine claims
should use per-piece comparisons on the shared subset (see runs.csv).

Verdicts (also the exit code, CI-friendly):

- `PASS` (0) — nothing regressed. Safe to adopt; re-run with
  `--save-baseline` and commit `benchmarks/baseline.json`.
- `REGRESSION` (1) — a severity-1 metric got worse. Do not adopt.
- `TRADEOFF` (2) — severity-1 held/improved but something lower regressed.
  A human decides; never auto-adopt. (Example: beam P2 improves both
  meters by 41/75 errors but drops voice accuracy 92.3→87.1%.)

The pipeline is deterministic, so any nonzero delta is real — there is no
noise band. Per-piece movers are printed so a summed improvement can't
hide a per-piece collapse.

## Ad-hoc ground truth: your MIDI + your MusicXML

`eval_pair.py` turns any (MIDI, MusicXML) pair into a scored run — the
XML is the ground truth, rendered through the corpus factory under the
120 BPM convention; the MIDI goes through the full pipeline and every
decision (downbeats per engine, meter, voices) is scored, with an
alignment sanity check up front (onset+pitch overlap %) so a misaligned
MIDI reads as "misaligned", not as pipeline failure:

```bash
python3 eval_pair.py --midi my_piece.mid --xml my_piece.musicxml
python3 eval_pair.py --xml score.xml --use-rendered-midi   # leak-free render
```

Artifacts land in corpus_runs/pairs/<name>/; per-engine rows accumulate
in corpus_runs/pairs/runs.csv. Pieces you want in the permanent corpus
should instead be built via make_ground_truth.py --files into
corpus_full and re-split.

## The adoption loop

1. Tune ONE phase against ITS OWN ground truth (Phase 1 → optimize_params
   vs markers; Phase 2 → chorale SATB; Phase 3/4 → corpus downbeats;
   Phase 4 bus weights via `--config` sweeps, see
   docs/phase4_signal_scaffold.md).
2. Run `run_benchmark.py` with the candidate settings.
3. PASS → adopt (update code/`final_optimized_configs.json`), re-run with
   `--save-baseline`, commit the new baseline in the same commit as the
   change. REGRESSION → reject. TRADEOFF → explicit decision, recorded in
   the session log.
4. The baseline file in git IS the memory of "previous improvements" —
   any later change is judged against it, so nothing gets overridden
   invisibly.

## Grid searches so far

**Thermo structural params, 2026-07-06** (`grid_search_thermo.py`: 27
configs over MIN_FREEZE_MS × bass weight × melody weight, Phase 1+2 frozen
at V3.1, train split): winner `V4_WEIGHT 3.0→4.0, V1_WEIGHT 2.0→3.0`
(MIN_FREEZE_MS stays 50). Train errors 1323→1289, val 1278→1237,
gate verdict PASS (spike, voices, held-out all exactly unchanged).
Adopted as defaults in phase3_thermo_meter.py.

**Bus channel weights, 2026-07-07** (`grid_search_bus.py`: 18 configs
over external-channel weights × bass_cadence scale): **INERT** — all 18
identical on train. The external channels (~30 sparse votes/piece)
cannot move an argmax built from thousands of onset votes at any weight
scale; bass down-weighting slightly hurt val. Weights left at defaults.

**Bus structural params, 2026-07-07** (`grid_search_bus.py
--structural`: 8 configs over max search period × prior widths): winner
`tactus_prior_sigma_oct 0.55→0.9, measure_prior_sigma_oct 1.0→1.4`
(MAX_PERIOD widening alone: zero effect — the narrow prior, not the
range, was crushing slow-tactus candidates). Train 1359→1270, val
1385→1371, gate PASS (all other metrics exactly unchanged; the sweep's
inline predictor said 1368 — CLI barline int-rounding flips 3 boundary
matches). Adopted
into phase4_meter_bus.py DEFAULT_WEIGHTS.

**Soft evidence × channel normalization, 2026-07-08**
(`grid_search_bus.py --soft`: 8 configs): **channel-mass normalization
is the largest single improvement in the project** — normalizing each
channel's total vote mass to 1 before weighting (so influence stops
scaling with vote count) cut train errors 1270→817 and val 1368→872
(inline; 945 via the production path — see below). Gate PASS; adopted as
`channel_norm: 1` in DEFAULT_WEIGHTS. Per-tier: the win concentrates in
the PIANO tier (592→243, −59%) — the product domain — with chorales
−64 and essen −13. The dense soft-evidence channels (Phase 1
per-keyframe salience via debug.diff, thermo Δη+ from grid_sample; now
emitted by phase4_make_votes.py) helped modestly WITHOUT norm but
slightly hurt UNDER norm at default weight — they need their own weight
sweep before joining the defaults. The 872 vs 945 gap traces to the
external-channel weight (sweep ran extras at 1.0, production at 1.8),
which means the weight knob is finally LIVE under normalization — the
follow-up weight sweep exists for exactly this.

**Bus weights retuned under norm, 2026-07-08** (24 configs, harness
fixed to inherit the production channel_norm flag — its first run
silently swept the no-norm regime): configs now spread 807–1078 where
the pre-norm sweep was flat. Winner: measure extra multiplier 2.2→1.0
and **bass_cadence halved** (0.9 / measure 1.0) — normalization
unmasked the scaffold doc's original diagnosis (chorale fifth-arrivals
peak pre-cadentially and lock the grid a beat early). Train 967→807,
val 949→867, gate PASS; chorales 310→222 with chorale_013 −31 and two
chorales to zero. Adopted.

**Dense-channel weight sweep, 2026-07-08** (`grid_search_bus.py
--dense`: 16 configs under production norm): **NEGATIVE, no adoption.**
Salience (per-keyframe debug.diff) is perfectly inert at every weight
(as a per-onset-event channel it folds to ~the same phase histogram as
onset_pulse — no new information); thermo Δη+ hurts at weight ≥1.0 and
is neutral lighter. Conclusion: densifying the harmonic channel needs
harmonic QUALITY per beat (DCML-style labels), not re-weighted change
salience. (Harness note: this sweep also exposed that inline extras ran
at weight 1.0 vs the CLI's 1.8 setdefault — run_config now mirrors the
CLI.)

## Baseline history

- 2026-07-05 (demo corpus): thermo=729, spike=1113, heldout=27 (F1 88.0),
  voices=92.26%.
- 2026-07-06 (val split, pre-adoption): thermo=1188, spike=1694,
  heldout=27, voices=90.57%.
- 2026-07-06 (val split, thermo V4=4/V1=3 adopted):
  thermo=1147, spike=1694, heldout=27 (F1 88.0), voices=90.57%.
- 2026-07-07 (Phase 4 bus added at untuned default weights):
  bus=1385 (all 43 pieces), thermo=1147 (37 pieces), spike=1694,
  heldout=27 (F1 88.0), voices=90.57%. Shared-subset head-to-head:
  bus 1272 vs thermo 1147, 17-17-3.
- 2026-07-07 (bus prior sigmas 0.9/1.4 adopted): bus=1371,
  thermo=1147, spike=1694, heldout=27 (F1 88.0), voices=90.57%.
- 2026-07-08 (bus channel_norm=1 adopted): **bus=945** —
  now the best meter engine overall — thermo=1147, spike=1694,
  heldout=27 (F1 88.0), voices=90.57%. Per-tier bus: chorale 310,
  essen 392, mixed/piano 243 (thermo still leads essen with 200).
- 2026-07-08 (bus weights retuned under norm — CURRENT): **bus=863**
  (chorale 222 / essen 382 / piano 259), thermo=1147, spike=1694,
  heldout=27 (F1 88.0), voices=90.57%.

## Rejected candidates (the gate working in reverse)

- 2026-07-07: partial discharge (energy_hierarchy port) in thermo's
  energy accumulator → REGRESSION (polonaises +32/+31, chorales
  +14/+10 downbeat errors). Reverted; standalone annotator retained.

## Known gaps

- Phase 4 metrics are reserved: GT already has key + per-note spelling;
  scorer activates when phase4_notation emits `key`/`spelling` fields.
- Voice fragmentation is captured by the scorer but not yet in the
  scorecard summary.
- 6 val pieces produce no thermo meter (insufficient freezes — sparse
  monophonic folk songs); they count as failures, not errors. The tactus
  degeneracy fix should target these.
