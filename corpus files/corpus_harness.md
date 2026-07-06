# Corpus Harness: The Ground Truth Factory

Two scripts that turn any notated score into labeled test data for the
MidiTrain pipeline, so weights get set by grid search against a corpus
instead of by intuition against one Beethoven sonata.

```
[music21 corpus / MusicXML]                       [your pipeline]
        |                                               |
  make_ground_truth.py                       phase3 / thermo output JSON
        |                                               |
        +--> corpus_out/midis/<id>.mid  ---- feed in ---+
        +--> corpus_out/groundtruth/<id>.gt.json        |
        +--> corpus_out/manifest.csv                    v
                        |                    score_against_truth.py
                        +------- truth ------------->   |
                                                        v
                                     P/R/F1, errors=N, diagnostics, CSV
```

`make_ground_truth.py` needs music21 + mido (`pip install music21 mido`).
`score_against_truth.py` is pure stdlib: drop it anywhere the pipeline runs.

## Honesty rules (enforced by default)

1. **No leaks.** Time signature and key signature MIDI meta events are
   stripped from rendered MIDIs. The engine can never peek at the answer.
   A tempo meta of 120 BPM is kept for DAW portability; your convention
   ignores tempo metadata anyway.
2. **Sounding order.** Repeats are expanded, ties merged into single
   sounding notes, grace notes dropped (and counted in stats).
3. **The 120 BPM convention.** Quarter note = 500ms, TPQ = 480 (integer
   ticks for triplets and quintuplets). All GT times are in the same
   coordinate space as your markers.
4. **Anacrusis encoded, not hidden.** A padded or short first measure is
   not a downbeat. `anacrusis_ms` records the pickup length, and the
   first entry of `downbeats_ms` is the true first downbeat.

## Ground truth schema (per piece)

```json
{
  "id": "bach_bwv66.6",
  "convention": {"tpq": 480, "ms_per_quarter": 500.0},
  "anacrusis_ms": 500,
  "downbeats_ms": [500, 2500, 4500, ...],
  "meter_map":  [{"start_ms": 0, "time_signature": "4/4",
                  "measure_ms": 2000, "beat_ms": 500,
                  "beats_per_measure": 4}],
  "key_map":    [{"start_ms": 0, "sharps": 3}],
  "analyzed_key": {"tonic": "F#", "mode": "minor", "confidence": 0.938},
  "notes": [{"onset_ms": 0, "duration_ms": 250, "pitch": 73,
             "velocity": 80,
             "spelling": {"step": "C", "alter": 1, "octave": 5,
                          "name": "C#5"},
             "gt_voice": 0, "gt_voice_name": "Soprano"}],
  "stats": {"n_notes": 163, "n_downbeats": 9, "graces_dropped": 0,
            "monophonic": false, "n_parts": 4}
}
```

## The tier ladder

| Tier | Command | What it isolates |
|---|---|---|
| Smoke | `build --preset demo` | bwv66.6 (anacrusis), bwv269 (3/4 + pickup), bwv846 (pure arpeggio texture, harmonic rhythm per bar: the freeze theory's home turf), Maple Leaf Rag (2/4, syncopation stress) |
| Meter at scale, no Phase 2 | `build --preset essen --limit 200` | Thousands of monophonic folk songs with meter labels. If meter works here but fails on piano texture, the bug is in the voice/harmony interaction, not the meter engine. Songs with `meters=?` in the manifest are free-meter: filter them out. |
| Voice ground truth | `build --preset chorales --limit 50` | SATB part labels = the Phase 2 ground truth that piano music cannot give you. Also a hierarchy stress test: chorales change harmony every BEAT, so bar-level meter must come from freeze magnitude hierarchy, not raw harmonic change. |
| Anacrusis subset | filter `manifest.csv` on `anacrusis_ms > 0` | Direct test of (period, phase) as a joint free variable. |
| Held out | your Pathetique chunks | Integration only. Never tune on these again. |

## Wiring into miditrain

1. Point the pipeline at the rendered MIDIs (copy or symlink
   `corpus_out/midis/*.mid` into `midis/`, then the existing
   `export_etme_data.py --midi_key <id>` flow works unchanged).
2. Run Phase 3 / thermodynamic meter to produce its output JSON.
3. Score: the prediction format is sniffed, so barlines as
   `[{"time_ms": ...}]` or bare number lists both work, and `meter`,
   `key`, and `notes` blocks are each optional and scored when present.

```bash
python3 score_against_truth.py \
    --truth corpus_out/groundtruth/bach_bwv66.6.gt.json \
    --pred  visualizer/public/phase3_bach_bwv66.6.json \
    --tol 50 --tag "spikes_v1" --csv runs.csv
```

The final stdout line is machine readable and matches the
optimize_params convention (minimize `errors = FP + FN`):

```
RESULT errors=3 fp=1 fn=2 f1=0.8571 ts=strict key=1.0 voices=0.9120
```

Grid search loop = the existing optimize_params pattern: for each config,
run pipeline on every manifest row, sum `errors`, rank. The `--csv` flag
accumulates rows per (tag, piece) for exactly this.

## Reading the diagnostics

The downbeat block explains WHY a run failed, not just that it failed:

- `period_ratio_snapped: 2.0` means the engine found half-measures
  (or `0.5`, double measures): right clock, wrong hierarchy level.
- `period_ratio: 1.0` + `phase_offset_ms: -500` + `anacrusis_ms: 500`
  means the grid is perfect but anchored to the piece start instead of
  the pickup: the `_project_barlines` t_start bug, named by the numbers.
- `mean_abs_snap_err_ms` isolates jitter from structural error.

Verified example (synthetic prediction reproducing the t_start anchor
bug on bwv66.6): F1 = 0 percent, yet `period_ratio 1.0`,
`phase_offset_ms -513`, so one glance says "fix the phase search."

## A/B discipline

Freezes vs raw spikes is now a measured fight: same corpus, two tags,
compare summed errors. Per repo rule 16, keep both engines selectable
until the numbers pick a winner.

## Reserved scorers (ground truth already captured, waiting on pipeline)

- **Spelling**: every GT note carries step/alter/octave. The scorer
  activates the moment pipeline notes emit a `spelling` field. Phase 1's
  interval machinery (b3 vs #2) already contains this answer.
- **Voices**: activates when pipeline notes carry `voice_tag` or
  `voice_id`. Scored under the best label permutation, plus a
  fragmentation count (label switches inside one true voice), which is
  the corpus version of the corrections-per-100-notes metric.
- **Per-segment keys**: `key_map` records notated signature changes for
  future modulation-aware scoring.

## Known limits

- **Velocity is flat.** Scores carry dynamics, not velocities, so
  rendered notes default to velocity 80. Corpus tiers therefore test the
  timing/harmony-driven parts of the thermodynamic model; velocity-as-
  mass behavior still needs real performance MIDI. Do not tune velocity
  weights on corpus data.
- Grace notes are dropped (counted in `stats.graces_dropped`).
- Inner-staff voices (two voices sharing one piano staff) are not yet
  extracted; chorales use one part per voice, which is why they are the
  Phase 2 tier.
- Free-meter Essen songs report no meter (`meters=?` in manifest) and
  should be excluded from meter scoring runs.
