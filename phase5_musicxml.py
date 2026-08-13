"""
Phase 5C: MusicXML Export
================================================================================
Turns the Phase 5A quantized notes into a standard MusicXML 4.0 score — the
back-propagation endpoint: MIDI in, engraved score out, in the same
interchange format a human-authored score uses.

Why a new phase instead of extending 5B: `phase5_notation.py` emits the
DreamFlow `IntermediateScore` (VexFlow-shaped: per-measure voices with
already-resolved rests, VexFlow duration codes, and a chronological
accidental filter). MusicXML wants absolute divisions, explicit
<backup>/<forward> between voices, and un-filtered accidentals. Exporting
from the quantized notes directly — reusing 5B's key detection and
enharmonic spelling engine as a library — keeps both writers honest about
their own format instead of translating one dialect into another.

Reads:  phase5_quantized_*.json (notes with n["quantized"]) + the grid file
        (any of phase3_grid_* / phase3_thermo_* / phase4_bus_*).
Writes: <out>.musicxml — one part, two staves (treble/bass), voices mapped
        exactly as Phase 5B maps them (V1/V2 treble, V3/V4 bass).

Usage:
    python3 phase5_musicxml.py <phase5_quantized_json> <grid_json> [--out X.musicxml] [--algo temperley|krumhansl] [--title T]
"""
import argparse
import json
import xml.etree.ElementTree as ET
from xml.dom import minidom

from phase5_notation import analyze_chunk_key, get_key_spellings

# Phase 5B's staff/voice map. MusicXML voice numbers are 1-based and unique
# across the part, so (staff, sub-voice) collapses to a single integer.
VOICE_MAP = {
    'Voice 1': (1, 1), 'Voice 2': (1, 2),
    'Voice 3': (2, 3), 'Voice 4': (2, 4),
    'Overflow (Chord)': (1, 1),
}
DEFAULT_VOICE = (1, 1)

# note type names by ratio to a whole note, longest first; each entry is
# (ratio, type_name, dots).
DURATION_TYPES = [
    (4.0, 'long', 0), (2.0, 'breve', 0),
    (1.0, 'whole', 0), (0.75, 'half', 1), (0.5, 'half', 0),
    (0.375, 'quarter', 1), (0.25, 'quarter', 0),
    (0.1875, 'eighth', 1), (0.125, 'eighth', 0),
    (0.09375, '16th', 1), (0.0625, '16th', 0),
    (0.046875, '32nd', 1), (0.03125, '32nd', 0),
    (0.015625, '64th', 0),
]

MODE_OF = {'m': 'minor'}


def duration_type(dur_divs, divisions_per_whole):
    """Nearest notated type+dots for a duration in divisions."""
    if divisions_per_whole <= 0 or dur_divs <= 0:
        return 'quarter', 0
    ratio = dur_divs / divisions_per_whole
    _, name, dots = min(DURATION_TYPES, key=lambda d: abs(ratio - d[0]))
    return name, dots


def key_fifths(best_key, acc_count):
    """Phase 5B returns e.g. ('Am', 0) or ('Eb', -3); MusicXML wants
    fifths + mode."""
    mode = 'minor' if best_key.endswith('m') else 'major'
    return acc_count, mode


