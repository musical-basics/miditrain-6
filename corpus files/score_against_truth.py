"""
Per-Decision Scorer for MidiTrain.

Diffs a pipeline output JSON against a ground truth JSON produced by
make_ground_truth.py. Pure stdlib: drop it next to the pipeline and run.

Scored decisions (each independent, each skipped gracefully if the
prediction file does not contain it yet):

  1. DOWNBEATS   precision / recall / F1 within a +-tolerance window,
                 plus period-ratio and phase-offset diagnostics that
                 tell you WHY it failed (wrong period vs wrong phase vs
                 jitter). errors = FP + FN, matching optimize_params.
  2. METER       strict time signature match, metrical family match,
                 tactus ratio.
  3. KEY         MIREX-weighted score (exact 1.0, fifth 0.5,
                 relative 0.3, parallel 0.2).
  4. VOICES      note-level accuracy under the best label permutation
                 (predicted voice ids have no canonical order), plus a
                 fragmentation count (splits inside a true voice).
  5. SPELLING    per-note step+alter accuracy (reserved: scores as soon
                 as the pipeline starts emitting spellings).

Prediction format is sniffed. Any of these shapes work for barlines:
  {"barlines": [{"time_ms": 0}, ...]}     {"barlines": [0, 1000, ...]}
  {"downbeats_ms": [...]}                 markers-style [{"time_ms":..}]
Meter: {"meter": {"time_signature": "2/4", "measure_ms": 1000,
        "beat_ms": 500}} or those keys at top level.
Key:   {"key": "F# minor"} or {"key": {"tonic": "F#", "mode": "minor"}}.
Notes: {"notes": [{"onset_ms":.., "pitch":.., "voice_tag": "Voice 1",
        "spelling": {"step": "E", "alter": -1}}, ...]}

Usage:
  python3 score_against_truth.py --truth gt.json --pred out.json
  python3 score_against_truth.py --truth gt.json --pred out.json \
      --tol 50 --json report.json --csv runs.csv --tag "freeze_v1"

Final stdout line is machine-greppable:
  RESULT errors=E fp=F fn=N f1=0.xxxx ts=strict|family|miss key=0.x ...
"""
import argparse
import csv
import itertools
import json
import os
import statistics
import sys

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def name_to_pc(name):
    if not name:
        return None
    name = name.strip()
    base = PC.get(name[0].upper())
    if base is None:
        return None
    for ch in name[1:]:
        if ch in ("#", "s"):
            base += 1
        elif ch in ("b", "-"):
            base -= 1
    return base % 12


def num_list(seq):
    out = []
    for x in seq:
        if isinstance(x, (int, float)):
            out.append(float(x))
        elif isinstance(x, dict):
            for k in ("time_ms", "time", "t_ms", "ms", "onset_ms"):
                if k in x:
                    out.append(float(x[k]))
                    break
    return sorted(out)


def sniff_barlines(pred, forced_key=None):
    keys = [forced_key] if forced_key else \
           ["barlines", "downbeats_ms", "downbeats", "measures"]
    for k in keys:
        if k and k in pred and isinstance(pred[k], list):
            v = num_list(pred[k])
            if v:
                return v, k
    if isinstance(pred, list):  # bare markers-style file
        v = num_list(pred)
        if v:
            return v, "(root list)"
    return None, None


def sniff_meter(pred):
    src = pred.get("meter") if isinstance(pred.get("meter"), dict) else pred
    out = {}
    for k in ("time_signature", "measure_ms", "beat_ms", "beats",
              "beats_per_measure"):
        if k in src:
            out[k] = src[k]
    if "beats" in out and "beats_per_measure" not in out:
        out["beats_per_measure"] = out["beats"]
    return out or None


def sniff_key(pred):
    k = pred.get("key") or pred.get("analyzed_key")
    if isinstance(k, str):
        parts = k.split()
        return {"tonic": parts[0],
                "mode": parts[1].lower() if len(parts) > 1 else "major"}
    if isinstance(k, dict) and "tonic" in k:
        return {"tonic": k["tonic"], "mode": k.get("mode", "major").lower()}
    return None


