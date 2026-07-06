"""
Phase 4B: Notation Map
================================================================================
Key detection (Krumhansl / Temperley), enharmonic spelling, and conversion of
Phase 4A quantized notes into the DreamFlow IntermediateScore JSON consumed by
the visualizer's VexFlow notation renderer.

(Ported from miditrain-4's phase3c_notation.py; renumbered per
`plan for improvements.md` — quantize-and-notate is Phase 4. The old
"osmd_ready" output prefix was renamed: the renderer is VexFlow, not OSMD.)

Usage:
    python phase4_notation.py <phase4_quantized_json> [<phase3_grid_json>] [--algo temperley|krumhansl]

Output: visualizer/public/phase4_notation_{...}.json
"""
import json
import sys
import os
import math

# ─── KEY SIGNATURE & ENHARMONIC SPELLING ENGINE ──────────────────

def detect_key(pitch_classes, algorithm='krumhansl'):
    """
    Detects Key Signature using cognitive Pearson correlation.
    Supports Krumhansl-Schmuckler and Temperley (CBMS) profiles.
    Returns: (best_key_string, accidental_count)
    """
    if algorithm == 'temperley':
        # Temperley (1999) "Simple" profiles (aka CBMS)
        major_profile = [5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0]
        minor_profile = [5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0]
    else:
        # Standard Krumhansl-Schmuckler profiles
        major_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
        minor_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
    
    total = sum(pitch_classes)
    if total == 0: return 'C', 0
    pc = [p/total for p in pitch_classes]
    
    def pearson(x, y):
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        num = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
        den = math.sqrt(sum((a - mean_x)**2 for a in x) * sum((b - mean_y)**2 for b in y))
        return num / den if den != 0 else 0

    max_corr = -1
    best_key = 'C'
    best_acc = 0
    
    major_names = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    major_acc = [0, -5, 2, -3, 4, -1, 6, 1, -4, 3, -2, 5]
    
    # We map relative minors to their relative major equivalents for VexFlow String APIs
    minor_names = ['Cm', 'C#m', 'Dm', 'Ebm', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'Bbm', 'Bm']
    minor_acc = [-3, 4, -1, -6, 1, -4, 3, -2, 5, 0, -5, 2]
    
    for i in range(12):
        maj_p = major_profile[-i:] + major_profile[:-i]
        min_p = minor_profile[-i:] + minor_profile[:-i]
        
        corr_maj = pearson(pc, maj_p)
        corr_min = pearson(pc, min_p)
        
        if corr_maj > max_corr:
            max_corr = corr_maj
            best_key = major_names[i]
            best_acc = major_acc[i]
            
        if corr_min > max_corr:
            max_corr = corr_min
            best_key = major_names[(i + 3) % 12] 
            best_acc = minor_acc[i]
            
    return best_key, best_acc

def get_key_spellings(acc_count):
    """
    Generates a 12-pitch enharmonic spelling map corresponding to the detected key.
    Resolves boundary crossing (e.g., spelling a B3 as a Cb4).
    """
    base_notes = ['c', 'd', 'e', 'f', 'g', 'a', 'b']
    base_pitches = [0, 2, 4, 5, 7, 9, 11]
    
    sharp_idx = [3, 0, 4, 1, 5, 2, 6]
    flat_idx = [6, 2, 5, 1, 4, 0, 3]
    
    # Universal fallback pool minimizes visual noise for extreme non-diatonic chords
    universal_pool = {
        0: 'c', 1: 'c#', 2: 'd', 3: 'eb', 4: 'e', 5: 'f',
        6: 'f#', 7: 'g', 8: 'g#', 9: 'a', 10: 'bb', 11: 'b'
    }

    notes = list(base_notes)
    pitches = list(base_pitches)
    
    if acc_count > 0:
        for i in range(acc_count):
            notes[sharp_idx[i]] += '#'
            pitches[sharp_idx[i]] += 1
    elif acc_count < 0:
        for i in range(-acc_count):
            notes[flat_idx[i]] += 'b'
            pitches[flat_idx[i]] -= 1
            
    diatonic = {}
    for n, p in zip(notes, pitches):
        real_p = p % 12
        offset = 0
        if p < 0: offset = 1
        if p > 11: offset = -1
        diatonic[real_p] = (n, offset)
        
    spelling = {}
    for p in range(12):
        if p in diatonic:
            spelling[p] = diatonic[p]
        else:
            spelling[p] = (universal_pool[p], 0)
            
    return spelling

