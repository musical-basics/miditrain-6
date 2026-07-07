"""
Ad-hoc ground-truth evaluation: YOUR MIDI + YOUR MusicXML.

The MusicXML is the ground truth. It is rendered through the corpus
factory (make_ground_truth.py) into a .gt.json carrying downbeats, meter
map, key, per-note spellings, and voice labels — under the system-wide
120 BPM convention (quarter = 500ms). Your MIDI is then run through the
FULL pipeline (Phase 1+2 at the V3.1 config, all three meter engines)
and every decision is scored against the truth.

Alignment assumption: the MIDI is quantized on the same 120 BPM timeline
as the score (e.g. a DAW export of the same music). The report prints a
note-count and onset-overlap sanity check so misalignment is visible
instead of silently scoring as errors.

Usage:
    python3 eval_pair.py --midi my_piece.mid --xml my_piece.musicxml
    python3 eval_pair.py --midi m.mid --xml s.xml --name mypiece --tol 50
    python3 eval_pair.py --xml s.xml --use-rendered-midi   # test on the
        factory's own leak-free render instead of your MIDI

Requires the corpus venv for the XML step:
    python3 -m venv "corpus files/venv"
    "corpus files/venv/bin/pip" install music21 mido

Outputs land in corpus_runs/pairs/<name>/ plus a CSV row per engine in
corpus_runs/pairs/runs.csv (tags pair_spike / pair_thermo / pair_bus).
"""
import argparse
import contextlib
import glob
import io
import json
import os
import shutil
import subprocess
import sys

from export_etme_data import export_analysis
from phase3_spike_meter import MacroMeterEstimator
from phase3_thermo_meter import ThermodynamicMeterEstimator
from phase4_make_votes import spike_votes
from run_corpus_eval import load_v31_config, run_scorer

VENV_PY = os.path.join("corpus files", "venv", "bin", "python3")
FACTORY = os.path.join("corpus files", "make_ground_truth.py")
PAIRS_DIR = os.path.join("corpus_runs", "pairs")


