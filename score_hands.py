"""
Hand-separation ground truth and scorer (Phase 0).

The metric a hand-separation algorithm is judged on, standing alone: raw
MIDI in, hand labels out, scored against the reference MusicXML where
part index IS the hand (part 0 = right, part 1 = left).

This deliberately does NOT depend on the pipeline. Phase 0 is proposed to
run BEFORE Phase 1 (docs/phase0_hands_spec.md), so its metric must be
computable without regimes, voices, meter or notation.

Two roles:

  1. Ground truth extractor — `--emit-truth` writes
     `<piece>.hands.json`: every note with its true hand, from the score.
  2. Scorer — given a predictions file (or the built-in baselines),
     reports accuracy overall, per hand, and — the number that matters —
     accuracy in the CROSSOVER REGION where the hands overlap in pitch,
     which is where every known failure lives.

Baselines included so any real algorithm has something to beat:
  split-60   fixed split at middle C (pitch >= 60 -> RH)
  split-best oracle fixed split (best single pitch threshold for THIS
             piece; an upper bound on what any pitch-only rule can do)

Usage:
    # build truth for every pair in musicxmls/
    python3 score_hands.py --emit-truth --all

    # score the baselines on one piece
    python3 score_hands.py --truth corpus_runs/hands/clementi.hands.json

    # score your algorithm's output
    python3 score_hands.py --truth ....hands.json --pred my_hands.json

Prediction format (either shape):
    [{"onset_ms": 0, "pitch": 60, "hand": "R"}, ...]
    {"notes": [{"onset_ms": ..., "pitch": ..., "hand": "L"}, ...]}

Requires the corpus venv (music21) for --emit-truth only; scoring is
pure stdlib.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

VENV_PY = os.path.join("corpus files", "venv", "bin", "python3")
XML_DIR = "musicxmls"
OUT_DIR = os.path.join("corpus_runs", "hands")
MS_PER_QUARTER = 500.0          # the 120 BPM convention, repo-wide


# ── ground truth ───────────────────────────────────────────────────────
TRUTH_SCRIPT = r'''
import json, sys
from music21 import converter

path, out = sys.argv[1], sys.argv[2]
score = converter.parse(path)
score = score.expandRepeats() if score.hasElementOfClass("Repeat") else score

parts = list(score.parts)
notes = []
for pi, part in enumerate(parts):
    for n in part.flatten().notes:
        for p in (n.pitches if hasattr(n, "pitches") else [n.pitch]):
            notes.append({
                "onset_ms": int(round(float(n.offset) * 500.0)),
                "duration_ms": int(round(float(n.quarterLength) * 500.0)),
                "pitch": int(p.midi),
                "hand": "R" if pi == 0 else "L",
                "part": pi,
            })
notes.sort(key=lambda x: (x["onset_ms"], -x["pitch"]))
json.dump({"source": path, "n_parts": len(parts), "notes": notes}, open(out, "w"))
print(json.dumps({"n_parts": len(parts), "n_notes": len(notes)}))
'''


def emit_truth(xml_path, out_path):
    if not os.path.exists(VENV_PY):
        raise SystemExit(f"corpus venv missing ({VENV_PY}); see docs/HANDOFF.md")
    proc = subprocess.run([VENV_PY, "-c", TRUTH_SCRIPT, xml_path, out_path],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  FAILED {os.path.basename(xml_path)}: "
              f"{proc.stderr.strip().splitlines()[-1][:160] if proc.stderr.strip() else ''}")
        return None
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── crossover region: where hand separation is actually hard ───────────
def crossover_band(notes):
    """
    Pitch range where both hands are active. Below it, everything is LH;
    above it, everything is RH; inside it pitch alone cannot decide, and
    that is where every failure in the session log lives.
    """
    rh = [n["pitch"] for n in notes if n["hand"] == "R"]
    lh = [n["pitch"] for n in notes if n["hand"] == "L"]
    if not rh or not lh:
        return None
    lo, hi = min(rh), max(lh)      # RH's floor, LH's ceiling
    return (lo, hi) if lo <= hi else None


# ── baselines ──────────────────────────────────────────────────────────
def baseline_fixed_split(notes, threshold):
    return ["R" if n["pitch"] >= threshold else "L" for n in notes]


def best_fixed_split(notes):
    """Oracle: the best single pitch threshold for THIS piece.

    Any pitch-only rule is bounded by this. A real algorithm that cannot
    beat it has learned nothing beyond 'high notes are the right hand'.
    """
    best = (0.0, 60)
    for t in range(21, 109):
        pred = baseline_fixed_split(notes, t)
        acc = sum(1 for p, n in zip(pred, notes) if p == n["hand"]) / len(notes)
        if acc > best[0]:
            best = (acc, t)
    return best[1]


# ── scoring ────────────────────────────────────────────────────────────
def score(notes, pred_hands, label):
    n = len(notes)
    correct = sum(1 for p, t in zip(pred_hands, notes) if p == t["hand"])
    per = {}
    for hand in ("R", "L"):
        idx = [i for i, t in enumerate(notes) if t["hand"] == hand]
        if idx:
            per[hand] = {
                "notes": len(idx),
                "correct": sum(1 for i in idx if pred_hands[i] == hand),
            }
            per[hand]["accuracy"] = round(per[hand]["correct"] / len(idx), 4)

    band = crossover_band(notes)
    cross = None
    if band:
        lo, hi = band
        idx = [i for i, t in enumerate(notes) if lo <= t["pitch"] <= hi]
        if idx:
            c = sum(1 for i in idx if pred_hands[i] == notes[i]["hand"])
            cross = {"band": [lo, hi], "notes": len(idx), "correct": c,
                     "accuracy": round(c / len(idx), 4),
                     "share_of_piece": round(len(idx) / n, 4)}

    # Fragmentation: how often the predicted hand flips between
    # consecutive notes of the same true hand — the "line continuity"
    # failure mode, invisible to plain accuracy.
    flips = 0
    last = {}
    for i, t in enumerate(notes):
        h = t["hand"]
        if h in last and pred_hands[last[h]] != pred_hands[i]:
            flips += 1
        last[h] = i

    return {
        "label": label,
        "total": n, "correct": correct, "accuracy": round(correct / n, 4),
        "per_hand": per, "crossover": cross,
        "hand_switches_within_true_hand": flips,
    }


def load_pred(path, notes):
    with open(path) as f:
        data = json.load(f)
    raw = data.get("notes", data) if isinstance(data, dict) else data
    lookup = {}
    for r in raw:
        onset = r.get("onset_ms", r.get("onset"))
        if onset is None or "pitch" not in r:
            continue
        lookup.setdefault((int(round(onset)), int(r["pitch"])), []).append(
            (r.get("hand") or r.get("staff") or "?").upper()[0])
    out, missing = [], 0
    for t in notes:
        k = (t["onset_ms"], t["pitch"])
        if lookup.get(k):
            out.append(lookup[k].pop(0))
        else:
            out.append("?")
            missing += 1
    if missing:
        print(f"  warning: {missing}/{len(notes)} notes had no prediction "
              f"(counted wrong)")
    return out


def report(res):
    print(f"\n  {res['label']:<14} {res['accuracy']*100:6.1f}%  "
          f"({res['correct']}/{res['total']})")
    for h in ("R", "L"):
        d = res["per_hand"].get(h)
        if d:
            print(f"    {h}H {d['accuracy']*100:5.1f}%  ({d['correct']}/{d['notes']})")
    c = res["crossover"]
    if c:
        print(f"    crossover {c['band'][0]}–{c['band'][1]}: "
              f"{c['accuracy']*100:5.1f}%  ({c['correct']}/{c['notes']}, "
              f"{c['share_of_piece']*100:.0f}% of piece)")
    print(f"    hand switches inside a true hand: "
          f"{res['hand_switches_within_true_hand']}")


def main():
    ap = argparse.ArgumentParser(description="Hand-separation truth + scorer")
    ap.add_argument("--emit-truth", action="store_true",
                    help="extract hand truth from reference MusicXML")
    ap.add_argument("--all", action="store_true",
                    help="with --emit-truth: every .musicxml in musicxmls/")
    ap.add_argument("--xml", default=None, help="one reference MusicXML")
    ap.add_argument("--truth", default=None, help="a .hands.json to score against")
    ap.add_argument("--pred", default=None, help="predictions JSON to score")
    ap.add_argument("--json", default=None, help="write the report as JSON")
    args = ap.parse_args()

    if args.emit_truth:
        os.makedirs(OUT_DIR, exist_ok=True)
        xmls = ([args.xml] if args.xml
                else sorted(glob.glob(os.path.join(XML_DIR, "*.musicxml"))))
        if not xmls:
            raise SystemExit(f"no MusicXML found in {XML_DIR}/")
        for x in xmls:
            stem = os.path.splitext(os.path.basename(x))[0]
            out = os.path.join(OUT_DIR, f"{stem}.hands.json")
            info = emit_truth(x, out)
            if info:
                print(f"  {stem}: {info['n_notes']} notes, "
                      f"{info['n_parts']} parts -> {out}")
        return

    if not args.truth:
        ap.error("pass --truth (or --emit-truth to build it first)")

    with open(args.truth) as f:
        truth = json.load(f)
    notes = truth["notes"]
    print(f"{os.path.basename(args.truth)}: {len(notes)} notes, "
          f"{truth['n_parts']} parts")
    if truth["n_parts"] != 2:
        print("  NOTE: reference is not 2-part; 'hands' is not meaningful here.")

    results = []
    results.append(score(notes, baseline_fixed_split(notes, 60), "split@60"))
    t = best_fixed_split(notes)
    results.append(score(notes, baseline_fixed_split(notes, t), f"split@{t}*"))
    if args.pred:
        results.append(score(notes, load_pred(args.pred, notes), "prediction"))

    for r in results:
        report(r)
    print("\n  * oracle fixed split — the ceiling for any pitch-only rule.")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"truth": args.truth, "results": results}, f, indent=1)
        print(f"  wrote {args.json}")


if __name__ == "__main__":
    main()
