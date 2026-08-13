"""
Score the DECISIONS the engine actually makes, against a reference MusicXML.

Motivation: when the MIDI is a render of the same MusicXML, comparing pitch
and onset is close to tautological — the notes were never in question, so a
100% "note accuracy" measures the identity function, not the engine. What the
engine genuinely decides, and can therefore get wrong, is:

  1. HAND (staff) assignment  — Phase 2 voices collapsed to treble/bass.
     Ground truth = the reference's part index (part 0 = RH, part 1 = LH).
     Scored two ways: raw agreement, and agreement under the better of the
     two global part->staff mappings (so a wholesale swap is reported as a
     swap, not as 0%).
  2. DOWNBEATS / barlines      — do the engine's barlines land where the
     reference's measures begin? P/R/F1 at a tolerance, plus the measure
     length and time signature it inferred.
  3. BEAMING                   — for each pair of consecutive eighths-or-
     shorter in the same hand, do generated and reference agree on whether
     they are beamed together? (Beam groups are a metrical claim: they are
     derived from where the engine thinks the beats are.)
  4. NOTATED DURATION          — the written rhythm, per note.
  5. STEM DIRECTION            — reported, low stakes, engraving-only.

Deliberately NOT scored: dynamics, articulations, fingerings, slurs,
ornaments, lyrics, layout — none are reconstructed by the pipeline.

Requires music21 (the corpus venv).

Usage:
    "corpus files/venv/bin/python3" score_notation.py \
        --generated g.musicxml --reference r.musicxml [--json out.json]
    # barline scoring also needs the engine's grid:
    ... --grid corpus_runs/.../bus_pred.json --tol-ms 50
"""
import argparse
import json
import sys
from collections import Counter


def load(path):
    """Flatten to note records carrying the decisions we score."""
    from music21 import converter

    score = converter.parse(path)
    parts = list(score.parts) if score.parts else [score]
    notes = []
    for pi, part in enumerate(parts):
        for el in part.flatten().notes:
            beams = []
            if hasattr(el, 'beams') and el.beams is not None:
                beams = [b.type for b in el.beams.beamsList]
            # staff: prefer an explicit MusicXML <staff>, else the part index
            staff = getattr(el, 'staffNumber', None)
            for p in el.pitches:
                notes.append({
                    'onset_q': round(float(el.offset), 6),
                    'pitch': int(p.midi),
                    'part': pi,
                    'staff': int(staff) if staff else pi + 1,
                    'dur_q': round(float(el.duration.quarterLength), 6),
                    'type': el.duration.type,
                    'dots': el.duration.dots,
                    'beams': beams,
                    'beamed': bool(beams),
                    'stem': el.stemDirection,
                    'measure': _measure_of(el),
                })
    notes.sort(key=lambda n: (n['onset_q'], n['pitch']))
    return notes, score


def _measure_of(el):
    m = el.getContextByClass('Measure')
    return int(m.number) if m is not None and m.number is not None else 0


def pair_notes(gen, ref, tol_q=0.05):
    """One-to-one match on (pitch, onset). These are the SAME notes by
    construction when the MIDI came from the score, so this is an alignment
    step, not a score."""
    by_pitch = {}
    for i, r in enumerate(ref):
        by_pitch.setdefault(r['pitch'], []).append(i)
    used, pairs, unmatched = set(), [], []
    for g in gen:
        best, best_d = None, None
        for i in by_pitch.get(g['pitch'], []):
            if i in used:
                continue
            d = abs(ref[i]['onset_q'] - g['onset_q'])
            if d <= tol_q and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is None:
            unmatched.append(g)
        else:
            used.add(best)
            pairs.append((g, best))
    return pairs, unmatched, used


def score_hands(pairs, ref):
    """Hand assignment. Reference truth = part index; generated = staff.

    Reported raw AND under the best global mapping, because 'every note on
    the wrong staff' is a labelling convention issue, not 333 mistakes."""
    conf = Counter()
    for g, ri in pairs:
        conf[(g['staff'], ref[ri]['part'])] += 1

    gen_staves = sorted({k[0] for k in conf})
    ref_parts = sorted({k[1] for k in conf})
    total = sum(conf.values())

    # identity-ish mapping: generated staff 1 -> part 0, staff 2 -> part 1
    raw = sum(v for (gs, rp), v in conf.items() if (gs - 1) == rp)

    # best global permutation (only 2 hands, so just try both)
    swapped = sum(v for (gs, rp), v in conf.items() if (gs - 1) != rp)
    best = max(raw, swapped)

    per_hand = {}
    for rp in ref_parts:
        tot = sum(v for (gs, r), v in conf.items() if r == rp)
        hit = sum(v for (gs, r), v in conf.items() if r == rp and (gs - 1) == rp)
        per_hand['RH' if rp == 0 else 'LH'] = {
            'notes': tot, 'correct': hit,
            'accuracy': round(hit / tot, 6) if tot else 0.0,
        }

    return {
        'total': total,
        'correct': raw,
        'accuracy': round(raw / total, 6) if total else 0.0,
        'best_mapping_accuracy': round(best / total, 6) if total else 0.0,
        'mapping_is_swapped': swapped > raw,
        'per_hand': per_hand,
        'confusion': {f'gen_staff{gs}->ref_part{rp}': v
                      for (gs, rp), v in sorted(conf.items())},
        'gen_staves': gen_staves, 'ref_parts': ref_parts,
    }


