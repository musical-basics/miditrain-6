"""
Phase 3: Thermodynamic Meter Bootstrap
================================================================================
Translates Phase 1 (Harmonic Regime) + Phase 2 (Voice Threading) outputs into
emergent thermodynamic variables, detects phase transitions ("freezing events"),
and bootstraps meter from the periodicity of those events.

(Ported from miditrain-4's thermodynamic_meter.py, where it was called
"Step 2.5". Renumbered per `plan for improvements.md`: the thermodynamic
meter IS Phase 3; quantize-and-notate is Phase 4.)

The Four-Step Pipeline:
  Step 1: TRANSLATION  — musical elements → thermodynamic particles
  Step 2: MICROCOSM    — simulate T(t), η(t), P(t) on a discrete time-grid
  Step 3: PHASE DETECT — find freezing events (Liquid/Gas → Solid transitions)
  Step 4: METER APPROX — infer time signature & barlines from freeze periodicity

Usage:
    python phase3_thermo_meter.py path/to/etme_*.json          # explicit file
    python phase3_thermo_meter.py --json                       # write output JSON

Output: visualizer/public/phase3_thermo_{base_key}.json

NOTE: the barline grid consumed by Phase 4 currently comes from
phase3_spike_meter.py (phase3_grid_*.json), not from this file — same wiring
as miditrain-4. This file's meter block lacks `subdivision`, which Phase 4
requires; adding it is the open step to promote thermo to grid source.
"""

import json
import sys
import math
import glob
from collections import Counter

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

BIN_MS = 25                     # Time-grid resolution (40 bins/sec)
ENTROPY_WINDOW_NOTES = 12       # Lookback window for interval entropy (notes)
ACTIVITY_WINDOW_MS = 200        # Window for note-density measurement
MIN_FREEZE_MS = 50              # Minimum freeze duration to count as structural
MUSICAL_NORM_DIVISORS = [2, 3, 4, 6, 8, 12]

