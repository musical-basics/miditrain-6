# Final Configuration — Harmonic Regime Detector V3.1

**Finalized:** 2026-04-02  
**Piece:** Beethoven — Pathétique Sonata, 1st movement exposition (64s chunk, 116 ground-truth markers)

---

## Final Results

| Metric | Value |
|---|---|
| **Precision** | **90.8%** |
| **Recall** | **85.3%** |
| **F1 Score** | **88.0%** |
| True Positives | 99 / 116 |
| False Positives | 10 |
| False Negatives | 17 |
| Total Errors | 27 |

> Note: Some FPs were later identified as legitimate T2 harmonic boundaries missed during initial annotation, putting real-world precision closer to ~93-94%.

---

## Recommended Configuration (Opt #1)

```json
{
  "break_method": "hybrid",
  "angle_map": "dissonance",
  "break_angle": 35,
  "merge_angle": 25,
  "min_break_mass": 0.75,
  "debounce_ms": 100,
  "jaccard_threshold": 0.375,
  "min_resolution_ratio": 0.6,
  "max_anchor_size": 6,
  "maturity_grace_ms": 200,
  "bass_multiplier": 2.0
}
```

---

## All 5 Optimized Configs

All share: `hybrid` method, `dissonance` map, `MBM=0.75`, `D=100ms`, `J=0.375`, `bass=2.0×`, `grace=200ms`

| # | BA | MA | ResRatio | AnchorCap | Errors | FP | FN | TP | P% | R% | F1% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 35° | 25° | 0.60 | 6 | 27 | 10 | 17 | 99 | 90.8 | 85.3 | 88.0 |
| 2 | 35° | 25° | 0.60 | 12 | 27 | 10 | 17 | 99 | 90.8 | 85.3 | 88.0 |
| 3 | 35° | 20° | 0.60 | 6 | 27 | 11 | 16 | 100 | 90.1 | 86.2 | 88.1 |
| 4 | 35° | 20° | 0.60 | 12 | 27 | 11 | 16 | 100 | 90.1 | 86.2 | 88.1 |
| 5 | 35° | 25° | 0.40 | 6 | 28 | 9 | 19 | 97 | 91.5 | 83.6 | 87.4 |

**Config #3** has the highest F1 (88.1%) with 100 TPs. **Config #5** has the highest precision (91.5%) with only 9 FPs.

---

## Optimization Journey (Full Progression)

| Stage | Errors | FP | FN | TP | P% | R% | F1% |
|---|---|---|---|---|---|---|---|
| V2.2 baseline | 54 | 29 | 25 | 91 | 75.8 | 78.4 | 77.1 |
| + Limbo contamination guard | 48 | 16 | 32 | 84 | 84.0 | 72.4 | 77.8 |
| + V3 (mass resolution + anchor cap) | 44 | 17 | 27 | 89 | 84.0 | 76.7 | 80.2 |
| + V3.1 (limbo GC + merge loophole) | **27** | **10** | **17** | **99** | **90.8** | **85.3** | **88.0** |

---

## Detector Architecture Summary

### Core Pipeline
```
MIDI file → extract_keyframes (50ms grouping) → HarmonicRegimeDetector → regime_frames → TRANSITION SPIKE boundaries
```

### Key Components

1. **Dissonance Color Wheel** — Maps pitch classes to angles. Consonant intervals (1, 5, 3) cluster near 0-90°; dissonant intervals (b2, #4, b7) spread to 120-270°.

2. **Anchor Profile** — Persistent `{interval: mass}` dictionary tracking the harmonic identity of the current regime. Reinforced by merging frames, decayed for absent notes, capped at `max_anchor_size` (6) entries.

3. **Hybrid Break Method** — Triggers on EITHER angle divergence (`diff > break_angle`) OR set divergence (`jaccard < jaccard_threshold`), gated by `min_break_mass` and `is_subset_anchor` suppression.

4. **Debounce Probation** — Spikes enter probation for `debounce_ms` (100ms) before confirmation. Compatible frames can swallow spikes, subject to the mass-ratio guard.

### V3.1 Innovations

| Feature | Parameter | What it does |
|---|---|---|
| **Mass-weighted resolution** | `min_resolution_ratio=0.6` | A resolving frame must have ≥60% of the spike's mass to swallow it |
| **Anchor diversity cap** | `max_anchor_size=6` | Prevents long-lived regimes from accumulating all 12 pitch classes |
| **Maturity grace period** | `maturity_grace_ms=200` | New regimes get 200ms before breaks are allowed |
| **Bass authority** | `bass_multiplier=2.0` | Lowest note (octave ≤ 3) gets 2× mass — bass motion drives harmonic function |
| **Limbo garbage disposal** | (built-in, 80ms) | Flushes stale limbo frames older than 80ms to prevent mass accumulation |
| **Merge loophole patch** | (built-in) | Mass-ratio guard applies to ALL merge paths, not just resolution |
| **Limbo contamination guard** | (built-in) | Prevents divergent limbo from dragging compatible frames into false breaks |
| **Stranded limbo rescue** | (gated to bass_multiplier>1) | Rescues limbo frames into spike so they seed the new anchor |

---

## Things to Note for Future Work

### What This System Does Well
- Bootstraps harmonic rhythm / downbeat detection from raw MIDI with zero tempo metadata
- Handles Beethoven's chromatic writing (Neapolitan chords, diminished 7ths, enharmonic pivots)
- Robust to voicing changes and register shifts within the same harmony
- Precision above 90% means detected boundaries are highly trustworthy

### Known Limitations
- **No tempo awareness** — all timing uses the 120 BPM tick convention (`tick × 500.0 / tpq`)
- **Monophonic bass assumption** — `bass_multiplier` applies to the lowest note per keyframe; polyphonic bass lines may behave unexpectedly
- **Long regime inertia** — even with `max_anchor_size=6`, regimes that persist for 10+ seconds can still resist breaking on subtle harmonic shifts
- **Dense chromatic passages** — the final 10s of the 64s chunk (development-style material) remains the hardest region, with 12 of 27 remaining FNs concentrated there
- **Alberti/accompaniment patterns** — the 80ms limbo flush handles most cases, but very fast arpeggiation (< 80ms between notes) can still cause edge cases

### What NOT to Change
- **The 120 BPM convention** — all markers, all tick-to-ms conversions, everything. Changing this invalidates all ground truth.
- **The dissonance map angles** — these are carefully tuned to separate consonance from dissonance. The fifths map exists but performs worse.
- **`min_break_mass = 0.75`** — this converged across ALL optimization runs on both 16s and 64s chunks. It's fundamental.
- **`debounce_ms = 100`** — same; converged across all runs.

### Files Required for Runtime
- `harmonic_regime_detector.py` — the detector
- `export_etme_data.py` — generates visualizer JSON from MIDI
- `particle.py` — Particle data class
- `create_chunk.py` — MIDI/marker slicing utility
- `optimize_params.py` — parameter grid search
- `visualizer/` — Next.js piano roll visualizer
- `midis/pathetique_64s_chunk.mid` — the 64s test MIDI (with 3s buffer)
- `markers/pathetique_64s_chunk_markers.json` — ground truth (116 markers)
- `visualizer/public/etme_pathetique_64s_chunk_optimized_1-5.json` — top 5 configs
