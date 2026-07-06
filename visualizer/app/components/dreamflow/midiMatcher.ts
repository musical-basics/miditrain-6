/**
 * midiMatcher.ts
 * 
 * Matches MIDI NoteEvent data onto VexFlow NoteData by converting
 * score positions (measure + beat fraction) → absolute time via anchors,
 * then finding the closest MIDI notes by time and pitch proximity.
 */

import type { NoteEvent, ParsedMidi, Anchor, BeatAnchor } from './types'
import type { NoteData } from './VexFlowHelpers'

// ─── VexFlow Key → MIDI Pitch Conversion ──────────────────────────

const NOTE_TO_SEMITONE: Record<string, number> = {
    'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11
}

/**
 * Convert a VexFlow key string (e.g. "c/4", "f#/5", "bb/3") to MIDI pitch number.
 * Returns undefined if the key can't be parsed.
 */
export function vexKeyToMidi(key: string): number | undefined {
    // VexFlow keys are formatted as "noteName/octave" e.g. "c/4", "f#/5", "eb/3"
    const parts = key.split('/')
    if (parts.length !== 2) return undefined

    const noteStr = parts[0].toLowerCase()
    const octave = parseInt(parts[1], 10)
    if (isNaN(octave)) return undefined

    const baseName = noteStr[0]
    const baseSemitone = NOTE_TO_SEMITONE[baseName]
    if (baseSemitone === undefined) return undefined

    // Handle accidentals
    let accidentalShift = 0
    const accidentalPart = noteStr.slice(1)
    if (accidentalPart === '#' || accidentalPart === '##') accidentalShift = accidentalPart.length
    else if (accidentalPart === 'b') accidentalShift = -1
    else if (accidentalPart === 'bb') accidentalShift = -2
    else if (accidentalPart === 'n') accidentalShift = 0

    // MIDI: C4 = 60, so C0 = 12
    return (octave + 1) * 12 + baseSemitone + accidentalShift
}

/**
 * Convert MIDI velocity (0-127) to an HSL CSS color string.
 * Same hue mapping as WaterfallRenderer: soft (purple, hue 270) → loud (red, hue 0).
 */
export function velocityToCSS(velocity: number): string {
    const v = Math.max(0, Math.min(127, velocity))
    let hue: number
    if (v <= 20) hue = 270
    else if (v >= 110) hue = 0
    else hue = 270 * (1 - ((v - 20) / 90))
    return `hsl(${Math.round(hue)}, 85%, 55%)`
}

/**
 * Convert a score position (measure + timestamp fraction) to absolute audio time
 * using the anchor/beat-anchor system.
 */
function scorePositionToTime(
    measure: number,
    timestamp: number, // fractional position 0..1 within measure
    anchors: Anchor[],
    beatAnchors: BeatAnchor[]
): number | undefined {
    if (anchors.length === 0) return undefined

    // Find the anchor for this measure and the next
    const sorted = [...anchors].sort((a, b) => a.measure - b.measure)
    let currentAnchor: Anchor | undefined
    let nextAnchor: Anchor | undefined

    for (let i = 0; i < sorted.length; i++) {
        if (sorted[i].measure <= measure) currentAnchor = sorted[i]
        if (sorted[i].measure > measure && !nextAnchor) nextAnchor = sorted[i]
    }

    if (!currentAnchor) return undefined

    // If we have beat anchors for this measure, use them for better precision
    const measureBeatAnchors = beatAnchors
        .filter(ba => ba.measure === measure)
        .sort((a, b) => a.beat - b.beat)

    if (measureBeatAnchors.length >= 2) {
        const timeSigNum = 4 
        const beatNumber = 1 + timestamp * timeSigNum

        let before: BeatAnchor | undefined
        let after: BeatAnchor | undefined
        for (const ba of measureBeatAnchors) {
            if (ba.beat <= beatNumber) before = ba
            if (ba.beat > beatNumber && !after) after = ba
        }

        if (before && after) {
            const frac = (beatNumber - before.beat) / (after.beat - before.beat)
            return before.time + frac * (after.time - before.time)
        }
        if (before) return before.time
    }

    if (nextAnchor && nextAnchor.measure > currentAnchor.measure) {
        const measureSpan = nextAnchor.measure - currentAnchor.measure
        const measureOffset = (measure - currentAnchor.measure + timestamp) / measureSpan
        return currentAnchor.time + measureOffset * (nextAnchor.time - currentAnchor.time)
    }

    return currentAnchor.time + timestamp * 2 
}

/**
 * Bake MIDI velocity and duration data onto NoteData entries by matching
 * score notes to MIDI notes via time and pitch proximity.
 */
export function bakeMidiOntoNotes(
    noteMap: Map<number, NoteData[]>,
    parsedMidi: ParsedMidi | null,
    anchors: Anchor[],
    beatAnchors: BeatAnchor[]
): void {
    if (!parsedMidi || parsedMidi.notes.length === 0 || anchors.length === 0) {
        noteMap.forEach(notes => notes.forEach(n => {
            n.velocity = undefined
            n.midiDurationSec = undefined
        }))
        return
    }

    const midiNotes = parsedMidi.notes 
    let matchCount = 0
    let missCount = 0

    noteMap.forEach((notes, measure) => {
        for (const note of notes) {
            if (note.isRest) continue

            const absTime = scorePositionToTime(measure, note.timestamp, anchors, beatAnchors)
            if (absTime === undefined) { missCount++; continue }

            let lo = 0, hi = midiNotes.length - 1
            while (lo < hi) {
                const mid = (lo + hi) >>> 1
                if (midiNotes[mid].startTimeSec < absTime - 0.3) lo = mid + 1
                else hi = mid
            }

            let bestMatch: NoteEvent | undefined
            let bestScore = Infinity

            for (let i = Math.max(0, lo - 5); i < Math.min(midiNotes.length, lo + 20); i++) {
                const mn = midiNotes[i]
                const timeDiff = Math.abs(mn.startTimeSec - absTime)
                if (timeDiff > 0.3) {
                    if (mn.startTimeSec > absTime + 0.3) break 
                    continue
                }

                let score = timeDiff
                if (note.pitches && note.pitches.length > 0) {
                    const pitchMatch = note.pitches.includes(mn.pitch)
                    if (pitchMatch) score -= 0.2 
                    else score += 0.1 
                }

                if (score < bestScore) {
                    bestScore = score
                    bestMatch = mn
                }
            }

            if (bestMatch) {
                note.velocity = bestMatch.velocity
                note.midiDurationSec = bestMatch.durationSec
                matchCount++
            } else {
                missCount++
            }
        }
    })

    console.log(`[MidiMatcher] Baked: ${matchCount} matched, ${missCount} missed`)
}
