"""
Ground Truth Factory for MidiTrain.

Renders scores (music21 corpus or local MusicXML/kern files) into:
  1. Quantized MIDI in the 120 BPM tick convention (quarter note = 500ms,
     tick x 500.0 / tpq). TPQ = 480 so triplets and quintuplets land on
     integer ticks.
  2. A ground truth JSON per piece: downbeat times, anacrusis, meter map,
     key map, analyzed key, and per-note spelling + voice labels.
  3. manifest.csv for tier filtering (anacrusis, meter family, monophonic,
     voice-labeled, note count).

Honesty rules baked in:
  - Time signature and key signature MIDI meta events are STRIPPED by
    default (--keep_meta to disable). The pipeline under test must never
    be able to peek at the answer.
  - Repeats are expanded (sounding order), ties are merged into single
    sounding notes, grace notes are dropped and counted.

Usage:
  python3 make_ground_truth.py list --query "bach" --limit 20
  python3 make_ground_truth.py build --ids bach/bwv66.6 bach/bwv269
  python3 make_ground_truth.py build --preset demo
  python3 make_ground_truth.py build --preset chorales --limit 40
  python3 make_ground_truth.py build --files path/to/score.musicxml

Outputs land in --out (default: corpus_out/):
  corpus_out/midis/<id>.mid
  corpus_out/groundtruth/<id>.gt.json
  corpus_out/manifest.csv
"""
import argparse
import csv
import json
import os
import sys
from fractions import Fraction

TPQ = 480                 # ticks per quarter in rendered MIDI
MS_PER_QUARTER = 500.0    # the 120 BPM convention
DEFAULT_VELOCITY = 80

PRESETS = {
    # Small mixed set for smoke testing every tier at once.
    "demo": [
        "bach/bwv66.6",        # 4/4, one-beat anacrusis, SATB voice labels
        "bach/bwv269",         # 3/4, anacrusis, SATB
        "bach/bwv846",         # WTC I Prelude in C: pure arpeggio texture, harmonic rhythm per bar
        "joplin/maple_leaf_rag",  # 2/4, heavy syncopation stress test
    ],
    # Monophonic folk songs with meter labels: meter engine at scale,
    # no Phase 2 dependency. Each file is an Opus containing many songs.
    "essen": ["essenFolksong/altdeu10", "essenFolksong/ballad30"],
}


def ql_to_ms(ql):
    return int(round(float(ql) * MS_PER_QUARTER))


def ql_to_ticks(ql):
    return int(round(float(ql) * TPQ))


def load_scores(cid):
    """Yield (sub_id, score) pairs. Handles Opus files (many songs per file)."""
    from music21 import corpus, converter, stream
    if os.path.exists(cid):
        parsed = converter.parse(cid)
        base = os.path.splitext(os.path.basename(cid))[0]
    else:
        parsed = corpus.parse(cid)
        base = cid.replace("/", "_")
    if isinstance(parsed, stream.Opus):
        for i, sc in enumerate(parsed.scores):
            yield f"{base}_op{i:03d}", sc
    else:
        yield base, parsed


def prepare(score):
    """Expand repeats to sounding order, then merge tied notes."""
    try:
        expanded = score.expandRepeats()
        if expanded is not None:
            score = expanded
    except Exception:
        pass  # no repeats or unexpandable: use written order
    try:
        score = score.stripTies()
    except Exception:
        pass
    return score


def get_parts(score):
    parts = list(score.parts)
    return parts if parts else [score]


def extract_notes(score):
    """Flatten every part into note events with spelling and voice labels."""
    from music21 import chord as m21chord
    events = []
    graces = 0
    max_err = 0.0
    for p_idx, part in enumerate(get_parts(score)):
        pname = getattr(part, "partName", None) or f"Part{p_idx + 1}"
        for el in part.flatten().notes:
            if el.duration.isGrace or el.duration.quarterLength == 0:
                graces += 1
                continue
            onset_ql = el.offset
            dur_ql = el.duration.quarterLength
            for q in (onset_ql, dur_ql):
                max_err = max(max_err, abs(float(q) * TPQ - round(float(q) * TPQ)))
            vel = None
            try:
                vel = el.volume.velocity
            except Exception:
                pass
            vel = int(vel) if vel else DEFAULT_VELOCITY
            pitches = el.pitches if isinstance(el, m21chord.Chord) else [el.pitch]
            for pit in pitches:
                events.append({
                    "onset_ms": ql_to_ms(onset_ql),
                    "duration_ms": max(1, ql_to_ms(dur_ql)),
                    "onset_ticks": ql_to_ticks(onset_ql),
                    "duration_ticks": max(1, ql_to_ticks(dur_ql)),
                    "pitch": pit.midi,
                    "velocity": vel,
                    "spelling": {
                        "step": pit.step,
                        "alter": int(pit.alter or 0),
                        "octave": pit.octave,
                        "name": pit.nameWithOctave,
                    },
                    "gt_voice": p_idx,
                    "gt_voice_name": pname,
                })
    events.sort(key=lambda e: (e["onset_ticks"], -e["pitch"]))
    return events, graces, max_err


