"""
Meter diagnostic producer: why did each engine choose the grid it chose?

96% of the Phase 4 bus's folk-song error mass (2026-07-08 baseline) comes
from ONE failure mode — locking onto the wrong metrical LEVEL (measure_ms
off by an integer or half ratio), not from phase or jitter. This script
emits, per corpus piece, everything a human needs to SEE that:

  - the notes (piano roll),
  - ground-truth barlines vs every engine's barlines on the same timeline,
  - the ratio GT_measure_ms / predicted_measure_ms, which classifies the
    failure (6.00 = picked the beat; 0.50 = picked the hypermeasure;
    1.00 = correct level, so any error is phase/jitter),
  - the bus's full period-score curve with the prior envelope drawn
    behind it — the evidence that produced the choice.

Nothing here re-implements the engines: grids come from the same calls
run_corpus_eval uses, and the period curve is recomputed with
phase4_meter_bus's own search functions at production weights.

Usage:
    python3 run_meter_diag.py                       # whole val split
    python3 run_meter_diag.py --split-key train
    python3 run_meter_diag.py --pieces essenFolksong_altdeu10_op003
    python3 run_meter_diag.py --name myrun

Writes visualizer/public/meterdiag/<name>/{manifest.json, <piece>.json}
and prints the localhost URL.
"""
import argparse
import contextlib
import io
import json
import math
import os
import shutil

import phase4_meter_bus as bus
import parallelism as par_mod
from signals_common import load_notes
from phase4_make_votes import spike_votes
from phase3_thermo_meter import ThermodynamicMeterEstimator
from phase3_spike_meter import MacroMeterEstimator
from grid_search_thermo import match_events, ensure_etme
from make_corpus_split import tier_of
from run_corpus_eval import load_v31_config, OUT_DIR

SPLIT_FILE = os.path.join("benchmarks", "corpus_split.json")
OUT_ROOT = os.path.join("visualizer", "public", "meterdiag")
TOL_MS = 50.0
LEVEL_TOL = 0.06          # |ratio-1| within this = "correct level"
MAX_ROLL_NOTES = 4000     # cap payload for very long pieces

ALL_INTERNAL = ["onset_pulse", "povel_essens", "agogic", "lbdm",
                "velocity", "surprisal", "attraction", "gap_fill",
                "bass_cadence"]


def snap_ratio(r):
    """Name the hierarchy relationship, or None if it is not a clean one."""
    for label, val in [("beat/6", 6.0), ("beat/4", 4.0), ("beat/3", 3.0),
                       ("half-measure", 2.0), ("dotted", 1.5),
                       ("correct", 1.0), ("2-bar hyper", 0.5),
                       ("3-bar hyper", 1 / 3), ("1.5-bar", 2 / 3)]:
        if abs(r - val) <= 0.06 * max(val, 1.0):
            return label
    return None


def period_curve(channels, pvotes, weights, pmin=240.0, pmax=1600.0):
    """
    Recompute the bus's tactus objective across ALL candidate periods
    (production returns only the top 6). Mirrors search_tactus exactly,
    and additionally reports the prior envelope separately so the page
    can show how much of the score shape is evidence vs prior.
    """
    periods = []
    p = pmin
    step = 2 ** (1 / 36)
    while p <= pmax:
        periods.append(p)
        p *= step

    total_par = sum(v["weight"] for v in pvotes) or 1.0
    wpar = weights.get("parallelism", 1.0)
    rows = []
    for P in periods:
        tol = max(15.0, 0.04 * P)
        combined = []
        for name, votes in channels.items():
            w = weights.get(name, 1.0)
            if w <= 0 or not votes:
                continue
            for v in votes:
                combined.append({"time_ms": v["time_ms"],
                                 "weight": v["weight"] * w})
        pmass, anchors = bus.par_support(pvotes, P)
        for a in anchors:
            combined.append({"time_ms": a["time_ms"],
                             "weight": a["weight"] * wpar})
        mass, phase = bus.fold_best(combined, P, tol)
        prior = bus.log_gauss_prior(P, weights["tactus_prior_center_ms"],
                                    weights["tactus_prior_sigma_oct"])
        evidence = mass * (1.0 + wpar * (pmass / total_par))
        rows.append({"period_ms": round(P, 1),
                     "score": round(evidence * prior, 4),
                     "evidence": round(evidence, 4),
                     "prior": round(prior, 4),
                     "phase_ms": round(phase, 1)})
    return rows


