// TypeScript interfaces for Ultimate Pianist
// Merged types from Synth + Score Follower

// ─── MIDI Data Types ───────────────────────────────────────────────

/** A single normalized MIDI note event with absolute timing */
export interface NoteEvent {
    id: string
    /** MIDI pitch: 21 (A0) to 108 (C8) */
    pitch: number
    /** Absolute start time in seconds */
    startTimeSec: number
    /** Absolute end time in seconds */
    endTimeSec: number
    /** Duration in seconds */
    durationSec: number
    /** Note velocity (0-127) */
    velocity: number
    /** Track index from MIDI file */
    trackId: number
}

/** Parsed MIDI file data */
export interface ParsedMidi {
    /** Song/file name */
    name: string
    /** Total duration in seconds */
    durationSec: number
    /** Flattened, sorted (by startTimeSec) note events */
    notes: NoteEvent[]
    /** Number of tracks */
    trackCount: number
    /** Tempo map entries */
    tempoChanges: { time: number; bpm: number }[]
}

// ─── Score Follower Types ──────────────────────────────────────────

/** A measure-level anchor mapping absolute time to a measure number */
export interface Anchor {
    measure: number
    time: number
}

/** A beat-level anchor mapping absolute time to a measure + beat */
export interface BeatAnchor {
    measure: number
    beat: number
    time: number
}

/** An exact rhythmic event extracted from MusicXML */
export interface XMLEvent {
    measure: number
    beat: number
    /** Cumulative beat position from start of piece (for beatsElapsed calc across measures) */
    globalBeat: number
    /** MIDI pitch numbers expected at this beat (e.g. [57, 64] for A3+E4 chord) */
    pitches: number[]
    /** Smallest note duration in quarter-note fractions (1=quarter, 0.5=eighth, 0.25=16th, 0.125=32nd) */
    smallestDuration: number
    /** Whether this beat has a fermata marking */
    hasFermata?: boolean
}