def parse_spelling(step_acc, pitch):
    """('c#', offset) + MIDI pitch -> (step, alter, octave)."""
    spelling, oct_offset = step_acc
    step = spelling[0].upper()
    alter = spelling[1:].count('#') - spelling[1:].count('b')
    octave = (pitch // 12) - 1 + oct_offset
    return step, alter, octave


def load_grid(grid_path):
    with open(grid_path) as f:
        grid = json.load(f)
    if isinstance(grid.get('meter'), dict):
        meter = dict(grid['meter'])
        # a bus file keeps barlines at top level as well as inside meter
        if 'barlines' not in meter and 'barlines' in grid:
            meter['barlines'] = grid['barlines']
        grid = meter
    return grid


def build_musicxml(notes, grid, algorithm='temperley', title='MidiTrain Export',
                   part_name='Piano'):
    beats_per_measure = grid.get('beats_per_measure', 4)
    denominator = grid.get('denominator', 4)
    subdivision = grid.get('subdivision', 4)
    ticks_per_measure = beats_per_measure * subdivision

    # MusicXML <divisions> = divisions per QUARTER note. One Phase 5A tick
    # is 1/subdivision of a beat, and a beat is a 1/denominator note, so a
    # tick is a (1 / (subdivision*denominator)) fraction of a whole note.
    # Taking divisions = subdivision*denominator/4 makes one tick exactly one
    # division when that is an integer; otherwise scale up so ticks stay
    # integral (e.g. subdivision 3 in 4/4 -> divisions 3, tick = 1 division).
    ticks_per_whole = subdivision * denominator
    divisions = max(1, ticks_per_whole // 4 if ticks_per_whole % 4 == 0
                    else ticks_per_whole)
    divisions_per_whole = divisions * 4
    divs_per_tick = divisions_per_whole / float(ticks_per_whole)

    best_key, acc_count = analyze_chunk_key(notes, algorithm)
    spelling_map = get_key_spellings(acc_count)
    fifths, mode = key_fifths(best_key, acc_count)

    # group notes by measure
    by_measure = {}
    for n in notes:
        q = n.get('quantized')
        if not q:
            continue
        by_measure.setdefault(q.get('measure', 0), []).append(n)
    if not by_measure:
        raise SystemExit('no quantized notes to export')

    m_nums = sorted(by_measure)
    first_m = m_nums[0]

    score = ET.Element('score-partwise', version='4.0')
    work = ET.SubElement(score, 'work')
    ET.SubElement(work, 'work-title').text = title
    ident = ET.SubElement(score, 'identification')
    enc = ET.SubElement(ident, 'encoding')
    ET.SubElement(enc, 'software').text = 'MidiTrain Phase 5C'
    part_list = ET.SubElement(score, 'part-list')
    sp = ET.SubElement(part_list, 'score-part', id='P1')
    ET.SubElement(sp, 'part-name').text = part_name
    part = ET.SubElement(score, 'part', id='P1')

    for m_num in m_nums:
        measure = ET.SubElement(part, 'measure',
                                number=str(m_num - first_m + 1))
        if m_num == first_m:
            attrs = ET.SubElement(measure, 'attributes')
            ET.SubElement(attrs, 'divisions').text = str(divisions)
            k = ET.SubElement(attrs, 'key')
            ET.SubElement(k, 'fifths').text = str(fifths)
            ET.SubElement(k, 'mode').text = mode
            t = ET.SubElement(attrs, 'time')
            ET.SubElement(t, 'beats').text = str(beats_per_measure)
            ET.SubElement(t, 'beat-type').text = str(denominator)
            ET.SubElement(attrs, 'staves').text = '2'
            for staff_no, sign, line in ((1, 'G', 2), (2, 'F', 4)):
                c = ET.SubElement(attrs, 'clef', number=str(staff_no))
                ET.SubElement(c, 'sign').text = sign
                ET.SubElement(c, 'line').text = str(line)

        # Phase 5A's measure numbering is 0-based on some grids and 1-based on
        # others, and an anacrusis can push abs_tick_start negative. Derive the
        # measure's tick origin from the notes actually in it rather than
        # trusting either convention.
        starts = [n['quantized']['abs_tick_start'] for n in by_measure[m_num]]
        measure_start_tick = (min(starts) // ticks_per_measure) * ticks_per_measure \
            if starts else (m_num - first_m) * ticks_per_measure

        # bucket this measure's notes by (staff, voice)
        buckets = {}
        for n in by_measure[m_num]:
            staff, voice = VOICE_MAP.get(n.get('voice_tag'), DEFAULT_VOICE)
            buckets.setdefault((staff, voice), []).append(n)

        # Ensure both staves are represented so the part stays 2-staff even
        # in measures where one hand is silent.
        for staff in (1, 2):
            if not any(s == staff for s, _ in buckets):
                buckets[(staff, staff * 2 - 1)] = []

        cursor = 0  # divisions elapsed in this measure, MusicXML-wise

        for idx, (staff, voice) in enumerate(sorted(buckets)):
            v_notes = sorted(buckets[(staff, voice)],
                             key=lambda x: x['quantized']['abs_tick_start'])
            if idx > 0:
                # rewind to the start of the measure for the next voice
                if cursor > 0:
                    b = ET.SubElement(measure, 'backup')
                    ET.SubElement(b, 'duration').text = str(cursor)
                cursor = 0

            local = 0  # ticks consumed within the measure for this voice
            i = 0
            while i < len(v_notes):
                n = v_notes[i]
                q = n['quantized']
                start_local = max(0, q['abs_tick_start'] - measure_start_tick)
                if start_local >= ticks_per_measure:
                    i += 1  # belongs to a later bar; the grid disagrees
                    continue
                dur_ticks = max(1, q.get('duration_ticks', 1))
                # clip to the measure — Phase 5A can hand back a note that
                # sounds past the barline; MusicXML measures must sum.
                dur_ticks = min(dur_ticks, ticks_per_measure - start_local)
                if dur_ticks <= 0:
                    i += 1
                    continue

                if start_local > local:
                    gap = start_local - local
                    _emit_rest(measure, gap, divs_per_tick,
                               divisions_per_whole, staff, voice)
                    cursor += _divs(gap, divs_per_tick)
                    local = start_local

                # collect the chord: same voice, same start tick
                chord = [n]
                j = i + 1
                while (j < len(v_notes)
                       and v_notes[j]['quantized']['abs_tick_start']
                       == q['abs_tick_start']):
                    chord.append(v_notes[j])
                    j += 1

                dur_divs = _divs(dur_ticks, divs_per_tick)
                ntype, dots = duration_type(dur_divs, divisions_per_whole)
                for ci, cn in enumerate(chord):
                    _emit_note(measure, cn, spelling_map, dur_divs, ntype,
                               dots, staff, voice, is_chord=(ci > 0))
                cursor += dur_divs
                local = start_local + dur_ticks
                i = j

            if local < ticks_per_measure:
                gap = ticks_per_measure - local
                _emit_rest(measure, gap, divs_per_tick, divisions_per_whole,
                           staff, voice)
                cursor += _divs(gap, divs_per_tick)

    return score


def _divs(ticks, divs_per_tick):
    """ticks -> MusicXML divisions (one scale, used by notes and rests)."""
    return max(1, int(round(ticks * divs_per_tick)))


def _emit_note(measure, n, spelling_map, dur_divs, ntype, dots, staff, voice,
               is_chord):
    el = ET.SubElement(measure, 'note')
    if is_chord:
        ET.SubElement(el, 'chord')
    pitch = n['pitch']
    step, alter, octave = parse_spelling(spelling_map[pitch % 12], pitch)
    p = ET.SubElement(el, 'pitch')
    ET.SubElement(p, 'step').text = step
    if alter:
        ET.SubElement(p, 'alter').text = str(alter)
    ET.SubElement(p, 'octave').text = str(octave)
    ET.SubElement(el, 'duration').text = str(dur_divs)
    ET.SubElement(el, 'voice').text = str(voice)
    ET.SubElement(el, 'type').text = ntype
    for _ in range(dots):
        ET.SubElement(el, 'dot')
    ET.SubElement(el, 'staff').text = str(staff)


def _emit_rest(measure, gap_ticks, divs_per_tick, divisions_per_whole,
               staff, voice):
    """Fill a gap with rests. A gap that isn't a single notatable value is
    split greedily into the largest representable pieces, so the measure's
    durations still sum exactly."""
    remaining = gap_ticks
    guard = 0
    while remaining > 0 and guard < 64:
        guard += 1
        dur_divs = _divs(remaining, divs_per_tick)
        ntype, dots = duration_type(dur_divs, divisions_per_whole)
        exact = _type_divs(ntype, dots, divisions_per_whole)
        if exact > dur_divs:
            # rounded up past the gap — step down to the next shorter value
            ntype, dots = _largest_fitting(dur_divs, divisions_per_whole)
            exact = _type_divs(ntype, dots, divisions_per_whole)
        el = ET.SubElement(measure, 'note')
        ET.SubElement(el, 'rest')
        ET.SubElement(el, 'duration').text = str(exact)
        ET.SubElement(el, 'voice').text = str(voice)
        ET.SubElement(el, 'type').text = ntype
        for _ in range(dots):
            ET.SubElement(el, 'dot')
        ET.SubElement(el, 'staff').text = str(staff)
        used_ticks = exact / divs_per_tick
        remaining -= max(1e-9, used_ticks)
        if remaining < 1e-6:
            break


def _type_divs(ntype, dots, divisions_per_whole):
    ratio = next(r for r, name, d in DURATION_TYPES
                 if name == ntype and d == dots)
    return max(1, int(round(ratio * divisions_per_whole)))


def _largest_fitting(dur_divs, divisions_per_whole):
    for ratio, name, dots in DURATION_TYPES:
        if int(round(ratio * divisions_per_whole)) <= dur_divs:
            return name, dots
    return DURATION_TYPES[-1][1], DURATION_TYPES[-1][2]


def write(score, out_path):
    raw = ET.tostring(score, encoding='unicode')
    pretty = minidom.parseString(raw).toprettyxml(indent='  ')
    body = pretty.split('\n', 1)[1]
    doctype = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<!DOCTYPE score-partwise PUBLIC '
               '"-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
               '"http://www.musicxml.org/dtds/partwise.dtd">\n')
    with open(out_path, 'w') as f:
        f.write(doctype + body)


def main():
    ap = argparse.ArgumentParser(description='Phase 5C: quantized notes -> MusicXML')
    ap.add_argument('quantized')
    ap.add_argument('grid')
    ap.add_argument('--out', default=None)
    ap.add_argument('--algo', default='temperley',
                    choices=['temperley', 'krumhansl'])
    ap.add_argument('--title', default='MidiTrain Export')
    args = ap.parse_args()

    with open(args.quantized) as f:
        data = json.load(f)
    notes = [n for n in data.get('notes', []) if 'quantized' in n]
    grid = load_grid(args.grid)

    score = build_musicxml(notes, grid, args.algo, args.title)
    out = args.out or args.quantized.replace('phase5_quantized_',
                                             'phase5_musicxml_').replace(
        '.json', '.musicxml')
    write(score, out)
    print(f'Phase 5C: wrote {out} ({len(notes)} notes)')


if __name__ == '__main__':
    main()
