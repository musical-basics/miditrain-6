# Benchmarking & Regression Gate

How to change weights/parameters in any phase without silently regressing
another phase. The core rule: **tune locally, accept globally.**

## The three data tiers

| Tier | Data | Role |
|---|---|---|
| Smoke / tuning | `corpus files/corpus_demo` (21 pieces; expandable via `make_ground_truth.py`, needs `pip install music21 mido`) | Grid searches and quick checks. Flat velocity 80 — never tune velocity weights here. |
| Held out | Pathétique 64s chunk + hand markers | Integration test. **Never tune on it again.** Only place Phase 1 has ground truth, and the only real-velocity data. |
| Eyeball | Revolutionary chunk, Phase 4B notation view | No ground truth; sanity display. |

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
| downbeat_errors_thermo / _spike (corpus, ±50ms) | 1 — global | Phase 3 |
| heldout_phase1_errors (markers, ±100ms) | 1 — global | Phase 1 |
| voices_mean_acc (SATB, permutation-matched) | 2 — local | Phase 2 |
| key / spelling (reserved — activates when pipeline emits fields) | 3 — cosmetic | Phase 4 |

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
   vs markers; Phase 2 → chorale SATB; Phase 3 → corpus downbeats).
2. Run `run_benchmark.py` with the candidate settings.
3. PASS → adopt (update code/`final_optimized_configs.json`), re-run with
   `--save-baseline`, commit the new baseline in the same commit as the
   change. REGRESSION → reject. TRADEOFF → explicit decision, recorded in
   the session log.
4. The baseline file in git IS the memory of "previous improvements" —
   any later change is judged against it, so nothing gets overridden
   invisibly.

## Current baseline (v3.1 greedy single-pass, 2026-07-05)

thermo=729, spike=1113, heldout_P1_errors=27 (F1 88.0 — exactly
reproduces the historical V3.1 optimizer result), voices=92.26%.

## Known gaps

- Corpus is texture-skewed (12 chorales, 5 folk, ~4 piano-ish). Before
  serious grid search: expand with a piano tier and split train/validation
  inside the corpus so the search can't memorize 19 pieces.
- Phase 4 metrics are reserved: GT already has key + per-note spelling;
  scorer activates when phase4_notation emits `key`/`spelling` fields.
- Voice fragmentation is captured by the scorer but not yet in the
  scorecard summary.
