"""
Phase 2 (Beam Search): Voice Threading via Time-Synchronous Beam Search

Replaces greedy left-to-right assignment with approximate dynamic programming.
Maintains a beam of K best hypotheses (parallel universes), branching each
note into 5 possible assignments (V1-V4 + Overflow), pruning to keep only
the cheapest K states.

Core insight: squared pitch elasticity (L2 norm) natively forces fast melodies
to stay on a single voice — no monophonic run patches needed.

Tuning: 5 weights, zero edge-case patches.
"""
import copy


class BeamState:
    """A single hypothesis: one possible assignment of all notes so far."""
    __slots__ = ('voices', 'cumulative_cost', 'history')

    def __init__(self):
        self.voices = [
            {'pitch': 0.0, 'end_time': -9999, 'active': False}
            for _ in range(4)
        ]
        self.cumulative_cost = 0.0
        self.history = {}  # note index -> voice_id (0-3 or 4=overflow)

    def clone(self):
        s = BeamState()
        s.voices = [v.copy() for v in self.voices]
        s.cumulative_cost = self.cumulative_cost
        s.history = self.history.copy()
        return s


class BeamVoiceThreader:
    """Phase 2: Beam Search Voice Threading."""

    def __init__(self, max_voices=4, beam_width=64):
        self.max_voices = max_voices
        self.beam_width = beam_width

        # 5 core weights
        self.W_COLLISION = 0.15       # Per-ms penalty for overlapping a ringing voice
        self.W_ELASTICITY = 0.08      # Squared pitch distance weight
        self.W_CROSSING = 40.0        # Penalty for voice order violation
        self.W_REGISTER = 0.3         # Pull toward ideal pitch lane
        self.W_OVERFLOW = 60.0        # Flat cost to dump a note to overflow

        self.LEGATO_GRACE_MS = 40     # Allow 40ms human legato overlap
        self.ANCHOR_DISCOUNT = 12.0   # Discount for Phase 1 anchors on outer voices

    def _calculate_transition_cost(self, note, v_idx, state, ideal_pitches, is_anchor):
        """Cost to assign `note` to voice `v_idx` in the given state."""
        if v_idx == self.max_voices:  # Overflow
            return self.W_OVERFLOW

        v = state.voices[v_idx]
        cost = 0.0

        # 1. COLLISION (Pauli Exclusion)
        overlap_ms = max(0, v['end_time'] - note.onset)
        if overlap_ms > self.LEGATO_GRACE_MS:
            cost += (overlap_ms - self.LEGATO_GRACE_MS) * self.W_COLLISION

        # 2. ELASTICITY (Squared Pitch Leap — L2 norm)
        # Only applies if the voice has been active (has a real pitch assignment)
        if v['active']:
            delta_p = note.pitch - v['pitch']
            cost += (delta_p ** 2) * self.W_ELASTICITY

        # 3. TOPOLOGY (Voice Crossing)
        for i, other_v in enumerate(state.voices):
            if i == v_idx:
                continue
            # Only penalize crossing against voices that are actually sounding
            if not other_v['active']:
                continue
            if note.onset < other_v['end_time'] + self.LEGATO_GRACE_MS:
                if v_idx > i and note.pitch > other_v['pitch']:
                    cost += self.W_CROSSING
                elif v_idx < i and note.pitch < other_v['pitch']:
                    cost += self.W_CROSSING

        # 4. REGISTER GRAVITY
        cost += abs(note.pitch - ideal_pitches[v_idx]) * self.W_REGISTER

        # 5. MACRO GRAVITY (Phase 1 anchor discount for outer voices)
        if is_anchor and v_idx in (0, self.max_voices - 1):
            cost -= self.ANCHOR_DISCOUNT

        return max(0.0, cost)

    def thread_particles(self, sorted_particles, regime_frames):
        """Beam search over all notes, sorted strictly by onset ASC, pitch DESC."""
        # Sort: onset ascending, pitch descending (highest first for natural unpacking)
        notes = sorted(sorted_particles, key=lambda p: (p.onset, -p.pitch))

        # Calibrate ideal pitch lanes from actual range
        if notes:
            pitch_min = min(p.pitch for p in notes)
            pitch_max = max(p.pitch for p in notes)
            pitch_range = max(pitch_max - pitch_min, 12)
            ideal_pitches = [
                pitch_max - (i * pitch_range / max(1, self.max_voices - 1))
                for i in range(self.max_voices)
            ]
        else:
            ideal_pitches = [72, 60, 48, 36]

        # Pre-compute Phase 1 anchor set for O(1) lookup
        anchor_times = set()
        if regime_frames:
            for f in regime_frames:
                if f['state'] == 'TRANSITION SPIKE!':
                    anchor_times.add(f['time'])

        def is_anchor(p):
            for at in anchor_times:
                if abs(at - p.onset) <= 50:
                    return True
            return False

        # Initialize beam with a single empty state, setting ideal pitches
        init_state = BeamState()
        for i in range(self.max_voices):
            init_state.voices[i]['pitch'] = ideal_pitches[i]
        beam = [init_state]

        total = len(notes)
        report_interval = max(1, total // 10)

        for idx, note in enumerate(notes):
            if idx % report_interval == 0 and idx > 0:
                print(f"  Beam search: {idx}/{total} notes processed ({len(beam)} states)")

            note_is_anchor = is_anchor(note)
            next_beam = []

            for state in beam:
                # Branch into max_voices + 1 universes (V1-V4 + Overflow)
                for v_idx in range(self.max_voices + 1):
                    delta = self._calculate_transition_cost(
                        note, v_idx, state, ideal_pitches, note_is_anchor
                    )
                    new_state = state.clone()
                    new_state.cumulative_cost += delta
                    new_state.history[idx] = v_idx

                    if v_idx < self.max_voices:
                        new_state.voices[v_idx]['pitch'] = note.pitch
                        new_state.voices[v_idx]['end_time'] = note.onset + note.duration
                        new_state.voices[v_idx]['active'] = True

                    next_beam.append(new_state)

            # Prune to beam width
            next_beam.sort(key=lambda s: s.cumulative_cost)
            beam = next_beam[:self.beam_width]

        # Extract best universe
        best = beam[0]
        print(f"  Beam search complete. Best cost: {best.cumulative_cost:.1f}")

        for idx, note in enumerate(notes):
            v_id = best.history.get(idx, 4)
            note.voice_id = v_id
            if v_id < self.max_voices:
                note.voice_tag = f"Voice {v_id + 1}"
            else:
                note.voice_tag = "Overflow (Chord)"

        return notes