def score_beaming(pairs, gen, ref):
    """Do generated and reference agree on which notes are beamed together?

    Compared as adjacency: for consecutive short notes within a hand, both
    sides either join them under one beam or they don't. This is a metrical
    claim — beam groups follow the beat structure the engine inferred.
    """
    # index pairs by (staff, onset) so we can walk each hand in time order
    gen_by_hand = {}
    for g, ri in pairs:
        gen_by_hand.setdefault(g['staff'], []).append((g, ref[ri]))
    for v in gen_by_hand.values():
        v.sort(key=lambda t: t[0]['onset_q'])

    agree = disagree = considered = 0
    examples = []
    for staff, seq in sorted(gen_by_hand.items()):
        for i in range(len(seq) - 1):
            (g1, r1), (g2, r2) = seq[i], seq[i + 1]
            # only meaningful for beamable (eighth or shorter) notes
            if g1['dur_q'] > 0.5 or r1['dur_q'] > 0.5:
                continue
            considered += 1
            g_join = _joined(g1, g2)
            r_join = _joined(r1, r2)
            if g_join == r_join:
                agree += 1
            else:
                disagree += 1
                if len(examples) < 40:
                    examples.append({
                        'staff': staff, 'measure': r1['measure'],
                        'onset_q': g1['onset_q'],
                        'generated_beamed': g_join, 'reference_beamed': r_join,
                    })

    return {
        'considered_adjacent_pairs': considered,
        'agree': agree, 'disagree': disagree,
        'accuracy': round(agree / considered, 6) if considered else None,
        'examples': examples,
    }


def _joined(a, b):
    """Are these two consecutive notes under one beam?"""
    if not a['beams'] or not b['beams']:
        return False
    # a beam continues across the pair when a is start/continue and b is
    # continue/stop
    return (a['beams'][0] in ('start', 'continue')
            and b['beams'][0] in ('continue', 'stop'))


def score_durations(pairs, ref):
    ok = sum(1 for g, ri in pairs if abs(g['dur_q'] - ref[ri]['dur_q']) < 1e-6)
    diffs = Counter()
    for g, ri in pairs:
        if abs(g['dur_q'] - ref[ri]['dur_q']) >= 1e-6:
            diffs[f"gen {g['dur_q']} vs ref {ref[ri]['dur_q']}"] += 1
    return {
        'total': len(pairs), 'correct': ok,
        'accuracy': round(ok / len(pairs), 6) if pairs else 0.0,
        'top_differences': dict(diffs.most_common(8)),
    }


def score_stems(pairs, ref):
    both = [(g, ref[ri]) for g, ri in pairs
            if g['stem'] in ('up', 'down') and ref[ri]['stem'] in ('up', 'down')]
    ok = sum(1 for g, r in both if g['stem'] == r['stem'])
    return {'compared': len(both), 'correct': ok,
            'accuracy': round(ok / len(both), 6) if both else None}


def score_downbeats(grid_path, ref_score, tol_ms, beat_ms=500.0):
    """Engine barlines vs the reference's measure starts.

    The reference is on the system-wide 120 BPM convention (quarter = 500ms),
    the same convention the pipeline reads MIDI under.
    """
    with open(grid_path) as f:
        grid = json.load(f)
    meter = grid.get('meter') if isinstance(grid.get('meter'), dict) else grid
    barlines = [b['time_ms'] if isinstance(b, dict) else b
                for b in (grid.get('barlines') or meter.get('barlines') or [])]

    truth = []
    part = ref_score.parts[0] if ref_score.parts else ref_score
    for m in part.getElementsByClass('Measure'):
        truth.append(float(m.offset) * beat_ms)

    # two-pointer 1:1 matching, same discipline as the corpus scorer
    tp = 0
    used = set()
    for b in barlines:
        best, bd = None, None
        for i, t in enumerate(truth):
            if i in used:
                continue
            d = abs(t - b)
            if d <= tol_ms and (bd is None or d < bd):
                best, bd = i, d
        if best is not None:
            used.add(best)
            tp += 1
    fp = len(barlines) - tp
    fn = len(truth) - tp
    prec = tp / len(barlines) if barlines else 0.0
    rec = tp / len(truth) if truth else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    ts = ref_score.flatten().getElementsByClass('TimeSignature')
    return {
        'predicted_barlines': len(barlines), 'true_measures': len(truth),
        'matched': tp, 'false_positives': fp, 'false_negatives': fn,
        'errors': fp + fn,
        'precision': round(prec, 6), 'recall': round(rec, 6),
        'f1': round(f1, 6), 'tolerance_ms': tol_ms,
        'predicted_time_signature': meter.get('time_signature'),
        'reference_time_signature': (f'{ts[0].numerator}/{ts[0].denominator}'
                                     if ts else None),
        'predicted_measure_ms': meter.get('measure_ms'),
    }


