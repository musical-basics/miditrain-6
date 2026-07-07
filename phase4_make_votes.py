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

    if args.thermo and os.path.exists(args.thermo):
        f_path = os.path.join(out_dir, f"phase4_votes_freezes_{base}.json")
        votes = freeze_votes(args.thermo)
        with open(f_path, "w") as f:
            json.dump(votes, f)
        print(f"{len(votes)} freeze votes -> {f_path}")


if __name__ == "__main__":
    main()
