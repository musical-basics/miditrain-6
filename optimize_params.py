"""
optimize_params.py — Harmonic Regime Detector Parameter Optimizer
=================================================================
Mirrors the visualizer's "Compare vs Model" scoring logic exactly:
  - Model signals  = regime boundaries with state == "TRANSITION SPIKE!"
  - Ground truth   = user markers from markers/pathetique_16s_chunk_markers.json
  - Tolerance      = 100 ms (same as visualizer default)

Goals:
  1. Grid-search all 6 continuous parameters (not just break_method × jaccard)
  2. Score with a precision-weighted F-beta (β=0.5) that penalises FP 4× more
  3. Apply tier weighting: Tier 1 FN counts 2× vs Tier 2 FN in the loss
  4. Export the top-5 configs as JSON files loadable by the visualizer
  5. Generate a heatmap of the solution landscape

Usage:
    python optimize_params.py
    python optimize_params.py --beta 0.5 --tolerance 100 --top_n 5
    python optimize_params.py --quick          # smaller grid, faster run

Outputs:
    visualizer/public/etme_pathetique_16s_chunk_optimized_1.json  ← top-5 ready to load
    ...
    visualizer/public/etme_pathetique_16s_chunk_optimized_5.json
    optimize_results.csv                       ← full ranked results table
    optimize_heatmap.png                       ← 2D sensitivity heatmap
"""

import argparse
import csv
import itertools
import json
import math
import os
import sys
import time
from pathlib import Path

# ─── Optional: matplotlib for heatmap (graceful fallback) ───────────────────
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[warn] matplotlib not found — heatmap output skipped. Install with: pip install matplotlib")

# ─── Local imports ───────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from harmonic_regime_detector import HarmonicRegimeDetector
from export_etme_data import extract_keyframes, export_analysis

REPO_ROOT    = Path(__file__).parent
DEFAULT_CHUNK = "pathetique_64s_chunk"
PUBLIC_DIR   = REPO_ROOT / "visualizer" / "public"

# ─── Tier weights for FN penalty ─────────────────────────────────────────────
TIER_WEIGHTS = {
    "tier1": 2.0,   # Downbeat + Harmonic — missing these hurts more
    "tier2": 1.0,   # Harmonic Spike only
}


# ═══════════════════════════════════════════════════════════════════════════════
# Scoring — mirrors computeComparison() in ETMEVisualizer.js exactly
# ═══════════════════════════════════════════════════════════════════════════════

def get_model_boundaries(regime_frames):
    """Extract TRANSITION SPIKE! start times — same logic as getModelBoundaries() in JS."""
    boundaries = []
    regimes = []
    current = None

    for frame in regime_frames:
        rid = frame["Regime_ID"]
        state = frame["State"]
        time_ms = frame["Time (ms)"]

        is_new = current is None or current["id"] != rid
        is_spike_start = state == "TRANSITION SPIKE!" and (current is None or current["state"] != "TRANSITION SPIKE!")
        is_spike_end = state != "TRANSITION SPIKE!" and current is not None and current["state"] == "TRANSITION SPIKE!"

        if is_new or is_spike_start or is_spike_end:
            if current:
                current["end_time"] = time_ms
                regimes.append(current)
            current = {"id": rid, "start_time": time_ms, "end_time": time_ms, "state": state}
        else:
            current["end_time"] = time_ms
            if state in ("Stable", "Regime Locked"):
                current["state"] = state

    if current:
        regimes.append(current)

    for r in regimes:
        if r["state"] == "TRANSITION SPIKE!":
            boundaries.append(r["start_time"])

    return boundaries


