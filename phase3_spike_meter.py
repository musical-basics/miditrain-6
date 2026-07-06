"""
Phase 3 (legacy spike model): Macro-Meter Estimator
================================================================================
Infers Tempo, Time Signature, and Barlines from Phase 1 Spikes and Phase 2 Voice 4.

(Ported from miditrain-4's phase3_meter.py, where it was "Phase 3A". Under the
renumbering in `plan for improvements.md` the thermodynamic meter
(phase3_thermo_meter.py) is the canonical Phase 3; this spike-anchored model is
kept because its grid output — with `subdivision` — is what Phase 4
(quantize + notation) currently consumes, same wiring as miditrain-4.)

Key Design Principles:
- Hierarchical IOI Clustering: detects sub-tactus (16ths) vs. tactus (beats) by
  finding integer-ratio IOI clusters, not just a single mode.
- Spike-Anchored Rubber-Band Grid: barlines elastically snap to real TRANSITION
  SPIKE frames when nearby, then dead-reckon forward otherwise.
- Musical Norm Clamping: ratio is snapped to {2, 3, 4, 6, 8, 12}.

Usage:
    python phase3_spike_meter.py path/to/etme_*.json      # explicit file
    python phase3_spike_meter.py --json                   # write phase3_grid_*.json

Output: visualizer/public/phase3_grid_{base_key}.json
"""

import json
import sys
import math
import glob
from collections import Counter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MUSICAL_NORM_DIVISORS = [2, 3, 4, 6, 8, 12]


def _bin_iois(iois, bin_size):
    """Bucket a list of IOIs into rounded multiples of bin_size."""
    return [round(x / bin_size) * bin_size for x in iois]


def _extract_clusters(times, bin_size=25, min_val=50, max_val=4000):
    """
    Returns a sorted list of (interval_ms, count) pairs from inter-onset intervals.
    Filters to [min_val, max_val] before binning.
    """
    if len(times) < 2:
        return []
    iois = [times[i] - times[i - 1] for i in range(1, len(times))]
    valid = [x for x in iois if min_val <= x <= max_val]
    if not valid:
        return []
    binned = _bin_iois(valid, bin_size)
    counter = Counter(binned)
    # Return sorted by count descending
    return sorted(counter.items(), key=lambda kv: -kv[1])


def _nearest_norm(ratio, norms=MUSICAL_NORM_DIVISORS):
    """Snap a floating ratio to the nearest musical integer norm."""
    if ratio < 1.5:
        return 2
    return min(norms, key=lambda n: abs(n - ratio))


def _meter_type(beats_per_measure):
    """Label the meter for human readability."""
    if beats_per_measure in (2,):
        return "simple_duple"
    if beats_per_measure in (3,):
        return "simple_triple"
    if beats_per_measure in (4,):
        return "simple_quadruple"
    if beats_per_measure in (6,):
        return "compound_duple"
    if beats_per_measure in (9,):
        return "compound_triple"
    if beats_per_measure in (12,):
        return "compound_quadruple"
    return "complex"


# ---------------------------------------------------------------------------
# MacroMeterEstimator
# ---------------------------------------------------------------------------

