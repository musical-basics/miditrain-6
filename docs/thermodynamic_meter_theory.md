# Step 2.5: Thermodynamic Meter Bootstrap — Theory

## The Problem

A composer doesn't discover meter by counting notes. They hear a phrase, feel where
it "lands," and impose a periodic frame around those landing points. Meter is not
a rhythmic property — it is a **structural byproduct of phrasing**, which is itself
a byproduct of **tension and release**.

The goal of Step 2.5 is to replicate this process computationally: translate the raw
musical elements (pitch, velocity, timing, voicing, harmony) into a small set of
**emergent thermodynamic variables**, simulate their evolution over time, detect the
moments where the musical system "freezes" (lands, resolves, cadences), and use the
periodicity of those freezing events to bootstrap the meter.

---

## Why Thermodynamics?

Phase 1 proved that mapping pitch intervals to angles on a color wheel and doing
vector addition lets harmonic identity **emerge** from physics — no chord lookup
tables, no if/then key-mapping rules. The HSL values are higher-order variables that
encode the combined effect of all intervals without enumerating them.

The thermodynamic model does the same thing for the **time domain**. Instead of
writing rules like "if bass note + high velocity + long duration + consonant harmony
→ downbeat," we compute Temperature, Viscosity, and Pressure, and the downbeat
**emerges** as a natural phase transition. Three variables replace a hundred rules.

The elegance: five raw properties (melody, harmony, timing, velocity, voicing)
collapse into three emergent variables (T, η, P). Three emergent variables produce
one structural signal (phase transitions). One structural signal implies the meter.

---

## The Four-Step Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: TRANSLATION                                        │
│  Raw musical elements → Thermodynamic particles              │
│  (pitch, velocity, onset, duration, voice, regime)           │
│       → per-note mass, kinetic energy, entropy, register     │
│                                                              │
│  Step 2: MICROCOSM                                           │
│  Particles simulated on a discrete time-grid                 │
│  matching the exact MIDI timing resolution                   │
│       → continuous T(t), η(t), P(t) field curves             │
│                                                              │
│  Step 3: PHASE DETECTION                                     │
│  Detect phase transitions from the thermodynamic field       │
│       → freezing events with exact timing + magnitude        │
│                                                              │
│  Step 4: METER APPROXIMATION                                 │
│  Use freezing event periodicity to infer meter               │
│       → time signature, BPM, barline grid                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Step 1: Translation — Musical Elements to Thermodynamic Particles

Every note in the MIDI becomes a thermodynamic particle with emergent properties
computed from Phase 1 (harmonic regime) and Phase 2 (voice assignment) outputs.

### 1.1 Per-Note Properties (Direct Translation)

| Musical Property | Thermodynamic Analog | Formula |
|---|---|---|
| **Velocity** (0–127) | Mass (m) | `m = velocity / 127.0` |
| **Duration** (ms) | Sustain inertia | `inertia = min(duration / 1000, 4.0)` (capped at 4s to prevent fermata distortion) |
| **Pitch** (0–127) | Register depth (d) | `d = (128 - pitch) / 128.0` (low notes → heavy, high notes → light) |
| **Voice Tag** (1–4) | Structural weight (w) | Voice 4 (Bass) = 3.0, Voice 1 (Soprano/Melody) = 2.0, Voices 2–3 (Inner) = 1.0 |
| **Regime State** | Harmonic anchoring | TRANSITION SPIKE = structural event marker |
| **Saturation** (Phase 1) | Harmonic clarity | High sat = clear tonal identity; low sat = ambiguous/chromatic |
| **Tonal Distance** (Phase 1) | Dissonance | Distance from nearest pure interval on color wheel |

### 1.2 Per-Note Compound Mass

Each note's total thermodynamic mass combines its raw properties:

```
M_note = m × inertia × (1 + d) × w
```

A forte (m=1.0), sustained (inertia=2.0), low (d=0.8), bass (w=3.0) whole note:
`M = 1.0 × 2.0 × 1.8 × 3.0 = 10.8`

