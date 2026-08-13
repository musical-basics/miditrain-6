"""
MIDI -> engine -> MusicXML -> compare against the human-authored MusicXML.

One command that drives the whole back-propagation loop for a (MIDI, MusicXML)
pair and writes everything the comparison GUI reads:

  1. Phase 1+2  export_etme_data       MIDI -> etme JSON (regimes, voices)
  2. Phase 3    spike + thermo         two meter grids
  3. Phase 4    meter evidence bus     the production grid (selectable)
  4. Phase 5A   phase5_quantize        notes -> tick coordinates
  5. Phase 5B   phase5_notation        -> IntermediateScore (VexFlow)
  6. Phase 5C   phase5_musicxml        -> generated .musicxml
  7.            reference conversion    the uploaded .musicxml -> IntermediateScore
  8.            compare_musicxml        notes-only diff -> comparison.json

Everything lands in visualizer/public/compare/<name>/ so the Next.js GUI can
fetch it statically.

Usage:
    python3 run_xml_compare.py --midi X.mid --xml X.musicxml [--name clementi]
                              [--engine bus|thermo|spike] [--tol 0.25]

Steps 7 and 8 need music21, so they run under the corpus venv; the pipeline
steps run under the system interpreter exactly as the rest of the project does.
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
from run_corpus_eval import load_v31_config

VENV_PY = os.path.join("corpus files", "venv", "bin", "python3")
OUT_ROOT = os.path.join("visualizer", "public", "compare")


def need_venv():
    if not os.path.exists(VENV_PY):
        raise SystemExit(
            f"corpus venv missing ({VENV_PY}). Create it with:\n"
            '  python3 -m venv "corpus files/venv"\n'
            '  "corpus files/venv/bin/pip" install music21 mido')


def run_engines(etme, out_dir):
    """All three meter engines. Returns {name: grid_path}."""
    preds = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            MacroMeterEstimator(etme).estimate(write_json=True)
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
                json.dump([{"time_ms": e["time_ms"],
                            "weight": e.get("magnitude", 1.0)}
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
    return preds


def main():
    ap = argparse.ArgumentParser(
        description="Run a MIDI through the engine and compare the generated "
                    "MusicXML against a reference MusicXML")
    ap.add_argument("--midi", required=True)
    ap.add_argument("--xml", required=True, help="reference (human) MusicXML")
    ap.add_argument("--name", default=None)
    ap.add_argument("--engine", default="bus",
                    choices=["bus", "thermo", "spike"])
    ap.add_argument("--algo", default="temperley",
                    choices=["temperley", "krumhansl"])
    ap.add_argument("--phase2_model", default="greedy",
                    choices=["greedy", "beam"])
    ap.add_argument("--tol", type=float, default=0.25,
                    help="onset tolerance in quarter notes")
    ap.add_argument("--tol-ms", type=float, default=50.0,
                    help="downbeat tolerance in ms (corpus convention: 50)")
    args = ap.parse_args()

    need_venv()
    name = args.name or os.path.splitext(os.path.basename(args.xml))[0]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    out_dir = os.path.join(OUT_ROOT, safe)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[1/7] Phase 1+2 on {args.midi} (V3.1, P2={args.phase2_model})...")
    etme = os.path.join(out_dir, "etme.json")
    config = load_v31_config()
    with contextlib.redirect_stdout(io.StringIO()):
        export_analysis(args.midi, output_json=etme,
                        phase2_model=args.phase2_model, **config)

    print("[2/7] Phase 3 + 4 meter engines...")
    preds = run_engines(etme, out_dir)
    if args.engine not in preds:
        raise SystemExit(f"engine '{args.engine}' produced no grid "
                         f"(available: {sorted(preds)})")
    grid = preds[args.engine]
    print(f"       using {args.engine}: {os.path.basename(grid)}")

    # Phase 5A/5B write to fixed visualizer/public/phase5_*_{stem}.json paths
    # derived from the ETME filename. Leave those scripts alone (they are the
    # production path the UI already drives) and relocate their output here.
    print("[3/7] Phase 5A quantize...")
    proc = subprocess.run([sys.executable, "phase5_quantize.py", etme, grid],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"quantize failed: {proc.stderr.strip()[:400]}")
    stem = os.path.basename(etme).replace("etme_", "")
    produced_q = os.path.join("visualizer", "public", f"phase5_quantized_{stem}")
    if not os.path.exists(produced_q):
        raise SystemExit(f"quantize produced no output at {produced_q}")
    # keep the phase5_quantized_ prefix: phase5_notation.py derives its own
    # output name by substituting that prefix, and would otherwise overwrite
    # its input.
    quant = os.path.join(out_dir, "phase5_quantized_run.json")
    shutil.move(produced_q, quant)

    print("[4/7] Phase 5B notation (IntermediateScore)...")
    proc = subprocess.run([sys.executable, "phase5_notation.py", quant, grid,
                           "--algo", args.algo], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"notation failed: {proc.stderr.strip()[:400]}")
    produced_n = os.path.join(out_dir, "phase5_notation_run.json")
    if not os.path.exists(produced_n):
        raise SystemExit(f"notation produced no output at {produced_n}")
    gen_score = os.path.join(out_dir, "generated_score.json")
    shutil.move(produced_n, gen_score)

    print("[5/7] Phase 5C MusicXML export...")
    gen_xml = os.path.join(out_dir, "generated.musicxml")
    proc = subprocess.run([sys.executable, "phase5_musicxml.py", quant, grid,
                           "--out", gen_xml, "--algo", args.algo,
                           "--title", f"{name} (MidiTrain)"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"musicxml export failed: {proc.stderr.strip()[:400]}")

    ref_xml = os.path.join(out_dir, "reference.musicxml")
    shutil.copyfile(args.xml, ref_xml)

    print("[6/7] Converting reference MusicXML to a renderable score...")
    proc = subprocess.run([VENV_PY, "musicxml_to_score.py", ref_xml,
                           "--out", os.path.join(out_dir, "reference_score.json")],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"reference conversion failed: {proc.stderr.strip()[:400]}")
    print(proc.stdout.strip())

    print("[7/8] Comparing notes (alignment check)...")
    cmp_json = os.path.join(out_dir, "comparison.json")
    proc = subprocess.run([VENV_PY, "compare_musicxml.py", "-g", gen_xml,
                           "-r", ref_xml, "--tol", str(args.tol),
                           "--json", cmp_json], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"comparison failed: {proc.stderr.strip()[:400]}")

    print("[8/8] Scoring engine decisions (hands, downbeats, beaming)...")
    dec_json = os.path.join(out_dir, "decisions.json")
    proc = subprocess.run([VENV_PY, "score_notation.py", "-g", gen_xml,
                           "-r", ref_xml, "--grid", grid,
                           "--tol-ms", str(args.tol_ms),
                           "--json", dec_json], capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        raise SystemExit(f"decision scoring failed: {proc.stderr.strip()[:400]}")

    with open(cmp_json) as f:
        rep = json.load(f)
    with open(dec_json) as f:
        dec = json.load(f)
    with open(grid) as f:
        gd = json.load(f)
    gm = gd.get("meter") if isinstance(gd.get("meter"), dict) else gd
    # Phase 5A ticks per quarter note: the GUI needs it to map a note's vfId
    # tick back onto the comparison's quarter-note onsets.
    subdivision = gm.get("subdivision", 4)
    denominator = gm.get("denominator", 4)
    manifest = {
        "ticks_per_quarter": subdivision * denominator / 4.0,
        "time_signature": gm.get("time_signature"),
        "measure_ms": gm.get("measure_ms"),
        "name": name,
        "midi": os.path.basename(args.midi),
        "reference_xml": os.path.basename(args.xml),
        "engine": args.engine,
        "phase2_model": args.phase2_model,
        "key_algo": args.algo,
        "tolerance_q": args.tol,
        "counts": rep["counts"],
        "note_accuracy": rep["note_accuracy"],
        "secondary": rep["secondary"],
        "engines_available": sorted(preds),
        # the numbers that actually measure the engine; note_accuracy above is
        # an ALIGNMENT check (the MIDI is a render of this score, so pitch and
        # onset agreement is expected and proves nothing about the pipeline)
        "decisions": {
            "hands": dec["hands"],
            "beaming": dec["beaming"],
            "durations": dec["durations"],
            "stems": dec["stems"],
            "downbeats": dec.get("downbeats"),
        },
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)

    print(f"\nArtifacts in {out_dir}")
    print(f"Open the GUI at http://localhost:3000/compare?run={safe}")


if __name__ == "__main__":
    main()