def main():
    ap = argparse.ArgumentParser(
        description='Score engine decisions (hands, downbeats, beaming, '
                    'rhythm) against a reference MusicXML')
    ap.add_argument('-g', '--generated', required=True)
    ap.add_argument('-r', '--reference', required=True)
    ap.add_argument('--grid', default=None,
                    help='engine grid JSON (bus/thermo/spike) for downbeats')
    ap.add_argument('--tol-ms', type=float, default=50.0)
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    try:
        gen, _ = load(args.generated)
        ref, ref_score = load(args.reference)
    except ImportError:
        sys.exit('music21 required: run with "corpus files/venv/bin/python3"')

    pairs, unmatched, used = pair_notes(gen, ref)

    report = {
        'generated_file': args.generated,
        'reference_file': args.reference,
        'alignment': {
            'generated_notes': len(gen), 'reference_notes': len(ref),
            'aligned': len(pairs),
            'unaligned_generated': len(unmatched),
            'unaligned_reference': len(ref) - len(used),
            'note': 'alignment only — the MIDI is a render of this score, so '
                    'pitch/onset agreement is expected and is NOT a result',
        },
        'hands': score_hands(pairs, ref),
        'beaming': score_beaming(pairs, gen, ref),
        'durations': score_durations(pairs, ref),
        'stems': score_stems(pairs, ref),
        # per-note staff errors, so the GUI can point at them on the score
        'wrong_hand': [{
            'onset_q': g['onset_q'], 'pitch': g['pitch'],
            'measure': ref[ri]['measure'],
            'generated_staff': g['staff'],
            'reference_staff': ref[ri]['part'] + 1,
        } for g, ri in pairs if g['staff'] != ref[ri]['part'] + 1],
    }
    if args.grid:
        report['downbeats'] = score_downbeats(args.grid, ref_score, args.tol_ms)

    h, b, d, s = (report['hands'], report['beaming'], report['durations'],
                  report['stems'])
    print('\n' + '=' * 66)
    print('ENGINE DECISION SCORECARD')
    print(f"  aligned {report['alignment']['aligned']}/"
          f"{report['alignment']['reference_notes']} notes "
          f"(alignment, not a score)")
    if 'downbeats' in report:
        db = report['downbeats']
        print(f"\n  DOWNBEATS   F1 {db['f1']:.1%}  errors {db['errors']} "
              f"(FP {db['false_positives']} / FN {db['false_negatives']}) "
              f"±{db['tolerance_ms']:g}ms")
        print(f"              time sig  predicted {db['predicted_time_signature']}"
              f"  vs reference {db['reference_time_signature']}")
    print(f"\n  HANDS       {h['accuracy']:.1%} "
          f"({h['correct']}/{h['total']})"
          + ('  [labels swapped]' if h['mapping_is_swapped'] else ''))
    for hand, v in h['per_hand'].items():
        print(f"              {hand}  {v['accuracy']:.1%} "
              f"({v['correct']}/{v['notes']})")
    if b['accuracy'] is not None:
        print(f"\n  BEAMING     {b['accuracy']:.1%} "
              f"({b['agree']}/{b['considered_adjacent_pairs']} adjacent pairs)")
    print(f"\n  DURATION    {d['accuracy']:.1%} ({d['correct']}/{d['total']})")
    for k, v in d['top_differences'].items():
        print(f"              {v:>4}x  {k}")
    if s['accuracy'] is not None:
        print(f"\n  STEMS       {s['accuracy']:.1%} ({s['correct']}/{s['compared']})"
              "   [engraving only]")
    print('=' * 66)

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(report, f, indent=1)
        print(f'full report -> {args.json}')


if __name__ == '__main__':
    main()
