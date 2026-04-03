# Prompt: Restructuring the Voice Threader (Phase 2)

## Context

I'm building **MidiTrain**, a system that analyzes MIDI piano music in two phases:

- **Phase 1 (Harmonic Regime Detection)** — detects harmonic boundaries (chord changes) by tracking angular divergence on a pitch-class color wheel. This works well (~91% precision, ~85% recall). It has a clean mathematical foundation: one signal (centroid angle), one threshold (break angle), and a few sensitivity parameters.

- **Phase 2 (Voice Threading)** — separates polyphonic MIDI into 4 independent voice lines (Soprano, Alto, Tenor, Bass). This is the problem child.

The full codebase is attached as a repomix XML. The key files are:
- `voice_threader.py` — the current Phase 2 implementation
- `harmonic_regime_detector.py` — Phase 1 (for reference on what "clean" looks like)
- `export_etme_data.py` — the pipeline that runs Phase 1 → Phase 2
- `docs/voice_threading_issues.md` — documented issues and fixes

## The Problem

The voice threader uses **greedy left-to-right assignment** with an **8-term cost function**:

1. Collision (Pauli exclusion for overlapping notes)
2. Elasticity (pitch leap cost)
3. Temperature (time gap cost)
4. Momentum (direction reversal penalty)
5. Register gravity (pull toward ideal pitch lane)
6. Structural gravity (Phase 1 spike anchoring)
7. Topological ordering (voice crossing penalty)
8. Outer voice affinity (highest→soprano, lowest→bass)

On top of these 8 terms, there are now **7+ edge-case patches**:
- Monophonic run detection (exempts fast arpeggios from is_top/is_bottom)
- Inner continuation checks (prevents tremolo/repetition from triggering soprano/bass)
- Ornament grace (relaxes collision for short notes)
- Simultaneous onset special-casing (35.0 vs 80.0 Pauli hack)
- Outer voice repulsion for inner notes
- Unison immunity revocation
- Post-processing pass to fix V2/V3 flip-flops

Each patch was a reasonable fix for a specific failure case (e.g., Chopin's Revolutionary Etude has monophonic LH arpeggios that get classified as "soprano" during RH gaps). But together they form a **fragile decision tree** where fixing one texture risks breaking another.

## What I Want

I'd like you to think deeply about **how to restructure Phase 2 from the ground up**. The current approach is greedy assignment with increasingly complex heuristics. I suspect the fundamental issue is that **greedy left-to-right is the wrong abstraction for voice leading**.

Specific questions:

### 1. Global vs Greedy
Should voice assignment be formulated as a **global optimization** instead of greedy? For example:
- Min-cost flow / network flow
- Hungarian algorithm per time slice
- Dynamic programming over time windows
- Something else entirely?

What are the trade-offs for real-time (eventual live MIDI) vs batch processing?

### 2. What's the Real Objective Function?
The current cost function has 8 terms + patches because it's trying to capture "voice continuity" via local proxies. What's the **actual mathematical quantity** we should be optimizing? Some candidates:
- Minimize total voice crossings
- Minimize total pitch displacement across all voices
- Maximize smoothness of each voice's pitch contour
- Some combination?

Can this be stated as a single optimizable quantity rather than a weighted sum of heuristics?

### 3. Should Chord Clustering Be Separate?
Currently there's an 80ms chord-clustering preprocessing step that groups simultaneous notes before voice assignment. This constrains what the threader sees. Should clustering and assignment be unified? Or is there a better way to handle the boundary between "these notes are simultaneous" vs "these notes are sequential"?

### 4. The is_top/is_bottom Problem
The most fragile part of the current system is deciding which note is "soprano" vs "bass" at any given moment. This is trivial in block chords but breaks in:
- Monophonic arpeggios (only one note sounding → it's both "top" and "bottom")
- Crossed voices (tenor temporarily above alto)
- Register ambiguity (middle-register notes that could belong to any voice)

Is there a way to avoid this classification entirely and let the optimization naturally place notes in the right voices?

### 5. Architecture Recommendation
Given the constraints (piano MIDI, 4 voices, batch processing now with eventual live MIDI support), what architecture would you recommend? Please be specific about:
- The mathematical formulation
- The algorithm
- What parameters need tuning (ideally fewer than the current 8 weights + 7 patches)
- How it handles the textures that currently break: arpeggios, crossed voices, block chords, legato overlaps

## Musical Context

The pieces being analyzed are classical piano:
- **Beethoven's Pathétique Sonata** — thick sustained chords with inner voice movement, pedal bass
- **Chopin's Revolutionary Etude** — fast monophonic LH arpeggios spanning 3+ octaves, RH chords with gaps

The system must handle both textures without piece-specific tuning.

## Constraints
- The output of Phase 1 (harmonic regime boundaries) is available and can be used as input
- Notes arrive as (pitch, velocity, onset_ms, duration_ms) — standard MIDI
- Target: 4 voices (Soprano, Alto, Tenor, Bass), with overflow for 5+ note chords
- Must work in batch mode now, but should be architecturally compatible with eventual real-time / low-latency processing
