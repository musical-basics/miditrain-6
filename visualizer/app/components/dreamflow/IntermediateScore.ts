// visualizer/app/components/dreamflow/IntermediateScore.ts

/**
 * IntermediateScore serves as the bridge between the MIDI processor
 * and our custom VexFlow rendering engine.
 */
export interface IntermediateScore {
    title?: string;
    measures: IntermediateMeasure[];
}

export interface IntermediateMeasure {
    /** 1-indexed measure number */
    measureNumber: number;

    /** Top number of the time signature (e.g., 3 for 3/4 time). Only present if it changes. */
    timeSignatureNumerator?: number;
    /** Bottom number of the time signature (e.g., 4 for 3/4 time). Only present if it changes. */
    timeSignatureDenominator?: number;

    /** VexFlow formatted key signature (e.g., 'G', 'Fm', 'C'). Only present if it changes. */
    keySignature?: string;

    /** Typically 2 staves for piano: 0 for Treble (Right Hand), 1 for Bass (Left Hand) */
    staves: IntermediateStaff[];
}

export interface IntermediateStaff {
    /** 0 for upper staff, 1 for lower staff */
    staffIndex: number;

    /** 'treble' or 'bass'. Only present if it changes in this measure for this staff. */
    clef?: 'treble' | 'bass';

    /** Multiple voices handle complex rhythms on the same staff */
    voices: IntermediateVoice[];
}

export interface IntermediateVoice {
    voiceIndex: number;
    notes: IntermediateNote[];
}

export interface IntermediateNote {
    /** VexFlow keys array: e.g., ["c/4", "e/4", "g/4"] */
    keys: string[];

    /** VexFlow duration string: 'w', 'h', 'q', '8', '16', '32' */
    duration: string;

    /** Number of dots applied to this note/chord */
    dots: number;

    isRest: boolean;

    /** Array of accidental strings matching the length of `keys` */
    accidentals: (string | null)[];

    /** True if this specific note in the chord is tied to the NEXT note */
    tiesToNext: boolean[];

    /** Articulation codes: 'a.', 'a>', etc. */
    articulations: string[];

    /** The exact musical beat this note lands on (1-indexed) */
    beat: number;

    /** Unique ID for coordinate tracking */
    vfId: string;

    /** Custom HSL color for the note (e.g., from Phase 1 harmonic data) */
    color?: string;

    tupletActual?: number;
    tupletNormal?: number;
    tupletStart?: boolean;
    tupletStop?: boolean;

    isGrace?: boolean;
    graceNotes?: IntermediateNote[];

    slurStarts?: number[];
    slurStops?: number[];
}
