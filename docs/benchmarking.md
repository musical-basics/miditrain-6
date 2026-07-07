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
1385→1368, gate PASS (all other metrics exactly unchanged). Adopted
into phase4_meter_bus.py DEFAULT_WEIGHTS.

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
- 2026-07-07 (bus prior sigmas 0.9/1.4 adopted — CURRENT): bus=1368,
  thermo=1147, spike=1694, heldout=27 (F1 88.0), voices=90.57%.

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