A piano (m=0.3), short (inertia=0.1), high (d=0.2), inner voice (w=1.0) grace note:
`M = 0.3 × 0.1 × 1.2 × 1.0 = 0.036`

The bass note is 300× heavier. This is correct — it contributes 300× more structural
gravity to the downbeat.

### 1.3 Per-Note Kinetic Contribution

Each note contributes kinetic energy based on its **interval delta** from the
previous note in the same voice:

```
KE_note = |Δp| × (1 / Δt)
```

Where Δp is the pitch interval (semitones) and Δt is the time since the last note
in this voice (seconds). Fast large leaps = high kinetic energy. Slow stepwise
motion = low kinetic energy. Repeated notes (Δp=0) contribute zero kinetic energy
regardless of speed — they carry no new information.

---

## Step 2: Microcosm — The Thermodynamic Time-Grid

The microcosm is a discrete time-grid with bins matching the MIDI's temporal
resolution. Each bin accumulates the thermodynamic contributions of all notes
active at that moment, producing three continuous field curves.

### 2.1 Grid Resolution

```
BIN_SIZE = 25ms  (40 bins per second — sufficient for 32nd notes at 120 BPM)
```

The grid spans from the first note onset to the last note offset.

### 2.2 Temperature T(t) — Melodic Incoherence

**Temperature is NOT speed. Temperature is speed × disorder.**

A Chopin etude with torrential 16th-note arpeggios following a predictable pattern
has HIGH speed but LOW temperature — it's a crystal, not a gas. Free jazz
improvisation at the same speed has HIGH temperature because the intervals are
unpredictable.

**Computation per time bin:**

1. Collect all note onsets within the bin's window (±WINDOW/2).
2. Compute **Activity Rate**: `A(t) = note_count / window_seconds`
3. Compute **Interval Entropy**: Shannon entropy over the distribution of recent
   pitch deltas (Δp values) in a sliding lookback window.

   ```
   H(t) = -Σ p(Δp) × log₂(p(Δp))
   ```

   Where p(Δp) is the probability of each unique interval value in the recent
   window. Repeated identical intervals (arpeggios, scales) → low H. Random
   leaps → high H.

4. **Temperature**:
   ```
   T(t) = A(t) × H(t)
   ```

**Critical property:** A trill (alternating two notes) has H ≈ 1 bit regardless
of speed. A chromatic scale has H ≈ 0 (every interval is +1). A random melody
with all 12 intervals equally likely has H ≈ 3.58 bits. Temperature correctly
distinguishes patterned speed (cold crystal) from chaotic speed (hot gas).

### 2.3 Viscosity η(t) — Resistance to Harmonic Change

**Viscosity is NOT voice count. Viscosity is harmonic inertia — how much the
current state resists being pushed aside.**

