class Particle:
    """A single musical note, represented as a physical particle."""
    def __init__(self, pitch, velocity, onset_ms, duration_ms):
        self.pitch = pitch              # Frequency (f)
        self.velocity = velocity        # Power (P) / Mass
        self.onset = onset_ms           # Position in Time
        self.duration = duration_ms     # Sustained Energy
        self.id_score = 0.0             # Information Density (Calculated in Phase 2)
        self.voice_tag = "Unassigned"   # Melody, Harmony, or Portal

    def __repr__(self):
        return f"Particle(pitch={self.pitch}, vel={self.velocity}, onset={self.onset}ms, id={self.id_score:.1f}, tag='{self.voice_tag}')"
