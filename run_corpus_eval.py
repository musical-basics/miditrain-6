"""
Corpus evaluation runner: the measured fight.

Runs the full pipeline (Phase 1+2 via export_analysis, then BOTH Phase 3
meter engines) over every piece in a corpus manifest, and scores each
engine's barlines against the ground truth with score_against_truth.py.
Also scores Phase 2 voice assignments on polyphonic pieces (SATB chorales
are real voice ground truth).

Config comes from final_optimized_configs.json (V3.1 rank-1) so corpus
numbers are comparable to the Pathétique benchmark. Tolerance default is
50ms (corpus MIDIs are quantized, so tighter than the 100ms marker
tolerance).

Usage:
    python3 run_corpus_eval.py                                # demo corpus
    python3 run_corpus_eval.py --pieces bach_bwv66.6,chorale_000
    python3 run_corpus_eval.py --phase2_model beam --tag-suffix _beam
    python3 run_corpus_eval.py --relaxation --tag-suffix _relax

Outputs land in corpus_runs/ (gitignored): per-piece pipeline JSONs plus
runs.csv with one row per (tag, piece). Summary table on stdout minimizes
errors = FP + FN, same convention as optimize_params.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys

from export_etme_data import export_analysis
from phase3_spike_meter import MacroMeterEstimator
from phase3_thermo_meter import ThermodynamicMeterEstimator

CORPUS_DIR = os.path.join("corpus files", "corpus_demo")
SCORER = os.path.join("corpus files", "score_against_truth.py")
CONFIGS_FILE = "final_optimized_configs.json"
OUT_DIR = "corpus_runs"


def load_v31_config():
    """Rank-1 V3.1 config → export_analysis kwargs."""
    with open(CONFIGS_FILE) as f:
        cfg = json.load(f)["configs"][0]
    return {
        "angle_map": cfg["angle_map"],
        "break_method": cfg["break_method"],
        "break_angle": cfg["break_angle"],
        "merge_angle": cfg["merge_angle"],
        "min_break_mass": cfg["min_break_mass"],
        "debounce_ms": cfg["debounce_ms"],
        "jaccard_threshold": cfg["jaccard_threshold"],
        "min_resolution_ratio": cfg["min_resolution_ratio"],
        "max_anchor_size": cfg["max_anchor_size"],
        "maturity_grace_ms": cfg["maturity_grace_ms"],
        "bass_multiplier": cfg["bass_multiplier"],
    }


def read_manifest(corpus_dir, skip_free_meter=True):
    rows = []
    with open(os.path.join(corpus_dir, "manifest.csv"), newline="") as f:
        for row in csv.DictReader(f):
            row["free_meter"] = "?" in row.get("meters", "")
            if skip_free_meter and row["free_meter"]:
                continue
            rows.append(row)
    return rows


def run_scorer(truth_path, pred_path, tol, tag, csv_path):
    """Invoke score_against_truth.py; return its RESULT line dict (or None)."""
    proc = subprocess.run(
        [sys.executable, SCORER, "--truth", truth_path, "--pred", pred_path,
         "--tol", str(tol), "--tag", tag, "--csv", csv_path],
        capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.returncode != 0:
        print(f"  scorer failed for {pred_path}: {proc.stderr.strip()[:200]}")
        return None
    m = re.search(r"^RESULT (.*)$", proc.stdout, re.MULTILINE)
    if not m:
        return None
    out = {}
    for kv in m.group(1).split():
        k, _, v = kv.partition("=")
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description="Run pipeline over corpus and score both meter engines")
    ap.add_argument("--corpus", default=CORPUS_DIR)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--tol", type=float, default=50.0)
    ap.add_argument("--pieces", default=None, help="comma-separated ids (default: all metered pieces)")
    ap.add_argument("--phase2_model", default="greedy", choices=["greedy", "beam"])
    ap.add_argument("--relaxation", action="store_true")
    ap.add_argument("--tag-suffix", default="", help="appended to tags, e.g. _beam / _relax")
    ap.add_argument("--include-free-meter", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "runs.csv")
    config = load_v31_config()
    rows = read_manifest(args.corpus, skip_free_meter=not args.include_free_meter)
    if args.pieces:
        wanted = set(args.pieces.split(","))
        rows = [r for r in rows if r["id"] in wanted]
    if not rows:
        print("No pieces selected."); sys.exit(1)

    print(f"Corpus eval: {len(rows)} pieces | P2={args.phase2_model} | "
          f"relaxation={args.relaxation} | tol=±{args.tol:g}ms | V3.1 config")

    totals = {}   # tag → {"errors": int, "pieces": int, "failed": int}
    voice_acc = {}  # tag → [accuracies]

    for row in rows:
        pid = row["id"]
        midi = os.path.join(args.corpus, "midis", f"{pid}.mid")
        truth = os.path.join(args.corpus, "groundtruth", f"{pid}.gt.json")
        etme_path = os.path.join(
            args.out, f"etme_{pid}_{config['angle_map']}_{config['break_method']}_{config['jaccard_threshold']}.json")

        print(f"\n########## {pid} ##########")
        try:
            export_analysis(midi, output_json=etme_path,
                            phase2_model=args.phase2_model,
                            relaxation=args.relaxation, **config)
        except Exception as e:
            print(f"  PIPELINE FAILED (export): {e}")
            for tag in ("spike", "thermo"):
                t = totals.setdefault(tag + args.tag_suffix, {"errors": 0, "pieces": 0, "failed": 0})
                t["failed"] += 1
            continue

        # ── Phase 3: both meter engines ──────────────────────────────
        preds = {}
        try:
            MacroMeterEstimator(etme_path).estimate(write_json=True)
            preds["spike"] = os.path.join(args.out, f"phase3_grid_{pid}.json")
        except Exception as e:
            print(f"  SPIKE METER FAILED: {e}")
        try:
            thermo = ThermodynamicMeterEstimator(etme_path).estimate(write_json=False)
            if thermo and thermo.get("meter"):
                # Scorer sniffs top-level barlines — flatten the meter block
                pred_path = os.path.join(args.out, f"thermo_pred_{pid}.json")
                with open(pred_path, "w") as f:
                    json.dump(thermo["meter"], f)
                preds["thermo"] = pred_path
            else:
                print("  THERMO METER: no meter block (no freeze events?)")
        except Exception as e:
            print(f"  THERMO METER FAILED: {e}")

        for engine in ("spike", "thermo"):
            tag = engine + args.tag_suffix
            t = totals.setdefault(tag, {"errors": 0, "pieces": 0, "failed": 0})
            if engine not in preds:
                t["failed"] += 1
                continue
            res = run_scorer(truth, preds[engine], args.tol, tag, csv_path)
            if res and "errors" in res:
                t["errors"] += int(res["errors"])
                t["pieces"] += 1
            else:
                t["failed"] += 1

        # ── Phase 2 voices (polyphonic pieces have SATB ground truth) ──
        if int(row.get("n_parts", 1)) > 1:
            vtag = f"voices_{args.phase2_model}{args.tag_suffix}"
            res = run_scorer(truth, etme_path, args.tol, vtag, csv_path)
            if res and "voices" in res:
                try:
                    voice_acc.setdefault(vtag, []).append(float(res["voices"]))
                except ValueError:
                    pass

    print("\n" + "=" * 62)
    print(f"SUMMARY  (errors = FP + FN summed over pieces, tol ±{args.tol:g}ms)")
    for tag, t in sorted(totals.items()):
        print(f"  {tag:<16} errors={t['errors']:<5} pieces={t['pieces']}"
              + (f"  FAILED={t['failed']}" if t["failed"] else ""))
    for tag, accs in sorted(voice_acc.items()):
        mean = sum(accs) / len(accs)
        print(f"  {tag:<16} mean_note_accuracy={mean:.1%} over {len(accs)} pieces")
    print(f"\nPer-piece rows appended to {csv_path}")


if __name__ == "__main__":
    main()