def extract_meter(score):
    """Downbeats, anacrusis, and a meter map from the first part's measures.

    Anacrusis rule: if the first measure is padded (paddingLeft > 0) or
    shorter than its bar duration, its START is not a downbeat. The first
    true downbeat is the offset of the following measure. Short FINAL
    measures still start on a downbeat and are kept.
    """
    from music21 import stream
    part0 = get_parts(score)[0]
    measures = list(part0.getElementsByClass(stream.Measure))
    if not measures:
        return [], 0, []

    m0 = measures[0]
    anacrusis = False
    try:
        bar_ql = m0.barDuration.quarterLength
        if (m0.paddingLeft and m0.paddingLeft > 0) or \
           (len(measures) > 1 and m0.duration.quarterLength < bar_ql):
            anacrusis = True
    except Exception:
        pass

    downbeat_measures = measures[1:] if anacrusis else measures
    downbeats_ms = sorted({ql_to_ms(m.offset) for m in downbeat_measures})
    anacrusis_ms = ql_to_ms(measures[1].offset) if anacrusis and len(measures) > 1 else 0

    meter_map = []
    current = None
    for m in measures:
        ts = m.timeSignature
        if ts is not None and (current is None or ts.ratioString != current):
            current = ts.ratioString
            meter_map.append({
                "start_ms": ql_to_ms(m.offset),
                "time_signature": ts.ratioString,
                "measure_ms": ql_to_ms(ts.barDuration.quarterLength),
                "beat_ms": ql_to_ms(ts.beatDuration.quarterLength),
                "beats_per_measure": ts.beatCount,
            })
    if not meter_map:
        # Fallback: TS attached to the stream rather than a Measure
        for ts in part0.flatten().getElementsByClass("TimeSignature"):
            if current is None or ts.ratioString != current:
                current = ts.ratioString
                meter_map.append({
                    "start_ms": ql_to_ms(ts.offset),
                    "time_signature": ts.ratioString,
                    "measure_ms": ql_to_ms(ts.barDuration.quarterLength),
                    "beat_ms": ql_to_ms(ts.beatDuration.quarterLength),
                    "beats_per_measure": ts.beatCount,
                })
    return downbeats_ms, anacrusis_ms, meter_map


def extract_keys(score):
    from music21 import stream
    part0 = get_parts(score)[0]
    key_map = []
    current = None
    for m in part0.getElementsByClass(stream.Measure):
        ks = m.keySignature
        if ks is not None and (current is None or ks.sharps != current):
            current = ks.sharps
            key_map.append({"start_ms": ql_to_ms(m.offset), "sharps": ks.sharps})
    analyzed = None
    try:
        k = score.analyze("key")
        analyzed = {
            "tonic": k.tonic.name,
            "mode": k.mode,
            "confidence": round(float(k.correlationCoefficient), 4),
        }
    except Exception:
        pass
    return key_map, analyzed


def is_monophonic(events):
    prev_end, prev_onset = -1, -1
    for e in sorted(events, key=lambda x: x["onset_ticks"]):
        if e["onset_ticks"] == prev_onset:
            return False
        if e["onset_ticks"] < prev_end - 1:
            return False
        prev_end = e["onset_ticks"] + e["duration_ticks"]
        prev_onset = e["onset_ticks"]
    return True


def write_midi(events, meter_map, key_map, path, keep_meta=False):
    import mido
    mid = mido.MidiFile(ticks_per_beat=TPQ)
    meta = mido.MidiTrack()
    mid.tracks.append(meta)
    meta.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    if keep_meta:
        for mm in meter_map:
            num, den = mm["time_signature"].split("/")
            meta.append(mido.MetaMessage(
                "time_signature", numerator=int(num), denominator=int(den),
                time=0))
        for km in key_map:
            pass  # key meta intentionally omitted even in keep_meta mode

    by_part = {}
    for e in events:
        by_part.setdefault(e["gt_voice"], []).append(e)

    for p_idx in sorted(by_part):
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage(
            "track_name", name=by_part[p_idx][0]["gt_voice_name"], time=0))
        msgs = []
        for e in by_part[p_idx]:
            msgs.append((e["onset_ticks"], 1, e["pitch"], e["velocity"]))
            msgs.append((e["onset_ticks"] + e["duration_ticks"], 0, e["pitch"], 0))
        msgs.sort(key=lambda m: (m[0], m[1]))  # offs before ons at same tick
        now = 0
        for tick, kind, pitch, vel in msgs:
            delta = tick - now
            now = tick
            if kind == 1:
                track.append(mido.Message("note_on", note=pitch,
                                          velocity=vel, time=delta))
            else:
                track.append(mido.Message("note_off", note=pitch,
                                          velocity=0, time=delta))
    mid.save(path)


