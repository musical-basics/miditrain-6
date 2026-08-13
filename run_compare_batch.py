"""
Batch producer for the /compare page: one run per corpus piece.

/compare needs a REFERENCE MusicXML per piece, and until now only the
Clementi sonatina had one (hand-supplied). The corpus, however, was built
by make_ground_truth.py from music21 sources — so the same sources can be
re-exported as MusicXML, giving every corpus piece a reference engraving
to diff the pipeline's output against.

  corpus id  ──music21──>  reference.musicxml   ┐
  corpus MIDI ──pipeline──> generated.musicxml  ┴──> run_xml_compare.py

Piece ids map back to music21 paths by undoing the factory's flattening
(`bach_bwv66.6` -> `bach/bwv66.6`); chorale_NNN ids come from the chorale
iterator, which is enumerated in the same order the factory used.

Usage:
    python3 run_compare_batch.py --pieces bach_bwv66.6,chorale_000
    python3 run_compare_batch.py --tier mixed          # piano-ish tier
    python3 run_compare_batch.py --split val --limit 10
    python3 run_compare_batch.py --all                 # every corpus piece

Each piece produces visualizer/public/compare/<id>/ exactly as
run_xml_compare.py does, so the existing page picks them up with no
changes. Already-built runs are skipped unless --force.
"""
import argparse
import csv
import json
import os
import subprocess
import sys

VENV_PY = os.path.join("corpus files", "venv", "bin", "python3")
CORPUS = os.path.join("corpus files", "corpus_full")
OUT_ROOT = os.path.join("visualizer", "public", "compare")
XML_CACHE = os.path.join("corpus_runs", "reference_xml")
SPLIT_FILE = os.path.join("benchmarks", "corpus_split.json")


def need_venv():
    if not os.path.exists(VENV_PY):
        raise SystemExit(
            f"corpus venv missing ({VENV_PY}). Create it with:\n"
            '  python3 -m venv "corpus files/venv"\n'
            '  "corpus files/venv/bin/pip" install music21 mido')


def corpus_id_for(pid):
    """Map a corpus piece id back to its music21 source identifier.

    The factory flattened 'bach/bwv66.6' -> 'bach_bwv66.6' and numbered
    Opus sub-scores as '<base>_opNNN'. Chorales were enumerated, not
    named, so those are resolved separately by index.
    """
    if pid.startswith("chorale_"):
        return ("chorale-index", int(pid.split("_")[1]))
    # Opus member: essenFolksong_altdeu10_op003 -> essenFolksong/altdeu10 #3
    if "_op" in pid and pid.rsplit("_op", 1)[1].isdigit():
        base, idx = pid.rsplit("_op", 1)
        return ("opus-index", (base.replace("_", "/", 1), int(idx)))
    # Plain path: first underscore is the collection separator; the rest
    # may itself contain underscores that were slashes (mozart_k155_movement1)
    return ("path", pid)


def export_reference_xml(pids, out_dir):
    """Write reference MusicXML for each id via music21. Returns {pid: path}."""
    os.makedirs(out_dir, exist_ok=True)
    todo = {p: os.path.join(out_dir, f"{p}.musicxml") for p in pids
            if not os.path.exists(os.path.join(out_dir, f"{p}.musicxml"))}
    have = {p: os.path.join(out_dir, f"{p}.musicxml") for p in pids
            if os.path.exists(os.path.join(out_dir, f"{p}.musicxml"))}
    if not todo:
        return have

    spec = [{"pid": p, "out": o, "kind": corpus_id_for(p)[0],
             "arg": corpus_id_for(p)[1]} for p, o in todo.items()]
    script = r'''
import json, sys
from music21 import corpus, converter, stream

spec = json.load(sys.stdin)
done = {}
chorale_cache = None

for item in spec:
    pid, out, kind, arg = item["pid"], item["out"], item["kind"], item["arg"]
    try:
        if kind == "chorale-index":
            if chorale_cache is None:
                chorale_cache = list(corpus.chorales.Iterator())
            sc = chorale_cache[arg]
        elif kind == "opus-index":
            base, idx = arg
            parsed = corpus.parse(base)
            sc = parsed.scores[idx] if isinstance(parsed, stream.Opus) else parsed
        else:
            # try progressively: exact, then underscores back to slashes
            cands = [arg, arg.replace("_", "/", 1), arg.replace("_", "/")]
            sc = None
            for c in cands:
                try:
                    sc = corpus.parse(c); break
                except Exception:
                    continue
            if sc is None:
                raise RuntimeError("no music21 source for " + arg)
        sc.write("musicxml", out)
        done[pid] = out
    except Exception as e:
        print("SKIP " + pid + ": " + str(e)[:160], file=sys.stderr)

print(json.dumps(done))
'''
    proc = subprocess.run([VENV_PY, "-c", script], input=json.dumps(spec),
                          capture_output=True, text=True)
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            if line.startswith("SKIP"):
                print("  " + line)
    try:
        have.update(json.loads(proc.stdout.strip().splitlines()[-1]))
    except Exception:
        print(f"  reference export failed: {proc.stderr.strip()[:300]}")
    return have


