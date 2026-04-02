"""
Run Phase 2 (Voice Threading) on an existing ETME Phase 1 JSON file.
Reads notes + regimes from the JSON, runs VoiceThreader, writes back with voice_tag added.
"""
import json
import sys
import argparse
from particle import Particle
from voice_threader import VoiceThreader


def run_phase2_on_json(input_json, output_json=None):
    if output_json is None:
        output_json = input_json  # overwrite in place

    print(f"Loading ETME JSON: {input_json}")
    with open(input_json, "r") as f:
        data = json.load(f)

    notes = data.get("notes", [])
    regimes = data.get("regimes", [])
    print(f"  {len(notes)} notes, {len(regimes)} regimes")

    # Reconstruct Particle objects from JSON notes
    particles = []
    for n in notes:
        p = Particle(
            pitch=n["pitch"],
            velocity=n["velocity"],
            onset_ms=n["onset"],
            duration_ms=n["duration"]
        )
        particles.append(p)
    particles.sort(key=lambda p: p.onset)

    # Build frame_lookup from regimes (VoiceThreader only needs time + state)
    frame_lookup = []
    for r in regimes:
        frame_lookup.append({
            "time": r["start_time"],
            "hue": r.get("hue", 0),
            "sat": r.get("saturation", 0),
            "v_vec": r.get("v_vec", [0, 0]),
            "state": r["state"],
            "debug": {}
        })

    # Run Phase 2
    print("Running Phase 2: Thermodynamic Voice Threading...")
    threader = VoiceThreader(max_voices=4)
    scored_particles = threader.thread_particles(particles, frame_lookup)

    voice_counts = {}
    for p in scored_particles:
        voice_counts[p.voice_tag] = voice_counts.get(p.voice_tag, 0) + 1
    for tag, count in sorted(voice_counts.items()):
        print(f"  {tag}: {count} notes")

    # Update notes in the JSON with voice_tag and id_score.
    # scored_particles may be reordered by thread_particles, so match by (onset, pitch).
    voice_map = {}
    for p in scored_particles:
        voice_map[(p.onset, p.pitch)] = (p.voice_tag, round(p.id_score, 2))
    for n in notes:
        key = (n["onset"], n["pitch"])
        if key in voice_map:
            n["voice_tag"] = voice_map[key][0]
            n["id_score"] = voice_map[key][1]

    data["notes"] = notes
    data["stats"]["voice_counts"] = voice_counts

    with open(output_json, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Phase 2 written to: {output_json}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Phase 2 on existing ETME JSON")
    parser.add_argument("input_json", help="Path to ETME Phase 1 JSON file")
    parser.add_argument("--output", "-o", help="Output path (default: overwrite input)")
    args = parser.parse_args()
    run_phase2_on_json(args.input_json, args.output)
