"""
Phase 4A: Micro-Quantize
================================================================================
Snaps ETME notes (with Phase 2 voice_tags) onto the Phase 3 barline grid.

(Ported from miditrain-4's phase3b_quantize.py; renumbered per
`plan for improvements.md` — quantize-and-notate is Phase 4.)

Reads:  etme_*.json (notes with voice_tag) + phase3_grid_*.json (barlines,
        beats_per_measure, subdivision, measure_ms, denominator)
Writes: visualizer/public/phase4_quantized_{...}.json — the full ETME data with
        n["quantized"] = {abs_tick_start, abs_tick_end, duration_ticks,
        measure, beat, sub_tick} added per note.

Usage:
    python phase4_quantize.py <etme_json> <phase3_grid_json>
"""
import json
import sys

def find_nearest_tick(time_ms, tick_map):
    """Finds the absolute tick index globally closest to `time_ms`."""
    if not tick_map:
        return 0
    # Binary search or simple linear scan. Since tick_map isn't huge, linear is fine.
    # tick_map is a list of (abs_tick, ms_time) sorted by ms_time.
    # Find the element with min abs(ms_time - time_ms)
    best_tick, best_ms = min(tick_map, key=lambda kv: abs(kv[1] - time_ms))
    return best_tick

def main(etme_path, grid_path):
    print(f"Loading ETME: {etme_path}")
    print(f"Loading Grid: {grid_path}")
    
    with open(etme_path, 'r') as f:
        etme_data = json.load(f)
    
    with open(grid_path, 'r') as f:
        grid_data = json.load(f)

    # Grid source can be a spike grid file (flat keys) or a thermo meter
    # file (phase3_thermo_*.json, keys nested under "meter").
    if isinstance(grid_data.get('meter'), dict):
        grid_data = grid_data['meter']

    notes = etme_data.get('notes', [])
    barlines = grid_data.get('barlines', [])
    beats_per_measure = grid_data.get('beats_per_measure', 4)
    subdivision = grid_data.get('subdivision', 4)  # 1 for quarters, 2 for 8ths, 4 for 16ths
    global_measure_ms = grid_data.get('measure_ms', 1000)

    ticks_per_measure = beats_per_measure * subdivision

    if not barlines:
        print("No barlines found in grid!")
        return

    # Ensure barlines are sorted by time_ms
    barlines.sort(key=lambda b: b['time_ms'])
    first_measure = barlines[0]['measure']

    # Step 1: Build Global Tick Map
    tick_map = []  # List of (abs_tick, time_ms)
    
    # Interpolate between contiguous barlines
    for i in range(len(barlines) - 1):
        b_start = barlines[i]
        b_end = barlines[i+1]
        
        m_start = b_start['measure']
        m_end = b_end['measure']
        
        start_ms = b_start['time_ms']
        end_ms = b_end['time_ms']
        
        duration = end_ms - start_ms
        measures_diff = m_end - m_start
        
        if measures_diff <= 0:
            continue
            
        ticks_in_gap = measures_diff * ticks_per_measure
        tick_duration = duration / max(1, ticks_in_gap)
        
        start_abs_tick = (m_start - first_measure) * ticks_per_measure
        
        for k in range(ticks_in_gap):
            tick_ms = start_ms + k * tick_duration
            tick_map.append((start_abs_tick + k, tick_ms))

    # Add the final barline's exact tick
    if barlines:
        last_b = barlines[-1]
        last_abs_tick = (last_b['measure'] - first_measure) * ticks_per_measure
        tick_map.append((last_abs_tick, last_b['time_ms']))

    tick_map.sort(key=lambda x: x[0])

    if not tick_map:
        return
        
    # Extrapolate backward for notes before the first barline
    first_tick, first_ms = tick_map[0]
    min_note_time = min((n['onset'] for n in notes), default=0)
    avg_tick_ms = global_measure_ms / max(1, ticks_per_measure)
    
    curr_t = first_tick - 1
    curr_ms = first_ms - avg_tick_ms
    while curr_ms > min_note_time - 1000:
        tick_map.insert(0, (curr_t, curr_ms))
        curr_t -= 1
        curr_ms -= avg_tick_ms

    # Extrapolate forward for notes after the last barline
    last_tick, last_ms = tick_map[-1]
    max_note_time = max((n['onset'] + n['duration'] for n in notes), default=0)
    
    curr_t = last_tick + 1
    curr_ms = last_ms + avg_tick_ms
    while curr_ms < max_note_time + 1000:
        tick_map.append((curr_t, curr_ms))
        curr_t += 1
        curr_ms += avg_tick_ms

    # Step 2: Strike Clusters (Rule 1 - Chord Glue)
    # Sort notes strictly by their onset time.
    notes.sort(key=lambda x: x['onset'])
    
    clusters = []
    current_cluster = []
    
    for n in notes:
        if not current_cluster:
            current_cluster.append(n)
        else:
            first_in_cluster_onset = current_cluster[0]['onset']
            # If within 45ms of the FIRST note of the cluster (or previous note? PRD says: "within <= 45ms of the previous note's onset")
            # FIX: Compare against the FIRST note [0] of the cluster to prevent unbounded growth
            if n['onset'] - current_cluster[0]['onset'] <= 45:
                current_cluster.append(n)
            else:
                clusters.append(current_cluster)
                current_cluster = [n]
    if current_cluster:
        clusters.append(current_cluster)

    # Calculate average onset for each cluster and snap it
    for cluster in clusters:
        avg_onset = sum(n['onset'] for n in cluster) / len(cluster)
        snapped_tick = find_nearest_tick(avg_onset, tick_map)
        for n in cluster:
            n['_snapped_cluster_tick'] = snapped_tick

    # Step 3: Sequence Preservation per Voice (Rule 3)
    voices = ['Voice 1', 'Voice 2', 'Voice 3', 'Voice 4', 'Overflow (Chord)']
    
    for v_tag in voices:
        v_notes = [n for n in notes if n.get('voice_tag') == v_tag]
        if not v_notes:
            continue
            
        last_tick = -999999
        last_cluster_id = None
        
        for n in v_notes:
            raw_tick = n['_snapped_cluster_tick']
            
            # Use Python's id() or similar to group chords. But wait, cluster is just a shared reference? 
            # We can uniquely identify the cluster by the original onset time or we can just say 
            # "if they had the same raw_tick previously and were within 45ms, they might be same cluster".
            # The PRD says "If Note A and Note B are in Voice 1, and are not part of the same Strike Cluster...".
            # Since we grouped them earlier, let's just use the `_snapped_cluster_tick` and note onset to tell if they were
            # the same cluster. Two notes are in the same cluster if they have the same `_snapped_cluster_tick` AND their original 
            # onsets were very close. Actually, let's tag them in Step 2.
            pass

    # Better logic for Step 3: Tag clusters explicitly
    cluster_id = 0
    for cluster in clusters:
        for n in cluster:
            n['_cluster_id'] = cluster_id
        cluster_id += 1

    for v_tag in voices:
        v_notes = [n for n in notes if n.get('voice_tag') == v_tag]
        # v_notes is already sorted by onset because notes was sorted
        last_occupied_tick = -999999
        last_occupied_cluster = -1
        
        for n in v_notes:
            desired_tick = n['_snapped_cluster_tick']
            
            if desired_tick <= last_occupied_tick and n['_cluster_id'] != last_occupied_cluster:
                # Force sequence preservation
                desired_tick = last_occupied_tick + 1
            
            n['quantized'] = {
                'abs_tick_start': desired_tick
            }
            last_occupied_tick = desired_tick
            last_occupied_cluster = n['_cluster_id']

    # Step 4: Minimum Duration Enforcement (Rule 2)
    for n in notes:
        # snap offset
        offset_ms = n['onset'] + n['duration']
        end_tick = find_nearest_tick(offset_ms, tick_map)
        start_tick = n['quantized']['abs_tick_start']
        
        if end_tick <= start_tick:
            end_tick = start_tick + 1
            
        n['quantized']['abs_tick_end'] = end_tick
        n['quantized']['duration_ticks'] = end_tick - start_tick
        
        # Hydrate topological coordinates
        abs_t = start_tick
        measure_offset = abs_t // ticks_per_measure
        remainder = abs_t % ticks_per_measure
        
        beat = (remainder // subdivision) + 1
        sub_tick = remainder % subdivision
        measure_num = first_measure + measure_offset
        
        n['quantized']['measure'] = measure_num
        n['quantized']['beat'] = beat
        n['quantized']['sub_tick'] = sub_tick
        
        # clean up temps
        n.pop('_snapped_cluster_tick', None)
        n.pop('_cluster_id', None)

    # Step 4.5: Voice Monophony Enforcement
    # Standard notation requires monophonic voice lines. Truncate overlapping pedal durations.
    for v_tag in voices:
        v_notes = [n for n in notes if n.get('voice_tag') == v_tag]
        # Sort strictly by quantized start tick
        v_notes.sort(key=lambda x: x['quantized']['abs_tick_start'])
        
        for i in range(len(v_notes) - 1):
            curr_n = v_notes[i]
            
            # Find the next note that strictly starts AFTER this one
            next_start = None
            for j in range(i + 1, len(v_notes)):
                if v_notes[j]['quantized']['abs_tick_start'] > curr_n['quantized']['abs_tick_start']:
                    next_start = v_notes[j]['quantized']['abs_tick_start']
                    break
            
            # Truncate duration to prevent visual and logical overlap
            if next_start is not None and curr_n['quantized']['abs_tick_end'] > next_start:
                curr_n['quantized']['abs_tick_end'] = next_start
                curr_n['quantized']['duration_ticks'] = next_start - curr_n['quantized']['abs_tick_start']

    # Step 5: Save JSON
    out_name = "visualizer/public/phase4_quantized_" + etme_path.split('/')[-1].replace('etme_', '')
    
    with open(out_name, 'w') as f:
        json.dump(etme_data, f, indent=2)
    print(f"Saved micro-quantized data to {out_name}")

    # Step 6: ASCII Verification Output (First 2 Measures)
    # We want to print Measure 1 and Measure 2 (from first_measure)
    print(f"\nMeasure {first_measure} & {first_measure+1} ({beats_per_measure}/{grid_data.get('denominator', 4)} Time) - Subdivisions: {subdivision} per beat ({ticks_per_measure} Ticks/Measure)")
    
    v_labels = {
        'Voice 1': 'V1 (Sop)',
        'Voice 2': 'V2 (Alt)',
        'Voice 3': 'V3 (Ten)',
        'Voice 4': 'V4 (Bas)'
    }
    
    NOTE_NAMES_FLAT = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B']
    def get_note_name(pitch):
        name = NOTE_NAMES_FLAT[pitch % 12]
        octave = (pitch // 12) - 1
        return f"{name}{octave}"
    
    for v_tag in ['Voice 1', 'Voice 2', 'Voice 3', 'Voice 4']:
        output_str = f"{v_labels[v_tag]}: "
        
        for m in [first_measure, first_measure + 1]:
            for t in range(ticks_per_measure):
                abs_tick_target = (m - first_measure) * ticks_per_measure + t
                
                # Find if any note in this voice starts on this tick
                hits = [n for n in notes if n.get('voice_tag') == v_tag and n['quantized']['abs_tick_start'] == abs_tick_target]
                
                if hits:
                    note_str = get_note_name(hits[0]['pitch'])
                    # pad to 2-3 chars
                    if len(note_str) > 4: note_str = note_str[:4]
                    output_str += f"[{note_str.ljust(3)}]--"
                else:
                    output_str += "[   ]--"
            
            output_str = output_str[:-2] # remove trailing dashes
            if m == first_measure:
                output_str += " | "
                
        print(output_str)
        

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python phase4_quantize.py <etme_json> <phase3_grid_json>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
