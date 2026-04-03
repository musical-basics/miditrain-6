"""
Exports ETME Phase 1 + Phase 2 analysis of a real MIDI file as JSON
for the browser-based piano roll visualizer.

Phase 1 uses the HarmonicRegimeDetector
(vector-based color wheel with HSL output).
Phase 2 uses the VoiceThreader
(thermodynamic polyphonic voice separation).
"""
import json
import math
import os
import sys
import argparse
from symusic import Score
from particle import Particle
from harmonic_regime_detector import HarmonicRegimeDetector, SEMITONE_MAP, ANGLE_MAPS, INTERVAL_ANGLES_DISSONANCE
from voice_threader import VoiceThreader
from voice_threader_beam import BeamVoiceThreader

# Map MIDI pitch class (0-11) to interval names for the regime detector
PC_TO_INTERVAL = {
    0: "1", 1: "b2", 2: "2", 3: "b3", 4: "3", 5: "4",
    6: "#4", 7: "5", 8: "b6", 9: "6", 10: "b7", 11: "7"
}


def calculate_weighted_chord_color(notes, interval_angles=None):
    if interval_angles is None:
        interval_angles = INTERVAL_ANGLES_DISSONANCE
    x_total = 0.0
    y_total = 0.0
    lightness_weighted_total = 0.0
    weight_total = 0.0

    for interval, octave, velocity in notes:
        if velocity <= 0:
            continue
        weight = velocity / 127.0
        weight_total += weight
        angle_rad = math.radians(interval_angles[interval])
        x_total += weight * math.cos(angle_rad)
        y_total += weight * math.sin(angle_rad)
        note_lightness = 5.0 + ((octave - 1) * 15.0)
        note_lightness = max(0.0, min(100.0, note_lightness))
        lightness_weighted_total += weight * note_lightness

    if weight_total == 0:
        return {"hue": 0.0, "sat": 0.0, "lightness": 0.0, "tonal_distance": 0.0}

    x_avg = x_total / weight_total
    y_avg = y_total / weight_total
    final_hue = math.degrees(math.atan2(y_avg, x_avg))
    if final_hue < 0:
        final_hue += 360
    final_saturation = math.sqrt(x_avg**2 + y_avg**2) * 100.0
    final_lightness = lightness_weighted_total / weight_total
    nearest_node = round(final_hue / 30.0) * 30.0
    tonal_distance = abs(final_hue - nearest_node)

    return {
        "hue": round(final_hue, 1),
        "sat": round(final_saturation, 1),
        "lightness": round(final_lightness, 1),
        "tonal_distance": round(tonal_distance, 1)
    }


def compute_rolling_color(onset_ms, all_particles, regime_start_ms, interval_angles=None):
    if interval_angles is None:
        interval_angles = INTERVAL_ANGLES_DISSONANCE
    lookahead = onset_ms + 50
    active_notes = []

    for p in all_particles:
        if p.onset < regime_start_ms:
            continue
        if p.onset > lookahead:
            break
        note_end = p.onset + p.duration
        if p.onset <= lookahead and note_end >= onset_ms:
            interval = PC_TO_INTERVAL[p.pitch % 12]
            octave = p.pitch // 12
            active_notes.append((interval, octave, p.velocity))

    if not active_notes:
        return {"hue": 0.0, "sat": 0.0, "lightness": 0.0, "tonal_distance": 0.0}
    return calculate_weighted_chord_color(active_notes, interval_angles)


def midi_to_particles(midi_path):
    score = Score(midi_path)
    tpq = score.ticks_per_quarter
    tick_to_ms = 500.0 / tpq  # System-wide convention: 120 BPM = 500ms/quarter
    particles = []
    for track in score.tracks:
        for note in track.notes:
            particles.append(Particle(
                pitch=note.pitch,
                velocity=note.velocity,
                onset_ms=int(note.start * tick_to_ms),
                duration_ms=int(note.duration * tick_to_ms)
            ))
    particles.sort(key=lambda p: p.onset)
    return particles


def extract_keyframes(midi_path, group_window_ms=50):
    score = Score(midi_path)
    tpq = score.ticks_per_quarter
    tick_to_ms = 500.0 / tpq  # System-wide convention: 120 BPM = 500ms/quarter
    raw_notes = []
    for track in score.tracks:
        for note in track.notes:
            time_ms = int(note.start * tick_to_ms)
            interval = PC_TO_INTERVAL[note.pitch % 12]
            octave = note.pitch // 12
            duration_ms = int(note.duration * tick_to_ms)
            raw_notes.append((time_ms, interval, octave, note.velocity, duration_ms))
    raw_notes.sort(key=lambda x: x[0])

    keyframes = []
    current_group_time = None
    current_group_notes = []
    for note in raw_notes:
        time_ms = note[0]
        note_data = (note[1], note[2], note[3], note[4])
        if current_group_time is None:
            current_group_time = time_ms
            current_group_notes.append(note_data)
        elif time_ms - current_group_time <= group_window_ms:
            current_group_notes.append(note_data)
        else:
            keyframes.append((current_group_time, current_group_notes))
            current_group_time = time_ms
            current_group_notes = [note_data]
    if current_group_time is not None:
        keyframes.append((current_group_time, current_group_notes))
    return keyframes


