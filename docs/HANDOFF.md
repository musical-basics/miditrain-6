# HANDOFF — start here

For the next session (AI or human). One page of orientation, then
pointers. Read this + `docs/pipeline_reference.md` and you can work on
any phase without excavating the code or the git log.

Last updated: 2026-07-08.

## What this project is

MidiTrain turns raw MIDI into sheet music through five phases
(P1 harmonic regimes → P2 voice threading → P3 meter engines →
P4 meter evidence bus → P5 quantize + notation), with every tunable
decision scored against ground truth and every change gated against a
committed baseline. The full phase logic, contracts, and file map:
**docs/pipeline_reference.md**. The eval discipline:
**docs/benchmarking.md**. Chronology and why each decision was made:
**docs/session-log.md** (newest first).

## Current state (the numbers that matter)

Validation split, downbeat errors = FP+FN at ±50ms, from
`benchmarks/baseline.json` (the committed source of truth):

| engine | total | chorale | essen | piano/mixed |
|---|---|---|---|---|
| **Phase 4 bus** (production choice) | **863** | 222 | 382 | 259 |
| Phase 3 thermo | 1147 | 364 | 200 | 583 |
| Phase 3 spike (legacy) | 1694 | 587 | 596 | 511 |

Phase 1: F1 88.0 (27 errors) on the held-out Pathétique markers —
unchanged through every adoption, by construction. Phase 2 voices:
90.57% mean vs SATB (greedy; beam measures worse at 87.1%). Phase 5:
runs end-to-end, **unscored** (its ground truth is already captured —
see next moves).

The bus became the best engine on 2026-07-08 via two gated adoptions:
channel-mass normalization (1371→945; piano tier −59%) and the weight
retune it unlocked (945→863; bass_cadence halved fixed the chorale
one-beat-early lock). Full history with rejected/inert experiments:
docs/benchmarking.md "Grid searches so far" + "Rejected candidates".

## The one rule

**Tune locally, accept globally, never skip the gate.**

```bash
python3 run_benchmark.py                  # gate any change (≈13 min)
python3 run_benchmark.py --save-baseline  # only after PASS, same commit
```

PASS(0) / REGRESSION(1) / TRADEOFF(2). The pipeline is deterministic —
any delta is real. Grid searches run on the train split only
(`grid_search_thermo.py`, `grid_search_bus.py` with `--structural`,
`--soft`, `--dense` modes, `optimize_params.py` for P1); the gate scores
the val split + held-out Pathétique. Committed baselines in git ARE the
memory of every improvement — a change that regresses one silently
cannot land.

## How to run things

- **Whole pipeline + UI**: `./run.sh` → visualizer on :3000, "Run
  Engine" drives all 7 steps; dropdowns select P2 model, grid source
  (spike/thermo/bus), key algorithm, relaxation.
- **Score your own piece**: `python3 eval_pair.py --midi x.mid --xml
  x.musicxml` — the XML is ground truth (120 BPM convention: beat =
  500ms), all engines + voices scored, alignment sanity-checked first.
- **Corpus eval**: `python3 run_corpus_eval.py` (all engines, all
  pieces, runs.csv).
- **See WHY a meter is wrong**: `python3 run_meter_diag.py --split-key val`
  then `http://localhost:3000/meter?run=val` — per piece: notes with GT vs
  every engine's barlines on one timeline, the GT/predicted measure ratio
  that classifies the failure, and the bus's period-score curve with its
  prior envelope. Diagnosis written up in docs/meter_hierarchy_spec.md.
- **Corpus building**: needs `corpus files/venv/` (gitignored):
  `python3 -m venv "corpus files/venv" && "corpus files/venv/bin/pip"
  install music21 mido`. Then `make_ground_truth.py build --preset ...
  --files ...`; after adding pieces re-run `make_corpus_split.py` and
  review the split diff.

## Gotchas that have already bitten once