def load_pieces(args):
    with open(os.path.join(CORPUS, "manifest.csv"), newline="") as f:
        rows = [r for r in csv.DictReader(f) if "?" not in r.get("meters", "")]
    ids = [r["id"] for r in rows]

    if args.pieces:
        wanted = set(args.pieces.split(","))
        ids = [p for p in ids if p in wanted]
    elif args.split:
        with open(SPLIT_FILE) as f:
            split = json.load(f)
        keep = set(split[args.split])
        ids = [p for p in ids if p in keep]

    if args.tier:
        from make_corpus_split import tier_of
        ids = [p for p in ids if tier_of(p) == args.tier]
    if args.limit:
        ids = ids[:args.limit]
    return ids


def main():
    ap = argparse.ArgumentParser(description="Build /compare runs for corpus pieces")
    ap.add_argument("--pieces", default=None, help="comma-separated ids")
    ap.add_argument("--split", default=None, choices=["train", "val"])
    ap.add_argument("--tier", default=None, choices=["chorale", "essen", "mixed"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="every metered corpus piece")
    ap.add_argument("--engine", default="bus", choices=["bus", "thermo", "spike"])
    ap.add_argument("--phase2_model", default="greedy", choices=["greedy", "beam"])
    ap.add_argument("--algo", default="temperley", choices=["temperley", "krumhansl"])
    ap.add_argument("--force", action="store_true", help="rebuild existing runs")
    args = ap.parse_args()

    need_venv()
    if not (args.pieces or args.split or args.tier or args.all):
        ap.error("select pieces: --pieces / --split / --tier / --all")

    ids = load_pieces(args)
    if not ids:
        raise SystemExit("no pieces selected")

    if not args.force:
        skipped = [p for p in ids
                   if os.path.exists(os.path.join(OUT_ROOT, p, "manifest.json"))]
        ids = [p for p in ids if p not in skipped]
        if skipped:
            print(f"Skipping {len(skipped)} already-built run(s); --force to rebuild.")
    if not ids:
        raise SystemExit("nothing to do")

    print(f"Exporting reference MusicXML for {len(ids)} piece(s)...")
    refs = export_reference_xml(ids, XML_CACHE)
    missing = [p for p in ids if p not in refs]
    if missing:
        print(f"  no reference for {len(missing)}: {', '.join(missing[:5])}"
              + (" ..." if len(missing) > 5 else ""))
    ids = [p for p in ids if p in refs]

    ok, failed = [], []
    for i, pid in enumerate(ids, 1):
        midi = os.path.join(CORPUS, "midis", f"{pid}.mid")
        if not os.path.exists(midi):
            print(f"[{i}/{len(ids)}] {pid}: MIDI missing, skipped")
            failed.append(pid)
            continue
        print(f"[{i}/{len(ids)}] {pid}")
        proc = subprocess.run(
            [sys.executable, "run_xml_compare.py",
             "--midi", midi, "--xml", refs[pid], "--name", pid,
             "--engine", args.engine, "--phase2_model", args.phase2_model,
             "--algo", args.algo],
            capture_output=True, text=True)
        if proc.returncode == 0:
            ok.append(pid)
            for line in proc.stdout.splitlines():
                if "DOWNBEATS" in line or "HANDS" in line or "Hands" in line:
                    print("    " + line.strip())
        else:
            failed.append(pid)
            print(f"    FAILED: {proc.stderr.strip().splitlines()[-1][:200]}"
                  if proc.stderr.strip() else "    FAILED")

    print(f"\nBuilt {len(ok)} run(s), {len(failed)} failed.")
    if failed:
        print("  failed: " + ", ".join(failed[:10]))
    print("http://localhost:3000/compare")


if __name__ == "__main__":
    main()