def export_analysis(midi_path, output_json="etme_analysis.json", angle_map='dissonance', break_method='centroid', jaccard_threshold=0.5, min_break_mass=0.75, break_angle=15.0, merge_angle=20.0, debounce_ms=100, trim_ms=None, phase2_model='greedy', **extra_params):
    print(f"Loading MIDI: {midi_path}")
    print(f"  Angle map: {angle_map}, Break method: {break_method}, Jaccard: {jaccard_threshold}, Min Break Mass: {min_break_mass}")
    print(f"  Break angle: {break_angle}°, Merge angle: {merge_angle}°, Debounce: {debounce_ms}ms")
    if extra_params:
        print(f"  V3 params: {extra_params}")
    particles = midi_to_particles(midi_path)
    keyframes = extract_keyframes(midi_path)
    print(f"  Loaded {len(particles)} particles, {len(keyframes)} keyframes")

    interval_angles = ANGLE_MAPS.get(angle_map, INTERVAL_ANGLES_DISSONANCE)

    print(f"Running Phase 1: Harmonic Regime Detector (Limbo V2.2)...")
    detector = HarmonicRegimeDetector(
        break_angle=break_angle, min_break_mass=min_break_mass, merge_angle=merge_angle,
        angle_map=angle_map, break_method=break_method, jaccard_threshold=jaccard_threshold,
        debounce_ms=debounce_ms, **extra_params
    )
    regime_frames = detector.process(keyframes)

    regimes = []
    current_regime = None
    for frame in regime_frames:
        rid = frame["Regime_ID"]
        state = frame["State"]
        is_new_regime = (current_regime is None or current_regime.get("id") != rid)
        is_spike_start = (state == "TRANSITION SPIKE!" and current_regime is not None
                          and current_regime.get("state") != "TRANSITION SPIKE!")
        is_spike_end = (state != "TRANSITION SPIKE!" and current_regime is not None
                        and current_regime.get("state") == "TRANSITION SPIKE!")
        if is_new_regime or is_spike_start or is_spike_end:
            if current_regime:
                current_regime["end_time"] = frame["Time (ms)"]
                regimes.append(current_regime)
            current_regime = {
                "id": rid,
                "start_time": frame["Time (ms)"],
                "end_time": frame["Time (ms)"],
                "state": state,
                "hue": frame["Hue"],
                "saturation": frame["Sat (%)"],
                "v_vec": frame["V_vec"]
            }
        else:
            current_regime["end_time"] = frame["Time (ms)"]
            if state in ["Stable", "Regime Locked"]:
                current_regime["state"] = state
    if current_regime:
        current_regime["end_time"] = particles[-1].onset + particles[-1].duration
        regimes.append(current_regime)

    print(f"  Detected {len(regimes)} harmonic regimes (after consolidation)")
    state_counts = {}
    for r in regimes:
        state_counts[r["state"]] = state_counts.get(r["state"], 0) + 1
    for s, c in state_counts.items():
        print(f"    {s}: {c}")

    frame_lookup = []
    for frame in regime_frames:
        frame_lookup.append({
            "time": frame["Time (ms)"],
            "hue": frame["Hue"],
            "sat": frame["Sat (%)"],
            "v_vec": frame["V_vec"],
            "state": frame["State"],
            "debug": frame.get("debug", {})
        })

    # =============================================
    # Phase 2: Thermodynamic Voice Threading
    # =============================================
    if phase2_model == 'beam':
        print("Running Phase 2: Beam Search Voice Threading...")
        threader = BeamVoiceThreader(max_voices=4, beam_width=64)
    else:
        print("Running Phase 2: Thermodynamic Voice Threading (Greedy)...")
        threader = VoiceThreader(max_voices=4)
    scored_particles = threader.thread_particles(particles, frame_lookup)

    voice_counts = {}
    for p in scored_particles:
        voice_counts[p.voice_tag] = voice_counts.get(p.voice_tag, 0) + 1
    for tag, count in sorted(voice_counts.items()):
        print(f"  {tag}: {count} notes")

    print("Computing per-note chord colors (truncating past regimes)...")
    notes_json = []

    def get_regime_start(onset):
        for i, r in enumerate(regimes):
            if onset >= r["start_time"] and (i == len(regimes) - 1 or onset < regimes[i + 1]["start_time"]):
                start = r["start_time"]
                rid = r["id"]
                j = i - 1
                while j >= 0 and regimes[j]["id"] == rid:
                    start = regimes[j]["start_time"]
                    j -= 1
                return start
        return regimes[0]["start_time"] if regimes else 0

    for p in particles:
        regime_start = get_regime_start(p.onset)
        color = compute_rolling_color(p.onset, particles, regime_start, interval_angles)
        closest_frame = min(frame_lookup, key=lambda f: abs(f["time"] - p.onset))

        notes_json.append({
            "pitch": p.pitch,
            "velocity": p.velocity,
            "onset": p.onset,
            "duration": p.duration,
            "id_score": round(p.id_score, 2),
            "voice_tag": p.voice_tag,
            "hue": color["hue"],
            "sat": color["sat"],
            "lightness": color["lightness"],
            "tonal_distance": color["tonal_distance"],
            "regime_state": closest_frame["state"],
            "debug": closest_frame.get("debug", {})
        })

    regimes_json = []
    for r in regimes:
        regimes_json.append({
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "state": r["state"],
            "hue": r["hue"],
            "saturation": r["saturation"],
            "v_vec": r["v_vec"]
        })

    # ─── Trim to scoring window (strip buffer zone) ─────────────────────
    if trim_ms is not None:
        notes_json = [n for n in notes_json if n["onset"] <= trim_ms]
        regimes_json = [r for r in regimes_json if r["start_time"] <= trim_ms]
        # Clamp the last regime's end_time to trim_ms
        if regimes_json and regimes_json[-1]["end_time"] > trim_ms:
            regimes_json[-1]["end_time"] = trim_ms
        print(f"  Trimmed to {trim_ms}ms: {len(notes_json)} notes, {len(regimes_json)} regimes")

    data = {
        "notes": notes_json,
        "regimes": regimes_json,
        "stats": {
            "total_notes": len(notes_json),
            "total_regimes": len(regimes_json),
            "voice_counts": voice_counts
        }
    }

    with open(output_json, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nAnalysis exported to: {output_json}")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export ETME Data (Phase 1 + Phase 2)")
    parser.add_argument('--midi_key', type=str, help='e.g. pathetique_full_chunk')
    parser.add_argument('--angle_map', type=str, help='e.g. dissonance, fifths')
    parser.add_argument('--break_method', type=str, help='e.g. centroid, histogram, hybrid, hybrid_split')
    parser.add_argument('--jaccard', type=float, default=0.5, help='Jaccard threshold')
    parser.add_argument('--min_break_mass', type=float, default=0.75, help='Minimum mass to trigger regime break')
    parser.add_argument('--phase2_model', type=str, default='greedy', choices=['greedy', 'beam'], help='Phase 2 voice threading model')
    args = parser.parse_args()

    # Auto-discover all .mid files in midis/ so new chunks work immediately
    midis_dir = os.path.join(os.path.dirname(__file__), 'midis')
    midis = {
        os.path.splitext(f)[0]: os.path.join('midis', f)
        for f in os.listdir(midis_dir) if f.endswith('.mid')
    }

    if args.midi_key and args.angle_map and args.break_method:
        if args.midi_key.endswith('.mid'):
            midi_path = args.midi_key
            base_key = os.path.splitext(os.path.basename(args.midi_key))[0]
        else:
            midi_path = midis.get(args.midi_key)
            base_key = args.midi_key
            if not midi_path:
                print(f"Unknown midi_key: {args.midi_key}")
                sys.exit(1)

        out = f"visualizer/public/etme_{base_key}_{args.angle_map}_{args.break_method}"
        if args.break_method in ('hybrid', 'hybrid_split', 'jaccard_only', 'jaccard_only_split', 'hybrid_v2', 'hybrid_v2_split'):
            out += f"_{args.jaccard}.json"
            export_analysis(midi_path, output_json=out, angle_map=args.angle_map, break_method=args.break_method, jaccard_threshold=args.jaccard, min_break_mass=args.min_break_mass, phase2_model=args.phase2_model)
        else:
            out += ".json"
            export_analysis(midi_path, output_json=out, angle_map=args.angle_map, break_method=args.break_method, min_break_mass=args.min_break_mass, phase2_model=args.phase2_model)
    else:
        out = "visualizer/public/etme_pathetique_full_chunk_dissonance_hybrid_0.5.json"
        export_analysis('midis/pathetique_full_chunk.mid', output_json=out,
                        angle_map='dissonance', break_method='hybrid', jaccard_threshold=0.5)