# ---------------------------------------------------------------- downbeats
def match_events(gt, pred, tol):
    """One-to-one greedy matching of sorted time lists within +-tol."""
    i = j = tp = 0
    offsets = []
    while i < len(gt) and j < len(pred):
        d = pred[j] - gt[i]
        if abs(d) <= tol:
            tp += 1
            offsets.append(d)
            i += 1
            j += 1
        elif d < -tol:
            j += 1
        else:
            i += 1
    fp = len(pred) - tp
    fn = len(gt) - tp
    return tp, fp, fn, offsets


def snap_ratio(r):
    grid = [0.25, 1 / 3, 0.5, 2 / 3, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
    for g in grid:
        if abs(r - g) / g <= 0.06:
            return g
    return None


def score_downbeats(truth, pred_times, pred_meter, tol):
    gt = [float(t) for t in truth["downbeats_ms"]]
    tp, fp, fn, offsets = match_events(gt, pred_times, tol)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0

    seg = truth["meter_map"][0] if truth.get("meter_map") else None
    diag = {}
    if seg and len(gt) >= 2:
        M = float(seg["measure_ms"])
        if pred_meter and pred_meter.get("measure_ms"):
            pm = float(pred_meter["measure_ms"])
        elif len(pred_times) >= 3:
            diffs = [b - a for a, b in zip(pred_times, pred_times[1:])]
            pm = statistics.median(diffs)
        else:
            pm = None
        if pm:
            diag["period_ratio"] = round(pm / M, 4)
            diag["period_ratio_snapped"] = snap_ratio(pm / M)
        g0 = gt[0]
        folded = []
        for p in pred_times:
            e = (p - g0) % M
            if e > M / 2:
                e -= M
            folded.append(e)
        if folded:
            diag["phase_offset_ms"] = round(statistics.median(folded), 1)
        diag["anacrusis_ms"] = truth.get("anacrusis_ms", 0)
    if offsets:
        diag["mean_abs_snap_err_ms"] = round(
            sum(abs(o) for o in offsets) / len(offsets), 2)

    return {"tp": tp, "fp": fp, "fn": fn, "errors": fp + fn,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), "n_gt": len(gt), "n_pred": len(pred_times),
            "diagnostics": diag}


# -------------------------------------------------------------------- meter
def ts_family(ts):
    try:
        num = int(ts.split("/")[0])
    except Exception:
        return "other"
    return {2: "simple duple", 4: "simple duple", 3: "simple triple",
            6: "compound duple", 9: "compound triple",
            12: "compound quadruple"}.get(num, "other")


def score_meter(truth, pred_meter):
    if not pred_meter:
        return None
    seg = truth["meter_map"][0] if truth.get("meter_map") else None
    if not seg:
        return None
    out = {"gt_ts": seg["time_signature"]}
    pts = pred_meter.get("time_signature")
    if pts:
        out["pred_ts"] = pts
        out["strict"] = (pts == seg["time_signature"])
        out["family"] = (ts_family(pts) == ts_family(seg["time_signature"]))
    if pred_meter.get("beat_ms"):
        r = float(pred_meter["beat_ms"]) / float(seg["beat_ms"])
        out["tactus_ratio"] = round(r, 4)
        out["tactus_ratio_snapped"] = snap_ratio(r)
        out["tactus_exact"] = abs(r - 1.0) <= 0.02
    return out


# ---------------------------------------------------------------------- key
def score_key(truth, pred_key):
    gt = truth.get("analyzed_key")
    if not gt or not pred_key:
        return None
    g_pc, p_pc = name_to_pc(gt["tonic"]), name_to_pc(pred_key["tonic"])
    if g_pc is None or p_pc is None:
        return None
    g_m, p_m = gt["mode"].lower(), pred_key["mode"].lower()
    if g_pc == p_pc and g_m == p_m:
        s, rel = 1.0, "exact"
    elif g_m == p_m and (p_pc - g_pc) % 12 in (7, 5):
        s, rel = 0.5, "fifth"
    elif g_m != p_m and (
            (g_m == "major" and p_pc == (g_pc + 9) % 12) or
            (g_m == "minor" and p_pc == (g_pc + 3) % 12)):
        s, rel = 0.3, "relative"
    elif g_pc == p_pc:
        s, rel = 0.2, "parallel"
    else:
        s, rel = 0.0, "miss"
    return {"gt": f"{gt['tonic']} {g_m}",
            "pred": f"{pred_key['tonic']} {p_m}",
            "score": s, "relation": rel}