def get_key_defaults(acc_count):
    """
    Seeds the chronological accidental memory using the parent Key Signature default values.
    """
    sharp_idx = ['f', 'c', 'g', 'd', 'a', 'e', 'b']
    flat_idx = ['b', 'e', 'a', 'd', 'g', 'c', 'f']
    
    state = {n: 'n' for n in 'cdefgab'}
    if acc_count > 0:
        for i in range(acc_count):
            state[sharp_idx[i]] = '#'
    elif acc_count < 0:
        for i in range(-acc_count):
            state[flat_idx[i]] = 'b'
    return state

def analyze_chunk_key(notes, algorithm='krumhansl'):
    """
    Builds a velocity and duration weighted frequency histogram to pass to cognitive profile.
    """
    pitch_classes = [0.0] * 12
    for n in notes:
        vel = n.get('velocity', 64) / 127.0
        dur = n.get('quantized', {}).get('duration_ticks', 1)
        pitch_classes[n['pitch'] % 12] += (vel * dur)
    
    return detect_key(pitch_classes, algorithm)


# ─── VEXFLOW FORMATTER ───────────────────────────────────────────

def get_vex_duration(dur_ticks, ticks_per_measure, beats_per_measure):
    """Approximates VexFlow duration string from ticks."""
    ticks_per_whole = (ticks_per_measure / beats_per_measure) * 4
    if ticks_per_whole == 0: return 'q', 0
    ratio = dur_ticks / ticks_per_whole
    
    durs = [
        (1.0, 'w', 0), (0.75, 'h', 1), (0.5, 'h', 0), (0.375, 'q', 1), (0.25, 'q', 0),
        (0.1875, '8', 1), (0.125, '8', 0), (0.09375, '16', 1), (0.0625, '16', 0), (0.03125, '32', 0)
    ]
    
    closest = min(durs, key=lambda d: abs(ratio - d[0]))
    return closest[1], closest[2]