def measure_curve(channels, pvotes, weights, P, phi_t, t0, t1):
    """Measure-level objective per grouping G, mirroring search_measure."""
    mw = weights["measure"]
    total_par = sum(v["weight"] for v in pvotes) or 1.0
    out = []
    for G in (2, 3, 4):
        M = G * P
        prior = bus.log_gauss_prior(M, weights["measure_prior_center_ms"],
                                    weights["measure_prior_sigma_oct"])
        pmass, _ = bus.par_support(pvotes, M, max_mult=2)
        pfrac = pmass / total_par
        best = None
        for k in range(G):
            phi = (phi_t + k * P) % M
            tol = max(25.0, 0.03 * M)
            s = 0.0
            for name, votes in channels.items():
                w = weights.get(name, 1.0) * mw.get(
                    name, mw.get("extra_default", 1.0)
                    if name.startswith("extra:") else 0.5)
                if w <= 0 or not votes:
                    continue
                s += w * bus.grid_mass_per_line(votes, M, phi, t0, t1, tol)
            s *= (1.0 + mw.get("parallelism", 1.0) * pfrac)
            s *= prior
            if best is None or s > best[0]:
                best = (s, phi)
        out.append({"grouping": G, "measure_ms": round(M, 1),
                    "score": round(best[0], 4), "phase_ms": round(best[1], 1),
                    "prior": round(prior, 4)})
    return out


def engine_grids(etme_path, out_dir, pid):
    """Run all three meter engines; return {engine: {meter, barlines}}."""
    silence = contextlib.redirect_stdout(io.StringIO())
    grids = {}

    # Phase 3 spike
    try:
        with silence:
            spike = MacroMeterEstimator(etme_path).estimate(write_json=False)
        if spike and spike.get("barlines"):
            grids["spike"] = {
                "measure_ms": spike["measure_ms"],
                "time_signature": spike["time_signature"],
                "tactus_ms": spike.get("tactus_ms"),
                "barlines": [b["time_ms"] for b in spike["barlines"]],
            }
    except Exception as e:
        grids["spike"] = {"error": str(e)[:200]}

    # Phase 3 thermo
    thermo = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            thermo = ThermodynamicMeterEstimator(etme_path).estimate(write_json=False)
        m = (thermo or {}).get("meter")
        if m and m.get("barlines"):
            grids["thermo"] = {
                "measure_ms": m["measure_ms"],
                "time_signature": m["time_signature"],
                "tactus_ms": m.get("tactus_ms"),
                "barlines": [b["time_ms"] for b in m["barlines"]],
            }
        else:
            grids["thermo"] = {"error": "no meter (insufficient freezing events)"}
    except Exception as e:
        grids["thermo"] = {"error": str(e)[:200]}

    return grids, thermo