# Voice structural weights (how much each voice contributes to η).
# Bass/soprano values set by corpus grid search 2026-07-06 (was 3.0/2.0
# hand-tuned): train errors 1323→1289, val 1278→1237, see
# docs/benchmarking.md and grid_search_thermo.py.
VOICE_WEIGHTS = {
    "Voice 4": 4.0,     # Bass — strongest structural anchor
    "Voice 1": 3.0,     # Soprano / Melody — secondary anchor
    "Voice 2": 1.0,     # Alto
    "Voice 3": 1.0,     # Tenor
    "Overflow (Chord)": 0.5,
    "Unassigned": 0.5,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: TRANSLATION — Musical Elements → Thermodynamic Particles
# ═══════════════════════════════════════════════════════════════════════════════

def _translate_particle(note):
    """
    Translate a single note (from ETME JSON) into thermodynamic properties.

    Returns a dict with:
      mass          — compound mass (velocity × inertia × depth × voice weight)
      register_depth — 0.0 (high) to 1.0 (low)
      voice_weight  — structural importance from voice assignment
      onset         — start time (ms)
      end           — end time (ms)
      pitch         — MIDI pitch
      stability     — harmonic clarity from Phase 1 saturation
      dissonance    — tension from Phase 1 tonal distance + low saturation
    """
    velocity_norm = note["velocity"] / 127.0
    duration_s = min(note["duration"] / 1000.0, 4.0)   # Cap at 4s
    register_depth = (128 - note["pitch"]) / 128.0      # Low notes → heavy
    voice_w = VOICE_WEIGHTS.get(note["voice_tag"], 0.5)

    # Compound mass: how much structural gravity this note exerts
    mass = velocity_norm * duration_s * (1.0 + register_depth) * voice_w

    # Harmonic stability from Phase 1 (high saturation = clear identity = stable)
    saturation = note.get("sat", 50.0)
    stability = saturation / 100.0

    # Dissonance: tonal distance + chromatic ambiguity
    tonal_dist = note.get("tonal_distance", 0.0)
    dissonance = (tonal_dist / 15.0) + (1.0 - stability)

    return {
        "mass": mass,
        "register_depth": register_depth,
        "voice_weight": voice_w,
        "onset": note["onset"],
        "end": note["onset"] + note["duration"],
        "pitch": note["pitch"],
        "stability": stability,
        "dissonance": dissonance,
        "velocity_norm": velocity_norm,
        "voice_tag": note["voice_tag"],
    }


def translate_all(notes):
    """Step 1: Translate all ETME notes into thermodynamic particles."""
    particles = [_translate_particle(n) for n in notes]
    particles.sort(key=lambda p: p["onset"])
    return particles


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: MICROCOSM — Simulate T(t), η(t), P(t) on a Discrete Time-Grid
# ═══════════════════════════════════════════════════════════════════════════════

def _shannon_entropy(values):
    """Shannon entropy of a discrete distribution (in bits)."""
    if not values:
        return 0.0
    counter = Counter(values)
    total = len(values)
    entropy = 0.0
    for count in counter.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def _compute_interval_deltas(particles):
    """
    Compute pitch delta (Δp) for each note relative to the previous note
    in the SAME voice. Returns a list parallel to particles.
    """
    last_pitch_by_voice = {}
    deltas = []
    for p in particles:
        voice = p["voice_tag"]
        prev = last_pitch_by_voice.get(voice)
        if prev is not None:
            deltas.append(p["pitch"] - prev)
        else:
            deltas.append(None)  # No previous note in this voice
        last_pitch_by_voice[voice] = p["pitch"]
    return deltas


def build_microcosm(particles, notes_raw):
    """
    Step 2: Build the thermodynamic time-grid.

    Returns:
      grid — list of dicts, one per time bin, with keys:
             t_ms, temperature, viscosity, pressure, phase,
             n_active, register_span, energy_accum, dissonance_avg
      meta — dict with normalization stats
    """
    if not particles:
        return [], {}

    t_start = particles[0]["onset"]
    t_end = max(p["end"] for p in particles)
    n_bins = max(1, int((t_end - t_start) / BIN_MS) + 2)

    # Pre-compute per-note interval deltas for entropy calculation
    deltas = _compute_interval_deltas(particles)

    # Build onset index for fast lookback: list of (onset_ms, delta)
    onset_deltas = []
    for i, p in enumerate(particles):
        if deltas[i] is not None:
            onset_deltas.append((p["onset"], deltas[i]))

    grid = []
    energy_accum = 0.0

    for b in range(n_bins):
        t_ms = t_start + b * BIN_MS
        t_center = t_ms + BIN_MS / 2

        # ── Collect active notes at this time bin ──────────────────────
        active = []
        for p in particles:
            if p["onset"] <= t_center + BIN_MS and p["end"] >= t_center:
                active.append(p)

        n_active = len(active)

        # ── TEMPERATURE T(t) = Activity × Entropy ─────────────────────

        # Activity: notes arriving within the activity window centered here
        window_start = t_center - ACTIVITY_WINDOW_MS / 2
        window_end = t_center + ACTIVITY_WINDOW_MS / 2
        arrivals = [p for p in particles
                    if window_start <= p["onset"] <= window_end]
        activity_rate = len(arrivals) / (ACTIVITY_WINDOW_MS / 1000.0)

        # Interval entropy: Shannon entropy of recent pitch deltas
        # Lookback: collect the last N deltas before this time
        recent_deltas = []
        for onset_t, delta in onset_deltas:
            if onset_t > t_center:
                break
            if onset_t >= t_center - ACTIVITY_WINDOW_MS * 2:
                recent_deltas.append(delta)
        # Keep only the last ENTROPY_WINDOW_NOTES
        recent_deltas = recent_deltas[-ENTROPY_WINDOW_NOTES:]

        entropy = _shannon_entropy(recent_deltas)
        temperature = activity_rate * entropy

        # ── VISCOSITY η(t) = Σ mass × stability × convergence ─────────

        # Count how many distinct voices are active (for convergence)
        active_voices = set(p["voice_tag"] for p in active)
        convergence = 1.0 + 0.5 * max(0, len(active_voices) - 1)

        viscosity = 0.0
        for p in active:
            viscosity += p["mass"] * p["stability"] * convergence

        # ── PRESSURE P(t) = n × T / V ─────────────────────────────────

        if active:
            pitches = [p["pitch"] for p in active]
            register_span = max(1, max(pitches) - min(pitches) + 1)
        else:
            register_span = 1

        pressure = (n_active * temperature) / register_span if register_span > 0 else 0.0

        # ── DISSONANCE (for energy accumulator) ───────────────────────

        if active:
            dissonance_avg = sum(p["dissonance"] for p in active) / len(active)
        else:
            dissonance_avg = 0.0

        # ── ENERGY ACCUMULATOR ────────────────────────────────────────

        dt = BIN_MS / 1000.0
        energy_accum += temperature * dissonance_avg * dt

        grid.append({
            "t_ms": t_ms,
            "temperature": temperature,
            "viscosity": viscosity,
            "pressure": pressure,
            "n_active": n_active,
            "register_span": register_span,
            "entropy": entropy,
            "activity_rate": activity_rate,
            "dissonance_avg": dissonance_avg,
            "energy_accum": energy_accum,
            "phase": None,       # Assigned in Step 3
        })

    # ── Percentile normalization for phase thresholds ──────────────────

    temps = sorted(g["temperature"] for g in grid if g["temperature"] > 0)
    viscs = sorted(g["viscosity"] for g in grid if g["viscosity"] > 0)

    def percentile(arr, pct):
        if not arr:
            return 0.0
        idx = int(len(arr) * pct / 100.0)
        idx = min(idx, len(arr) - 1)
        return arr[idx]

    meta = {
        "t_start": t_start,
        "t_end": t_end,
        "n_bins": n_bins,
        "T_median": percentile(temps, 50),
        "T_75": percentile(temps, 75),
        "eta_median": percentile(viscs, 50),
        "eta_75": percentile(viscs, 75),
    }

    return grid, meta


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3: PHASE DETECTION — Find Freezing Events
# ═══════════════════════════════════════════════════════════════════════════════

def classify_phases(grid, meta):
    """
    Assign a phase label to each time bin based on T and η thresholds.

    Phase diagram:
      - Frozen Solid:  T < T_median  AND  η > η_75
      - Crystal Solid: T ≥ T_median  AND  η > η_75
      - Gas:           T ≥ T_75      AND  η ≤ η_75
      - Liquid:        everything else
    """
    T_med = meta["T_median"]
    T_75 = meta["T_75"]
    eta_75 = meta["eta_75"]

    for g in grid:
        T = g["temperature"]
        eta = g["viscosity"]

        if eta > eta_75:
            if T < T_med:
                g["phase"] = "frozen_solid"
            else:
                g["phase"] = "crystal"
        elif T >= T_75:
            g["phase"] = "gas"
        else:
            g["phase"] = "liquid"


def _is_solid(phase):
    return phase in ("frozen_solid", "crystal")


def detect_freezing_events(grid, regimes):
    """
    Step 3: Walk the time-grid and detect transitions INTO solid phase.

    A freezing event fires when the phase changes from liquid/gas → solid.
    The magnitude encodes structural importance (hierarchical beat strength).

    Also computes the tonic vector bonus: freezing events that coincide with
    harmonic motion TOWARD the tonic (H_tonic) receive a multiplier.
    """
    if len(grid) < 2:
        return []

    # Determine H_tonic: the hue of the longest/first stable regime
    H_tonic = _estimate_tonic_hue(regimes)

    events = []
    freeze_start = None
    pre_freeze_pressure = 0.0
    pre_freeze_energy = 0.0
    pre_freeze_phase = "liquid"
    pre_freeze_eta = 0.0

    for i in range(1, len(grid)):
        prev = grid[i - 1]
        curr = grid[i]

        was_solid = _is_solid(prev["phase"])
        is_solid = _is_solid(curr["phase"])

        if not was_solid and is_solid:
            # ── FREEZE ONSET ──────────────────────────────────────────
            freeze_start = i
            pre_freeze_pressure = prev["pressure"]
            pre_freeze_energy = prev["energy_accum"]
            pre_freeze_phase = prev["phase"]
            pre_freeze_eta = prev["viscosity"]

            # Reset energy accumulator (tension discharged)
            energy_released = curr["energy_accum"]
            for j in range(i, len(grid)):
                grid[j]["energy_accum"] -= energy_released

        elif was_solid and not is_solid and freeze_start is not None:
            # ── FREEZE END ────────────────────────────────────────────
            freeze_end = i
            freeze_onset_bin = grid[freeze_start]
            duration_ms = (freeze_end - freeze_start) * BIN_MS

            if duration_ms < MIN_FREEZE_MS:
                freeze_start = None
                continue

            # Viscosity spike: how much η jumped at the freeze
            delta_eta = freeze_onset_bin["viscosity"] - pre_freeze_eta
            delta_eta = max(0.0, delta_eta)

            # Tonic vector bonus
            tonic_bonus = _tonic_bonus(freeze_onset_bin["t_ms"], regimes, H_tonic)

            # Composite magnitude
            magnitude = (
                delta_eta
                * (1.0 + pre_freeze_pressure)
                * max(0.1, pre_freeze_energy)
                * tonic_bonus
            )

            events.append({
                "time_ms": freeze_onset_bin["t_ms"],
                "magnitude": round(magnitude, 3),
                "eta_spike": round(delta_eta, 3),
                "pressure_before": round(pre_freeze_pressure, 3),
                "energy_released": round(pre_freeze_energy, 3),
                "tonic_bonus": round(tonic_bonus, 3),
                "duration_ms": duration_ms,
                "phase_from": pre_freeze_phase,
                "phase_to": freeze_onset_bin["phase"],
            })

            freeze_start = None

    # Handle case where piece ends in a solid phase
    if freeze_start is not None:
        freeze_onset_bin = grid[freeze_start]
        duration_ms = (len(grid) - freeze_start) * BIN_MS
        if duration_ms >= MIN_FREEZE_MS:
            delta_eta = max(0.0, freeze_onset_bin["viscosity"] - pre_freeze_eta)
            tonic_bonus = _tonic_bonus(freeze_onset_bin["t_ms"], regimes, H_tonic)
            magnitude = (
                delta_eta
                * (1.0 + pre_freeze_pressure)
                * max(0.1, pre_freeze_energy)
                * tonic_bonus
            )
            events.append({
                "time_ms": freeze_onset_bin["t_ms"],
                "magnitude": round(magnitude, 3),
                "eta_spike": round(delta_eta, 3),
                "pressure_before": round(pre_freeze_pressure, 3),
                "energy_released": round(pre_freeze_energy, 3),
                "tonic_bonus": round(tonic_bonus, 3),
                "duration_ms": duration_ms,
                "phase_from": pre_freeze_phase,
                "phase_to": freeze_onset_bin["phase"],
            })

    return events


def _estimate_tonic_hue(regimes):
    """
    Estimate H_tonic as the hue of the longest stable regime block.
    This represents the macro-key's tonal center on the color wheel.
    """
    if not regimes:
        return 0.0

    best_hue = 0.0
    best_duration = 0

    for r in regimes:
        if r["state"] in ("Stable", "Regime Locked"):
            dur = r["end_time"] - r["start_time"]
            if dur > best_duration:
                best_duration = dur
                best_hue = r["hue"]

    return best_hue


def _angular_distance(a, b):
    """Shortest angular distance on a 360° wheel."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _tonic_bonus(time_ms, regimes, H_tonic):
    """
    Compute the tonic resolution bonus for a freezing event.
    If the harmonic field is moving TOWARD H_tonic at this moment,
    the freeze is a tonal resolution and gets a bonus multiplier.
    """
    if not regimes or H_tonic is None:
        return 1.0

    # Find the regime active at this time and the one before it
    current_regime = None
    previous_regime = None
    for i, r in enumerate(regimes):
        if r["start_time"] <= time_ms <= r["end_time"]:
            current_regime = r
            if i > 0:
                previous_regime = regimes[i - 1]
            break

    if current_regime is None or previous_regime is None:
        return 1.0

    dist_before = _angular_distance(previous_regime["hue"], H_tonic)
    dist_now = _angular_distance(current_regime["hue"], H_tonic)

    if dist_now < dist_before:
        # Moving TOWARD tonic — tonal resolution
        improvement = (dist_before - dist_now) / 180.0
        return 1.0 + improvement
    else:
        return 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Step 4: METER APPROXIMATION — Infer Meter from Freezing Periodicity
# ═══════════════════════════════════════════════════════════════════════════════

def _nearest_norm(ratio, norms=MUSICAL_NORM_DIVISORS):
    """Snap a floating ratio to the nearest musical integer norm."""
    if ratio < 1.5:
        return 2
    return min(norms, key=lambda n: abs(n - ratio))


def _meter_type(beats):
    labels = {2: "simple_duple", 3: "simple_triple", 4: "simple_quadruple",
              6: "compound_duple", 9: "compound_triple", 12: "compound_quadruple"}
    return labels.get(beats, "complex")


def _estimate_subdivision(particles, tactus_ms):
    """
    Estimate the sub-tactus subdivision (grid ticks per beat) so the thermo
    meter block can feed Phase 4 directly (the quantizer needs `subdivision`).

    The freeze-derived tactus gives the beat; the note-onset IOI spectrum
    gives the fastest common pulse (sub-tactus) — same hierarchical IOI
    clustering idea as the spike meter, applied to all note onsets.

    Returns (subdivision, sub_tactus_ms).
    """
    onsets = sorted(set(p["onset"] for p in particles))
    if len(onsets) < 2 or not tactus_ms:
        return 1, None
    iois = [onsets[i] - onsets[i - 1] for i in range(1, len(onsets))]
    valid = [x for x in iois if 50 <= x <= 2000]
    if not valid:
        return 1, None
    # Tight 10ms binning to resolve fast sub-tactus pulses
    binned = [round(x / 10) * 10 for x in valid]
    sub_tactus_ms = Counter(binned).most_common(1)[0][0]
    if sub_tactus_ms <= 0 or sub_tactus_ms > tactus_ms:
        return 1, sub_tactus_ms

    ratio = tactus_ms / sub_tactus_ms
    # Freeze-derived tactus can sit high in the metric hierarchy (half note,
    # whole measure), so allow the full musical-norm ladder up to 12
    # (e.g. Pathétique: 1000ms tactus / 80ms triplet-16ths → 12).
    subdivision = min([1] + MUSICAL_NORM_DIVISORS, key=lambda r: abs(r - ratio))
    # Reject a snap that misrepresents the true ratio by more than 35%
    if abs(subdivision - ratio) > 0.35 * subdivision:
        subdivision = 1
    return subdivision, sub_tactus_ms


def approximate_meter(events, grid, particles):
    """
    Step 4: Use the freezing events to infer time signature and barlines.

    Strategy:
      1. Autocorrelate the magnitude-weighted impulse train of freezing events
         to find the dominant period (measure length).
      2. Cluster sub-freeze IOIs to find the tactus (beat level).
      3. Derive time signature from measure/tactus ratio.
      4. Project barlines using rubber-band snapping to freezing events.
    """
    if not events or not grid:
        return None

    t_start = grid[0]["t_ms"]
    t_end = grid[-1]["t_ms"]
    max_time = t_end - t_start

    # ── 4.1: Autocorrelation of freeze impulse train ──────────────────

    # Build magnitude-weighted impulse array on the time-grid
    n_bins = len(grid)
    impulse = [0.0] * n_bins
    for e in events:
        idx = int((e["time_ms"] - t_start) / BIN_MS)
        if 0 <= idx < n_bins:
            impulse[idx] = e["magnitude"]

    # Autocorrelate: lags from 200ms to 8000ms
    min_lag = max(1, int(200 / BIN_MS))
    max_lag = min(n_bins // 2, int(8000 / BIN_MS))

    autocorr = []
    for lag in range(min_lag, max_lag + 1):
        pairs = n_bins - lag
        if pairs <= 0:
            break
        raw = sum(impulse[i] * impulse[i + lag] for i in range(pairs))
        score = raw / pairs
        autocorr.append((lag * BIN_MS, score))

    if not autocorr:
        return None

    # Find the dominant period
    scores = [s for _, s in autocorr]
    max_score = max(scores) if scores else 0
    if max_score == 0:
        return None

    NOISE_FLOOR = max_score * 0.25

    # Find local maxima above noise floor
    peaks = []
    for i in range(1, len(scores) - 1):
        if scores[i] > scores[i - 1] and scores[i] > scores[i + 1] and scores[i] > NOISE_FLOOR:
            peaks.append((autocorr[i][0], scores[i]))

    if not peaks:
        measure_ms = max(autocorr, key=lambda x: x[1])[0]
    else:
        # Smallest lag with ≥75% of max score
        significant = [(lag, s) for lag, s in peaks if s >= max_score * 0.75]
        if significant:
            measure_ms = min(significant, key=lambda x: x[0])[0]
        else:
            measure_ms = min(peaks, key=lambda x: x[0])[0]

    # ── 4.2: Tactus from inter-freeze IOIs ────────────────────────────

    freeze_times = sorted(e["time_ms"] for e in events)
    if len(freeze_times) >= 2:
        iois = [freeze_times[i] - freeze_times[i - 1]
                for i in range(1, len(freeze_times))
                if 50 <= freeze_times[i] - freeze_times[i - 1] <= 4000]
        if iois:
            # Bin and find the mode
            binned = [round(x / 25) * 25 for x in iois]
            counter = Counter(binned)
            tactus_ms = counter.most_common(1)[0][0]
        else:
            tactus_ms = measure_ms
    else:
        tactus_ms = measure_ms

    # Ensure tactus ≤ measure
    if tactus_ms > measure_ms:
        tactus_ms = measure_ms

    # ── 4.3: Time signature derivation ────────────────────────────────

    raw_ratio = measure_ms / tactus_ms if tactus_ms > 0 else 4
    beats_per_measure = _nearest_norm(raw_ratio)

    bpm_tactus = round(60000 / tactus_ms) if tactus_ms > 0 else 120

    # Denominator from BPM heuristic
    if bpm_tactus > 200:
        denominator = 16
    elif bpm_tactus > 140:
        denominator = 8
    elif bpm_tactus > 60:
        denominator = 4
    else:
        denominator = 2

    meter_label = _meter_type(beats_per_measure)

    # Subdivision (ticks per beat) from note-onset IOIs — required by
    # Phase 4's quantizer when this meter block is used as the grid source.
    subdivision, sub_tactus_ms = _estimate_subdivision(particles, tactus_ms)

    # ── 4.4: Barline projection (rubber-band snap to freezes) ─────────

    barlines = _project_barlines(events, grid, measure_ms, t_start, t_end)

    # ── 4.5: Consistency repair ───────────────────────────────────────

    barlines, repaired = _repair_barlines(barlines, measure_ms, events)

    # Normalized autocorrelation for export
    autocorr_norm = [
        {"lag_ms": lag, "score": round(s / max_score, 4) if max_score > 0 else 0}
        for lag, s in autocorr
    ]

    return {
        "measure_ms": int(measure_ms),
        "tactus_ms": int(tactus_ms),
        "sub_tactus_ms": int(sub_tactus_ms) if sub_tactus_ms else None,
        "subdivision": subdivision,
        "bpm_tactus": bpm_tactus,
        "beats_per_measure": beats_per_measure,
        "denominator": denominator,
        "time_signature": f"{beats_per_measure}/{denominator}",
        "meter_type": meter_label,
        "barlines": barlines,
        "pass2_repaired": repaired,
        "autocorr": autocorr_norm,
        "autocorr_peak_ms": int(measure_ms),
    }


def _project_barlines(events, grid, measure_ms, t_start, t_end):
    """
    Project barlines with rubber-band snapping to freezing events.
    Gas regions act as anti-anchors: barlines landing in gas phase are
    slid to the nearest non-gas boundary.
    """
    snap_window = int(measure_ms * 0.15)
    min_gap = int(measure_ms * 0.5)

    # Build quick lookup: freeze times + magnitudes
    freeze_lookup = [(e["time_ms"], e["magnitude"]) for e in events]

    # Build phase lookup (time_ms → phase)
    phase_at = {}
    for g in grid:
        phase_at[g["t_ms"]] = g["phase"]

    barlines = []
    current_time = t_start
    last_barline = -9999
    measure = 1

    while current_time <= t_end + measure_ms:
        # Find nearby freezing events within snap window
        nearby = [
            (t, mag) for t, mag in freeze_lookup
            if abs(t - current_time) <= snap_window
            and t - last_barline >= min_gap
        ]

        if nearby:
            # Snap to the highest-magnitude freeze in the window
            best = max(nearby, key=lambda x: x[1])
            actual = best[0]
            drift = actual - current_time
            barlines.append({
                "measure": measure,
                "time_ms": int(actual),
                "snapped": True,
                "drift_ms": int(drift),
                "source": "freeze_event",
                "freeze_magnitude": round(best[1], 3),
            })
            current_time = actual
            last_barline = actual
        else:
            # Anti-anchor: check if we're in a gas region
            nearest_bin = round((current_time - grid[0]["t_ms"]) / BIN_MS) * BIN_MS + grid[0]["t_ms"]
            phase = phase_at.get(nearest_bin, "liquid")

            placed_time = current_time
            source = "dead_reckoning"

            if phase == "gas":
                # Slide to nearest non-gas boundary
                slid = _slide_out_of_gas(current_time, grid)
                if slid is not None and slid - last_barline >= min_gap:
                    placed_time = slid
                    source = "gas_slide"

            barlines.append({
                "measure": measure,
                "time_ms": int(placed_time),
                "snapped": False,
                "drift_ms": 0,
                "source": source,
            })
            last_barline = placed_time

        current_time = (barlines[-1]["time_ms"]) + measure_ms
        measure += 1

    return barlines


def _slide_out_of_gas(time_ms, grid):
    """
    If a barline lands in a gas region, slide it to the nearest
    liquid or solid boundary. Returns the adjusted time or None.
    """
    # Search outward in both directions
    best = None
    best_dist = float("inf")

    for g in grid:
        if g["phase"] != "gas":
            dist = abs(g["t_ms"] - time_ms)
            if dist < best_dist:
                best_dist = dist
                best = g["t_ms"]

    return best


def _repair_barlines(barlines, measure_ms, events):
    """
    Pass 2: Consistency repair.
    Reject snapped barlines that create intervals deviating >15% from
    expected measure length, unless confirmed by a high-magnitude freeze.
    """
    TOLERANCE = 0.15
    repaired = list(barlines)
    changed = False

    # Magnitude threshold: freezes above this are unconditionally trusted
    if events:
        magnitudes = sorted(e["magnitude"] for e in events)
        mag_threshold = magnitudes[int(len(magnitudes) * 0.75)] if magnitudes else 0
    else:
        mag_threshold = float("inf")

    for i in range(1, len(repaired)):
        interval = repaired[i]["time_ms"] - repaired[i - 1]["time_ms"]
        projected = repaired[i - 1]["time_ms"] + measure_ms

        too_short = interval < measure_ms * (1 - TOLERANCE)
        too_long = interval > measure_ms * (1 + TOLERANCE)

        if (too_short or too_long) and repaired[i]["snapped"]:
            freeze_mag = repaired[i].get("freeze_magnitude", 0)

            # High-magnitude freezes are unconditionally trusted
            if freeze_mag >= mag_threshold:
                continue

            repaired[i] = {
                "measure": repaired[i]["measure"],
                "time_ms": int(projected),
                "snapped": False,
                "drift_ms": 0,
                "source": "corrected_dead_reckoning",
                "veto_reason": (
                    f"interval={'short' if too_short else 'long'} "
                    f"({interval}ms vs {int(measure_ms)}ms expected); "
                    f"freeze_mag={freeze_mag:.2f} < threshold={mag_threshold:.2f}"
                ),
            }
            changed = True

            # Cascade correction to subsequent dead-reckoned barlines
            for j in range(i + 1, len(repaired)):
                if not repaired[j]["snapped"]:
                    repaired[j] = dict(repaired[j])
                    repaired[j]["time_ms"] = repaired[j - 1]["time_ms"] + measure_ms
                else:
                    break

    return repaired, changed


# ═══════════════════════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class ThermodynamicMeterEstimator:
    """
    Step 2.5: Thermodynamic Meter Bootstrap.

    Translates Phase 1 + Phase 2 outputs into emergent thermodynamic variables,
    detects phase transitions, and bootstraps meter from freezing event periodicity.
    """

    def __init__(self, json_path):
        with open(json_path, "r") as f:
            self.data = json.load(f)
        self.json_path = json_path
        self.notes = self.data["notes"]
        self.regimes = self.data["regimes"]

    def estimate(self, write_json=False):
        sep = "=" * 65

        print(f"\n{sep}")
        print(f"  🌡️   STEP 2.5: THERMODYNAMIC METER BOOTSTRAP")
        print(f"  📄  {self.json_path.split('/')[-1]}")
        print(f"{sep}")

        # ── Step 1: Translation ───────────────────────────────────────
        print(f"\n  ⚛️   STEP 1: TRANSLATION")
        print(f"  {'─'*55}")
        particles = translate_all(self.notes)
        print(f"  Translated {len(particles)} notes → thermodynamic particles")

        masses = [p["mass"] for p in particles]
        if masses:
            print(f"  Mass range: {min(masses):.3f} – {max(masses):.3f}  "
                  f"(median: {sorted(masses)[len(masses)//2]:.3f})")

        # ── Step 2: Microcosm ─────────────────────────────────────────
        print(f"\n  🔬  STEP 2: MICROCOSM")
        print(f"  {'─'*55}")
        grid, meta = build_microcosm(particles, self.notes)
        print(f"  Time-grid: {meta['n_bins']} bins × {BIN_MS}ms "
              f"({meta['t_start']}ms – {meta['t_end']}ms)")
        print(f"  T thresholds: median={meta['T_median']:.2f}  75th={meta['T_75']:.2f}")
        print(f"  η thresholds: median={meta['eta_median']:.2f}  75th={meta['eta_75']:.2f}")

        # ── Step 3: Phase Detection ───────────────────────────────────
        print(f"\n  🧊  STEP 3: PHASE DETECTION")
        print(f"  {'─'*55}")
        classify_phases(grid, meta)

        # Phase census
        phase_counts = Counter(g["phase"] for g in grid)
        total_bins = len(grid)
        for phase in ["frozen_solid", "crystal", "liquid", "gas"]:
            count = phase_counts.get(phase, 0)
            pct = round(100 * count / max(1, total_bins))
            bar = "█" * (pct // 2)
            print(f"    {phase:14s}  {pct:3d}%  {bar}")

        # Detect freezing events
        events = detect_freezing_events(grid, self.regimes)
        print(f"\n  Freezing events detected: {len(events)}")

        if events:
            mags = [e["magnitude"] for e in events]
            print(f"  Magnitude range: {min(mags):.3f} – {max(mags):.3f}")
            print()
            for i, e in enumerate(events):
                strength = "███" if e["magnitude"] > sorted(mags)[len(mags)*2//3] else \
                           "██" if e["magnitude"] > sorted(mags)[len(mags)//3] else "█"
                print(f"    [{i+1:02d}]  t={e['time_ms']:6d}ms  "
                      f"mag={e['magnitude']:8.3f}  "
                      f"Δη={e['eta_spike']:6.3f}  "
                      f"P={e['pressure_before']:6.3f}  "
                      f"E={e['energy_released']:6.3f}  "
                      f"tonic={e['tonic_bonus']:.2f}  "
                      f"dur={e['duration_ms']:4d}ms  "
                      f"{e['phase_from']}→{e['phase_to']}  {strength}")

        # ── Step 4: Meter Approximation ───────────────────────────────
        print(f"\n  📐  STEP 4: METER APPROXIMATION")
        print(f"  {'─'*55}")

        meter = approximate_meter(events, grid, particles)

        if meter is None:
            print("  ⚠️  Could not determine meter (insufficient freezing events).")
            return None

        print(f"  Measure length:   ~{meter['measure_ms']} ms  (autocorrelation peak)")
        print(f"  Tactus:           ~{meter['tactus_ms']} ms")
        print(f"  Time Signature:    {meter['time_signature']}  ({meter['meter_type']})")
        print(f"  Tempo (tactus):    {meter['bpm_tactus']} BPM")

        print(f"\n  📏  BARLINE GRID  ({len(meter['barlines'])} measures)")
        print(f"  {'─'*55}")
        snapped = sum(1 for b in meter["barlines"] if b["snapped"])
        vetoed = sum(1 for b in meter["barlines"]
                     if b.get("source") == "corrected_dead_reckoning")
        gas_slid = sum(1 for b in meter["barlines"]
                       if b.get("source") == "gas_slide")
        print(f"  Snapped to freezes:  {snapped}/{len(meter['barlines'])}  "
              f"({round(100*snapped/max(1,len(meter['barlines'])))}%)")
        if vetoed:
            print(f"  ⚕️  Consistency repair: {vetoed} barline(s) corrected")
        if gas_slid:
            print(f"  💨  Gas anti-anchor: {gas_slid} barline(s) slid out of gas regions")

        print()
        for b in meter["barlines"]:
            if b["snapped"]:
                snap_str = (f"← FREEZE  drift:{b['drift_ms']:+d}ms  "
                            f"mag:{b.get('freeze_magnitude', 0):.3f}")
            elif b.get("source") == "corrected_dead_reckoning":
                snap_str = f"⚕️  corrected  [{b.get('veto_reason', '')}]"
            elif b.get("source") == "gas_slide":
                snap_str = "💨 slid out of gas"
            else:
                snap_str = "↔ dead-reckoned"
            print(f"    Measure {b['measure']:02d}:  {b['time_ms']:6d} ms    {snap_str}")

        print(f"\n{sep}\n")

        # ── Build full result ─────────────────────────────────────────

        result = {
            "source_file": self.json_path,
            "thermodynamic_meta": {
                "T_median": round(meta["T_median"], 4),
                "T_75": round(meta["T_75"], 4),
                "eta_median": round(meta["eta_median"], 4),
                "eta_75": round(meta["eta_75"], 4),
            },
            "phase_census": {
                phase: round(100 * phase_counts.get(phase, 0) / max(1, total_bins), 1)
                for phase in ["frozen_solid", "crystal", "liquid", "gas"]
            },
            "freezing_events": events,
            "meter": meter,
            # Compact grid export: only bins with significant activity
            "grid_sample": [
                {
                    "t_ms": g["t_ms"],
                    "T": round(g["temperature"], 4),
                    "eta": round(g["viscosity"], 4),
                    "P": round(g["pressure"], 4),
                    "phase": g["phase"],
                    "E": round(g["energy_accum"], 4),
                }
                for g in grid[::4]  # Every 4th bin (100ms spacing for export)
            ],
        }

        if write_json:
            import os
            # Extract base_key intelligently from etme_*.json filename
            # Examples:
            #   etme_chunk1_dissonance_hybrid.json → chunk1
            #   etme_pathetique_full_chunk_dissonance_hybrid_split_0.5.json → pathetique_full_chunk
            basename = os.path.basename(self.json_path)
            if basename.startswith("etme_") and basename.endswith(".json"):
                # Remove 'etme_' prefix and '.json' suffix
                middle = basename[5:-5]
                # Split on known angle_maps
                for angle_map in ['dissonance', 'fifths']:
                    if angle_map in middle:
                        base_key = middle.split(f'_{angle_map}')[0]
                        break
                else:
                    base_key = middle
            else:
                base_key = basename.split(".")[0]

            out_dir = os.path.dirname(self.json_path)
            out_path = os.path.join(out_dir, f"phase3_thermo_{base_key}.json")

            with open(out_path, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  ✅  Output written to: {out_path}")

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

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
            estimator = ThermodynamicMeterEstimator(path)
            estimator.estimate(write_json=write_json)
        except FileNotFoundError:
            print(f"  ❌  File not found: {path}")
        except KeyError as e:
            print(f"  ❌  Unexpected JSON schema (missing key {e}): {path}")
