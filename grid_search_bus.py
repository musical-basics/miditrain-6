"""
Grid search over the Phase 4 meter-bus weights, scored against corpus
downbeat ground truth on the TRAIN split only.

The scaffold doc left the default weights deliberately rough "so the
corpus decides" — this is the corpus deciding. Swept dimensions target
the measured failure modes:

  EXTRA_W    — tactus-level weight of the external channels (Phase 1
               spikes + Phase 3 freezes): the harmonic half of the
               argument the rhythm-only baseline lacks.
  EXTRA_MW   — measure-level multiplier for the external channels
               (bar disambiguation is where harmony matters most).
  BASS_SCALE — scales bass_cadence at both levels: the doc measured
               chorale fifth-arrivals peaking on the PRE-cadential beat,
               so down-weighting may stop the one-beat-early lock.

Phase 1+2+3 are frozen: ETME exports and vote channels are built once
per piece; each config only re-runs the (period, phase) search.

Discipline (docs/benchmarking.md): winner must pass run_benchmark.py
before its values are adopted into phase4_meter_bus.py DEFAULT_WEIGHTS.

Usage:
    python3 grid_search_bus.py --on-val
"""
import argparse
import contextlib
import copy
import io
import itertools
import json
import os

import phase4_meter_bus as bus
import parallelism as par_mod
from signals_common import load_notes
from phase4_make_votes import spike_votes, salience_votes, viscosity_votes
from phase3_thermo_meter import ThermodynamicMeterEstimator
from grid_search_thermo import match_events, ensure_etme
from run_corpus_eval import load_v31_config, OUT_DIR

SPLIT_FILE = os.path.join("benchmarks", "corpus_split.json")

GRID = {
    # Widened DOWNWARD after channel_norm adoption: normalized sparse
    # channels carry full unit mass, so the extras' old floor (1.8) is
    # likely too heavy — the soft sweep's inline run at extras=1.0
    # scored 872 val vs production's 945 at 1.8.
    "EXTRA_W": [0.5, 1.0, 1.8, 3.0],
    "EXTRA_MW": [1.0, 2.2, 4.0],
    "BASS_SCALE": [0.5, 1.0],
}
# BASS_SCALE is relative to the (already-halved) defaults adopted 2026-07-08
BASELINE_CFG = {"EXTRA_W": 1.8, "EXTRA_MW": 1.0, "BASS_SCALE": 1.0}

# Structural sweep (--structural): the channel-weight sweep proved inert
# (all 18 configs identical on train — external votes are too sparse to
# move the argmax at any scale). The measured failures are structural:
# archaic meters (4/2, 4/1) have 2000ms+ tactus, outside MAX_PERIOD and
# crushed by the 600ms-centered tactus prior.
STRUCTURAL_GRID = {
    "MAX_PERIOD": [1600.0, 3200.0],
    "TACTUS_SIGMA": [0.55, 0.9],
    "MEASURE_SIGMA": [1.0, 1.4],
}
STRUCTURAL_BASELINE = {"MAX_PERIOD": 1600.0, "TACTUS_SIGMA": 0.9,
                       "MEASURE_SIGMA": 1.4}

# Soft-evidence sweep (--soft): dense pre-threshold channels (Phase 1
# per-keyframe salience, thermo Δη+) × channel-mass normalization — the
# two halves of "export soft evidence, normalize before weighting", the
# fix for the measured vote-density problem.
SOFT_GRID = {
    "NORM": [0, 1],
    "DENSE": ["none", "salience", "visc", "both"],
}
SOFT_BASELINE = {"NORM": 1, "DENSE": "none"}

# Dense-weight sweep (--dense): the soft sweep ran dense channels at
# extra_default (1.8) where they slightly hurt under normalization; with
# unit channel mass the weight IS the influence, so try light weights.
DENSE_GRID = {
    "DENSE": ["none", "salience", "visc", "both"],
    "DENSE_W": [0.2, 0.5, 1.0, 1.8],
}
DENSE_BASELINE = {"DENSE": "none", "DENSE_W": 0.2}  # W irrelevant for none

ALL_INTERNAL = ["onset_pulse", "povel_essens", "agogic", "lbdm",
                "velocity", "surprisal", "attraction", "gap_fill",
                "bass_cadence"]


def prep_piece(etme_path):
    """Weight-independent per-piece inputs: notes, channels, period votes,
    plus the dense soft-evidence channels kept separate so sweep configs
    can include or exclude them."""
    notes = load_notes(etme_path)
    channels = bus.collect_channels(notes, ALL_INTERNAL, None, None)
    channels["extra:harmonic"] = spike_votes(etme_path)
    dense = {"extra:salience": salience_votes(etme_path)}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            thermo = ThermodynamicMeterEstimator(etme_path).estimate(write_json=False)
        if thermo and thermo.get("freezing_events"):
            channels["extra:freezes"] = [
                {"time_ms": e["time_ms"], "weight": e.get("magnitude", 1.0)}
                for e in thermo["freezing_events"]]
        if thermo:
            dense["extra:visc"] = viscosity_votes(thermo)
    except Exception:
        pass
    pvotes = par_mod.period_votes(notes)
    return {"notes": notes, "channels": channels, "pvotes": pvotes,
            "dense": dense}


def make_weights(cfg):
    w = copy.deepcopy(bus.DEFAULT_WEIGHTS)
    if "EXTRA_W" in cfg:
        w["extra:harmonic"] = cfg["EXTRA_W"]
        w["extra:freezes"] = cfg["EXTRA_W"]
        w["measure"]["extra_default"] = cfg["EXTRA_MW"]
        w["bass_cadence"] *= cfg["BASS_SCALE"]
        w["measure"]["bass_cadence"] *= cfg["BASS_SCALE"]
    if "TACTUS_SIGMA" in cfg:
        w["tactus_prior_sigma_oct"] = cfg["TACTUS_SIGMA"]
        w["measure_prior_sigma_oct"] = cfg["MEASURE_SIGMA"]
    return w


