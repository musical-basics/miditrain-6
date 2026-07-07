"""
energy_hierarchy.py: partial discharge for the energy accumulator
(Lerdahl's hierarchical tension, made deterministic).

Your Step 3.3 resets E to zero at every freeze, so a half cadence and a
final cadence discharge identically, which flattens exactly the
primary vs secondary distinction Step 4.2 needs. Fix: discharge is
PARTIAL, scaled by cadence strength, and the residue keeps accumulating
across weak landings. Phrase hierarchy then falls out: big residue
release = structural downbeat, small = local landing.

  cadence_strength = clamp01( w_bass  * bass_schema
                            + w_tonic * tonic_snap
                            + w_mag   * magnitude_pct )
  E_after = E_before * (1 - cadence_strength)

bass_schema: 1.0 for a falling fifth / rising fourth into the freeze,
0.5 for stepwise descent, else 0. tonic_snap: normalized angular
approach toward H_tonic on the Phase 1 wheel. magnitude_pct: freeze
magnitude percentile within the piece so far (causal).

Run standalone to annotate a freezes JSON, or port the ~15 lines of
`partial_discharge` into thermodynamic_meter.py, replacing the
`energy_accum = 0` reset in Step 3.3.

Usage:
  python3 energy_hierarchy.py --freezes freezes.json --notes notes.json \
      [--regimes regimes.json --tonic-hue 210] --out annotated.json
"""
import argparse
import bisect
import json

from signals_common import load_notes, bass_line

W_BASS, W_TONIC, W_MAG = 0.45, 0.35, 0.30
PRIMARY_THRESH = 0.55


def clamp01(x):
    return max(0.0, min(1.0, x))


def bass_schema(bass, t, window_ms=180):
    """Score the bass motion INTO the freeze at time t."""
    times = [b["time_ms"] for b in bass]
    i = bisect.bisect_right(times, t + window_ms) - 1
    if i < 1 or abs(bass[i]["time_ms"] - t) > window_ms:
        return 0.0
    dp = bass[i]["pitch"] - bass[i - 1]["pitch"]
    if dp in (-7, 5):
        return 1.0
    if dp in (-5, 7):
        return 0.6
    if dp in (-1, -2):
        return 0.5
    return 0.0


def angular_distance(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def tonic_snap(regimes, t, tonic_hue):
    """Normalized approach toward H_tonic across the freeze."""
    if not regimes or tonic_hue is None:
        return 0.0
    times = [r["time_ms"] for r in regimes]
    i = bisect.bisect_right(times, t) - 1
    if i < 1:
        return 0.0
    d_now = angular_distance(regimes[i].get("hue", 0.0), tonic_hue)
    d_prev = angular_distance(regimes[i - 1].get("hue", 0.0), tonic_hue)
    return clamp01((d_prev - d_now) / 180.0)


def partial_discharge(freezes, bass, regimes=None, tonic_hue=None):
    """Annotate freezes in place with cadence_strength, E_before,
    E_after, level. Expects each freeze to carry time_ms and
    energy_released (your Step 3.5 output); magnitude optional."""
    seen_mags = []
    e_residue = 0.0
    for f in sorted(freezes, key=lambda x: x["time_ms"]):
        t = f["time_ms"]
        mag = f.get("magnitude", f.get("energy_released", 1.0))
        seen_mags.append(mag)
        rank = sorted(seen_mags).index(mag) / max(1, len(seen_mags) - 1) \
            if len(seen_mags) > 1 else 0.5

        cs = clamp01(W_BASS * bass_schema(bass, t)
                     + W_TONIC * tonic_snap(regimes, t, tonic_hue)
                     + W_MAG * rank)

        e_before = e_residue + f.get("energy_released", 0.0)
        e_after = e_before * (1.0 - cs)
        released = e_before - e_after

        f["cadence_strength"] = round(cs, 4)
        f["E_before"] = round(e_before, 4)
        f["E_after"] = round(e_after, 4)
        f["hierarchical_release"] = round(released, 4)
        f["level"] = "primary" if cs >= PRIMARY_THRESH else "secondary"
        e_residue = e_after
    return freezes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freezes", required=True,
                    help="thermodynamic_meter freezing events JSON")
    ap.add_argument("--notes", required=True)
    ap.add_argument("--regimes", default=None,
                    help="Phase 1 regime timeline with hue per event")
    ap.add_argument("--tonic-hue", type=float, default=None,
                    help="H_tonic from Phase 1")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.freezes) as f:
        data = json.load(f)
    freezes = data.get("events", data) if isinstance(data, dict) else data
    notes = load_notes(args.notes)
    regimes = None
    if args.regimes:
        with open(args.regimes) as f:
            rd = json.load(f)
        regimes = rd.get("regimes", rd) if isinstance(rd, dict) else rd

    annotated = partial_discharge(freezes, bass_line(notes),
                                  regimes, args.tonic_hue)
    with open(args.out, "w") as f:
        json.dump({"events": annotated}, f, indent=1)
    prim = sum(1 for x in annotated if x["level"] == "primary")
    print(f"annotated {len(annotated)} freezes: {prim} primary, "
          f"{len(annotated) - prim} secondary -> {args.out}")

    # Primary freezes double as bar-level votes for meter_hypothesis:
    # python3 meter_hypothesis.py --votes freezes=annotated.json ...
    # (load_extra_votes reads time_ms + magnitude automatically)


if __name__ == "__main__":
    main()
