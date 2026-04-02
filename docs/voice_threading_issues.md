# Voice Threading Issues

## Issue 1: Voice Splitting in 3→4 Voice Transitions (7000-8000ms region, Opt #1)

**Location**: ~7000-7500ms in pathetique_64s_chunk_optimized_1

**Symptom**: V2 (alto/blue) notes at pitch 51 appear below V3 (tenor/gold) notes at pitch 55, causing visual voice crossing.

**Root cause**: The passage transitions from 3 active voices to 4. Two closely-spaced top pitches (55 and 58) function musically as a single soprano voice (parallel thirds or a compound melody), but the 4-voice threader splits them into V1 and V3. This leaves V2 dormant. When V2 finally wakes up at 7125ms with pitch 51, it's below V3's sustained pitch 55 — creating the crossing.

**Proposed fix (deferred)**: Detect when two top notes are functioning as a single compound soprano voice and merge them into V1. This could be based on:
- Both notes within ~7 semitones (a fifth)
- Both moving in parallel motion
- No independent rhythmic activity distinguishing them

**Risk**: Merging could cause edge cases in true 4-voice passages where V1 and V2 are genuinely independent (e.g. fugal entries). Needs careful scoping.

**Status**: Documented. Revisit after clearing other voice threading issues.

## Issue 2: V1 Instability in Fast Melodic Runs (21500-22062ms, Opt #1)

**Location**: ~21500-22062ms in pathetique_64s_chunk_optimized_1

**Symptom**: A fast descending soprano scale (77→75→74→72→70→69→68→65, all 62ms notes) alternates V1/V2 on every other note. V1 is unstable — it should carry this entire line.

**Root cause**: The 80ms chord clustering window groups the fast run into pairs: (77,75), (74,72), (70,69). Within each pair, V1 takes the highest note, then V2 gets the second because V1 just consumed a note in the same cluster. The threader sees chord pairs, not a continuous melodic run.

**Why this matters**: V1 (soprano) and V4 (bass) are the structurally critical outer voices. They must be stable. V2/V3 instability is tolerable, but V1 flickering breaks the model.

**Partial fix applied (IFFY FIX)**: Monophonic run detection — pre-scans for sequences of 3+ consecutive solo notes (no simultaneous onsets within 5ms) and prevents them from being clustered together. Each solo run note becomes its own cluster, gets `is_top=True`, V1 wins.

**What it fixes**: Pure monophonic runs (21500→21687: 77→75→74→72) are now all V1.

**What it doesn't fix**: When the run passes through a chord onset (e.g. 21750 where pitch 70 coincides with chord tones 56/50/46), the mono bypass can't help — the note IS simultaneous. Pitch 70 gets clustered with the chord, loses `is_top` to a higher carryover note, and falls to V2. This may need a structural rethink of how clustering interacts with melodic continuation.

**Status**: Partially fixed. Remaining edge cases at chord intersections are structural.