1. **Inline-vs-production drift**: grid-search scripts replicate the bus
   via `bus_predict()`; the production CLI rounds barlines to int and
   applies weights slightly differently. Expect a few errors of drift
   between sweep numbers and gate numbers (872 vs 945 was a weight
   mismatch; 1368 vs 1371 was rounding). The GATE number is the truth.
2. **Harness must inherit production flags**: the first post-norm weight
   sweep silently ran without normalization because `run_config` keyed
   off the sweep config instead of `weights["channel_norm"]`. Fixed —
   but any new production flag needs the same care.
3. **Engine totals aren't head-to-head comparable**: thermo skips
   pieces it can't process (counts `failed`, not errors); spike/bus
   always predict. Compare engines per-piece on the shared subset.
4. **Never tune velocity weights on the corpus** (flat velocity 80) and
   **never tune anything on the Pathétique chunk** (held out forever).
5. **`dreamflow` is a local file: dependency** (`visualizer/
   package.json` → `../../../UltimatePianist Repos/dreamflow`). Fresh
   clones fail `pnpm install` without that repo in place.
6. **After every code change**: `npx tsc --noEmit` + `pnpm build` in
   visualizer/ if you touched it; commit + push every completed change
   (repo rule); update docs/session-log.md at session end.
7. Corpus outputs land in gitignored `corpus_runs/`; don't regenerate
   `visualizer/public/etme_*` datasets that carry uncommitted work.

## Next moves, ranked (full detail: pipeline_reference "Open problems")

1. **Densify the harmonic channel with REAL labels** — the cheap
   versions are measured out (2026-07-08 `--dense` sweep: salience inert
   at every weight, Δη+ hurts). What's left is per-beat harmonic QUALITY
   votes, which needs DCML-style annotations (see 3). The extraction
   plumbing in `phase4_make_votes.py` is ready for richer sources.
2. **Metrical hierarchy selection redesign** — THE top item, spec'd in
   docs/meter_hierarchy_spec.md and visible at `/meter`. 59% of all val
   error (507/863) is the bus committing to the wrong LEVEL (bar vs beat
   vs hypermeasure), including a 106-error piano-tier piece; 242 of those
   errors are pieces whose true beat (2000ms) is outside the hardcoded
   240–1600ms search range — unreachable by construction. Four
   weight/prior sweeps are exhausted; this needs an architect redesign,
   not another parameter. Time-signature CHANGES are explicitly out of
   scope (only 1 corpus piece has one — unmeasurable until constant-meter
   is fixed).
3. **External data**: ASAP (performance MIDI + downbeats — real
   velocities, real rubato) and DCML corpora (beat-level harmony labels
   → corpus-scale Phase 1 supervision + dense harmonic ground truth).
4. **Phase 5 scoring** — cheapest activation in the repo: emit `key` +
   per-note `spelling` from phase5_notation.py and the scorer's
   key/spelling sections wake up automatically; add duration accuracy.
   Then regime-aware spelling and per-measure subdivision.
5. **Phase 2 weight search** — neither threader has ever been optimized;
   chorale SATB is the objective (greedy 92.3 vs beam 87.1).
6. **Retire spike** — measured-worst in every tier; keep as a vote
   channel only. Do this after (1) settles so the bus is unambiguous.

## Repo map (one line each; full table in pipeline_reference)

Pipeline: `export_etme_data.py` (P1+P2) → `phase3_thermo_meter.py` /
`phase3_spike_meter.py` → `phase4_make_votes.py` + `phase4_meter_bus.py`
→ `phase5_quantize.py` → `phase5_notation.py`.
Eval: `run_corpus_eval.py`, `run_benchmark.py`, `eval_pair.py`,
`grid_search_*.py`, `make_corpus_split.py`, `optimize_params.py`,
`corpus files/` (factory, scorer, corpora), `benchmarks/` (baseline +
split — committed).
UI: `visualizer/` (Next.js; `app/components/ETMEVisualizer.js` is the
driver; per-phase renderers; VexFlow via local `dreamflow`).