A sustained bass pedal under a moving melody has enormous viscosity (one note, but
immovable). A tremolo chord has low viscosity despite many notes (it's agitated,
unstable). A resolved root-position triad has high viscosity (it's settled, at rest).

**Computation per time bin:**

1. For each note **actively sounding** at time t:
   ```
   η_contribution = M_note × stability × convergence
   ```

   Where:
   - `M_note` = compound mass (from Step 1.2)
   - `stability` = Phase 1 saturation / 100 (high sat = clear harmonic ID = stable)
   - `convergence` = 1.0 + (0.5 × other_voices_on_same_chord) — voices landing
     together on the same harmony amplify each other's inertia, like molecules
     locking into a crystal lattice

2. Sum across all active notes:
   ```
   η(t) = Σ_active η_contribution_i
   ```

**Critical property:** η naturally spikes at cadence points (heavy bass + resolved
harmony + multiple voices converging) and stays low during single-voice passages.
This is exactly what "harmonic heaviness" feels like.

### 2.4 Pressure P(t) — Textural Urgency

**Pressure captures the compression/urgency of the texture — many disordered events
crammed into a narrow space.**

From the ideal gas law (PV = nRT), adapted:

```
P(t) = n(t) × T(t) / V(t)
```

Where:
- `n(t)` = number of notes active at time t
- `T(t)` = temperature (kinetic disorder)
- `V(t)` = register span (highest active pitch − lowest active pitch + 1, in
  semitones). Minimum clamped to 1 to avoid division by zero.

**Critical property:** Chromatic contrary motion converging into a narrow register
produces extreme pressure — the music feels like it's about to explode. Open
voicing across 4 octaves with a simple pattern produces almost no pressure.
Pressure is what triggers the *demand* for resolution.

---

## Step 3: Phase Detection — Finding the Freezing Events

### 3.1 The Phase Diagram

With T and η as continuous signals, each moment occupies a region in phase space:

```
                    High η (Resists change)
                         │
           ┌─────────────┼─────────────┐
           │   FROZEN     │   CRYSTAL    │
           │  SOLID       │   SOLID      │
           │  Block chord │  Patterned   │
           │  Cadence     │  arpeggio    │
           │  Bass pillar │  Trill       │
     Low T ├──────────────┼──────────────┤ High T
           │   LIQUID     │   GAS        │
           │  Flowing     │  Chaotic     │
           │  melody      │  Free improv │
           │  Counterpoint│  Cadenza     │
           └──────────────┼──────────────┘
                    Low η (Yields easily)
```

Phase classification thresholds (calibrated per piece via percentile normalization):

| Phase | Condition |
|---|---|
| **Frozen Solid** | T < T_median AND η > η_75th |
| **Crystal** | T ≥ T_median AND η > η_75th |
| **Liquid** | T < T_75th AND η ≤ η_75th |
| **Gas** | T ≥ T_75th AND η ≤ η_75th |

### 3.2 Freezing Event Detection

A **freezing event** occurs when the system transitions INTO the Solid phase
(Frozen or Crystal) from any non-Solid phase. This is the thermodynamic analog
of a musical "landing" — a cadence, a structural downbeat, a phrase resolution.

**Detection algorithm:**

1. Walk the time-grid. Track the current phase at each bin.
2. When the phase transitions from Liquid/Gas → Solid:
   - Record the **onset time** of the freezing event.
   - Compute the **magnitude** of the phase transition:
     ```
     Freeze_Magnitude = Δη × (1 + P_before) × E_release
     ```
     Where:
     - `Δη = η_after - η_before` (how much viscosity spiked)
     - `P_before` = pressure immediately before the freeze (higher pressure =
       more dramatic resolution, like a dam breaking)
     - `E_release` = accumulated energy discharged (see 3.3)
   - Record the **duration** of the Solid phase (how long it stays frozen).

3. Filter: discard freezing events shorter than `MIN_FREEZE_MS` (e.g. 50ms) —
   these are transient mass fluctuations, not structural events.

### 3.3 The Energy Accumulator

The energy accumulator integrates tension over time and discharges at freezing
events:

```
E(t) = E(t-1) + T(t) × D(t) × dt
```

Where `D(t)` is dissonance, derived from Phase 1:
- `D(t) = tonal_distance(t) / 15.0 + (1.0 - saturation(t) / 100.0)`
- Tonal distance: how far from a pure interval (Phase 1 color wheel)
- Low saturation: ambiguous harmonic identity = chromatic tension

At each freezing event, the accumulator **discharges**:
```
E_release = E(t)
E(t) = 0  (reset — the tension has been resolved)
```

Large E_release values correspond to major structural arrivals (end of a long
tense passage). Small E_release values correspond to local phrase boundaries.
This naturally creates **hierarchical beat strength** without any concept of meter.

### 3.4 Tonic Vector Bonus

Phase 1 provides H_tonic (the macro-key's hue on the color wheel). A freezing
event that coincides with a harmonic snap back toward H_tonic receives a bonus
multiplier:

```
if angular_distance(current_hue, H_tonic) < angular_distance(previous_hue, H_tonic):
    # Moving TOWARD tonic — this is a tonal resolution
    tonic_bonus = 1.0 + (previous_distance - current_distance) / 180.0
else:
    tonic_bonus = 1.0  # neutral
```

Authentic cadences (V→I) produce the largest tonic bonus. Deceptive cadences
(V→vi) produce no bonus (energy redirected, not resolved).

### 3.5 Freezing Event Output

Each freezing event is output as:

```python
{
    "time_ms": int,           # Exact onset of the freeze
    "magnitude": float,       # Composite strength score
    "eta_spike": float,       # Raw viscosity jump
    "pressure_before": float, # Pre-freeze pressure
    "energy_released": float, # Accumulated tension discharged
    "tonic_bonus": float,     # Harmonic resolution multiplier
    "duration_ms": int,       # How long the solid phase persists
    "phase_from": str,        # "liquid" or "gas"
    "phase_to": str,          # "frozen_solid" or "crystal"
}
```

---

## Step 4: Meter Approximation

Freezing events replace raw Phase 1 spikes as the structural pillars for meter
inference. The periodicity of freezing events implies the time signature.

### 4.1 Dominant Period Detection

Compute autocorrelation of the freezing event signal (magnitude-weighted impulse
train) to find the dominant periodicity:

1. Build a magnitude-weighted impulse array on the time-grid.
2. Autocorrelate across lags from ~200ms to ~8000ms.
3. The first significant peak = measure length (or half-measure for duple meter).

### 4.2 Hierarchical Beat Strength

Freezing events naturally cluster at two scales:
- **Primary freezes** (large magnitude) → Beat 1 candidates
- **Secondary freezes** (smaller magnitude) → Beat 3 candidates (in 4/4) or
  mid-measure stress points

The ratio of primary-to-secondary freeze spacing reveals the meter type:
- 2:1 ratio → duple (4/4, 2/4)
- 3:1 ratio → triple (3/4, 6/8)
- No consistent secondary → simple pulse

### 4.3 Time Signature Derivation

1. **Measure length** from autocorrelation peak → `measure_ms`
2. **Tactus** from sub-freeze IOI clustering → `beat_ms`
3. `beats_per_measure = round(measure_ms / beat_ms)` snapped to {2, 3, 4, 6}
4. **Denominator** from BPM heuristic (same as current Phase 3)

### 4.4 Barline Projection

Same rubber-band approach as current Phase 3, but anchored to **freezing events**
instead of raw harmonic spikes:

1. Start from piece start (always Beat 1, Measure 1).
2. Advance by `measure_ms` each step.
3. If a freezing event falls within the snap window, warp the barline to it.
4. Otherwise, dead-reckon forward.
5. Pass 2: consistency repair — reject snapped barlines that create intervals
   deviating >15% from expected measure length, unless confirmed by a high-
   magnitude freeze.

### 4.5 Anti-Anchor: Gas Transparency

Barlines must **never** be placed inside a Gas region. If the projected barline
lands in a Gas phase, slide it to the nearest Liquid or Solid boundary. Gas
passages (ornamental runs, cadenzas) are structurally transparent — the meter
grid passes through them without anchoring.

---

## Architecture in Context

```
Phase 1: Harmonic Compass
  └── Hue, Saturation, Tonal Distance, H_tonic
  └── TRANSITION SPIKEs (harmonic rhythm)

Phase 2: Voice Threader
  └── 4-voice assignment (Soprano, Alto, Tenor, Bass)
  └── Structural anchoring to Phase 1

Step 2.5: Thermodynamic Meter Bootstrap    ← NEW
  └── Step 1: Translate notes → thermodynamic particles
  └── Step 2: Simulate T(t), η(t), P(t) on time-grid
  └── Step 3: Detect freezing events (phase transitions)
  └── Step 4: Infer meter from freezing event periodicity
  └── Output: time signature, BPM, barline grid, freezing events

Phase 3: Quantize + Notate
  └── Snap notes to the Step 2.5 grid
  └── Generate musical notation
```