def score_params(params, markers, keyframes, tolerance_ms=100, beta=None,
                 score_end_ms=None):
    """
    Run the detector with `params`, score against ground-truth `markers`.

    Primary objective: minimize (FP + FN) — fewest total errors wins.
    Tiebreaker: FP (if equal total errors, prefer the one with fewer FPs).

    If score_end_ms is set, model boundaries beyond that time are excluded
    from scoring (they fall in the MIDI buffer zone, not the marked region).

    Returns a dict with:
        tp, fp, fn, total_errors, precision, recall, f1
    """
    detector = HarmonicRegimeDetector(
        break_angle=params["break_angle"],
        min_break_mass=params["min_break_mass"],
        merge_angle=params["merge_angle"],
        angle_map=params["angle_map"],
        break_method=params["break_method"],
        debounce_ms=params["debounce_ms"],
        jaccard_threshold=params["jaccard_threshold"],
        min_resolution_ratio=params.get("min_resolution_ratio", 0.0),
        max_anchor_size=params.get("max_anchor_size", 12),
        maturity_grace_ms=params.get("maturity_grace_ms", 0),
        bass_multiplier=params.get("bass_multiplier", 1.0),
    )
    regime_frames = detector.process(keyframes)
    model_bounds = get_model_boundaries(regime_frames)

    # Exclude boundaries in the buffer zone (beyond the scored region)
    if score_end_ms is not None:
        model_bounds = [b for b in model_bounds if b <= score_end_ms]

    user_times = [m["time_ms"] for m in markers]
    matched_user = set()
    matched_model = set()

    # True positives — greedy nearest-neighbour (same as JS)
    for mi, mb in enumerate(model_bounds):
        best_dist, best_ui = math.inf, -1
        for ui, ut in enumerate(user_times):
            if ui in matched_user:
                continue
            d = abs(mb - ut)
            if d < best_dist:
                best_dist, best_ui = d, ui
        if best_dist <= tolerance_ms and best_ui >= 0:
            matched_model.add(mi)
            matched_user.add(best_ui)

    tp = len(matched_model)
    fp = len(model_bounds) - tp
    fn = len(markers) - len(matched_user)
    total_errors = fp + fn

    # Standard P/R/F1 for reporting only
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn,
        "total_errors": total_errors,   # PRIMARY sort key (ascending — fewer = better)
        "precision": round(precision * 100, 1),
        "recall":    round(recall    * 100, 1),
        "f1":        round(f1        * 100, 2),
        "n_bounds":  len(model_bounds),
        "n_markers": len(markers),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Grid definition
# ═══════════════════════════════════════════════════════════════════════════════

FULL_GRID = {
    "break_angle":    [15, 25, 35, 45, 55, 65],
    "min_break_mass": [0.25, 0.5, 0.75, 1.0, 1.25],
    "merge_angle":    [5, 10, 15, 20, 25, 30],
    "debounce_ms":    [10, 25, 50, 75, 100, 150],
    "jaccard_threshold": [0.125, 0.25, 0.375, 0.5, 0.625, 0.75],
    "break_method":   ["hybrid", "hybrid_split"],
    "angle_map":      ["dissonance"],
}

QUICK_GRID = {
    "break_angle":      [15, 25, 40],
    "min_break_mass":   [0.5, 0.75, 1.0, 1.3],
    "merge_angle":      [15, 25],
    "debounce_ms":      [100, 200],
    "jaccard_threshold":[0.3, 0.5, 0.7],
    "break_method":     ["hybrid_v2", "hybrid_v2_split"],
    "angle_map":        ["dissonance"],
}

# V3 grid: lock base params from top 5, search new Method 1/2/3 variables
# + expanded debounce range as suggested by deep think analysis
V3_GRID = {
    "break_angle":           [15, 25, 35],
    "min_break_mass":        [0.75],
    "merge_angle":           [20, 25],
    "debounce_ms":           [100, 150, 200],
    "jaccard_threshold":     [0.25, 0.375, 0.5],
    "break_method":          ["hybrid"],
    "angle_map":             ["dissonance"],
    "min_resolution_ratio":  [0.0, 0.25, 0.40, 0.60],
    "max_anchor_size":       [4, 5, 6, 12],
    "maturity_grace_ms":     [0, 100, 150, 200],
    "bass_multiplier":       [1.0, 1.5, 2.0, 3.0],
}


