# Spec: Metrical Hierarchy Selection (Phase 4)

**Status**: objectives defined, diagnosis complete, **implementation not
started — deliberately**. This is a design brief for an architect-level
redesign, not a parameter tweak. Written 2026-08-13 against baseline
bus=863 / thermo=1147 / spike=1694.

**See it first**: `python3 run_meter_diag.py --split-key val` then
`http://localhost:3000/meter?run=val`. Every claim below is visible there.

---

## 1. The problem in one sentence

The Phase 4 bus reliably finds *a* periodicity in the music, but
frequently commits to the **wrong level of the metrical hierarchy** —
calling the beat a bar, or a two-bar hypermeasure a bar — and the current
architecture has no mechanism that reasons about level as such.

## 2. Measured failure decomposition (validation split, 43 pieces, ±50ms)

| | pieces | bus errors | share |
|---|---|---|---|
| **Wrong metrical level** (GT_measure_ms / pred_measure_ms ≠ 1) | 14 | **507** | 59% |
| Correct level, phase/jitter only | 29 | 356 | 41% |

Within the folk-song tier (where the bus loses to thermo 382 vs 200) the
concentration is starker: **96% of errors come from wrong level**, and
the 8 pieces at the correct level contribute 17 errors total, five of
them scoring zero.

The wrong-level ratios are not noise — they are near-exact simple
ratios: 6.00, 4.50, 3.00, 2.00, 2.00, 1.50, 1.50, 0.68, 0.67, 0.50,
0.50. The engine is landing on a *real* pulse in the music; it is
choosing the wrong one to call a bar.

### 2a. The hard sub-case: truth is unreachable by construction

3 val pieces have a **true beat of 2000ms**, outside the bus's hardcoded
240–1600ms tactus search range (`phase4_meter_bus.py` CLI defaults, also
hardcoded in `grid_search_bus.bus_predict`). These are archaic notations
(4/1, 3/1) whose bars run 6–8 seconds.