class MacroMeterEstimator:
    """
    Phase 3A: Macro-Meter Bootstrapper.

    Infers Tempo, Time Signature, and Barlines using:
      - Phase 1  → TRANSITION SPIKE start_times (harmonic rhythm anchor)
      - Phase 2  → Voice 4 (Bass) note onsets    (Tactus / sub-tactus)
    """

    def __init__(self, json_path):
        with open(json_path, "r") as f:
            self.data = json.load(f)
        self.json_path = json_path
        self.notes = self.data["notes"]
        self.regimes = self.data["regimes"]

    # ------------------------------------------------------------------
    # Step 1: Tactus Estimation (Hierarchical IOI Clustering)
    # ------------------------------------------------------------------

    def _estimate_tactus(self, bass_onsets):
        """
        Find the fundamental beat from Voice 4 IOIs.

        Strategy:
          1. Extract all Bass IOI clusters.
          2. The SMALLEST common cluster is the sub-tactus (e.g., 84ms = 16th note).
          3. Look for a cluster at 2x, 3x, or 4x the sub-tactus — that is the tactus (beat).
          4. If no integer multiple cluster exists, the sub-tactus IS the tactus.

        Returns (sub_tactus_ms, tactus_ms, subdivision).
        """
        # Tight binning — use 10ms bins to accurately resolve sub-tactus
        # e.g. 82ms bins to 80ms, 332ms bins to 330ms
        clusters = _extract_clusters(bass_onsets, bin_size=10, min_val=50, max_val=2000)
        if not clusters:
            return None, None, 1

        # Sub-tactus = most common short interval (the tightest pulse)
        sub_tactus_ms = clusters[0][0]

        # Search for the STRONGEST cluster at an integer multiple of sub_tactus.
        # We evaluate all ratios and pick the one with the highest count.
        # Include 6 to cover triplet-16th → quarter-note subdivisions
        # (e.g. Pathétique arpeggios: 6 × 80ms = 480ms ≈ 500ms quarter note)
        candidate_ratios = [2, 3, 4, 6]
        best_tactus = sub_tactus_ms
        best_subdivision = 1
        best_count = 0

        for ratio in candidate_ratios:
            target = sub_tactus_ms * ratio
            tolerance = sub_tactus_ms * 0.35  # ±35% of sub-tactus
            for interval_ms, count in clusters:
                if abs(interval_ms - target) <= tolerance:
                    if count > best_count:  # count is authoritative — higher count wins
                        best_count = count
                        best_tactus = interval_ms  # use actual cluster center
                        best_subdivision = ratio
                    break


        return sub_tactus_ms, best_tactus, best_subdivision

    def _estimate_measure_length(self, spike_times, tactus_ms, max_time):
        """
        Autocorrelation of the COHERENT MACRO-DENSITY envelope to find the dominant
        macro-period (measure length) above the tactus level.

        Phase 3 Coherent Merge:
        Merges Phase 1 (Harmonic Spikes) with Phase 2 (Thermodynamic Voice Threading).
        A Phase 1 spike's structural weight is amplified by the mass of Phase 2 notes 
        (especially Voice 4 Bass and Voice 1 Melody) that strike simultaneously.
        This powerfully filters out passing harmonic chords and amplifies true downbeats.
        """
        BIN_MS = 50
        n_bins = max(2, int(max_time / BIN_MS) + 2)

        # Build coherent density array
        density = [0.0] * n_bins
        for t in spike_times:
            idx = int(t / BIN_MS)
            if 0 <= idx < n_bins:
                weight = 1.0  # Base weight for a harmonic spike
                
                # Phase 2 Merge: Find coincident structural notes
                for n in self.notes:
                    if abs(n["onset"] - t) <= 50:
                        # Calculate mass: velocity (0.0-1.0) * duration factor
                        dur_factor = max(0.5, min(n["duration"] / 1000.0, 2.0))
                        mass = (n["velocity"] / 127.0) * dur_factor
                        
                        if n["voice_tag"] == "Voice 4":
                            weight += mass * 3.0  # Bass is the strongest measure anchor
                        elif n["voice_tag"] == "Voice 1":
                            weight += mass * 1.5  # Melody provides secondary structural weight
                        else:
                            weight += mass * 0.5  # Inner voices contribute lightly

                # The Coherent Merge Fix: Square the accumulated structural weight
                # to mathematically crush bins lacking heavy bass or melody anchors.
                density[idx] += weight ** 2

        # Autocorrelate: lags from tactus_ms up to half the total duration
        min_lag_bins = max(1, int(tactus_ms / BIN_MS))
        max_lag_bins = min(n_bins // 2, int(8000 / BIN_MS))
        n = len(density)

        autocorr = []
        for lag in range(min_lag_bins, max_lag_bins + 1):
            pairs = n - lag
            if pairs <= 0:
                break
            raw = sum(density[i] * density[i + lag] for i in range(pairs))
            score = raw / pairs  # normalize by number of overlapping pairs
            autocorr.append((lag * BIN_MS, score))

        if not autocorr:
            return tactus_ms, [{"t_ms": i * BIN_MS, "count": round(density[i], 2)} for i in range(n_bins) if density[i] > 0], []

        # Find the dominant period: highest score above tactus.
        scores = [s for _, s in autocorr]
        max_score = max(scores) if scores else 0
        NOISE_FLOOR = max_score * 0.25  # peaks must exceed 25% of global max

        # Find all local maxima above noise floor
        peaks = []
        for i in range(1, len(scores) - 1):
            if scores[i] > scores[i - 1] and scores[i] > scores[i + 1] and scores[i] > NOISE_FLOOR:
                peaks.append((autocorr[i][0], scores[i]))

        if not peaks:
            best_lag_ms = max(autocorr, key=lambda x: x[1])[0]
        else:
            # Pick the SMALLEST lag peak that has >= 75% of the global maximum
            # (Previously 50%, which incorrectly allowed the 250ms 70% passing-chord noise to leak through)
            significant = [(lag, s) for lag, s in peaks if s >= max_score * 0.75]
            if significant:
                best_lag_ms = min(significant, key=lambda x: x[0])[0]
            else:
                best_lag_ms = min(peaks, key=lambda x: x[0])[0]

        # Normalize autocorr to 0-1 for JSON export
        autocorr_norm = [
            {"lag_ms": lag, "score": round(s / max_score, 4) if max_score > 0 else 0}
            for lag, s in autocorr
        ]

        # Compact density export: round floats to 2 decimal places for the JSON payload
        density_export = [
            {"t_ms": i * BIN_MS, "count": round(density[i], 2)}
            for i in range(n_bins) if density[i] > 0
        ]

        return best_lag_ms, density_export, autocorr_norm


    def _derive_time_signature(self, sub_tactus_ms, tactus_ms, subdivision, measure_ms):
        """
        Divide measure_ms / tactus_ms and snap to the nearest musical norm.

        If a subdivision >1 was detected (e.g., 4x → quarter from 16ths),
        the promoted tactus IS the quarter note, so denominator = 4.
        If subdivision == 1 (no promotion), fall back to BPM heuristic.

        Returns (beats_per_measure, denominator).
        """
        raw_ratio = measure_ms / tactus_ms
        beats = _nearest_norm(raw_ratio)

        if subdivision > 1:
            # The tactus was promoted from a sub-division.
            # sub_tactus → 16th/8th, tactus → quarter/half
            if subdivision == 4:
                # 16ths promoted to quarters
                denominator = 4
            elif subdivision == 3:
                # Triplet sub-division promoted
                denominator = 4  # compound feel, still quarter reference
            elif subdivision == 2:
                # 8ths promoted to quarters
                denominator = 4
            else:
                denominator = 4
        else:
            # No subdivision detected — use BPM heuristic
            bpm = 60000 / tactus_ms
            if bpm > 200:
                denominator = 16
            elif bpm > 140:
                denominator = 8
            elif bpm > 60:
                denominator = 4
            else:
                denominator = 2

        return beats, denominator

    # ------------------------------------------------------------------
    # Step 4: Project Rubber-Band Barlines
    # ------------------------------------------------------------------

    def _project_barlines(self, spike_times, measure_ms, tactus_ms, max_time):
        """
        Projects barlines elastically:
        - Start from piece start (spike_times[0], always 0ms or first regime).
        - Advance by measure_ms each step.
        - If a real spike falls within ±tactus_ms*0.4, snap to it (rubato-corrected).
        - Enforces a minimum gap of measure_ms*0.5 between consecutive barlines
          to prevent beat-level spikes from being misidentified as barlines.
        - Otherwise, dead-reckon forward.

        Returns list of dicts: {measure, time_ms, snapped, drift_ms, source}
        """
        snap_window = int(tactus_ms * 0.4) if tactus_ms else 200
        min_barline_gap = int(measure_ms * 0.5)  # minimum gap between two barlines
        start_time = spike_times[0] if spike_times else 0
        barlines = []
        current_time = start_time
        last_barline_time = -9999
        measure = 1

        while current_time <= max_time + measure_ms:
            # Look for a nearby real spike, but only if we're far enough from the last barline
            nearby = [
                s for s in spike_times
                if abs(s - current_time) <= snap_window
                and s - last_barline_time >= min_barline_gap
            ]
            if nearby:
                actual = min(nearby, key=lambda s: abs(s - current_time))
                drift = actual - current_time
                barlines.append({
                    "measure": measure,
                    "time_ms": int(actual),
                    "snapped": True,
                    "drift_ms": int(drift),
                    "source": "spike"
                })
                current_time = actual
                last_barline_time = actual
            else:
                barlines.append({
                    "measure": measure,
                    "time_ms": int(current_time),
                    "snapped": False,
                    "drift_ms": 0,
                    "source": "dead_reckoning"
                })
                last_barline_time = current_time

            current_time += measure_ms
            measure += 1

        return barlines
    def _check_and_repair_barlines(self, barlines, measure_ms, bass_times, tactus_ms):
        """
        Pass 2: Consistency repair.

        After Pass 1, check if any inter-barline interval deviates from the
        expected measure_ms by more than CONSISTENCY_TOLERANCE. If so, the
        spike that caused the snap was a mid-measure harmonic event, not a
        true barline. Revoke the snap ONLY IF the snapped spike had no nearby
        bass note (bass-coincidence veto). Replace with a dead-reckoned position.

        Bass-coincidence window: ±tactus_ms * 0.1 (very tight — 50ms for 500ms tactus).
        """
        CONSISTENCY_TOLERANCE = 0.15  # 15% deviation from expected measure_ms triggers check
        # Bass coincidence window: ±30% of tactus. At 500ms tactus → ±150ms.
        # This is intentionally wider than the strict 50ms to account for rubato —
        # the bassist might land slightly before or after the spike.
        BASS_COINCIDENCE_WINDOW = int(tactus_ms * 0.3) if bass_times else 150

        repaired = list(barlines)  # work on a copy
        changed = False

        for i in range(1, len(repaired)):
            interval = repaired[i]["time_ms"] - repaired[i - 1]["time_ms"]
            projected_time = repaired[i - 1]["time_ms"] + measure_ms  # mathematically correct position

            # Flag if interval is too short (early snap) OR too long (late snap)
            too_short = interval < measure_ms * 0.90
            too_long  = interval > measure_ms * 1.10

            suspect = (too_short or too_long) and repaired[i]["snapped"]

            if suspect:
                snapped_time = repaired[i]["time_ms"]

                # A bass note confirms the spike ONLY IF:
                #   1. It's within the coincidence window of the spike, AND
                #   2. It's strictly closer to the spike than to the projected barline.
                #      A bass note equidistant or closer to the projection belongs
                #      to the mathematically correct barline, not this rogue spike.
                bass_nearby = any(
                    abs(b - snapped_time) <= BASS_COINCIDENCE_WINDOW
                    and abs(b - snapped_time) < abs(b - projected_time)
                    for b in bass_times
                )

                if not bass_nearby:
                    repaired[i] = {
                        "measure": repaired[i]["measure"],
                        "time_ms": int(projected_time),
                        "snapped": False,
                        "drift_ms": 0,
                        "source": "corrected_dead_reckoning",
                        "veto_reason": (
                            f"spike@{snapped_time}ms interval={'short' if too_short else 'long'} "
                            f"({interval}ms vs expected {int(measure_ms)}ms); "
                            f"no bass closer to spike than to projected@{int(projected_time)}ms"
                        )
                    }
                    changed = True
                    # Cascade: adjust subsequent dead-reckoned barlines
                    for j in range(i + 1, len(repaired)):
                        if not repaired[j]["snapped"]:
                            repaired[j] = dict(repaired[j])
                            repaired[j]["time_ms"] = repaired[j - 1]["time_ms"] + measure_ms
                        else:
                            break  # next snapped barline is a real anchor, stop cascading

        return repaired, changed




    def estimate(self, write_json=False):
        """
        Full pipeline. Returns a dict with all computed fields and prints a report.
        """
        sep = "=" * 55

        print(f"\n{sep}")
        print(f"  🎵  PHASE 3A: MACRO-METER ESTIMATOR")
        print(f"  📄  {self.json_path.split('/')[-1]}")
        print(f"{sep}")

        # ── All onsets ──────────────────────────────────────────
        all_onsets = sorted([n["onset"] for n in self.notes])

        if len(all_onsets) < 3:
            print("  ⚠️  Not enough notes to establish a pulse.")
            return None

        # Re-build bass_onsets since Pass 2 bass-coincidence veto needs them
        bass_notes = sorted(
            [n for n in self.notes if n["voice_tag"] == "Voice 4"],
            key=lambda n: n["onset"],
        )
        bass_onsets = [n["onset"] for n in bass_notes]

        # Feed all onsets to the tactus estimator so it can detect 16th notes/triplets
        sub_tactus_ms, tactus_ms, subdivision = self._estimate_tactus(all_onsets)
        if not tactus_ms:
            print("  ⚠️  Tactus estimation failed.")
            return None

        # ── Phase 1 Spike times ─────────────────────────────────────────
        spike_times = sorted(
            [r["start_time"] for r in self.regimes if r["state"] == "TRANSITION SPIKE!"]
        )
        # ALWAYS anchor the grid at piece start (0ms or first regime start).
        # The piece always begins on Beat 1, Measure 1, regardless of when the
        # first harmonic spike fires. Spikes mark harmonic events, NOT necessarily barlines.
        piece_start = self.regimes[0]["start_time"] if self.regimes else 0
        if piece_start not in spike_times:
            spike_times.insert(0, piece_start)

        max_time = max(n["onset"] + n["duration"] for n in self.notes) if self.notes else 0

        measure_ms, spike_density, autocorr = self._estimate_measure_length(spike_times, tactus_ms, max_time)
        beats_per_measure, denominator = self._derive_time_signature(sub_tactus_ms, tactus_ms, subdivision, measure_ms)

        bpm_sub = round(60000 / sub_tactus_ms)
        bpm_tactus = round(60000 / tactus_ms)
        meter_label = _meter_type(beats_per_measure)



        barlines = self._project_barlines(spike_times, measure_ms, tactus_ms, max_time)

        # ── Pass 2: Consistency repair (bass-coincidence veto) ────────────
        barlines, pass2_triggered = self._check_and_repair_barlines(barlines, measure_ms, bass_onsets, tactus_ms)

        # ── Report ──────────────────────────────────────────────────────
        print(f"\n  📊  PULSE ANALYSIS")
        print(f"  {'─'*50}")
        print(f"  Sub-tactus (raw IOI mode):  ~{sub_tactus_ms} ms  ({bpm_sub} BPM)")
        if subdivision > 1:
            print(f"  Subdivision detected:       {subdivision}× → tactus = {tactus_ms} ms  ({bpm_tactus} BPM)")
        else:
            print(f"  Tactus (= sub-tactus):      {tactus_ms} ms  ({bpm_tactus} BPM)")
        print(f"  Harmonic rhythm (Spikes):   ~{int(measure_ms)} ms  ({len(spike_times)} spikes detected)")
        print(f"  Ratio (measure/tactus):     {measure_ms/tactus_ms:.2f}  →  {beats_per_measure} beats/measure")

        print(f"\n  🎯  ESTIMATED METER")
        print(f"  {'─'*50}")
        print(f"  Time Signature:  {beats_per_measure}/{denominator}  ({meter_label})")
        print(f"  Tempo (tactus):  {bpm_tactus} BPM  (relative to ♩ = {denominator}th note)")
        print(f"  Tempo (♩ note):  ~{round(60000 / (tactus_ms * max(1, 4 // denominator)))} BPM  (quarter-note reference)")

        print(f"\n  📏  BARLINE GRID  ({len(barlines)} measures projected)")
        print(f"  {'─'*50}")
        snapped = sum(1 for b in barlines if b["snapped"])
        vetoed = sum(1 for b in barlines if b.get("source") == "corrected_dead_reckoning")
        print(f"  Snapped to spikes:  {snapped}/{len(barlines)}  ({round(100*snapped/max(1,len(barlines)))}%)")
        if pass2_triggered:
            print(f"  ⚕️  Pass 2 consistency repair: {vetoed} barline(s) corrected (spike had no bass confirmation)")
        print()
        for b in barlines:
            if b["snapped"]:
                snap_str = f"← SPIKE  drift:{b['drift_ms']:+d}ms"
            elif b.get("source") == "corrected_dead_reckoning":
                snap_str = f"⚕️  corrected  [{b.get('veto_reason', '')}]"
            else:
                snap_str = "↔ dead-reckoned"
            print(f"    Measure {b['measure']:02d}:  {b['time_ms']:6d} ms    {snap_str}")

        print(f"\n{sep}\n")


        # ── Build result dict ────────────────────────────────────────────
        result = {
            "source_file": self.json_path,
            "sub_tactus_ms": sub_tactus_ms,
            "tactus_ms": tactus_ms,
            "subdivision": subdivision,
            "bpm_tactus": bpm_tactus,
            "measure_ms": int(measure_ms),
            "beats_per_measure": beats_per_measure,
            "denominator": denominator,
            "time_signature": f"{beats_per_measure}/{denominator}",
            "meter_type": meter_label,
            "spike_count": len(spike_times),
            "barlines": barlines,
            "spike_density": spike_density,
            "autocorr": autocorr,
            "autocorr_peak_ms": int(measure_ms),
        }

        if write_json:
            import os
            import re
            # Extract base_key intelligently from etme_*.json filename
            # Examples:
            #   etme_chunk1_dissonance_hybrid.json → chunk1
            #   etme_pathetique_full_chunk_dissonance_hybrid_split_0.5.json → pathetique_full_chunk
            basename = os.path.basename(self.json_path)
            if basename.startswith('etme_') and basename.endswith('.json'):
                # Remove 'etme_' prefix and '.json' suffix
                middle = basename[5:-5]
                # Split on known angle_maps and break_methods
                for angle_map in ['dissonance', 'fifths']:
                    if angle_map in middle:
                        base_key = middle.split(f'_{angle_map}')[0]
                        break
                else:
                    base_key = middle
            else:
                base_key = basename.split('.')[0]

            out_dir = os.path.dirname(self.json_path)
            out_path = os.path.join(out_dir, f"phase3_grid_{base_key}.json")
            
            with open(out_path, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  ✅  Grid written to: {out_path}")

        return result


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    write_json = "--json" in args
    run_all = "--all" in args
    args = [a for a in args if not a.startswith("--")]

    if run_all:
        targets = sorted(glob.glob("visualizer/public/etme_*.json"))
    elif args:
        targets = args
    else:
        candidates = glob.glob("visualizer/public/etme_pathetique_64s_chunk_dissonance_hybrid_0.5.json")
        if not candidates:
            candidates = sorted(glob.glob("visualizer/public/etme_*.json"))
        targets = candidates[:1] if candidates else []

    if not targets:
        print("❌ No JSON files found. Pass a path or use --all.")
        sys.exit(1)

    for path in targets:
        try:
            estimator = MacroMeterEstimator(path)
            estimator.estimate(write_json=write_json)
        except FileNotFoundError:
            print(f"  ❌  File not found: {path}")
        except KeyError as e:
            print(f"  ❌  Unexpected JSON schema (missing key {e}): {path}")
