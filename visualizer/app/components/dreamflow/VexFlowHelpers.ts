// components/score/VexFlowHelpers.ts
//
// Shared constants, types, and helper functions used by VexFlowRenderer.
// Keeps the renderer component lean and focused on layout + rendering.

import { StaveNote, Articulation, GraceNote, GraceNoteGroup, Curve } from 'dreamflow'
import type { IntermediateNote } from './IntermediateScore'

// ─── Layout Constants ──────────────────────────────────────────────

export const MIN_STAVE_WIDTH = 250      // minimum width per measure
export const MAX_PAGE_WIDTH = 1200      // width before wrapping in paged mode
export const STAVE_Y_TREBLE = 40      // Y offset for treble stave
export const STAVE_SPACING = 120      // vertical space between treble and bass
export const LEFT_MARGIN = 20         // px left margin
export const SYSTEM_HEIGHT = 300      // total height for a grand staff system

// ─── Types ─────────────────────────────────────────────────────────

export type NoteData = {
    id: string
    measureIndex: number
    timestamp: number
    isRest?: boolean     // Whether this note is a rest (skip effects, but allow reveal)
    numerator?: number   // Time signature numerator for correct beat interpolation
    element: HTMLElement | null
    stemElement: HTMLElement | null
    // Pre-cached for animation loop (avoid per-frame DOM queries)
    pathsAndRects?: HTMLElement[]
    absoluteX?: number
    isRevealed?: boolean
    isActive?: boolean
    activeSince?: number
    deactivatedAt?: number
    animProgress?: number
    currentTransform?: string
    // MIDI-matched fields (baked by midiMatcher)
    pitches?: number[]        // MIDI pitch numbers from VexFlow keys (e.g. [60, 64, 67])
    velocity?: number         // Matched MIDI velocity (0-127)
    midiDurationSec?: number  // Matched MIDI note duration in seconds
    hasGrace?: boolean        // Whether this note has grace notes attached
}

export interface VexFlowRenderResult {
    measureXMap: Map<number, number>
    beatXMap: Map<number, Map<number, number>>
    noteMap: Map<number, NoteData[]>
    systemYMap: { top: number; height: number }
    measureCount: number
}

// ─── Note Helpers ──────────────────────────────────────────────────

/**
 * Create a VexFlow StaveNote from an IntermediateNote.
 * If stemDirection is provided (1=up, -1=down), use it instead of autoStem.
 */
export function createStaveNote(
    note: IntermediateNote,
    staffIndex: number,
    stemDirection?: number,
    clefOverride?: string,
): StaveNote {
    const clef = clefOverride || (staffIndex === 0 ? 'treble' : 'bass')

    if (stemDirection !== undefined) {
        return new StaveNote({
            keys: note.keys,
            duration: note.duration,
            clef,
            stemDirection,
        })
    }

    return new StaveNote({
        keys: note.keys,
        duration: note.duration,
        clef,
        autoStem: true,
    })
}

/**
 * Check if a note duration is beamable (8th note or shorter).
 */
export function isBeamable(duration: string): boolean {
    const baseDur = duration.replace(/[rd]/g, '')
    return ['8', '16', '32', '64'].includes(baseDur)
}

/**
 * Create and attach an articulation modifier to a StaveNote.
 */
export function addArticulation(staveNote: StaveNote, artCode: string): void {
    const art = new Articulation(artCode)
    staveNote.addModifier(art)
}

// ─── Tuplet Helpers ────────────────────────────────────────────────

export type TupletData = {
    notes: StaveNote[]
    actual: number
    normal: number
}

/**
 * Convert a VexFlow duration string to beats (in quarter-note units).
 */
export function durationToBeats(dur: string): number {
    const base = dur.replace(/[rd]/g, '')
    switch (base) {
        case 'w': return 4
        case 'h': return 2
        case 'q': return 1
        case '8': return 0.5
        case '16': return 0.25
        case '32': return 0.125
        default: return 1
    }
}

/**
 * Calculate total beat value for a voice's notes, accounting for dots
 * and existing tuplet time-modifications.
 */
export function calculateVoiceDuration(notes: IntermediateNote[]): number {
    let totalBeats = 0
    for (const n of notes) {
        let beats = durationToBeats(n.duration)
        let dotValue = beats / 2
        for (let d = 0; d < n.dots; d++) {
            beats += dotValue
            dotValue /= 2
        }
        if (n.tupletActual && n.tupletNormal) {
            beats = beats * n.tupletNormal / n.tupletActual
        }
        totalBeats += beats
    }
    return totalBeats
}

