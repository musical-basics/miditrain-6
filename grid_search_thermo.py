"""
Grid search over the thermodynamic meter's structural parameters, scored
against corpus downbeat ground truth on the TRAIN split only.

Discipline (docs/benchmarking.md): tune locally here, then the winning
config must pass run_benchmark.py (validation split + held-out Pathétique)
before its values are adopted as defaults in phase3_thermo_meter.py.

Phase 1+2 are frozen at the V3.1 config: ETME exports are built once per
piece, then each grid config only re-runs the (fast) thermo estimator, so
the sweep isolates Phase 3.

Swept parameters (module globals, overridden per config):
  MIN_FREEZE_MS            — minimum freeze duration to count as structural
  VOICE_WEIGHTS["Voice 4"] — bass structural weight
  VOICE_WEIGHTS["Voice 1"] — melody structural weight

Usage:
    python3 grid_search_thermo.py                    # train split
    python3 grid_search_thermo.py --top 10
"""
import argparse
import itertools
import json
import os

import phase3_thermo_meter as thermo_mod
from export_etme_data import export_analysis
from run_corpus_eval import load_v31_config, OUT_DIR

SPLIT_FILE = os.path.join("benchmarks", "corpus_split.json")

GRID = {
    "MIN_FREEZE_MS": [25, 50, 100],
    "V4_WEIGHT": [2.0, 3.0, 4.0],
    "V1_WEIGHT": [1.0, 2.0, 3.0],
}
BASELINE_CFG = {"MIN_FREEZE_MS": 50, "V4_WEIGHT": 4.0, "V1_WEIGHT": 3.0}


def match_events(gt, pred, tol):
    """Identical to score_against_truth.match_events (two-pointer 1:1)."""
    i = j = tp = 0
    while i < len(gt) and j < len(pred):
        d = pred[j] - gt[i]
        if abs(d) <= tol:
            tp += 1; i += 1; j += 1
        elif d < -tol:
            j += 1
        else:
            i += 1
    return tp, len(pred) - tp, len(gt) - tp


def ensure_etme(corpus, pieces, config, out_dir):
    """Build Phase 1+2 exports once per piece (frozen across the sweep)."""
    import contextlib, io
    paths = {}
    for pid in pieces:
        etme = os.path.join(
            out_dir, f"etme_{pid}_{config['angle_map']}_{config['break_method']}_{config['jaccard_threshold']}.json")
        if not os.path.exists(etme):
            print(f"  exporting {pid}...")
            with contextlib.redirect_stdout(io.StringIO()):
                export_analysis(os.path.join(corpus, "midis", f"{pid}.mid"),
                                output_json=etme, **config)
        paths[pid] = etme
    return paths


def apply_cfg(cfg):
    thermo_mod.MIN_FREEZE_MS = cfg["MIN_FREEZE_MS"]
    thermo_mod.VOICE_WEIGHTS["Voice 4"] = cfg["V4_WEIGHT"]
    thermo_mod.VOICE_WEIGHTS["Voice 1"] = cfg["V1_WEIGHT"]


def run_config(cfg, etme_paths, truths, tol):
    """Sum downbeat errors over pieces for one thermo config."""
    import contextlib, io
    apply_cfg(cfg)
    errors = failed = 0
    for pid, etme in etme_paths.items():
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = thermo_mod.ThermodynamicMeterEstimator(etme).estimate(write_json=False)
        except Exception:
            result = None
        meter = (result or {}).get("meter")
        gt = truths[pid]
        if not meter or not meter.get("barlines"):
            # No prediction: every true downbeat is a miss (FN), same as
            # the scorer would count an empty barline list.
            errors += len(gt)
            failed += 1
            continue
        pred = sorted(b["time_ms"] for b in meter["barlines"])
        tp, fp, fn = match_events(gt, pred, tol)
        errors += fp + fn
    return errors, failed


def main():
    ap = argparse.ArgumentParser(description="Grid search thermo meter params on the train split")
    ap.add_argument("--split", default=SPLIT_FILE)
    ap.add_argument("--tol", type=float, default=50.0)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--on-val", action="store_true",
                    help="also evaluate the top config on the validation split")
    args = ap.parse_args()

    with open(args.split) as f:
        split = json.load(f)
    corpus = split["corpus"]
    config = load_v31_config()
    out_dir = os.path.join(OUT_DIR, "gridsearch")
    os.makedirs(out_dir, exist_ok=True)

    truths = {}
    for pid in split["train"] + split["val"]:
        with open(os.path.join(corpus, "groundtruth", f"{pid}.gt.json")) as f:
            gt = json.load(f)
        truths[pid] = sorted(float(t) for t in gt["downbeats_ms"])

    print(f"Building frozen Phase 1+2 exports ({len(split['train'])} train pieces)...")
    train_etme = ensure_etme(corpus, split["train"], config, out_dir)

    combos = [dict(zip(GRID, vals)) for vals in itertools.product(*GRID.values())]
    print(f"Sweeping {len(combos)} thermo configs on train (tol ±{args.tol:g}ms)...")
    results = []
    for cfg in combos:
        errors, failed = run_config(cfg, train_etme, truths, args.tol)
        star = "  <- current defaults" if cfg == BASELINE_CFG else ""
        results.append((errors, failed, cfg))
        print(f"  freeze={cfg['MIN_FREEZE_MS']:<4} V4={cfg['V4_WEIGHT']:<4} "
              f"V1={cfg['V1_WEIGHT']:<4} errors={errors:<5} failed={failed}{star}")

    results.sort(key=lambda r: (r[0], r[1]))
    print(f"\nTOP {args.top} (train):")
    for errors, failed, cfg in results[:args.top]:
        star = "  <- current defaults" if cfg == BASELINE_CFG else ""
        print(f"  errors={errors:<5} failed={failed}  {cfg}{star}")

    baseline_errors = next(e for e, _, c in results if c == BASELINE_CFG)
    best_errors, best_failed, best_cfg = results[0]
    print(f"\nCurrent defaults: {baseline_errors} train errors | "
          f"best: {best_errors} ({best_errors - baseline_errors:+d})")

    if args.on_val and split.get("val"):
        print(f"\nValidation check ({len(split['val'])} pieces):")
        val_etme = ensure_etme(corpus, split["val"], config, out_dir)
        for label, cfg in [("defaults", BASELINE_CFG), ("best", best_cfg)]:
            errors, failed = run_config(cfg, val_etme, truths, args.tol)
            print(f"  {label:<9} {cfg}  val_errors={errors} failed={failed}")

    # restore defaults for anything imported later in this process
    apply_cfg(BASELINE_CFG)


if __name__ == "__main__":
    main()