def build_dreamflow_score(notes, ticks_per_measure, beats_per_measure, time_sig_num, time_sig_den, algorithm='krumhansl'):
    """
    Transforms flat list of quantized notes into an IntermediateScore JSON structure.
    Integrates dynamic key signature derivation and chronologically filtered enharmonic spelling.
    """
    # 1. Macro Analysis: Calculate Key Signature to anchor the chunk matrix
    best_key, acc_count = analyze_chunk_key(notes, algorithm)
    
    # 2. Extract Enharmonic Spelling Tables
    key_spelling_map = get_key_spellings(acc_count)
    key_state = get_key_defaults(acc_count)

    measures_dict = {}
    for n in notes:
        m_num = n.get('quantized', {}).get('measure', 0)
        if m_num not in measures_dict:
            measures_dict[m_num] = []
        measures_dict[m_num].append(n)
        
    sorted_m_nums = sorted(measures_dict.keys())
    if not sorted_m_nums: return {"measures": []}

    measures_output = []
    
    voice_map = {
        'Voice 1': (0, 0), 'Voice 2': (0, 1),
        'Voice 3': (1, 0), 'Voice 4': (1, 1),
        'Overflow (Chord)': (0, 0)
    }

    for m_num in sorted_m_nums:
        m_notes = measures_dict[m_num]
        
        measure_obj = {
            "measureNumber": int(m_num) + 1,
            "staves": [
                {"staffIndex": 0, "voices": []},
                {"staffIndex": 1, "voices": []}
            ]
        }
        
        # Instantiate structural headers identically on the very first measure only
        if m_num == sorted_m_nums[0]:
            measure_obj["staves"][0]["clef"] = "treble"
            measure_obj["staves"][1]["clef"] = "bass"
            measure_obj["timeSignatureNumerator"] = time_sig_num
            measure_obj["timeSignatureDenominator"] = time_sig_den
            measure_obj["keySignature"] = best_key

        staff_voice_notes = {}
        for n in m_notes:
            v_tag = n.get('voice_tag', 'Overflow (Chord)')
            staff_idx, voice_idx = voice_map.get(v_tag, (0, 0))
            key = (staff_idx, voice_idx)
            if key not in staff_voice_notes:
                staff_voice_notes[key] = []
            staff_voice_notes[key].append(n)
            
        # 3. REDUNDANCY FILTER
        # Process sequential timelines per staff (instead of per voice) to prevent isolated 
        # voices from repeating active accidentals earlier altered in a different sub-voice.
        for staff_idx in [0, 1]:
            active_accidentals = {}
            staff_notes = [n for n in m_notes if voice_map.get(n.get('voice_tag', 'Overflow (Chord)'), (0, 0))[0] == staff_idx]
            staff_notes.sort(key=lambda x: x.get('quantized', {}).get('abs_tick_start', 0))
            
            for n in staff_notes:
                pitch = n['pitch']
                pc = pitch % 12
                spelling, oct_offset = key_spelling_map[pc]
                
                base_octave = (pitch // 12) - 1
                octave = base_octave + oct_offset
                
                letter = spelling[0]
                acc = spelling[1:] if len(spelling) > 1 else 'n'
                
                k = f"{letter}{octave}"
                current_acc = active_accidentals.get(k, key_state[letter])
                
                # Suppress the VexFlow accidental attribute if it matches the current musical history 
                if acc == current_acc:
                    n['_accidental'] = None
                else:
                    active_accidentals[k] = acc
                    # A return to the natural state overrides the key signature and requires an explicit 'n'
                    n['_accidental'] = acc if acc != 'n' else 'n'
                    
                n['_vex_key'] = f"{spelling}/{octave}"
        
        # 4. Construct Intermediate Voices
        for (staff_idx, voice_idx), v_notes in staff_voice_notes.items():
            v_notes.sort(key=lambda x: x.get('quantized', {}).get('abs_tick_start', 0))
            voices_list = measure_obj["staves"][staff_idx]["voices"]
            
            voice_obj = next((v for v in voices_list if v["voiceIndex"] == voice_idx), None)
            if not voice_obj:
                voice_obj = {"voiceIndex": voice_idx, "notes": []}
                voices_list.append(voice_obj)
            
            # Start of measure base tick
            current_tick = (m_num - sorted_m_nums[0]) * ticks_per_measure # Handle offset if first measure is not 0
            
            for vn in v_notes:
                q = vn.get('quantized', {})
                start_tick = q.get('abs_tick_start', current_tick)
                # Ensure we calculate gap relative to the measure bounds
                local_start = start_tick % ticks_per_measure
                local_current = current_tick % ticks_per_measure
                
                dur_ticks = q.get('duration_ticks', ticks_per_measure // beats_per_measure)
                
                # Fill implicit preceding gaps with Rests
                if local_start > local_current:
                    gap = local_start - local_current
                    dur_str, dots = get_vex_duration(gap, ticks_per_measure, beats_per_measure)
                    voice_obj["notes"].append({
                        "keys": ["b/4" if staff_idx == 0 else "d/3"],
                        "duration": dur_str + "r",
                        "dots": dots,
                        "isRest": True,
                        "accidentals": [None],
                        "tiesToNext": [False],
                        "articulations": [],
                        "beat": (local_current / (ticks_per_measure / beats_per_measure)) + 1,
                        "vfId": f"rest-{start_tick}-gap"
                    })
                
                dur_str, dots = get_vex_duration(dur_ticks, ticks_per_measure, beats_per_measure)
                
                note_obj = {
                    "keys": [vn.get('_vex_key', 'c/4')],
                    "duration": dur_str,
                    "dots": dots,
                    "isRest": False,
                    "accidentals": [vn.get('_accidental')],
                    "tiesToNext": [False],
                    "articulations": [],
                    "beat": (local_start / (ticks_per_measure / beats_per_measure)) + 1,
                    "vfId": f"n-{vn['pitch']}-{start_tick}"
                }
                
                if 'hue' in vn:
                    note_obj["color"] = f"hsl({vn['hue']}, 90%, 50%)"
                
                voice_obj["notes"].append(note_obj)
                current_tick = start_tick + dur_ticks

            # Close dangling measure gaps
            local_current = current_tick % ticks_per_measure
            if local_current > 0 and local_current < ticks_per_measure:
                gap = ticks_per_measure - local_current
                dur_str, dots = get_vex_duration(gap, ticks_per_measure, beats_per_measure)
                voice_obj["notes"].append({
                    "keys": ["b/4" if staff_idx == 0 else "d/3"],
                    "duration": dur_str + "r",
                    "dots": dots,
                    "isRest": True,
                    "accidentals": [None],
                    "tiesToNext": [False],
                    "articulations": [],
                    "beat": (local_current / (ticks_per_measure / beats_per_measure)) + 1,
                    "vfId": f"rest-{current_tick}-end"
                })
        
        # Ensure all staves render by instantiating empty whole notes
        for staff in measure_obj["staves"]:
            if not staff["voices"]:
                staff["voices"].append({
                    "voiceIndex": 0,
                    "notes": [{
                        "keys": ["b/4" if staff["staffIndex"] == 0 else "d/3"],
                        "duration": "wr",
                        "dots": 0,
                        "isRest": True,
                        "accidentals": [None],
                        "tiesToNext": [False],
                        "articulations": [],
                        "beat": 1,
                        "vfId": f"m-{m_num}-empty-rest"
                    }]
                })

        measures_output.append(measure_obj)
        
    return {"measures": measures_output}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python phase4_notation.py <phase4_quantized_json> [<phase3_grid_json>]")
        sys.exit(1)
        
    p3b_path = sys.argv[1]
    
    with open(p3b_path, 'r') as f:
        data = json.load(f)
        
    ticks_per_measure = 16 
    beats_per_measure = 4
    denominator = 4
    if len(sys.argv) >= 3:
        try:
            with open(sys.argv[2], 'r') as f:
                grid_data = json.load(f)
                # Accept a thermo meter file (keys nested under "meter")
                if isinstance(grid_data.get('meter'), dict):
                    grid_data = grid_data['meter']
                beats_per_measure = grid_data.get('beats_per_measure', 4)
                denominator = grid_data.get('denominator', 4)
                subdivision = grid_data.get('subdivision', 4)
                ticks_per_measure = beats_per_measure * subdivision
        except FileNotFoundError:
            pass

    notes = data.get('notes', [])
    valid_notes = [n for n in notes if 'quantized' in n]

    # ─── CLI PARSING ───
    algorithm = 'temperley'
    if '--algo' in sys.argv:
        idx = sys.argv.index('--algo')
        if idx + 1 < len(sys.argv):
            algorithm = sys.argv[idx + 1].lower()
    elif '-a' in sys.argv:
        idx = sys.argv.index('-a')
        if idx + 1 < len(sys.argv):
            algorithm = sys.argv[idx + 1].lower()

    score = build_dreamflow_score(valid_notes, ticks_per_measure, beats_per_measure, beats_per_measure, denominator, algorithm)
    
    basename = os.path.basename(p3b_path)
    out_name = basename.replace('phase4_quantized_', 'phase4_notation_')
    out_path = os.path.join(os.path.dirname(p3b_path), out_name)

    with open(out_path, 'w') as f:
        json.dump(score, f, indent=2)

    print(f"Phase 4B DreamFlow mapping complete! Detected Key: {score['measures'][0].get('keySignature', 'C')} (Algorithm: {algorithm}). Wrote to {out_path}")