**They account for 242 errors — 63% of the entire folk-song tier and 28%
of all validation error.** No weighting, prior, or scoring change can fix
them; the correct answer is not in the candidate set. The `/meter` page
prints this explicitly when it applies ("truth beat XXXXms is OUTSIDE the
240–1600ms search range — unreachable by construction").

### 2b. The structural sub-case

Even when the tactus is reachable, the measure search only considers
**G ∈ {2, 3, 4}** (`search_measure`). If the truth needs a different
multiple of the chosen beat, no grouping can express it. The page's
"Measure grouping" panel states per piece whether the truth is reachable
from the chosen tactus.

## 3. Why the obvious fixes are the wrong shape

Recorded so they are not re-attempted (all measured, see
docs/benchmarking.md):

- **Widening the search range alone: zero effect.** The 2026-07-07
  structural sweep tried MAX_PERIOD 1600→3200 and it changed *nothing* —
  because the log-Gaussian tactus prior (centre 600ms) crushes candidates
  two octaves out faster than a wider range admits them. Range and prior
  are coupled; moving one without the other is inert.
- **Widening the priors: already done, already banked.** σ 0.55→0.9 and
  1.0→1.4 were adopted (−89 train). Widening further trades the pieces we
  currently get right — this is a local move on a global problem.
- **Channel weights: exhausted.** Three sweeps (18, 24, 16 configs).
  Post-normalization the knob is live but the remaining spread is small.
- **Dense soft-evidence channels: measured out.** Per-keyframe salience
  is inert at every weight; thermo Δη+ hurts.

The pattern across all four: **the objective is being re-weighted, but
the failure is in what the objective ranges over.** A candidate set that
excludes the answer, and a scoring function with no notion of "this
period is the bar, that one is the beat," cannot be fixed by weights.

## 4. Objectives for the redesign

**Primary**: reduce wrong-level errors without losing the 29 pieces
currently at the correct level.

Specific properties the design should have:

1. **The candidate set must contain the truth.** Tactus range and
   grouping set must jointly span at least 250–2500ms beats and bars up
   to ~8000ms. Widening naively will admit garbage — which is why this is
   a redesign and not a constant change.
2. **Level should be an explicit variable, not an emergent one.** The
   current pipeline picks a tactus by one argmax, then a grouping by a
   second, with priors doing the level reasoning implicitly. A design in
   which the metrical *hierarchy* (a small tree of related periods:
   sub-beat, beat, bar, hypermeasure) is proposed and scored as a unit
   would let evidence at one level inform the others — a strong bar
   hypothesis should be able to override a locally-better beat.
3. **Scale-free where possible.** Priors centered on absolute ms are what
   make archaic notation unreachable. Relationships between levels
   (integer ratios, consistent phase) are scale-free and generalize
   across tempo and notation era.
4. **Must not regress the other tiers.** Chorale (222) and piano (259)
   are majority-correct-level; the design must not trade them for folk
   songs. Per-tier reporting is in the benchmark scorecard.
5. **Deterministic.** The gate assumes it; any nondeterminism breaks the
   whole eval discipline.

**Explicit non-objective — time-signature changes.** One grid per piece
stays. User's reasoning, and the data supports it: only 1 corpus piece
has a meter change, so the feature cannot be measured, and its switch
penalty cannot be tuned while the constant-meter error rate is still this
noisy. Fix constant-meter first. (Piecewise DP remains valuable later as
the rubato/live tracker — but that is blocked on ASAP data anyway.)

## 5. Constraints and workflow (non-negotiable)

- Tune on **train** only (`grid_search_bus.py` conventions); the gate
  scores **val** + held-out Pathétique.
- `python3 run_benchmark.py` must PASS: no severity-1 metric may regress
  (bus / thermo / spike downbeats, held-out Phase 1 errors), voices
  unchanged. Adopt + `--save-baseline` in the same commit.
- Keep the old path selectable until numbers decide (repo rule 16); the
  bus already has `channel_norm`-style flags as precedent.
- **Harness gotchas that have bitten before** (docs/HANDOFF.md): sweep
  harnesses must inherit production flags; `bus_predict` in
  `grid_search_bus.py` duplicates the CLI's search and must be updated in
  lockstep (it also hardcodes 240–1600); the gate number is the truth
  when it disagrees with an inline sweep number.

## 6. Where to look

| what | where |
|---|---|
| See the failure | `/meter?run=val` (produce with `run_meter_diag.py`) |
| Tactus + measure search | `phase4_meter_bus.py:search_tactus`, `search_measure`, `derive_ts` |
| Sweep harness (mirrors the above) | `grid_search_bus.py:bus_predict`, `run_config` |
| Per-piece truth | `corpus files/corpus_full/groundtruth/<id>.gt.json` → `meter_map[0]` |
| Current standings + history | `benchmarks/baseline.json`, `docs/benchmarking.md` |
| Phase 4 theory / channel map | `docs/phase4_signal_scaffold.md` |

## 7. Reference: the 14 wrong-level val pieces

Ratio = GT measure_ms / predicted measure_ms. Ratio > 1 means the engine
chose a *shorter* bar than truth (picked a beat); < 1 means longer
(picked a hypermeasure).

| piece | tier | GT ts | GT measure | pred | ratio | errors |
|---|---|---|---|---|---|---|
| essen op003 | essen | 4/1 | 8000 | 1333 | 6.00 | 149 |
| essen op023 | essen | 3/1 | 6000 | 1333 | 4.50 | 66 |
| essen op013 | essen | 3/1 | 6000 | 2000 | 3.00 | 27 |
| essen op039 | essen | 3/2 | 3000 | 2000 | 1.50 | 24 |
| essen op005 | essen | 3/4 | 1500 | 2996 | 0.50 | 21 |
| essen op015 | essen | 4/2 | 4000 | 2000 | 2.00 | 18 |
| essen op017 | essen | 4/2 | 4000 | 2000 | 2.00 | 18 |
| essen op037 | essen | 6/4 | 3000 | 1998 | 1.50 | 14 |
| essen op009 | essen | 6/8 | 1500 | 2197 | 0.68 | 13 |
| essen op035 | essen | 4/4 | 2000 | 2993 | 0.67 | 10 |
| essen op021 | essen | 6/8 | 1500 | 2990 | 0.50 | 5 |
| **schumann polonaise op1n1** | **piano** | 3/4 | 1500 | 2990 | **0.50** | **106** |
| chorale_021 | chorale | 4/4 | 2000 | 2996 | 0.67 | 19 |
| chorale_025 | chorale | 4/4 | 2000 | 2996 | 0.67 | 17 |

The three 2000ms-beat pieces (op003, op023, op013) are the unreachable
sub-case from §2a and alone are 242 of the 507 wrong-level errors.

**This is not a folk-song problem.** The single largest non-essen failure
is a Clara Schumann polonaise — 106 errors, the engine choosing a
two-bar hypermeasure (ratio 0.50) in the target repertoire. The two
chorales fail the same way at 0.67. Fixing hierarchy selection pays out
in the piano tier too, which is why this ranks above the remaining
phase/jitter work.
