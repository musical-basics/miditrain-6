"""
Benchmark gate: run the canonical evaluation suite and diff it against the
committed baseline, so an improvement in one phase can't silently regress
another.

The scorecard covers every phase that has ground truth:
  - Phase 3 (severity 1, global): downbeat errors for BOTH meter engines
    over the corpus (errors = FP + FN, minimized).
  - Phase 1 (severity 1, global): spike-boundary F1 vs the hand markers on
    the HELD-OUT Pathétique chunk (100ms tolerance, the historical
    convention). Held out = never tuned on again; reported so texture
    regressions show up even when corpus numbers improve.
  - Phase 2 (severity 2, local): mean voice note-accuracy vs SATB labels.
  - Phase 4 (severity 3, cosmetic): key/spelling — activates once the
    pipeline emits scorable fields.

Verdict logic (severity-ordered, deterministic pipeline → exact compares):
  REGRESSION — any severity-1 metric got worse. Do not adopt.
  TRADEOFF   — severity-1 improved or held, but a lower-severity metric
               regressed. Surface to the user; do not auto-adopt.
  PASS       — nothing regressed (improved or unchanged).

Usage:
    python3 run_benchmark.py --save-baseline          # commit current numbers
    python3 run_benchmark.py                          # compare vs baseline
    python3 run_benchmark.py --phase2_model beam      # gate a candidate change
"""
import argparse
import json
import os
import sys

from export_etme_data import export_analysis
from run_corpus_eval import evaluate, load_v31_config, OUT_DIR

BASELINE_PATH = os.path.join("benchmarks", "baseline.json")
HELDOUT_MIDI = os.path.join("midis", "pathetique_64s_chunk.mid")
HELDOUT_MARKERS = os.path.join("markers", "pathetique_64s_chunk_markers.json")
HELDOUT_TOL_MS = 100  # historical marker convention


def score_heldout_phase1(phase2_model, relaxation, config):
    """
    Phase 1 spike boundaries vs hand markers on the held-out Pathétique
    chunk, via the same export_analysis code path as production (so
    relaxation and threader choice are reflected). Matching mirrors
    optimize_params: greedy best-match per model boundary within tolerance.
    """
    with open(HELDOUT_MARKERS) as f:
        mdata = json.load(f)
    mlist = mdata["markers"] if isinstance(mdata, dict) else mdata
    score_end = mdata.get("score_end_ms") if isinstance(mdata, dict) else None
    truth = sorted(m["time_ms"] for m in mlist)
    if score_end:
        truth = [t for t in truth if t <= score_end]

    import contextlib, io
    out_path = os.path.join(OUT_DIR, "etme_heldout_pathetique.json")
    with contextlib.redirect_stdout(io.StringIO()):
        data = export_analysis(HELDOUT_MIDI, output_json=out_path,
                               phase2_model=phase2_model,
                               relaxation=relaxation, **config)

    spikes = sorted(r["start_time"] for r in data["regimes"]
                    if r["state"] == "TRANSITION SPIKE!")
    if score_end:
        spikes = [s for s in spikes if s <= score_end]

    used = set()
    tp = 0
    for s in spikes:
        best, bi = HELDOUT_TOL_MS + 1, -1
        for i, t in enumerate(truth):
            if i in used:
                continue
            if abs(s - t) < best:
                best, bi = abs(s - t), i
        if best <= HELDOUT_TOL_MS:
            used.add(bi)
            tp += 1
    fp = len(spikes) - tp
    fn = len(truth) - tp
    p = 100 * tp / max(1, tp + fp)
    r = 100 * tp / max(1, tp + fn)
    f1 = 2 * p * r / max(1, p + r)
    return {"tp": tp, "fp": fp, "fn": fn, "errors": fp + fn,
            "precision": round(p, 1), "recall": round(r, 1),
            "f1": round(f1, 1)}


def build_scorecard(phase2_model, relaxation, tol, label=""):
    config = load_v31_config()
    print(f"Benchmark run: P2={phase2_model} relaxation={relaxation} "
          f"corpus tol=±{tol:g}ms | held-out tol=±{HELDOUT_TOL_MS}ms")

    corpus = evaluate(tol=tol, phase2_model=phase2_model,
                      relaxation=relaxation, quiet=True,
                      csv_path=os.path.join(OUT_DIR, "benchmark_runs.csv"))

    print("\nScoring held-out Pathétique (Phase 1 vs hand markers)...")
    heldout = score_heldout_phase1(phase2_model, relaxation, config)

    totals = corpus["totals"]
    vtag = f"voices_{phase2_model}"
    accs = corpus["voice_acc"].get(vtag, [])

    metrics = {
        # severity 1 — global
        "downbeat_errors_thermo": totals.get("thermo", {}).get("errors"),
        "downbeat_errors_spike": totals.get("spike", {}).get("errors"),
        "heldout_phase1_errors": heldout["errors"],
        # severity 2 — local
        "voices_mean_acc": round(sum(accs) / len(accs), 4) if accs else None,
        # informational
        "heldout_phase1_f1": heldout["f1"],
        "thermo_pieces_scored": totals.get("thermo", {}).get("pieces"),
        "spike_pieces_scored": totals.get("spike", {}).get("pieces"),
        "voices_pieces_scored": len(accs),
    }
    return {
        "label": label,
        "pipeline": {"phase2_model": phase2_model, "relaxation": relaxation,
                     "corpus_tol_ms": tol},
        "config": config,
        "metrics": metrics,
        "heldout_detail": heldout,
        "per_piece": corpus["per_piece"],
    }