# ------------------------------------------------------------------- voices
def pred_voice_label(n):
    for k in ("voice_id", "voice_tag", "voice"):
        if k in n and n[k] is not None:
            return str(n[k])
    return None


def score_voices(truth, pred_notes):
    if not pred_notes:
        return None
    gt_lookup = {}
    for n in truth["notes"]:
        gt_lookup.setdefault((n["onset_ms"], n["pitch"]), []).append(
            n["gt_voice"])

    # One ordered pass: (gt_voice, pred_label) pairs, matched by onset+pitch
    ordered = []
    for n in sorted(pred_notes,
                    key=lambda x: x.get("onset_ms", x.get("onset", 0))):
        lab = pred_voice_label(n)
        onset = n.get("onset_ms", n.get("onset"))
        if lab is None or onset is None or "pitch" not in n:
            continue
        stack = gt_lookup.get((int(round(onset)), n["pitch"]))
        if stack:
            ordered.append((stack.pop(0), lab))
    if not ordered:
        return None

    labels = sorted({lab for _, lab in ordered})
    gts = sorted({g for g, _ in ordered})
    if len(labels) > 8:
        return {"note": "too many predicted labels", "labels": len(labels)}

    # Best injective label -> part mapping (predicted ids have no canonical
    # order, so score under the optimal permutation)
    best_acc, best_map = -1.0, None
    slots = gts + [None] * max(0, len(labels) - len(gts))
    for perm in itertools.permutations(slots, len(labels)):
        mapping = dict(zip(labels, perm))
        acc = sum(1 for g, lab in ordered if mapping[lab] == g) / len(ordered)
        if acc > best_acc:
            best_acc, best_map = acc, mapping

    # Fragmentation: label switches inside a single true voice stream
    frags, last_lab = 0, {}
    for g, lab in ordered:
        if g in last_lab and last_lab[g] != lab:
            frags += 1
        last_lab[g] = lab

    return {"note_accuracy": round(best_acc, 4),
            "n_scored": len(ordered),
            "mapping": {k: (f"part{v}" if v is not None else "unmapped")
                        for k, v in best_map.items()},
            "fragmentation": frags}


