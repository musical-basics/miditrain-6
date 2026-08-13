"""
MusicXML A/B comparison — generated score vs. reference score, NOTES ONLY.

Deliberately ignores everything the pipeline does not claim to reconstruct:
dynamics, articulations, fingerings, slurs, ornaments, beams, stems, lyrics,
measure counts, part/staff assignment and layout. What it compares is the
note content on a shared musical timeline:

  onset (in quarter notes from the start) + MIDI pitch

Two notes match when they share an onset within `--tol` quarter notes and the
same pitch. Matching is greedy nearest-onset, one-to-one, which is the same
discipline the corpus downbeat scorer uses (no double-counting).

For each matched pair it additionally reports, as SEPARATE non-fatal
statistics, whether the spelling (step+alter) and the notated duration agree —
those are Phase 5B/5A quality signals, not note-identity errors.

Usage:
    python3 compare_musicxml.py --generated g.musicxml --reference r.musicxml
    python3 compare_musicxml.py -g g.musicxml -r r.musicxml --json out.json

Requires music21 (the corpus venv):
    "corpus files/venv/bin/python3" compare_musicxml.py ...
"""
import argparse
import json
import sys


def load_notes(path):
    """Flatten a score to [{onset_q, pitch, step, alter, octave, dur_q,
    measure, voice}] sorted by (onset, pitch)."""
    from music21 import converter

    score = converter.parse(path)
    out = []
    for part_idx, part in enumerate(score.parts if score.parts else [score]):
        for el in part.flatten().notes:
            onset = float(el.offset)
            for p in el.pitches:
                out.append({
                    'onset_q': round(onset, 6),
                    'pitch': int(p.midi),
                    'step': p.step,
                    'alter': int(p.alter or 0),
                    'octave': int(p.octave) if p.octave is not None else 4,
                    'name': f'{p.step}{"#" * int(p.alter or 0)}'
                            f'{"b" * -int(p.alter or 0)}{p.octave}',
                    'dur_q': round(float(el.duration.quarterLength), 6),
                    'measure': _measure_of(el),
                    'part': part_idx,
                })
    out.sort(key=lambda n: (n['onset_q'], n['pitch']))
    return out


def _measure_of(el):
    m = el.getContextByClass('Measure')
    return int(m.number) if m is not None and m.number is not None else 0


def match(gen, ref, tol_q):
    """Greedy one-to-one match on (onset within tol, exact pitch).

    Returns (pairs, only_gen, only_ref) where pairs is a list of
    (gen_note, ref_note)."""
    by_pitch = {}
    for i, r in enumerate(ref):
        by_pitch.setdefault(r['pitch'], []).append(i)
    used = set()
    pairs, only_gen = [], []

    for g in gen:
        cands = by_pitch.get(g['pitch'], [])
        best, best_d = None, None
        for i in cands:
            if i in used:
                continue
            d = abs(ref[i]['onset_q'] - g['onset_q'])
            if d <= tol_q and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is None:
            only_gen.append(g)
        else:
            used.add(best)
            pairs.append((g, ref[best]))

    only_ref = [r for i, r in enumerate(ref) if i not in used]
    return pairs, only_gen, only_ref


def compare(gen_path, ref_path, tol_q=0.25):
    gen = load_notes(gen_path)
    ref = load_notes(ref_path)
    pairs, only_gen, only_ref = match(gen, ref, tol_q)

    matched = len(pairs)
    precision = matched / len(gen) if gen else 0.0
    recall = matched / len(ref) if ref else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)

    spelling_ok = sum(1 for g, r in pairs
                      if g['step'] == r['step'] and g['alter'] == r['alter'])
    duration_ok = sum(1 for g, r in pairs
                      if abs(g['dur_q'] - r['dur_q']) < 1e-6)
    onset_err = [abs(g['onset_q'] - r['onset_q']) for g, r in pairs]

    return {
        'generated_file': gen_path,
        'reference_file': ref_path,
        'tolerance_q': tol_q,
        'counts': {
            'generated': len(gen), 'reference': len(ref), 'matched': matched,
            'extra_in_generated': len(only_gen), 'missing_from_generated':
                len(only_ref),
        },
        'note_accuracy': {
            'precision': round(precision, 6), 'recall': round(recall, 6),
            'f1': round(f1, 6),
        },
        'secondary': {
            'spelling_agree': spelling_ok,
            'spelling_pct': round(spelling_ok / matched, 6) if matched else 0,
            'duration_agree': duration_ok,
            'duration_pct': round(duration_ok / matched, 6) if matched else 0,
            'mean_onset_err_q': round(sum(onset_err) / matched, 6)
                                if matched else 0,
            'max_onset_err_q': round(max(onset_err), 6) if onset_err else 0,
        },
        'pairs': [{
            'onset_q': g['onset_q'], 'ref_onset_q': r['onset_q'],
            'pitch': g['pitch'], 'gen_name': g['name'], 'ref_name': r['name'],
            'gen_dur_q': g['dur_q'], 'ref_dur_q': r['dur_q'],
            'gen_measure': g['measure'], 'ref_measure': r['measure'],
            'spelling_match': g['step'] == r['step'] and g['alter'] == r['alter'],
            'duration_match': abs(g['dur_q'] - r['dur_q']) < 1e-6,
        } for g, r in pairs],
        'extra': only_gen,
        'missing': only_ref,
    }


def main():
    ap = argparse.ArgumentParser(description='Compare two MusicXML scores (notes only)')
    ap.add_argument('-g', '--generated', required=True)
    ap.add_argument('-r', '--reference', required=True)
    ap.add_argument('--tol', type=float, default=0.25,
                    help='onset tolerance in quarter notes (default 0.25 = a 16th)')
    ap.add_argument('--json', default=None, help='write the full report here')
    args = ap.parse_args()

    try:
        rep = compare(args.generated, args.reference, args.tol)
    except ImportError:
        sys.exit('music21 required: run with "corpus files/venv/bin/python3"')

    c, a, s = rep['counts'], rep['note_accuracy'], rep['secondary']
    print(f"\n{'=' * 62}\nNOTE COMPARISON  (tolerance {rep['tolerance_q']}q)")
    print(f"  generated : {c['generated']} notes  ({rep['generated_file']})")
    print(f"  reference : {c['reference']} notes  ({rep['reference_file']})")
    print(f"  matched   : {c['matched']}")
    print(f"  extra     : {c['extra_in_generated']} (in generated, not in reference)")
    print(f"  missing   : {c['missing_from_generated']} (in reference, not in generated)")
    print(f"\n  PRECISION {a['precision']:.2%}   RECALL {a['recall']:.2%}   F1 {a['f1']:.2%}")
    print(f"\n  secondary (not note-identity):")
    print(f"    spelling agrees  {s['spelling_pct']:.1%} ({s['spelling_agree']}/{c['matched']})")
    print(f"    duration agrees  {s['duration_pct']:.1%} ({s['duration_agree']}/{c['matched']})")
    print(f"    onset error      mean {s['mean_onset_err_q']:.4f}q  max {s['max_onset_err_q']:.4f}q")
    print('=' * 62)

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(rep, f, indent=1)
        print(f'full report -> {args.json}')


if __name__ == '__main__':
    main()