# metric → (severity, direction) ; direction "min" = lower is better
GATED_METRICS = {
    "downbeat_errors_thermo": (1, "min"),
    "downbeat_errors_spike": (1, "min"),
    "heldout_phase1_errors": (1, "min"),
    "voices_mean_acc": (2, "max"),
}


def compare(baseline, current):
    b_m, c_m = baseline["metrics"], current["metrics"]
    print("\n" + "=" * 70)
    print(f"{'metric':<28}{'baseline':>12}{'current':>12}{'delta':>12}  verdict")
    print("-" * 70)

    worst = 0  # 0 pass, 2 tradeoff, 3 regression
    improved = False
    for name, (severity, direction) in GATED_METRICS.items():
        b, c = b_m.get(name), c_m.get(name)
        if b is None or c is None:
            print(f"{name:<28}{str(b):>12}{str(c):>12}{'--':>12}  (unscored)")
            continue
        delta = c - b
        better = (delta < 0) if direction == "min" else (delta > 0)
        worse = (delta > 0) if direction == "min" else (delta < 0)
        if abs(delta) < 1e-9:
            mark = "="
        elif better:
            mark = "improved"
            improved = True
        else:
            mark = f"REGRESSED (sev {severity})"
            worst = max(worst, 3 if severity == 1 else 2)
        d_str = f"{delta:+.4g}" if isinstance(delta, float) else f"{delta:+d}"
        print(f"{name:<28}{b:>12}{c:>12}{d_str:>12}  {mark}")

    # informational rows
    for name in ("heldout_phase1_f1", "thermo_pieces_scored",
                 "spike_pieces_scored", "voices_pieces_scored"):
        b, c = b_m.get(name), c_m.get(name)
        print(f"{name:<28}{str(b):>12}{str(c):>12}{'':>12}  (info)")

    # per-piece movers (severity-1 drill-down)
    movers = []
    for pid, cur in current.get("per_piece", {}).items():
        base = baseline.get("per_piece", {}).get(pid, {})
        for engine in ("thermo", "spike"):
            cb = (base.get(engine) or {}).get("errors")
            cc = (cur.get(engine) or {}).get("errors")
            if cb is not None and cc is not None and cc != cb:
                movers.append((cc - cb, pid, engine, cb, cc))
    if movers:
        print("\nPer-piece downbeat movers (worst first):")
        for d, pid, engine, cb, cc in sorted(movers, reverse=True)[:10]:
            print(f"  {pid:<32}{engine:<8}{cb:>4} → {cc:<4} ({d:+d})")

    if baseline.get("pipeline") != current.get("pipeline") or \
       baseline.get("config") != current.get("config"):
        print("\nNote: pipeline/config differs from baseline (that is the "
              "point of a candidate run) — diffs:")
        for k in set(baseline.get("pipeline", {})) | set(current.get("pipeline", {})):
            bv, cv = baseline.get("pipeline", {}).get(k), current.get("pipeline", {}).get(k)
            if bv != cv:
                print(f"  pipeline.{k}: {bv} → {cv}")
        for k in set(baseline.get("config", {})) | set(current.get("config", {})):
            bv, cv = baseline.get("config", {}).get(k), current.get("config", {}).get(k)
            if bv != cv:
                print(f"  config.{k}: {bv} → {cv}")

    print("\n" + "=" * 70)
    if worst >= 3:
        print("VERDICT: REGRESSION — a global (severity-1) metric got worse. "
              "Do not adopt.")
        return 1
    if worst == 2:
        print("VERDICT: TRADEOFF — severity-1 held or improved, but a "
              "lower-severity metric regressed. Decide explicitly.")
        return 2
    if improved:
        print("VERDICT: PASS — improved with no regressions. Safe to adopt "
              "(and to --save-baseline).")
    else:
        print("VERDICT: PASS — identical to baseline.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Benchmark suite with regression gate")
    ap.add_argument("--save-baseline", action="store_true",
                    help="write this run's scorecard as the new committed baseline")
    ap.add_argument("--phase2_model", default="greedy", choices=["greedy", "beam"])
    ap.add_argument("--relaxation", action="store_true")
    ap.add_argument("--tol", type=float, default=50.0)
    ap.add_argument("--label", default="", help="human label for this run")
    args = ap.parse_args()

    card = build_scorecard(args.phase2_model, args.relaxation, args.tol,
                           label=args.label)

    if args.save_baseline:
        os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
        with open(BASELINE_PATH, "w") as f:
            json.dump(card, f, indent=1)
        print(f"\nBaseline written to {BASELINE_PATH}. Commit it.")
        m = card["metrics"]
        print(f"  thermo={m['downbeat_errors_thermo']} spike={m['downbeat_errors_spike']} "
              f"heldout_P1_errors={m['heldout_phase1_errors']} "
              f"(F1 {m['heldout_phase1_f1']}) voices={m['voices_mean_acc']}")
        return

    if not os.path.exists(BASELINE_PATH):
        print(f"\nNo baseline at {BASELINE_PATH}. Run with --save-baseline first.")
        sys.exit(1)
    with open(BASELINE_PATH) as f:
        baseline = json.load(f)
    sys.exit(compare(baseline, card))


if __name__ == "__main__":
    main()