# ----------------------------------------------------------------- spelling
def score_spelling(truth, pred_notes):
    if not pred_notes:
        return None
    gt_lookup = {}
    for n in truth["notes"]:
        sp = n["spelling"]
        gt_lookup.setdefault((n["onset_ms"], n["pitch"]), []).append(
            (sp["step"], sp["alter"]))
    hit = tot = 0
    for n in pred_notes:
        sp = n.get("spelling")
        if isinstance(sp, str):
            step = sp[0].upper()
            alter = sp.count("#") - sp.count("b") - sp.count("-")
            sp = {"step": step, "alter": alter}
        onset = n.get("onset_ms", n.get("onset"))
        if not sp or onset is None or "pitch" not in n:
            continue
        stack = gt_lookup.get((int(round(onset)), n["pitch"]))
        if stack:
            g = stack.pop()
            tot += 1
            if g == (sp.get("step"), int(sp.get("alter", 0))):
                hit += 1
    if not tot:
        return None
    return {"accuracy": round(hit / tot, 4), "n_scored": tot}


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Score pipeline output vs truth")
    ap.add_argument("--truth", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--tol", type=float, default=50.0,
                    help="downbeat match tolerance in ms (default 50)")
    ap.add_argument("--barlines-key", default=None)
    ap.add_argument("--json", default=None, help="write full report JSON")
    ap.add_argument("--csv", default=None, help="append one row to a CSV")
    ap.add_argument("--tag", default="", help="config label for the CSV row")
    args = ap.parse_args()

    with open(args.truth) as f:
        truth = json.load(f)
    with open(args.pred) as f:
        pred = json.load(f)

    report = {"truth": truth.get("id"), "pred_file": os.path.basename(args.pred),
              "tol_ms": args.tol, "tag": args.tag}

    pred_times, src = sniff_barlines(pred, args.barlines_key)
    pred_meter = sniff_meter(pred) if isinstance(pred, dict) else None
    pred_key = sniff_key(pred) if isinstance(pred, dict) else None
    pred_notes = pred.get("notes") if isinstance(pred, dict) else None

    if pred_times:
        report["downbeats"] = score_downbeats(truth, pred_times,
                                              pred_meter, args.tol)
        report["downbeats"]["source_field"] = src
    report["meter"] = score_meter(truth, pred_meter)
    report["key"] = score_key(truth, pred_key)
    report["voices"] = score_voices(truth, pred_notes) if pred_notes else None
    report["spelling"] = (score_spelling(truth, pred_notes)
                          if pred_notes else None)

    print(f"\n=== {truth.get('id')}  vs  {os.path.basename(args.pred)} ===")
    db = report.get("downbeats")
    if db:
        print(f"DOWNBEATS  P={db['precision']:.1%} R={db['recall']:.1%} "
              f"F1={db['f1']:.1%}  errors={db['errors']} "
              f"(FP={db['fp']} FN={db['fn']}, {db['n_pred']} pred / "
              f"{db['n_gt']} true, +-{int(args.tol)}ms, from {src})")
        for k, v in db["diagnostics"].items():
            print(f"           {k}: {v}")
    else:
        print("DOWNBEATS  (no barlines found in prediction)")
    if report["meter"]:
        m = report["meter"]
        line = f"METER      gt={m['gt_ts']}"
        if "pred_ts" in m:
            line += (f" pred={m['pred_ts']} strict={m['strict']} "
                     f"family={m['family']}")
        if "tactus_ratio" in m:
            line += f" tactus_ratio={m['tactus_ratio']}"
        print(line)
    if report["key"]:
        k = report["key"]
        print(f"KEY        gt={k['gt']} pred={k['pred']} "
              f"score={k['score']} ({k['relation']})")
    if report["voices"]:
        v = report["voices"]
        if "note_accuracy" in v:
            print(f"VOICES     acc={v['note_accuracy']:.1%} over "
                  f"{v['n_scored']} notes, fragmentation={v['fragmentation']}"
                  f"  mapping={v['mapping']}")
    if report["spelling"]:
        s = report["spelling"]
        print(f"SPELLING   acc={s['accuracy']:.1%} over {s['n_scored']} notes")

    parts = []
    if db:
        parts.append(f"errors={db['errors']} fp={db['fp']} fn={db['fn']} "
                     f"f1={db['f1']:.4f}")
    if report["meter"] and "strict" in report["meter"]:
        m = report["meter"]
        parts.append("ts=" + ("strict" if m["strict"] else
                              "family" if m["family"] else "miss"))
    if report["key"]:
        parts.append(f"key={report['key']['score']}")
    if report["voices"] and "note_accuracy" in report["voices"]:
        parts.append(f"voices={report['voices']['note_accuracy']:.4f}")
    print("RESULT " + " ".join(parts))

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=1)
    if args.csv:
        flat = {"tag": args.tag, "piece": truth.get("id")}
        if db:
            flat.update({"errors": db["errors"], "fp": db["fp"],
                         "fn": db["fn"], "f1": db["f1"]})
        if report["meter"] and "strict" in report["meter"]:
            flat["ts_strict"] = report["meter"]["strict"]
        if report["key"]:
            flat["key_score"] = report["key"]["score"]
        if report["voices"] and "note_accuracy" in report["voices"]:
            flat["voice_acc"] = report["voices"]["note_accuracy"]
        exists = os.path.exists(args.csv)
        with open(args.csv, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(flat.keys()))
            if not exists:
                w.writeheader()
            w.writerow(flat)


if __name__ == "__main__":
    main()
