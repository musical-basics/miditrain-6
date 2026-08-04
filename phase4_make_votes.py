"""
Phase 4 vote extraction: convert Phase 1 and Phase 3 outputs into the
time-vote JSONs that phase4_meter_bus.py ingests via --votes.

  harmonic votes — TRANSITION SPIKE! regime start times from an ETME
                   export (regimes use `start_time`, which
                   load_extra_votes does not sniff — hence this adapter)
  freeze votes   — freezing_events from a phase3_thermo_*.json (those
                   already carry time_ms + magnitude; this just unwraps
                   the `freezing_events` key)

Usage:
    python3 phase4_make_votes.py <etme_json> [<phase3_thermo_json>] --out-dir <dir>

Writes <dir>/phase4_votes_harmonic_{base}.json and, when a thermo file is
given, <dir>/phase4_votes_freezes_{base}.json. Prints the paths.
"""
import argparse
import json
import os


def spike_votes(etme_path):
    with open(etme_path) as f:
        data = json.load(f)
    return [{"time_ms": r["start_time"], "weight": 1.0}
            for r in data.get("regimes", [])
            if r.get("state") == "TRANSITION SPIKE!"]


def freeze_votes(thermo_path):
    with open(thermo_path) as f:
        data = json.load(f)
    return [{"time_ms": e["time_ms"], "weight": e.get("magnitude", 1.0)}
            for e in data.get("freezing_events", [])]


def salience_votes(etme_path, min_weight=0.05):
    """
    DENSE harmonic evidence: Phase 1's pre-threshold salience. Every
    keyframe's angular divergence vs the current anchor (debug.diff,
    0-180°) is already persisted per note in the ETME export — this
    extracts one vote per keyframe, weight = diff/180. Unlike the ~30
    binary spikes, this is the detector's continuous evidence (~1 vote
    per onset event), the vote-density fix motivated by the inert
    channel-weight sweep.
    """
    with open(etme_path) as f:
        data = json.load(f)
    by_onset = {}
    for n in data.get("notes", []):
        d = n.get("debug", {}).get("diff", 0) or 0
        if n["onset"] not in by_onset:
            by_onset[n["onset"]] = d
    return [{"time_ms": t, "weight": d / 180.0}
            for t, d in sorted(by_onset.items())
            if d / 180.0 >= min_weight]


def viscosity_votes(thermo_data):
    """
    DENSE thermodynamic evidence: positive viscosity jumps (Δη+) from the
    thermo grid_sample (100ms spacing) — the raw signal freezes are
    thresholded from. Accepts a loaded thermo result dict or a file path.
    """
    if isinstance(thermo_data, str):
        with open(thermo_data) as f:
            thermo_data = json.load(f)
    grid = (thermo_data or {}).get("grid_sample", [])
    votes = []
    for a, b in zip(grid, grid[1:]):
        d_eta = b["eta"] - a["eta"]
        if d_eta > 0:
            votes.append({"time_ms": b["t_ms"], "weight": d_eta})
    if not votes:
        return []
    floor = 0.01 * max(v["weight"] for v in votes)
    return [v for v in votes if v["weight"] >= floor]


def base_key_of(etme_path):
    base = os.path.basename(etme_path).replace("etme_", "").replace(".json", "")
    for am in ("dissonance", "fifths"):
        if f"_{am}" in base:
            return base.split(f"_{am}")[0]
    return base


def main():
    ap = argparse.ArgumentParser(description="Extract Phase 4 vote channels")
    ap.add_argument("etme")
    ap.add_argument("thermo", nargs="?", default=None)
    ap.add_argument("--out-dir", default=None,
                    help="default: same directory as the ETME file")
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.dirname(args.etme) or "."
    base = base_key_of(args.etme)

    h_path = os.path.join(out_dir, f"phase4_votes_harmonic_{base}.json")
    votes = spike_votes(args.etme)
    with open(h_path, "w") as f:
        json.dump(votes, f)
    print(f"{len(votes)} harmonic votes -> {h_path}")

    s_path = os.path.join(out_dir, f"phase4_votes_salience_{base}.json")
    votes = salience_votes(args.etme)
    with open(s_path, "w") as f:
        json.dump(votes, f)
    print(f"{len(votes)} salience votes -> {s_path}")

    if args.thermo and os.path.exists(args.thermo):
        f_path = os.path.join(out_dir, f"phase4_votes_freezes_{base}.json")
        votes = freeze_votes(args.thermo)
        with open(f_path, "w") as f:
            json.dump(votes, f)
        print(f"{len(votes)} freeze votes -> {f_path}")

        v_path = os.path.join(out_dir, f"phase4_votes_visc_{base}.json")
        votes = viscosity_votes(args.thermo)
        with open(v_path, "w") as f:
            json.dump(votes, f)
        print(f"{len(votes)} viscosity votes -> {v_path}")


if __name__ == "__main__":
    main()