def bus_grid_and_curves(etme_path, thermo):
    """Run the bus at production weights and capture its decision surface."""
    notes = load_notes(etme_path)
    weights = json.loads(json.dumps(bus.DEFAULT_WEIGHTS))

    channels = bus.collect_channels(notes, ALL_INTERNAL, None, None)
    channels["extra:harmonic"] = spike_votes(etme_path)
    if thermo and thermo.get("freezing_events"):
        channels["extra:freezes"] = [
            {"time_ms": e["time_ms"], "weight": e.get("magnitude", 1.0)}
            for e in thermo["freezing_events"]]
    for key in ("extra:harmonic", "extra:freezes"):
        if key in channels:
            weights.setdefault(key, weights["extra_default"])

    vote_counts = {k: len(v) for k, v in channels.items()}
    if weights.get("channel_norm"):
        channels = bus.normalize_channels(channels)

    pvotes = par_mod.period_votes(notes)
    t0 = notes[0]["onset_ms"]
    t1 = max(n["onset_ms"] for n in notes)

    P, phi_t, _ = bus.search_tactus(channels, pvotes, weights, 240.0, 1600.0)
    G, phi_m = bus.search_measure(channels, pvotes, weights, P, phi_t, t0, t1)
    is_comp = bus.compound_test(notes, P)
    ts, M = bus.derive_ts(G, P, is_comp)

    barlines = []
    k = 0
    t = phi_m
    while t < t0 - 30:
        k += 1
        t = phi_m + k * M
    while t <= t1 + 30:
        barlines.append(int(round(t)))
        k += 1
        t = phi_m + k * M

    grid = {"measure_ms": int(round(M)), "time_signature": ts,
            "tactus_ms": int(round(P)), "grouping": G, "compound": is_comp,
            "tactus_phase_ms": round(phi_t, 1),
            "measure_phase_ms": round(phi_m, 1),
            "barlines": barlines, "vote_counts": vote_counts}
    curves = {
        "tactus": period_curve(channels, pvotes, weights),
        "measure": measure_curve(channels, pvotes, weights, P, phi_t, t0, t1),
        "prior": {"tactus_center_ms": weights["tactus_prior_center_ms"],
                  "tactus_sigma_oct": weights["tactus_prior_sigma_oct"],
                  "measure_center_ms": weights["measure_prior_center_ms"],
                  "measure_sigma_oct": weights["measure_prior_sigma_oct"],
                  "search_min_ms": 240.0, "search_max_ms": 1600.0},
    }
    return grid, curves, notes


def score_grid(gt_downbeats, barlines):
    tp, fp, fn = match_events(gt_downbeats, sorted(barlines), TOL_MS)
    p = tp / max(1, tp + fp)
    r = tp / max(1, tp + fn)
    f1 = 2 * p * r / max(1e-9, p + r)
    return {"tp": tp, "fp": fp, "fn": fn, "errors": fp + fn,
            "precision": round(p, 4), "recall": round(r, 4),
            "f1": round(f1, 4)}


