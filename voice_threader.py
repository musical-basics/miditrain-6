"""
Phase 2: Thermodynamic VoiceThreader
Polyphonic voice separation via thermodynamic pathfinding.

Uses Phase 1's Harmonic Regime data (Transition Spikes) as Macro-Gravity
to anchor structural notes into outer bounding voices.
"""
import math

class VoiceThread:
    """A continuous horizontal stream of particles (e.g., Soprano, Alto, Tenor, Bass)."""
    def __init__(self, voice_id):
        self.voice_id = voice_id
        self.particles = []
        self.last_pitch = None
        self.last_onset = -9999
        self.last_end_time = -9999
        self.last_is_structural = False
        self.momentum = 0.0  # +1 for ascending trajectory, -1 for descending
        self.ideal_pitch = None  # Set dynamically from actual pitch range


class VoiceThreader:
    """Phase 2: Polyphonic Voice Separation via Thermodynamic Pathfinding."""
    def __init__(self, max_voices=4):
        self.max_voices = max_voices

        # Thermodynamic Tuning Weights
        self.W_ELASTICITY = 1.5       # Cost per semitone of pitch stretch (Δp)
        self.W_TEMPERATURE = 2.0      # Cost per second of silence/cooling (Δt)
        self.W_MOMENTUM_PENALTY = 2.0 # Cost to abruptly reverse trajectory
        self.W_GRAVITY = -15.0        # Discount for aligning with Phase 1 Anchors
        self.W_SPAWN_PENALTY = 25.0   # Cost to initialize an empty thread
        self.W_REGISTER = 0.75        # Restoring force pulling threads back to their ideal lane
        self.W_COLLISION = 10.0       # Soft Pauli exclusion for pedal overlaps

        self.LEGATO_GRACE_MS = 40     # Allow 40ms of overlap for human legato

    def _calculate_connection_cost(self, p, thread, all_threads, is_structural, is_top=False, is_bottom=False, is_inner=False):
        """Calculates the energy (ΔE) required to append particle 'p' to 'thread'."""

        # Base case: Empty thread initialization
        if thread.last_pitch is None:
            # Register gravity acts heavily on initialization
            base_cost = (abs(p.pitch - thread.ideal_pitch) * self.W_REGISTER) + self.W_SPAWN_PENALTY
            
            # Forgive outer bounding notes for stretching to reach outer wires
            if is_top and thread.voice_id == 0:
                base_cost -= (abs(p.pitch - thread.ideal_pitch) * self.W_REGISTER)
            elif is_top and thread.voice_id != 0:
                base_cost += 20.0  # Top bounds forcibly repel from inner wires
                
            if is_bottom and thread.voice_id == self.max_voices - 1:
                base_cost -= (abs(p.pitch - thread.ideal_pitch) * self.W_REGISTER)
            elif is_bottom and thread.voice_id != self.max_voices - 1:
                base_cost += 20.0  # Bottom bounds forcibly repel from inner wires

            # Structural notes get a massive discount for waking up outer bounding wires
            if is_structural and not is_inner:
                if thread.voice_id == 0 or thread.voice_id == self.max_voices - 1:
                    base_cost += self.W_GRAVITY
                else:
                    # Penalty for putting heavy structural chords in inner filler voices
                    base_cost += abs(self.W_GRAVITY)
            return max(0.0, base_cost)

        # 1. COLLISION (Soft Pauli Exclusion)
        cost_collision = 0.0
        
        # Nullify collision for completely identical simultaneous onsets (Block Chords ringing polyphonically on the same track)
        if p.onset == thread.last_onset:
            # We apply a 35.0 Pauli Exclusion penalty to discourage a single string from arbitrarily swallowing a full chord.
            # This precisely overcomes the 40.0 'empty wire' inertia, guaranteeing empty adjacent strings wake up to capture harmony notes.
            # However, it remains vastly cheaper than the ~150+ collision cost of overlapping a non-simultaneous sustained string, 
            # allowing overflowing 5-note chords to naturally stack inside their closest active register.
            cost_collision = 35.0
        else:
            # Instead of throwing 'inf' for pedal overlaps, allow them but penalize them heavily.
            overlap_ms = thread.last_end_time - p.onset
            if overlap_ms > self.LEGATO_GRACE_MS:
                # Multiply by 10 to ensure collision behaves as a semi-hard wall (e.g. 500ms = 150 penalty)
                cost_collision = (overlap_ms / 1000.0) * self.W_COLLISION * 10.0
                # Protect structural anchors from being easily truncated by passing arpeggios
                if thread.last_is_structural:
                    cost_collision *= 2.0

        # 2. ELASTICITY (Pitch Leaps)
        delta_p = abs(p.pitch - thread.last_pitch)
        cost_elastic = delta_p * self.W_ELASTICITY

        # 3. TEMPERATURE (Time Gaps)
        # Logarithmic scale prevents long rests from becoming infinitely expensive.
        gap_s = max(0, p.onset - thread.last_end_time) / 1000.0
        cost_temp = math.log1p(gap_s) * self.W_TEMPERATURE

        # 4. MOMENTUM (Newton's First Law)
        cost_momentum = 0.0
        direction = p.pitch - thread.last_pitch
        if (direction > 0 and thread.momentum < 0) or (direction < 0 and thread.momentum > 0):
            cost_momentum = self.W_MOMENTUM_PENALTY

        # 5. REGISTER GRAVITY (Restoring Force)
        # Outer boundaries (1 & 4) possess weaker internal register bounds (0.5) because they natively span thicker envelopes.
        # Internal voices (2 & 3) possess strict register bounds (0.75) to tightly pack polyphony.
        weight = self.W_REGISTER
        if thread.voice_id == 0 or thread.voice_id == self.max_voices - 1:
            weight = 0.5
            
        cost_register = abs(p.pitch - thread.ideal_pitch) * weight
            
        # Top/Bottom structural bounds retain their elasticity, but non-structural inner voices invading the boundaries are severely punished
        if is_top and thread.voice_id != 0:
            outer = all_threads[0]
            outer_is_active = (outer.last_end_time >= p.onset - self.LEGATO_GRACE_MS)
            # If Soprano is actively singing legato, Unison Immunity is unequivocally revoked!
            if thread.last_pitch != p.pitch or outer_is_active:
                cost_register += 20.0
            
        if is_bottom and thread.voice_id != self.max_voices - 1:
            outer = all_threads[self.max_voices - 1]
            outer_is_active = (outer.last_end_time >= p.onset - self.LEGATO_GRACE_MS)
            # If Bass is actively sounding legato, Unison Immunity is revoked.
            # However, because Bass frequently rests while inner voices hold roots, this penalty is softer (+15.0) than the Soprano boundary (+20.0)
            if thread.last_pitch != p.pitch or outer_is_active:
                cost_register += 15.0

        # 6. STRUCTURAL INVADER REPULSION
        # Heavily penalize outer boundary voices attempting to natively snatch the internal filling wires
        cost_gravity = 0.0
        if is_inner and (thread.voice_id == self.max_voices - 1 or thread.voice_id == 0):
            # Only trigger inner-snatch repel if the outer wire isn't ALREADY holding this exact inner unision pitch!
            if thread.last_pitch != p.pitch:
                cost_gravity += 30.0
                
        # 7. STRICT TOPOLOGICAL ORDERING (Non-Crossing Constraint)
        # Prevents Voice 2 from diving beneath Voice 3's CURRENTLY RINGING pitch to 'assist' heavy chords
        cost_topology = 0.0
        for other in all_threads:
            if other.voice_id == thread.voice_id: 
                continue
                
            is_active = False
            # If the other thread's EXACT note overlaps with this evaluated note, it is actively occupying physical space!
            if other.last_end_time != -9999 and other.last_onset != -9999:
                overlap = max(0, other.last_end_time - p.onset)
                # If they share the exact onset, they are simultaneously evaluating inside the same block chord!
                if overlap > 0 or other.last_onset == p.onset:
                    is_active = True
                    
            if is_active and other.last_pitch is not None:
                if thread.voice_id < other.voice_id:
                    # Thread is a HIGHER voice (e.g. Alto vs Tenor). It CANNOT drop equal to or below other's pitch.
                    if p.pitch <= other.last_pitch:
                        cost_topology += 60.0
                elif thread.voice_id > other.voice_id:
                    # Thread is a LOWER voice. It CANNOT rise equal to or above other's pitch.
                    if p.pitch >= other.last_pitch:
                        cost_topology += 60.0
            
        return max(0.0, cost_collision + cost_elastic + cost_temp + cost_momentum + cost_register + cost_gravity + cost_topology)

    def thread_particles(self, sorted_particles, regime_frames):
        """Scans left-to-right, threading particles into the path of least resistance."""
        threads = [VoiceThread(i) for i in range(self.max_voices)]

        # Sort strictly by onset ascending, then pitch DESCENDING
        sorted_particles = sorted(sorted_particles, key=lambda p: (p.onset, -p.pitch))

        # Dynamically calibrate ideal_pitch from actual pitch range
        if sorted_particles:
            pitch_min = min(p.pitch for p in sorted_particles)
            pitch_max = max(p.pitch for p in sorted_particles)
            pitch_range = max(pitch_max - pitch_min, 12)  # At least one octave
            for t in threads:
                # V0 targets top of range, V(N-1) targets bottom
                t.ideal_pitch = pitch_max - (t.voice_id * (pitch_range / max(1, self.max_voices - 1)))

        i = 0
        while i < len(sorted_particles):
            # Collect chord cluster (within 50ms)
            chord_start = sorted_particles[i].onset
            chord = []
            while i < len(sorted_particles) and sorted_particles[i].onset - chord_start <= 50:
                chord.append(sorted_particles[i])
                i += 1

            # Assign notes greedily (highest to lowest).
            for p in chord:
                is_structural = self._is_phase1_anchor(p, regime_frames)
                
                is_top = False
                is_bottom = False
                is_inner = False
                if len(chord) > 1:
                    if p is chord[0]:
                        # It is the top struck note. But is it the top resonating note globally?
                        # Check actively sustaining wires.
                        physically_top = True
                        for t in threads:
                            if t.last_pitch is not None and t.last_end_time > p.onset:
                                if t.last_pitch > p.pitch:
                                    physically_top = False
                        if physically_top:
                            is_top = True
                            
                    elif p is chord[-1]:
                        physically_bottom = True
                        for t in threads:
                            if t.last_pitch is not None and t.last_end_time > p.onset:
                                if t.last_pitch < p.pitch:
                                    physically_bottom = False
                        
                        if physically_bottom and (p.pitch <= threads[-1].ideal_pitch + 24 or p.pitch < 60):
                            is_bottom = True
                            
                    if not is_top and not is_bottom:
                        is_inner = True
                        
                best_thread = None
                lowest_cost = float('inf')

                # Cost auction across all available threads
                for thread in threads:
                    cost = self._calculate_connection_cost(p, thread, threads, is_structural, is_top=is_top, is_bottom=is_bottom, is_inner=is_inner)
                    if cost < lowest_cost:
                        lowest_cost = cost
                        best_thread = thread

                if best_thread:
                    if best_thread.last_pitch is not None:
                        best_thread.momentum = math.copysign(1.0, p.pitch - best_thread.last_pitch) if p.pitch != best_thread.last_pitch else 0.0
                    
                    best_thread.particles.append(p)
                    best_thread.last_pitch = p.pitch
                    best_thread.last_onset = p.onset
                    # If this is a simultaneous block chord on the same thread, stretch the sustain envelope logically
                    best_thread.last_end_time = max(best_thread.last_end_time, p.onset + p.duration) if best_thread.last_end_time != -9999 else p.onset + p.duration
                    best_thread.last_is_structural = is_structural
                    
                    p.voice_tag = f"Voice {best_thread.voice_id + 1}"
                    p.voice_id = best_thread.voice_id
                else:
                    p.voice_tag = "Overflow (Chord)"
                    p.voice_id = -1

        return sorted_particles

    def _is_phase1_anchor(self, p, regime_frames):
        """Check if this particle's onset aligns with a TRANSITION SPIKE! regime frame."""
        if not regime_frames:
            return False
        closest = min(regime_frames, key=lambda f: abs(f["time"] - p.onset))
        if abs(closest["time"] - p.onset) <= 50 and closest["state"] == "TRANSITION SPIKE!":
            return True
        return False