/**
 * Heuristic triplet detection.
 */
export function detectHeuristicTuplets(
    voiceNotes: IntermediateNote[],
    vfNotes: StaveNote[],
    existingTuplets: TupletData[],
    timeSigNum: number,
    timeSigDen: number,
    measureNumber: number,
): TupletData[] {
    const measureCapacity = timeSigNum * (4 / timeSigDen)
    const totalBeats = calculateVoiceDuration(voiceNotes)

    if (totalBeats <= measureCapacity + 0.01) return []

    const detected: TupletData[] = []
    const tupletNoteIds = new Set<StaveNote>()
    existingTuplets.forEach(t => t.notes.forEach(n => tupletNoteIds.add(n)))

    for (let ni = 0; ni <= voiceNotes.length - 3; ni++) {
        const n0 = voiceNotes[ni]
        const n1 = voiceNotes[ni + 1]
        const n2 = voiceNotes[ni + 2]
        const allEighths = n0.duration === '8' && n1.duration === '8' && n2.duration === '8'
        const noRests = !n0.isRest && !n1.isRest && !n2.isRest
        const notAlreadyTuplet = !tupletNoteIds.has(vfNotes[ni]) && !tupletNoteIds.has(vfNotes[ni + 1]) && !tupletNoteIds.has(vfNotes[ni + 2])
        const noTupletFlags = !n0.tupletStart && !n0.tupletStop && !n1.tupletStart && !n1.tupletStop && !n2.tupletStart && !n2.tupletStop

        if (allEighths && noRests && notAlreadyTuplet && noTupletFlags) {
            const tripletNotes = [vfNotes[ni], vfNotes[ni + 1], vfNotes[ni + 2]]
            detected.push({ notes: tripletNotes, actual: 3, normal: 2 })
            tripletNotes.forEach(n => tupletNoteIds.add(n))
        }
    }

    return detected
}

// ─── Grace Note Helpers ────────────────────────────────────────────

/**
 * Create a VexFlow GraceNoteGroup from IntermediateNote.graceNotes
 */
export function attachGraceNotes(
    mainNote: StaveNote,
    graceNotes: IntermediateNote[],
    staffIndex: number,
    clef?: string,
): void {
    if (graceNotes.length === 0) return

    const vfGraceNotes = graceNotes.map(gn => {
        const graceClef = clef || (staffIndex === 0 ? 'treble' : 'bass')
        const gnote = new GraceNote({
            keys: gn.keys,
            duration: gn.duration.replace(/[rd]/g, '') || '8', 
            clef: graceClef,
            slash: true, 
        })
        for (let ki = 0; ki < gn.accidentals.length; ki++) {
            const acc = gn.accidentals[ki]
            if (acc) gnote.addModifier(new Articulation(acc), ki)
        }
        if (gn.color) {
            gnote.setStyle({ fillStyle: gn.color, strokeStyle: gn.color });
        }
        return gnote
    })

    const graceGroup = new GraceNoteGroup(vfGraceNotes, true)
    mainNote.addModifier(graceGroup)
}

// ─── Slur Helpers ──────────────────────────────────────────────────

export interface SlurData {
    startNote: StaveNote
    slurNumber: number
}

export type ActiveSlurs = Map<number, SlurData>

export function processSlurs(
    note: IntermediateNote,
    staveNote: StaveNote,
    activeSlurs: ActiveSlurs,
): Curve[] {
    const completedCurves: Curve[] = []

    if (note.slurStops) {
        for (const slurNum of note.slurStops) {
            const slurData = activeSlurs.get(slurNum)
            if (slurData) {
                try {
                    const curve = new Curve(slurData.startNote, staveNote, {
                        cps: [{ x: 0, y: 20 }, { x: 0, y: 20 }],
                    })
                    completedCurves.push(curve)
                } catch (e) {
                    console.warn(`[SLUR] Failed to create curve for slur ${slurNum}:`, e)
                }
                activeSlurs.delete(slurNum)
            }
        }
    }

    if (note.slurStarts) {
        for (const slurNum of note.slurStarts) {
            activeSlurs.set(slurNum, { startNote: staveNote, slurNumber: slurNum })
        }
    }

    return completedCurves
}