def bus_predict(prepped, weights, max_period=1600.0):
    """Replicates phase4_meter_bus.main()'s search + barline projection."""
    notes = prepped["notes"]
    t0 = notes[0]["onset_ms"]
    t1 = max(n["onset_ms"] for n in notes)
    P, phi_t, _ = bus.search_tactus(prepped["channels"], prepped["pvotes"],
                                    weights, 240.0, max_period)
    G, phi_m = bus.search_measure(prepped["channels"], prepped["pvotes"],
                                  weights, P, phi_t, t0, t1)
    is_comp = bus.compound_test(notes, P)
    _, M = bus.derive_ts(G, P, is_comp)
    barlines = []
    k = 0
    t = phi_m
    while t < t0 - 30:
        k += 1
        t = phi_m + k * M
    while t <= t1 + 30:
        barlines.append(t)
        k += 1
        t = phi_m + k * M
    return barlines


def run_config(cfg, prepped_pieces, truths, tol):
    weights = make_weights(cfg)
    max_period = cfg.get("MAX_PERIOD", 1600.0)
    dense_sel = cfg.get("DENSE", "none")
    # Match the production CLI: external channels default to extra_default
    # unless the config sets them (the CLI does the same setdefault).
    for key in ("extra:harmonic", "extra:freezes"):
        weights.setdefault(key, weights["extra_default"])
    errors = 0
    for pid, prepped in prepped_pieces.items():
        channels = dict(prepped["channels"])
        for key, votes in prepped.get("dense", {}).items():
            short = key.split(":")[1]
            if votes and dense_sel in (short, "both"):
                channels[key] = votes
                if "DENSE_W" in cfg:
                    weights[key] = cfg["DENSE_W"]
                else:
                    weights.setdefault(key, weights["extra_default"])
        # Respect the production default (weights["channel_norm"]) unless
        # the config explicitly overrides it via a NORM key.
        if cfg.get("NORM", weights.get("channel_norm")):
            channels = bus.normalize_channels(channels)
        piece = dict(prepped, channels=channels)
        try:
            pred = bus_predict(piece, weights, max_period)
        except Exception:
            pred = []
        gt = truths[pid]
        if not pred:
            errors += len(gt)
            continue
        tp, fp, fn = match_events(gt, sorted(pred), tol)
        errors += fp + fn
    return errors


def main():
    ap = argparse.ArgumentParser(description="Grid search Phase 4 bus weights on the train split")
    ap.add_argument("--split", default=SPLIT_FILE)
    ap.add_argument("--tol", type=float, default=50.0)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--on-val", action="store_true")
    ap.add_argument("--structural", action="store_true",
                    help="sweep period range + prior widths instead of channel weights")
    ap.add_argument("--soft", action="store_true",
                    help="sweep dense soft-evidence channels × channel normalization")
    ap.add_argument("--dense", action="store_true",
                    help="sweep dense-channel weights under the production norm")
    args = ap.parse_args()

    grid, baseline_cfg = ((DENSE_GRID, DENSE_BASELINE) if args.dense
                          else (SOFT_GRID, SOFT_BASELINE) if args.soft
                          else (STRUCTURAL_GRID, STRUCTURAL_BASELINE)
                          if args.structural else (GRID, BASELINE_CFG))

    with open(args.split) as f:
        split = json.load(f)
    config = load_v31_config()
    out_dir = os.path.join(OUT_DIR, "gridsearch")
    os.makedirs(out_dir, exist_ok=True)

    truths = {}
    for pid in split["train"] + split["val"]:
        with open(os.path.join(split["corpus"], "groundtruth", f"{pid}.gt.json")) as f:
            gt = json.load(f)
        truths[pid] = sorted(float(t) for t in gt["downbeats_ms"])

    print(f"Preparing frozen inputs for {len(split['train'])} train pieces...")
    train_etme = ensure_etme(split["corpus"], split["train"], config, out_dir)
    train_prep = {pid: prep_piece(p) for pid, p in train_etme.items()}

    combos = [dict(zip(grid, vals)) for vals in itertools.product(*grid.values())]
    print(f"Sweeping {len(combos)} bus weight configs on train (tol ±{args.tol:g}ms)...")
    results = []
    for cfg in combos:
        errors = run_config(cfg, train_prep, truths, args.tol)
        star = "  <- current defaults" if cfg == baseline_cfg else ""
        results.append((errors, cfg))
        print(f"  {cfg} errors={errors}{star}")

    results.sort(key=lambda r: r[0])
    print(f"\nTOP {args.top} (train):")
    for errors, cfg in results[:args.top]:
        star = "  <- current defaults" if cfg == baseline_cfg else ""
        print(f"  errors={errors:<5} {cfg}{star}")

    baseline_errors = next(e for e, c in results if c == baseline_cfg)
    best_errors, best_cfg = results[0]
    print(f"\nCurrent defaults: {baseline_errors} train errors | "
          f"best: {best_errors} ({best_errors - baseline_errors:+d})")

    if args.on_val and split.get("val"):
        print(f"\nValidation check ({len(split['val'])} pieces):")
        val_etme = ensure_etme(split["corpus"], split["val"], config, out_dir)
        val_prep = {pid: prep_piece(p) for pid, p in val_etme.items()}
        for label, cfg in [("defaults", baseline_cfg), ("best", best_cfg)]:
            errors = run_config(cfg, val_prep, truths, args.tol)
            print(f"  {label:<9} {cfg}  val_errors={errors}")


if __name__ == "__main__":
    main()