def build_trials(grid):
    keys = list(grid.keys())
    for combo in itertools.product(*[grid[k] for k in keys]):
        yield dict(zip(keys, combo))


# ═══════════════════════════════════════════════════════════════════════════════
# Main runner
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Harmonic Regime Parameter Optimizer")
    parser.add_argument("--chunk",         type=str,   default=DEFAULT_CHUNK,
                        help=f"Base name of the MIDI/markers chunk (default: {DEFAULT_CHUNK})")
    parser.add_argument("--tolerance",     type=int,   default=100,  help="Matching window in ms (default 100)")
    parser.add_argument("--top_n",         type=int,   default=5,    help="Number of top configs to export")
    parser.add_argument("--min_precision", type=float, default=0.0,  help="Optional hard floor on precision %% (0 = disabled)")
    parser.add_argument("--min_recall",    type=float, default=50.0, help="Hard floor on recall %% — prevents degenerate low-detection configs (default: 50.0)")
    parser.add_argument("--quick",         action="store_true",      help="Use quick (smaller) grid for fast testing")
    parser.add_argument("--v3",            action="store_true",      help="V3 grid: search new Method 1/2/3 params with locked base config")
    args = parser.parse_args()

    midi_path    = REPO_ROOT / "midis"   / f"{args.chunk}.mid"
    markers_path = REPO_ROOT / "markers" / f"{args.chunk}_markers.json"
    assert midi_path.exists(),    f"MIDI not found: {midi_path}"
    assert markers_path.exists(), f"Markers not found: {markers_path}"

    grid = V3_GRID if args.v3 else (QUICK_GRID if args.quick else FULL_GRID)
    trials = list(build_trials(grid))
    total = len(trials)

    print(f"\n{'='*70}")
    print(f"  HARMONIC REGIME OPTIMIZER")
    print(f"  Chunk:      {args.chunk}")
    print(f"  Midi:       {midi_path.name}")
    print(f"  Markers:    {markers_path.name}")
    print(f"  Tolerance:  {args.tolerance} ms")
    print(f"  Objective:  minimize (FP + FN)  — fewest total errors wins")
    print(f"  Tiebreaker: fewest FP  (prefer FN over FP when total errors equal)")
    if args.min_precision > 0:
        print(f"  Min P floor:{args.min_precision}%")
    if args.min_recall > 0:
        print(f"  Min R floor:{args.min_recall}%  (prevents degenerate low-detection configs)")
    print(f"  Grid size:  {total:,} trials  ({'quick' if args.quick else 'full'})")
    print(f"{'='*70}\n")

    # Load ground-truth markers
    with open(markers_path) as f:
        marker_data = json.load(f)
    markers = marker_data if isinstance(marker_data, list) else marker_data["markers"]
    score_end_ms = marker_data.get("score_end_ms") if isinstance(marker_data, dict) else None
    print(f"  Ground truth: {len(markers)} markers  "
          f"({sum(1 for m in markers if m['tier']=='tier1')} Tier1, "
          f"{sum(1 for m in markers if m['tier']=='tier2')} Tier2)")
    if score_end_ms is not None:
        print(f"  score_end_ms: {score_end_ms}ms  (MIDI has buffer beyond this; boundaries in buffer excluded)")
    print()

    # Pre-extract keyframes once (reused for every trial)
    print("  Pre-extracting keyframes...")
    keyframes = extract_keyframes(str(midi_path))
    print(f"  {len(keyframes)} keyframes extracted.\n")

    # ─── Grid search ──────────────────────────────────────────────────────────
    results = []
    t0 = time.time()
    report_every = max(1, total // 20)  # report at 5% intervals

    for i, params in enumerate(trials):
        s = score_params(params, markers, keyframes,
                         tolerance_ms=args.tolerance,
                         score_end_ms=score_end_ms)
        results.append({**params, **s})

        if (i + 1) % report_every == 0 or (i + 1) == total:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (total - i - 1) / rate
            best_so_far = min(results, key=lambda r: (r["total_errors"], r["fp"]))
            print(f"  [{i+1:>6}/{total}]  "
                  f"elapsed={elapsed:.0f}s  eta={eta:.0f}s  "
                  f"best errors={best_so_far['total_errors']} (FP={best_so_far['fp']} FN={best_so_far['fn']})  "
                  f"P={best_so_far['precision']:.1f}% R={best_so_far['recall']:.1f}% F1={best_so_far['f1']:.1f}%")

    total_time = time.time() - t0
    print(f"\n  Done! {total} trials in {total_time:.1f}s ({total/total_time:.0f} trials/sec)\n")

    # ─── Filter by floors, then sort ─────────────────────────────────────────
    passed = results
    if args.min_precision > 0:
        passed = [r for r in passed if r["precision"] >= args.min_precision]
        print(f"  Precision floor {args.min_precision}%: {len(results)-len(passed):,} excluded, {len(passed):,} remain.")
    if args.min_recall > 0:
        n_before = len(passed)
        passed = [r for r in passed if r["recall"] >= args.min_recall]
        print(f"  Recall floor {args.min_recall}%: {n_before-len(passed):,} excluded, {len(passed):,} remain.")

    if not passed:
        print(f"  ⚠️  No configs passed the precision floor. Lower --min_precision.")
        return

    # Primary:   fewest total errors (FP + FN)
    # Tiebreaker: fewest FP (prefer FN over FP when tied)
    passed.sort(key=lambda r: (r["total_errors"], r["fp"]))
    top = passed[:args.top_n]

    print(f"\n{'─'*70}")
    print(f"  TOP {args.top_n} CONFIGS  (minimize FP+FN, tiebreak: fewer FP)")
    print(f"{'─'*70}")
    for rank, r in enumerate(top, 1):
        print(f"\n  #{rank}  errors={r['total_errors']} (FP={r['fp']} + FN={r['fn']})  "
              f"TP={r['tp']}  F1={r['f1']:.1f}%  P={r['precision']:.1f}%  R={r['recall']:.1f}%")
        print(f"       break_method={r['break_method']}  angle_map={r['angle_map']}")
        print(f"       break_angle={r['break_angle']}°  merge_angle={r['merge_angle']}°")
        print(f"       min_break_mass={r['min_break_mass']}  debounce_ms={r['debounce_ms']}ms")
        print(f"       jaccard={r['jaccard_threshold']}")

    print(f"\n{'─'*70}\n")

    # ─── Save CSV ─────────────────────────────────────────────────────────────
    csv_path = REPO_ROOT / "optimize_results.csv"
    fieldnames = list(passed[0].keys())
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(passed)
    print(f"  Full results saved → {csv_path.name}")

    # ─── Export top-N as visualizer-ready JSON files ──────────────────────────
    print(f"\n  Generating top-{args.top_n} JSON files for the visualizer...")
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    exported = []

    for rank, r in enumerate(top, 1):
        out_path = PUBLIC_DIR / f"etme_{args.chunk}_optimized_{rank}.json"
        print(f"    #{rank} → {out_path.name}  "
              f"({r['break_method']} J={r['jaccard_threshold']} "
              f"BA={r['break_angle']} MBM={r['min_break_mass']} "
              f"D={r['debounce_ms']}ms)  "
              f"errors={r['total_errors']} FP={r['fp']} FN={r['fn']}")
        # Collect V3 params if present
        v3_keys = ["min_resolution_ratio", "max_anchor_size", "maturity_grace_ms", "bass_multiplier"]
        v3_params = {k: r[k] for k in v3_keys if k in r}
        export_analysis(
            midi_path=str(midi_path),
            output_json=str(out_path),
            angle_map=r["angle_map"],
            break_method=r["break_method"],
            jaccard_threshold=r["jaccard_threshold"],
            min_break_mass=r["min_break_mass"],
            break_angle=r["break_angle"],
            merge_angle=r["merge_angle"],
            debounce_ms=r["debounce_ms"],
            trim_ms=score_end_ms,
            **v3_params,
        )
        # Patch the JSON to embed the full param config as metadata
        with open(out_path) as jf:
            jdata = json.load(jf)
        base_params = {
            "break_method":     r["break_method"],
            "angle_map":        r["angle_map"],
            "break_angle":      r["break_angle"],
            "merge_angle":      r["merge_angle"],
            "min_break_mass":   r["min_break_mass"],
            "debounce_ms":      r["debounce_ms"],
            "jaccard_threshold":r["jaccard_threshold"],
        }
        base_params.update(v3_params)
        jdata["optimizer_meta"] = {
            "rank": rank,
            "total_errors": r["total_errors"],
            "f1": r["f1"],
            "precision": r["precision"],
            "recall": r["recall"],
            "tp": r["tp"], "fp": r["fp"], "fn": r["fn"],
            "params": base_params
        }
        with open(out_path, "w") as jf:
            json.dump(jdata, jf, indent=2)
        exported.append(out_path)

    print(f"\n  ✅ Exported {len(exported)} JSON files to visualizer/public/\n")

    # ─── Heatmap: break_angle × min_break_mass, best f_beta per cell ─────────
    if HAS_MPL:
        _plot_heatmap(results, args.beta)
    else:
        print("  [skip] matplotlib not available — heatmap skipped.\n")

    print("  Done. Load any 'optimized_N' file in the visualizer to inspect visually.\n")


def _plot_heatmap(results, beta):
    """Generate a 2D heatmap: break_angle (x) × min_break_mass (y), colour = f_beta."""
    # Pivot: for each (break_angle, min_break_mass) cell, take the max f_beta across all other params
    from collections import defaultdict
    cell_best = defaultdict(float)
    for r in results:
        key = (r["break_angle"], r["min_break_mass"])
        if r["f_beta"] > cell_best[key]:
            cell_best[key] = r["f_beta"]

    angles = sorted(set(r["break_angle"] for r in results))
    masses  = sorted(set(r["min_break_mass"] for r in results))

    data = [[cell_best.get((a, m), 0.0) for a in angles] for m in masses]

    fig, ax = plt.subplots(figsize=(max(8, len(angles) * 0.9), max(5, len(masses) * 0.7)))
    im = ax.imshow(data, aspect='auto', origin='lower',
                   cmap='YlOrRd', vmin=0, vmax=100)
    ax.set_xticks(range(len(angles)))
    ax.set_xticklabels([f"{a}°" for a in angles], fontsize=9)
    ax.set_yticks(range(len(masses)))
    ax.set_yticklabels([str(m) for m in masses], fontsize=9)
    ax.set_xlabel("break_angle", fontsize=11)
    ax.set_ylabel("min_break_mass", fontsize=11)
    ax.set_title(f"Best F-beta (β={beta}) per (break_angle × min_break_mass)\nmax over all other params",
                 fontsize=12, pad=12)
    fig.colorbar(im, ax=ax, label="F-beta %")

    # Annotate each cell with the score
    for yi, m in enumerate(masses):
        for xi, a in enumerate(angles):
            val = cell_best.get((a, m), 0.0)
            colour = "black" if val > 60 else "white"
            ax.text(xi, yi, f"{val:.1f}", ha='center', va='center',
                    fontsize=7, color=colour, fontweight='bold')

    plt.tight_layout()
    hm_path = REPO_ROOT / "optimize_heatmap.png"
    plt.savefig(hm_path, dpi=150)
    plt.close()
    print(f"  Heatmap saved → {hm_path.name}\n")


if __name__ == "__main__":
    main()