def build_ground_truth(xml_path, out_dir):
    """Render the MusicXML into GT via the corpus factory. Returns
    (gt_json_path, rendered_midi_path)."""
    if not os.path.exists(VENV_PY):
        raise SystemExit(
            f"corpus venv missing ({VENV_PY}). Create it with:\n"
            '  python3 -m venv "corpus files/venv"\n'
            '  "corpus files/venv/bin/pip" install music21 mido')
    proc = subprocess.run(
        [VENV_PY, FACTORY, "build", "--files", xml_path, "--out", out_dir],
        capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.returncode != 0:
        raise SystemExit(f"ground-truth build failed: {proc.stderr.strip()[:400]}")
    gts = glob.glob(os.path.join(out_dir, "groundtruth", "*.gt.json"))
    if not gts:
        raise SystemExit("factory produced no ground truth (piece skipped?)")
    gt = max(gts, key=os.path.getmtime)
    base = os.path.basename(gt).replace(".gt.json", "")
    return gt, os.path.join(out_dir, "midis", f"{base}.mid")


def alignment_check(gt_path, etme_path, tol_ms=30):
    """Sanity check: do the MIDI's onsets line up with the truth's?"""
    with open(gt_path) as f:
        gt_notes = json.load(f)["notes"]
    with open(etme_path) as f:
        midi_notes = json.load(f)["notes"]
    gt_set = {(n["onset_ms"], n["pitch"]) for n in gt_notes}
    hits = sum(1 for n in midi_notes
               if any((n["onset"] + d, n["pitch"]) in gt_set
                      for d in range(-tol_ms, tol_ms + 1, 5)))
    frac = hits / max(1, len(midi_notes))
    print(f"\nALIGNMENT  GT notes={len(gt_notes)}  MIDI notes={len(midi_notes)}  "
          f"onset+pitch overlap={frac:.0%} (±{tol_ms}ms)")
    if frac < 0.5:
        print("  WARNING: under half the MIDI notes match the score's "
              "timeline. Check that the MIDI is the same music, quantized "
              "at the 120 BPM convention, starting at time 0. Downbeat "
              "scores below will largely reflect misalignment, not the "
              "pipeline.")
    return frac


def main():
    ap = argparse.ArgumentParser(description="Score your MIDI against your MusicXML (the ground truth)")
    ap.add_argument("--midi", default=None, help="your MIDI (quantized, 120 BPM convention)")
    ap.add_argument("--xml", required=True, help="MusicXML/kern score = ground truth")
    ap.add_argument("--name", default=None, help="run name (default: xml basename)")
    ap.add_argument("--tol", type=float, default=50.0)
    ap.add_argument("--phase2_model", default="greedy", choices=["greedy", "beam"])
    ap.add_argument("--use-rendered-midi", action="store_true",
                    help="evaluate the factory's leak-free render of the XML instead of --midi")
    args = ap.parse_args()
    if not args.midi and not args.use_rendered_midi:
        ap.error("pass --midi, or --use-rendered-midi to test the score's own render")

    name = args.name or os.path.splitext(os.path.basename(args.xml))[0]
    out_dir = os.path.join(PAIRS_DIR, name)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)  # fresh GT per run — inputs may have changed
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(PAIRS_DIR, "runs.csv")

    print(f"[1/4] Building ground truth from {args.xml}...")
    truth, rendered_midi = build_ground_truth(args.xml, out_dir)

    midi = rendered_midi if args.use_rendered_midi else args.midi
    print(f"\n[2/4] Running Phase 1+2 on {midi} (V3.1 config, P2={args.phase2_model})...")
    config = load_v31_config()
    etme = os.path.join(out_dir, "etme_pair.json")
    with contextlib.redirect_stdout(io.StringIO()):
        export_analysis(midi, output_json=etme,
                        phase2_model=args.phase2_model, **config)

    alignment_check(truth, etme)

    print(f"\n[3/4] Running all three meter engines...")
    preds = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            MacroMeterEstimator(etme).estimate(write_json=True)
        # spike writes phase3_grid_{key}.json next to the etme file
        grids = glob.glob(os.path.join(out_dir, "phase3_grid_*.json"))
        if grids:
            preds["spike"] = grids[0]
    except Exception as e:
        print(f"  spike failed: {e}")
    thermo = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            thermo = ThermodynamicMeterEstimator(etme).estimate(write_json=False)
        if thermo and thermo.get("meter"):
            p = os.path.join(out_dir, "thermo_pred.json")
            with open(p, "w") as f:
                json.dump(thermo["meter"], f)
            preds["thermo"] = p
        else:
            print("  thermo: no meter (insufficient freezes)")
    except Exception as e:
        print(f"  thermo failed: {e}")
    try:
        h = os.path.join(out_dir, "votes_harmonic.json")
        with open(h, "w") as f:
            json.dump(spike_votes(etme), f)
        vote_args = ["--votes", f"harmonic={h}"]
        if thermo and thermo.get("freezing_events"):
            fz = os.path.join(out_dir, "votes_freezes.json")
            with open(fz, "w") as f:
                json.dump([{"time_ms": e["time_ms"], "weight": e.get("magnitude", 1.0)}
                           for e in thermo["freezing_events"]], f)
            vote_args += ["--votes", f"freezes={fz}"]
        bus_out = os.path.join(out_dir, "bus_pred.json")
        proc = subprocess.run([sys.executable, "phase4_meter_bus.py",
                               "--notes", etme, *vote_args, "--out", bus_out],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            preds["bus"] = bus_out
        else:
            print(f"  bus failed: {proc.stderr.strip()[:200]}")
    except Exception as e:
        print(f"  bus failed: {e}")

    print(f"\n[4/4] Scoring against ground truth (±{args.tol:g}ms)...")
    summary = {}
    for engine, pred in preds.items():
        res = run_scorer(truth, pred, args.tol, f"pair_{engine}", csv_path)
        if res:
            summary[engine] = res
    # voices/spelling: the ETME file itself is the prediction
    res = run_scorer(truth, etme, args.tol, f"pair_voices_{args.phase2_model}", csv_path)
    if res and "voices" in res:
        summary["voices"] = res

    print("\n" + "=" * 60)
    print(f"SUMMARY  {name}  (truth = {os.path.basename(args.xml)})")
    for engine in ("spike", "thermo", "bus"):
        r = summary.get(engine)
        if r and "errors" in r:
            print(f"  {engine:<8} downbeat errors={r['errors']:<5} F1={float(r['f1']):.1%}"
                  + (f"  ts={r['ts']}" if "ts" in r else ""))
        else:
            print(f"  {engine:<8} (no prediction)")
    if "voices" in summary:
        print(f"  voices   accuracy={float(summary['voices']['voices']):.1%} ({args.phase2_model})")
    print(f"\nArtifacts in {out_dir}; CSV rows appended to {csv_path}")


if __name__ == "__main__":
    main()