def main():
    ap = argparse.ArgumentParser(description="Produce meter-hierarchy diagnostic data")
    ap.add_argument("--split", default=SPLIT_FILE)
    ap.add_argument("--split-key", default="val", choices=["val", "train", "both"])
    ap.add_argument("--pieces", default=None, help="comma-separated ids")
    ap.add_argument("--name", default=None, help="run name (default: split key)")
    args = ap.parse_args()

    with open(args.split) as f:
        split = json.load(f)
    corpus = split["corpus"]
    pieces = (split["train"] + split["val"] if args.split_key == "both"
              else split[args.split_key])
    if args.pieces:
        wanted = set(args.pieces.split(","))
        pieces = [p for p in pieces if p in wanted]
    if not pieces:
        raise SystemExit("no pieces selected")

    name = args.name or args.split_key
    out_dir = os.path.join(OUT_ROOT, name)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    config = load_v31_config()
    etme_dir = os.path.join(OUT_DIR, "gridsearch")
    os.makedirs(etme_dir, exist_ok=True)
    print(f"Preparing Phase 1+2 exports for {len(pieces)} pieces...")
    etme_paths = ensure_etme(corpus, pieces, config, etme_dir)

    index = []
    for i, pid in enumerate(pieces, 1):
        print(f"[{i}/{len(pieces)}] {pid}")
        with open(os.path.join(corpus, "groundtruth", f"{pid}.gt.json")) as f:
            gt = json.load(f)
        gt_downbeats = sorted(float(t) for t in gt["downbeats_ms"])
        gt_meter = gt["meter_map"][0]
        etme = etme_paths[pid]

        grids, thermo = engine_grids(etme, out_dir, pid)
        bus_grid, curves, notes = bus_grid_and_curves(etme, thermo)
        grids["bus"] = bus_grid

        engines = {}
        for eng, g in grids.items():
            if "error" in g:
                engines[eng] = {"error": g["error"], "errors": len(gt_downbeats),
                                "ratio": None, "level": None}
                continue
            sc = score_grid(gt_downbeats, g["barlines"])
            ratio = (gt_meter["measure_ms"] / g["measure_ms"]
                     if g["measure_ms"] else None)
            engines[eng] = {
                **{k: v for k, v in g.items() if k != "barlines"},
                **sc,
                "barlines": g["barlines"],
                "ratio": round(ratio, 3) if ratio else None,
                "level": snap_ratio(ratio) if ratio else None,
                "correct_level": bool(ratio and abs(ratio - 1.0) <= LEVEL_TOL),
            }

        roll = [{"o": int(n["onset_ms"]), "d": int(n["duration_ms"]),
                 "p": n["pitch"], "v": n["velocity"]}
                for n in notes[:MAX_ROLL_NOTES]]

        piece_doc = {
            "id": pid, "tier": tier_of(pid),
            "ground_truth": {
                "time_signature": gt_meter["time_signature"],
                "measure_ms": gt_meter["measure_ms"],
                "beat_ms": gt_meter["beat_ms"],
                "beats_per_measure": gt_meter["beats_per_measure"],
                "anacrusis_ms": gt.get("anacrusis_ms", 0),
                "downbeats": [int(t) for t in gt_downbeats],
                "n_notes": gt["stats"]["n_notes"],
                "meter_changes": len(gt["meter_map"]) > 1,
            },
            "engines": engines,
            "curves": curves,
            "notes": roll,
            "notes_truncated": len(notes) > MAX_ROLL_NOTES,
        }
        with open(os.path.join(out_dir, f"{pid}.json"), "w") as f:
            json.dump(piece_doc, f)

        index.append({
            "id": pid, "tier": piece_doc["tier"],
            "gt_ts": gt_meter["time_signature"],
            "gt_measure_ms": gt_meter["measure_ms"],
            "n_downbeats": len(gt_downbeats),
            "n_notes": gt["stats"]["n_notes"],
            "engines": {e: {"errors": d["errors"], "f1": d.get("f1"),
                            "ratio": d.get("ratio"), "level": d.get("level"),
                            "correct_level": d.get("correct_level", False),
                            "ts": d.get("time_signature"),
                            "measure_ms": d.get("measure_ms")}
                        for e, d in engines.items()},
        })

    # Failure-mode rollup: the headline this page exists to make visible.
    summary = {}
    for eng in ("bus", "thermo", "spike"):
        tot = lvl = phase = 0
        n_ok = n_bad = n_fail = 0
        for row in index:
            d = row["engines"].get(eng)
            if not d:
                continue
            tot += d["errors"]
            if d["ratio"] is None:
                n_fail += 1
                lvl += d["errors"]
            elif d["correct_level"]:
                n_ok += 1
                phase += d["errors"]
            else:
                n_bad += 1
                lvl += d["errors"]
        summary[eng] = {
            "total_errors": tot,
            "errors_from_wrong_level": lvl,
            "errors_from_phase_or_jitter": phase,
            "pct_wrong_level": round(100 * lvl / max(1, tot), 1),
            "pieces_correct_level": n_ok, "pieces_wrong_level": n_bad,
            "pieces_no_prediction": n_fail,
        }

    manifest = {
        "name": name, "split_key": args.split_key, "corpus": corpus,
        "tolerance_ms": TOL_MS, "level_tolerance": LEVEL_TOL,
        "n_pieces": len(index), "config": config,
        "bus_weights": {k: v for k, v in bus.DEFAULT_WEIGHTS.items()
                        if k != "measure"},
        "summary": summary, "pieces": index,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)

    print(f"\nWrote {len(index)} pieces to {out_dir}")
    for eng, s in summary.items():
        print(f"  {eng:<7} errors={s['total_errors']:<5} "
              f"wrong-level={s['errors_from_wrong_level']} "
              f"({s['pct_wrong_level']}%)  "
              f"pieces ok/bad/none={s['pieces_correct_level']}/"
              f"{s['pieces_wrong_level']}/{s['pieces_no_prediction']}")
    print(f"\nhttp://localhost:3000/meter?run={name}")


if __name__ == "__main__":
    main()