def build_one(sub_id, score, out_dir, keep_meta=False):
    score = prepare(score)
    events, graces, max_err = extract_notes(score)
    if not events:
        raise ValueError("no notes extracted")
    if max_err > 1.0:
        raise ValueError(f"quantize error {max_err:.2f} ticks (exotic tuplets)")
    downbeats, anacrusis_ms, meter_map = extract_meter(score)
    key_map, analyzed = extract_keys(score)
    title = None
    try:
        title = score.metadata.title if score.metadata else None
    except Exception:
        pass

    midi_path = os.path.join(out_dir, "midis", f"{sub_id}.mid")
    gt_path = os.path.join(out_dir, "groundtruth", f"{sub_id}.gt.json")
    write_midi(events, meter_map, key_map, midi_path, keep_meta=keep_meta)

    gt = {
        "id": sub_id,
        "title": title,
        "convention": {"tpq": TPQ, "ms_per_quarter": MS_PER_QUARTER},
        "anacrusis_ms": anacrusis_ms,
        "downbeats_ms": downbeats,
        "meter_map": meter_map,
        "key_map": key_map,
        "analyzed_key": analyzed,
        "notes": [{k: v for k, v in e.items()
                   if k not in ("onset_ticks", "duration_ticks")}
                  for e in events],
        "stats": {
            "n_notes": len(events),
            "n_downbeats": len(downbeats),
            "graces_dropped": graces,
            "max_quantize_err_ticks": round(max_err, 4),
            "monophonic": is_monophonic(events),
            "n_parts": len({e["gt_voice"] for e in events}),
        },
    }
    with open(gt_path, "w") as f:
        json.dump(gt, f, indent=1)

    row = {
        "id": sub_id,
        "title": title or "",
        "meters": "|".join(m["time_signature"] for m in meter_map) or "?",
        "anacrusis_ms": anacrusis_ms,
        "n_notes": len(events),
        "n_downbeats": len(downbeats),
        "monophonic": gt["stats"]["monophonic"],
        "n_parts": gt["stats"]["n_parts"],
        "analyzed_key": (f"{analyzed['tonic']} {analyzed['mode']}"
                         if analyzed else ""),
    }
    return row


def cmd_build(args):
    out_dir = args.out
    os.makedirs(os.path.join(out_dir, "midis"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "groundtruth"), exist_ok=True)

    ids = list(args.ids or [])
    if args.preset == "chorales":
        from music21 import corpus
        for i, ch in enumerate(corpus.chorales.Iterator()):
            if args.limit and i >= args.limit:
                break
            ids.append(ch)  # already-parsed scores
    elif args.preset:
        ids = PRESETS[args.preset] + ids
    files = list(args.files or [])

    rows, skipped = [], []
    work = [(cid, None) for cid in ids if isinstance(cid, str)] + \
           [(None, sc) for sc in ids if not isinstance(sc, str)] + \
           [(f, None) for f in files]

    count = 0
    for cid, pre_parsed in work:
        try:
            pairs = ([(f"chorale_{count:03d}", pre_parsed)] if pre_parsed
                     else list(load_scores(cid)))
        except Exception as ex:
            skipped.append((cid, str(ex)))
            continue
        for sub_id, sc in pairs:
            if args.limit and len(rows) >= args.limit:
                break
            try:
                row = build_one(sub_id, sc, out_dir, keep_meta=args.keep_meta)
                rows.append(row)
                print(f"  [ok] {sub_id}: {row['n_notes']} notes, "
                      f"{row['n_downbeats']} downbeats, meters={row['meters']}, "
                      f"anacrusis={row['anacrusis_ms']}ms")
            except Exception as ex:
                skipped.append((sub_id, str(ex)))
                print(f"  [skip] {sub_id}: {ex}")
        count += 1

    man_path = os.path.join(out_dir, "manifest.csv")
    write_header = not os.path.exists(man_path)
    with open(man_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["id"])
        if write_header and rows:
            w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nBuilt {len(rows)} pieces, skipped {len(skipped)}. "
          f"Manifest: {man_path}")


def cmd_list(args):
    from music21 import corpus
    hits = corpus.search(args.query)
    for i, h in enumerate(hits):
        if i >= args.limit:
            break
        print(f"  {h.sourcePath}  |  {h.metadata.title if h.metadata else ''}")
    print(f"({len(hits)} total matches)")


def main():
    ap = argparse.ArgumentParser(description="MidiTrain ground truth factory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="render pieces to MIDI + ground truth")
    b.add_argument("--ids", nargs="*", help="corpus ids, e.g. bach/bwv66.6")
    b.add_argument("--files", nargs="*", help="local MusicXML/kern files")
    b.add_argument("--preset", choices=list(PRESETS) + ["chorales"])
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--out", default="corpus_out")
    b.add_argument("--keep_meta", action="store_true",
                   help="keep time signature meta in MIDI (leaky, off by default)")
    b.set_defaults(func=cmd_build)

    l = sub.add_parser("list", help="search the music21 corpus")
    l.add_argument("--query", required=True)
    l.add_argument("--limit", type=int, default=25)
    l.set_defaults(func=cmd_list)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
