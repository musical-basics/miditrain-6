"""
MusicXML -> DreamFlow IntermediateScore (the format the VexFlow renderer eats).

Purpose: render the human-authored reference score side by side with the
pipeline's generated score using the SAME renderer, so any visual difference
is a real difference in the notes and not a difference in two renderers'
conventions.

Notes only, by design — this mirrors what the comparison scores. Dynamics,
articulations, fingerings, slurs, ornaments, lyrics and layout are dropped;
pitch, duration, dots, rests, staff/voice and measure structure are kept.

Requires music21 (the corpus venv).

Usage:
    "corpus files/venv/bin/python3" musicxml_to_score.py in.musicxml --out score.json
"""
import argparse
import json
import sys

# quarterLength -> (VexFlow duration code, dots)
VEX_DURATIONS = [
    (4.0, 'w', 0), (6.0, 'w', 1),
    (2.0, 'h', 0), (3.0, 'h', 1),
    (1.0, 'q', 0), (1.5, 'q', 1),
    (0.5, '8', 0), (0.75, '8', 1),
    (0.25, '16', 0), (0.375, '16', 1),
    (0.125, '32', 0), (0.1875, '32', 1),
    (0.0625, '64', 0),
]


def vex_duration(ql):
    if ql <= 0:
        return 'q', 0
    _, code, dots = min(VEX_DURATIONS, key=lambda d: abs(ql - d[0]))
    return code, dots


def vex_key(p):
    """music21 Pitch -> 'c#/4' plus the VexFlow accidental code."""
    step = p.step.lower()
    alter = int(p.alter or 0)
    acc = '#' * alter + 'b' * (-alter)
    octave = p.octave if p.octave is not None else 4
    return f'{step}{acc}/{octave}', (acc if acc else None)


def convert(path):
    from music21 import converter, key as m21key

    score = converter.parse(path)

    ts = score.flatten().getElementsByClass('TimeSignature')
    num = ts[0].numerator if ts else 4
    den = ts[0].denominator if ts else 4

    ks = score.flatten().getElementsByClass('KeySignature')
    key_name = 'C'
    if ks:
        k = ks[0]
        try:
            tonic = k.asKey()
            key_name = tonic.tonic.name.replace('-', 'b')
            if tonic.mode == 'minor':
                key_name += 'm'
        except Exception:
            key_name = 'C'

    parts = list(score.parts) if score.parts else [score]

    # measure number -> staff index -> voice index -> notes
    measures = {}
    for staff_idx, part in enumerate(parts[:2]):
        for m in part.getElementsByClass('Measure'):
            m_num = int(m.number) if m.number is not None else 0
            bucket = measures.setdefault(m_num, {}).setdefault(staff_idx, {})

            # music21 exposes explicit <voice> groups, or a flat stream
            voice_streams = list(m.voices) if m.voices else [m]
            for v_idx, vs in enumerate(voice_streams):
                notes = bucket.setdefault(v_idx, [])
                for el in vs.notesAndRests:
                    ql = float(el.duration.quarterLength)
                    code, dots = vex_duration(ql)
                    beat = float(el.offset) * (den / 4.0) + 1

                    if el.isRest:
                        notes.append({
                            'keys': ['b/4' if staff_idx == 0 else 'd/3'],
                            'duration': code + 'r',
                            'dots': dots,
                            'isRest': True,
                            'accidentals': [None],
                            'tiesToNext': [False],
                            'articulations': [],
                            'beat': beat,
                            'vfId': f'ref-r-{m_num}-{staff_idx}-{v_idx}-{el.offset}',
                        })
                        continue

                    keys, accs, ties = [], [], []
                    for p in el.pitches:
                        k, acc = vex_key(p)
                        keys.append(k)
                        accs.append(acc)
                        ties.append(bool(getattr(el, 'tie', None)
                                         and el.tie.type in ('start', 'continue')))
                    notes.append({
                        'keys': keys,
                        'duration': code,
                        'dots': dots,
                        'isRest': False,
                        'accidentals': accs,
                        'tiesToNext': ties,
                        'articulations': [],
                        'beat': beat,
                        'vfId': f'ref-n-{m_num}-{staff_idx}-{v_idx}-{el.offset}',
                    })

    out_measures = []
    for i, m_num in enumerate(sorted(measures)):
        mo = {
            'measureNumber': m_num,
            'staves': [{'staffIndex': 0, 'voices': []},
                       {'staffIndex': 1, 'voices': []}],
        }
        if i == 0:
            mo['staves'][0]['clef'] = 'treble'
            mo['staves'][1]['clef'] = 'bass'
            mo['timeSignatureNumerator'] = num
            mo['timeSignatureDenominator'] = den
            mo['keySignature'] = key_name

        for staff_idx, voices in measures[m_num].items():
            if staff_idx > 1:
                continue
            for v_idx, notes in sorted(voices.items()):
                if notes:
                    mo['staves'][staff_idx]['voices'].append(
                        {'voiceIndex': v_idx, 'notes': notes})

        # a staff with nothing in it still has to render
        for staff in mo['staves']:
            if not staff['voices']:
                staff['voices'].append({'voiceIndex': 0, 'notes': [{
                    'keys': ['b/4' if staff['staffIndex'] == 0 else 'd/3'],
                    'duration': 'wr', 'dots': 0, 'isRest': True,
                    'accidentals': [None], 'tiesToNext': [False],
                    'articulations': [], 'beat': 1,
                    'vfId': f'ref-empty-{m_num}-{staff["staffIndex"]}',
                }]})
        out_measures.append(mo)

    return {'measures': out_measures, 'sourceKey': key_name,
            'timeSignature': f'{num}/{den}'}


def main():
    ap = argparse.ArgumentParser(description='MusicXML -> IntermediateScore JSON')
    ap.add_argument('input')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    try:
        score = convert(args.input)
    except ImportError:
        sys.exit('music21 required: run with "corpus files/venv/bin/python3"')

    with open(args.out, 'w') as f:
        json.dump(score, f, indent=1)
    print(f"reference score: {len(score['measures'])} measures, "
          f"key {score['sourceKey']}, {score['timeSignature']} -> {args.out}")


if __name__ == '__main__':
    main()
