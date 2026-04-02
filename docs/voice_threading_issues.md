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

**Additional occurrence**: ~21500-22062ms — fast descending scale (77→75→74→72→70→69→68→65) is a single soprano melody, but 80ms chord clustering splits it into pairs. Within each pair V1 takes the first note, V2 gets the second. Same root cause: the threader sees chord pairs, not a continuous melodic run.

**Status**: Documented. Revisit after clearing other voice threading issues.
