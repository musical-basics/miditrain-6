# Phase 3A Macro-Meter — Session Summary
*2026-03-28*

## What We Tackled

The goal: get barlines projecting correctly across all 3 chunks of the Pathétique 2nd movement.

---

## ✅ What Worked

### 1. Piece-Start Anchor Fix
**Problem:** Chunk 1 was anchoring m1 at 500ms instead of 0ms.  
**Root cause:** `spike_times[0] > piece_start + tactus_ms` was `500 > 500` → False. So 0ms was never inserted.  
**Fix:** Changed to `if piece_start not in spike_times: insert(0, piece_start)` — unconditional anchor at piece start.  
**Result:** Chunk 1 m1=0ms ✅

---

### 2. Min-Gap Guard Against Beat-Level Spikes
**Problem:** Spikes at the beat level (every 500ms) were getting snapped as barlines.  
**Fix:** Added `min_barline_gap = measure_ms * 0.5` — two barlines can't be closer than half a measure. Also tightened snap window from 50% → 40% of tactus.  
**Result:** Prevented beat-level spikes from masquerading as barlines.

---

### 3. Two-Pass Barline Repair (Bass-Coincidence Veto)
**Problem:** Chunk 2 m3 was at 1875ms (mid-measure harmonic spike) instead of 2000ms.  
**Analysis:** The spike at 1875ms had no bass note nearby. Bass at 2000ms is closer to the *projected* barline than to the spike.  
**Fix:** Pass 2 via `_check_and_repair_barlines()`:
- After Pass 1, checks if any inter-barline interval falls outside `[measure_ms × 0.90, measure_ms × 1.10]`
- If a suspect snapped barline has no bass note *strictly closer to the spike than to the projected position*, the snap is revoked and dead-reckoning used instead
- Cascades corrections downstream

**Key insight:** The bass-proximity tie-breaker distinguishes rubato (bassist plays slightly early → bass close to spike) from wrong-spike (bassist plays at the correct position → bass closer to projection).  
**Result:** Chunk 2 m3=2000ms ✅, m6 corrected ✅

---

### 4. Subdivision Search Extended to 6× (Triplet Fix)
**Problem:** Chunk 3 tactus computed as 330ms instead of 500ms. The Pathétique left-hand arpeggios play 6 notes per beat at ~80ms each. Our search only checked `[2×, 3×, 4×]` multiples.  
**Fix:** Added `6` to `candidate_ratios = [2, 3, 4, 6]`. Count-based tie-breaking already picks the highest-count match (6×: count=3 wins over 4×: count=2).  
**Result:** Tactus = 500ms (120 BPM) ✅ — no hardcoded tempo.

---

### 5. Autocorrelation Measure Estimator (No Hardcoded Fallback)
**Problem:** `_estimate_measure_length` used spike IOI clustering with a `min_measure = 2×tactus` floor — a hardcoded 2/4 assumption. With only 2 valid spike IOIs for Chunk 3, it picked 1500ms (3/4) over 1000ms (2/4).  
**Fix:** Full replacement with autocorrelation-based `_estimate_measure_length(spike_times, tactus_ms, max_time)`:
1. Build 50ms-binned spike density array
2. Autocorrelate from `tactus_ms` up to `max_time/2`
3. Find the **smallest lag with a peak score ≥ 50% of the global max** → the measure period

No hardcoded multiple. The period emerges from data self-similarity.  
**Result:** Chunk 3 measure = 1000ms ✅, 11/15 barlines snapping at 0ms drift ✅  
**Also exports:** `spike_density` and `autocorr` arrays in the grid JSON for visualization.

---

### 6. Spike Density + ACF Curve in Visualizer
Two new visual layers in Phase 3A:
- **Amber bar strip** at the bottom of the piano roll: raw spike density at 50ms resolution
- **Orange ACF curve** in the ruler: autocorrelation score vs. lag period
- **Gold dot** marking the detected peak with ms label
- **Legend panel** showing ACF peak formula: `◎ ACF peak: 1000ms = 2 beats × 500ms`

---

## ❌ What Didn't Work (Attempts Before Final Fix)

| Attempt | Why it failed |
|---------|--------------|
| Tight snap_window (40%) without min-gap guard | Chunk 1 m5 rubato got killed too |
| `CONSISTENCY_TOLERANCE = 0.12` | Over-triggered Pass 2 on valid spikes in Chunk 3 |
| `CONSISTENCY_TOLERANCE = 0.15` with 875ms interval | 12.5% deviation < 15% threshold → m3 correction missed |
| Bass-coincidence without closer-to-spike check | Bass at 2000ms equidistant from 1875ms and 2000ms → passed veto incorrectly |
| IOI cluster picking 1500ms for Chunk 3 | Only 2 data points at valid IOI level; first one wins by tiebreak |
| 3/4 time signature with 6× fix alone (without autocorr) | 1500ms IOI still dominated with count=1 over 2000ms count=1 |

---

## 📊 Final State: All Three Chunks

| Chunk | Measures | Barlines snapped | Notes |
|-------|----------|-----------------|-------|
| Chunk 1 (Mm. 1-4) | 0, 1000, 2000, 3000, 4000ms | 4/6 | m5 Pass-2 corrected |
| Chunk 2 (Mm. 5-8) | 0, 1000, 2000, 3000, 4000ms | 4/7 | m3 + m6 Pass-2 corrected |
| Chunk 3 (Mm. 9-12) | 0, 1000, …, 12000ms | 11/15 | 0ms drift for most barlines |

All: **2/4 time, 120 BPM, tactus = 500ms** ✅

---

## 🔲 What to Tackle Next (Priority Order)

1. **Step 3B — Micro-Quantizer**: Map each note onset to the nearest beat subdivision → `(measure, beat, subdivision)` tuples
2. **API Route for on-demand grid generation**: Chunk selector triggers a server-side run of `phase3_meter.py`
3. **Step 3C — Grammar Engine**: Convert quantized positions into valid MusicXML durations, ties, rests
4. **Step 3D — MusicXML Export**: Terminal goal of Phase 3
5. **Multi-chunk alignment**: Ensure measure numbering is continuous (chunk 2 starts at m5, not m1)
6. **Rubato tolerance mode** (future): preserve spike snaps for performance analysis rather than notation grid
