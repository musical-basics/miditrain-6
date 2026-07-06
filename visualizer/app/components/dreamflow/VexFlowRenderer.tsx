'use client'

// components/score/VexFlowRenderer.tsx
//
// Renders an IntermediateScore using VexFlow's SVG backend.
// Produces: measureXMap, beatXMap, noteMap, systemYMap via onRenderComplete.
// Does NOT touch xmlEvents — that comes from OsmdParser.

import * as React from 'react'
import { useRef, useEffect, useCallback, useState } from 'react'
import { VexFlow } from 'dreamflow'
import {
    Renderer,
    Stave,
    StaveNote,
    Voice,
    Formatter,
    Beam,
    StaveTie,
    Accidental,
    Dot,
    StaveConnector,
    Tuplet,
    Fraction,
    type RenderContext,
    VoiceMode,
} from 'dreamflow'
import type { IntermediateScore } from './IntermediateScore'
import {
    MIN_STAVE_WIDTH, MAX_PAGE_WIDTH, STAVE_Y_TREBLE, STAVE_SPACING, LEFT_MARGIN, SYSTEM_HEIGHT,
    createStaveNote, isBeamable, addArticulation, detectHeuristicTuplets,
    attachGraceNotes, processSlurs,
    type NoteData, type VexFlowRenderResult, type TupletData, type ActiveSlurs,
} from './VexFlowHelpers'

export type { NoteData, VexFlowRenderResult }
import { vexKeyToMidi } from './midiMatcher'

interface VexFlowRendererProps {
    score: IntermediateScore | null
    onRenderComplete?: (result: VexFlowRenderResult) => void
    onNoteHover?: (noteId: string | null, e: MouseEvent) => void
    onNoteClick?: (noteId: string, e: MouseEvent) => void
    darkMode?: boolean
    musicFont?: string
    paged?: boolean
}

// ─── Component ─────────────────────────────────────────────────────

const VexFlowRendererComponent: React.FC<VexFlowRendererProps> = ({
    score,
    onRenderComplete,
    onNoteHover,
    onNoteClick,
    darkMode = false,
    musicFont = '',
    paged = false,
}) => {
    const containerRef = useRef<HTMLDivElement>(null)
    const rendererRef = useRef<Renderer | null>(null)
    const [isRendered, setIsRendered] = useState(false)
    const [fontsLoaded, setFontsLoaded] = useState(false)

    // Preload ALL music fonts once on mount (DreamFlow forces browser download internally)
    useEffect(() => {
        console.log('[FONT DEBUG] Preloading all DreamFlow fonts...')
        VexFlow.loadFonts('Bravura', 'Gonville', 'Petaluma', 'Academico')
            .then(() => {
                // DreamFlow's Font.load() now calls document.fonts.load() internally,
                // so no redundant browser-level font loading is needed here.
                setFontsLoaded(true)
            }).catch((err: unknown) => {
                console.warn('[DREAMFLOW] Font preloading failed, using defaults', err)
                setFontsLoaded(true)
            })
    }, [])

    const renderScore = useCallback(() => {
        if (!score || !containerRef.current || score.measures.length === 0 || !fontsLoaded) return
        // Set the active font synchronously BEFORE creating any VexFlow objects
        if (musicFont) VexFlow.setFonts(musicFont)
        const fontAvailable = musicFont ? document.fonts.check(`30px "${musicFont}"`) : true
        console.log('[FONT DEBUG] renderScore: musicFont =', JSON.stringify(musicFont), 'fontAvailable:', fontAvailable, 'getFonts():', VexFlow.getFonts())

        // Clear previous render
        containerRef.current.innerHTML = ''
        setIsRendered(false)

        const measures = score.measures
        // ── Layout Calculation ──
        // In the first pass, we determine how many rows we need and the total width.
        // We'll simulate the layout to find a safe canvas size.
        const ROW_WIDTH_LIMIT = paged ? MAX_PAGE_WIDTH : 99999
        let totalWidth = ROW_WIDTH_LIMIT
        let estimatedRows = 1
        let currentXForSize = LEFT_MARGIN

        // We'll perform actual coordinate calculations during the render loop.
        // For sizing purposes, we'll start with a conservative height and resize later if possible,
        // or just use a sufficiently large height for the grid.
        const rowCount = paged ? Math.ceil(measures.length / 2) : 1 // rough estimate
        const initialHeight = (measures.length * SYSTEM_HEIGHT) + 100 // Safe upper bound

        // Create SVG renderer
        const renderer = new Renderer(containerRef.current, Renderer.Backends.SVG)
        renderer.resize(totalWidth, initialHeight)
        rendererRef.current = renderer

        const context = renderer.getContext() as RenderContext
        
        // Apply colors based on darkMode
        const color = darkMode ? '#ffffff' : '#000000'
        context.setFillStyle(color)
        context.setStrokeStyle(color)

        // Track state for rendering
        const measureXMap = new Map<number, number>()
        const beatXMap = new Map<number, Map<number, number>>()
        const allNoteData = new Map<number, NoteData[]>()

        // Track current clefs
        let currentTrebleClef = 'treble'
        let currentBassClef = 'bass'
        let currentKeySig = 'C'
        let currentTimeSigNum = 4
        let currentTimeSigDen = 4

        // Track previous measure's last notes for ties
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const prevMeasureLastNotes: Map<string, { staveNote: any; keyIndex: number }> = new Map()

        // Track active slurs across measures
        const activeSlurs: ActiveSlurs = new Map()
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const allCurves: any[] = []

        // Store tie data for cross-measure ties
        interface TieRequest {
            firstNote: StaveNote
            lastNote: StaveNote
            firstIndices: number[]
            lastIndices: number[]
        }
        const tieRequests: TieRequest[] = []

        // Layout tracking
        let currentX = LEFT_MARGIN
        let currentRow = 0
        let maxRowX = 0

        // Render each measure
        for (let mIdx = 0; mIdx < measures.length; mIdx++) {
            const measure = measures[mIdx]
            const measureNumber = measure.measureNumber
            
            // We'll determine the stave's width after formatting to be perfect,
            // but for now we'll start with a width and draw later.
            // Actually VexFlow requires the Stave to have a width UPFRONT.
            // We'll use a density-aware heuristic: 250px base + 30px per note.
            let noteCount = 0
            measure.staves.forEach(s => s.voices.forEach(v => noteCount += v.notes.length))
            const estimatedWidth = Math.max(MIN_STAVE_WIDTH, (noteCount * 25) / measure.staves.length)
            
            if (paged && (currentX + estimatedWidth > MAX_PAGE_WIDTH) && mIdx > 0) {
                currentX = LEFT_MARGIN
                currentRow++
            }

            const x = currentX
            const yOffset = currentRow * SYSTEM_HEIGHT

            // Update running state
            if (measure.keySignature) currentKeySig = measure.keySignature
            if (measure.timeSignatureNumerator) currentTimeSigNum = measure.timeSignatureNumerator
            if (measure.timeSignatureDenominator) currentTimeSigDen = measure.timeSignatureDenominator

            // ── Create staves ──
            const trebleStave = new Stave(x, STAVE_Y_TREBLE + yOffset, estimatedWidth)
            const bassStave = new Stave(x, STAVE_Y_TREBLE + STAVE_SPACING + yOffset, estimatedWidth)

            // Clefs
            for (const staff of measure.staves) {
                if (staff.staffIndex === 0 && staff.clef) {
                    currentTrebleClef = staff.clef
                }
                if (staff.staffIndex === 1 && staff.clef) {
                    currentBassClef = staff.clef
                }
            }

            if (mIdx === 0 || (paged && x === LEFT_MARGIN)) {
                trebleStave.addClef(currentTrebleClef)
                bassStave.addClef(currentBassClef)

                if (currentKeySig && currentKeySig !== 'C' && currentKeySig !== 'Am') {
                    trebleStave.addKeySignature(currentKeySig)
                    bassStave.addKeySignature(currentKeySig)
                }

                trebleStave.addTimeSignature(`${currentTimeSigNum}/${currentTimeSigDen}`)
                bassStave.addTimeSignature(`${currentTimeSigNum}/${currentTimeSigDen}`)
            } else {
                // Only add if changed
                if (measure.staves[0]?.clef) trebleStave.addClef(currentTrebleClef)
                if (measure.staves[1]?.clef) bassStave.addClef(currentBassClef)

                if (measure.keySignature) {
                    if (currentKeySig !== 'C' && currentKeySig !== 'Am') {
                        trebleStave.addKeySignature(currentKeySig)
                        bassStave.addKeySignature(currentKeySig)
                    }
                }

                if (mIdx === 0 || (paged && x === LEFT_MARGIN) || measure.timeSignatureNumerator) {
                    trebleStave.addTimeSignature(`${currentTimeSigNum}/${currentTimeSigDen}`)
                    bassStave.addTimeSignature(`${currentTimeSigNum}/${currentTimeSigDen}`)
                }
            }

            trebleStave.setContext(context).draw()
            bassStave.setContext(context).draw()

            // Brace + line connector on first measure or start of row
            if (mIdx === 0 || (paged && x === LEFT_MARGIN)) {
                new StaveConnector(trebleStave, bassStave).setType('brace').setContext(context).draw()
                new StaveConnector(trebleStave, bassStave).setType('singleLeft').setContext(context).draw()
            }
            // End barline connector
            new StaveConnector(trebleStave, bassStave).setType('singleRight').setContext(context).draw()

            // Record measure X position
            measureXMap.set(measureNumber, trebleStave.getX() + trebleStave.getNoteStartX() - trebleStave.getX())

            // ── Create notes for each staff ──
            const staveMap: { [staffIdx: number]: Stave } = {
                0: trebleStave,
                1: bassStave,
            }

            const measureNoteData: NoteData[] = []
            const measureBeatPositions = new Map<number, number>()
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const currentMeasureFirstNotes: Map<string, { staveNote: any; keyIndex: number }> = new Map()

            // Collections for synchronous formatting
            const vfVoices: Voice[] = []
            const multiVoiceVoices = new Set<Voice>() // voices from multi-voice staves
            const voiceStaveMap = new Map<Voice, Stave>()
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const measureBeams: any[] = []
            const measureTuplets: { notes: StaveNote[]; actual: number; normal: number }[] = []
            let currentTupletNotes: StaveNote[] | null = null
            let currentTupletActual = 3
            let currentTupletNormal = 2
            const coordinateExtractors: (() => void)[] = []

            for (const staff of measure.staves) {
                const stave = staveMap[staff.staffIndex]
                if (!stave) continue

                const isMultiVoice = staff.voices.length > 1

                for (const voice of staff.voices) {
                    if (voice.notes.length === 0) continue

                    // Multi-voice: first voice stems UP (1), second voice stems DOWN (-1)
                    // Single voice: undefined → autoStem
                    const stemDir = isMultiVoice
                        ? (voice.voiceIndex === Math.min(...staff.voices.map(v => v.voiceIndex)) ? 1 : -1)
                        : undefined

                    const vfNotes: StaveNote[] = []
                    const beamableNotes: StaveNote[] = []

                    for (const note of voice.notes) {
                        const staveClef = staff.staffIndex === 0 ? currentTrebleClef : currentBassClef
                        const staveNote = createStaveNote(note, staff.staffIndex, stemDir, staveClef)

                        // Apply custom color if present
                        if (note.color) {
                            staveNote.setStyle({ fillStyle: note.color, strokeStyle: note.color });
                        }

                        for (let ki = 0; ki < note.accidentals.length; ki++) {
                            const acc = note.accidentals[ki]
                            if (acc) staveNote.addModifier(new Accidental(acc), ki)
                        }

                        if (note.dots > 0) Dot.buildAndAttach([staveNote], { all: true })

                        for (const artCode of note.articulations) {
                            addArticulation(staveNote, artCode)
                        }

                        vfNotes.push(staveNote)

                        // Grace notes: attach to this main note
                        if (note.graceNotes && note.graceNotes.length > 0) {
                            try {
                                attachGraceNotes(staveNote, note.graceNotes, staff.staffIndex, staveClef)
                            } catch (e) {
                                console.warn(`[GRACE] Failed to attach grace notes:`, e)
                            }
                        }

                        // Slurs: track start/stop and collect completed curves
                        const completedCurves = processSlurs(note, staveNote, activeSlurs)
                        allCurves.push(...completedCurves)

                        // Tuplet tracking
                        if (note.tupletStart) {
                            currentTupletNotes = [staveNote]
                            currentTupletActual = note.tupletActual || 3
                            currentTupletNormal = note.tupletNormal || 2
                        } else if (currentTupletNotes) {
                            currentTupletNotes.push(staveNote)
                        }
                        if (note.tupletStop && currentTupletNotes && currentTupletNotes.length > 0) {
                            measureTuplets.push({
                                notes: currentTupletNotes,
                                actual: currentTupletActual,
                                normal: currentTupletNormal,
                            })
                            currentTupletNotes = null
                        }

                        // All beamable notes go into auto-beam pool (including tuplets)
                        if (!note.isRest && isBeamable(note.duration)) {
                            beamableNotes.push(staveNote)
                        }

                        // Tie tracking
                        if (!note.isRest) {
                            for (let ki = 0; ki < note.keys.length; ki++) {
                                const tieKey = `${staff.staffIndex}-${note.keys[ki]}`
                                if (!currentMeasureFirstNotes.has(tieKey)) {
                                    currentMeasureFirstNotes.set(tieKey, { staveNote, keyIndex: ki })
                                }
                                const prev = prevMeasureLastNotes.get(tieKey)
                                if (prev) {
                                    tieRequests.push({
                                        firstNote: prev.staveNote,
                                        lastNote: staveNote,
                                        firstIndices: [prev.keyIndex],
                                        lastIndices: [ki],
                                    })
                                    prevMeasureLastNotes.delete(tieKey)
                                }
                            }
                            for (let ki = 0; ki < note.tiesToNext.length; ki++) {
                                if (note.tiesToNext[ki]) {
                                    const tieKey = `${staff.staffIndex}-${note.keys[ki]}`
                                    prevMeasureLastNotes.set(tieKey, { staveNote, keyIndex: ki })
                                }
                            }
                        }

                        // DELAY coordinate extraction until after the master Formatter runs
                        coordinateExtractors.push(() => {
                            if (!note.isRest) {
                                try {
                                    measureBeatPositions.set(note.beat, staveNote.getAbsoluteX())
                                } catch { /* ignore */ }
                            }

                            let element: HTMLElement | null = null
                            let pathsAndRects: HTMLElement[] | undefined
                            try {
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                const svgEl = (staveNote as any).getSVGElement?.() as HTMLElement | undefined
                                if (svgEl) {
                                    const group = (svgEl.closest('.vf-stavenote') as HTMLElement) || svgEl
                                    element = group
                                    pathsAndRects = Array.from(group.querySelectorAll('path, rect, text')) as HTMLElement[]
                                }
                            } catch { /* ignore */ }

                            const pitches = note.isRest ? undefined : note.keys
                                .map(k => vexKeyToMidi(k))
                                .filter((p): p is number => p !== undefined)

                            measureNoteData.push({
                                id: note.vfId,
                                measureIndex: measureNumber,
                                timestamp: (note.beat - 1) / currentTimeSigNum,
                                isRest: note.isRest,
                                numerator: currentTimeSigNum,
                                element,
                                stemElement: null,
                                pathsAndRects,
                                pitches: pitches && pitches.length > 0 ? pitches : undefined,
                                hasGrace: !!(note.graceNotes && note.graceNotes.length > 0),
                            })
                        })
                    }

                    // Heuristic triplet detection
                    const heuristicTuplets = detectHeuristicTuplets(
                        voice.notes, vfNotes, measureTuplets,
                        currentTimeSigNum, currentTimeSigDen, measureNumber
                    )
                    measureTuplets.push(...heuristicTuplets)

                    // Flush unclosed tuplets
                    if (currentTupletNotes && currentTupletNotes.length >= 2) {
                        measureTuplets.push({
                            notes: currentTupletNotes,
                            actual: currentTupletActual,
                            normal: currentTupletNormal,
                        })
                    }
                    currentTupletNotes = null

                    const vfVoice = new Voice({
                        numBeats: currentTimeSigNum,
                        beatValue: currentTimeSigDen,
                    }).setMode(VoiceMode.SOFT)

                    vfVoice.addTickables(vfNotes)
                    vfVoices.push(vfVoice)
                    voiceStaveMap.set(vfVoice, stave)
                    if (isMultiVoice) multiVoiceVoices.add(vfVoice)

                    if (beamableNotes.length >= 2) {
                        try {
                            const groups = [new Fraction(currentTimeSigNum, currentTimeSigDen)]
                            const beamOpts: any = { groups }
                            if (stemDir !== undefined) {
                                beamOpts.stemDirection = stemDir
                                beamOpts.maintainStemDirections = true
                            }
                            measureBeams.push(...Beam.generateBeams(beamableNotes, beamOpts))
                        } catch { /* ignore */ }
                    }
                }
            }

            // ── Format ──
            if (vfVoices.length > 0) {
                const formatter = new Formatter()
                const voicesByStave = new Map<Stave, Voice[]>()
                vfVoices.forEach(v => {
                    const stave = voiceStaveMap.get(v)!
                    if (!voicesByStave.has(stave)) voicesByStave.set(stave, [])
                    voicesByStave.get(stave)!.push(v)
                })
                voicesByStave.forEach(voices => formatter.joinVoices(voices))

                // Create Tuplet objects BEFORE formatting
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const vfTuplets: any[] = []
                measureTuplets.forEach(t => {
                    try {
                        for (const note of t.notes) {
                            try {
                                const n = note as any
                                n.applyTickMultiplier(t.normal, t.actual)
                            } catch { /* ignore */ }
                        }

                        const tuplet = new Tuplet(t.notes, {
                            numNotes: t.actual,
                            notesOccupied: t.normal,
                            bracketed: false,
                        })
                        vfTuplets.push(tuplet)
                    } catch { /* ignore */ }
                })

                // Synchronize note start X
                const staves = Object.values(staveMap)
                const maxNoteStartX = Math.max(...staves.map(s => {
                    try { return s.getNoteStartX() } catch { return 0 }
                }))
                staves.forEach(s => {
                    try {
                        if (s.getNoteStartX() < maxNoteStartX) {
                            s.setNoteStartX(maxNoteStartX)
                        }
                    } catch { /* ignore */ }
                })

                const noteEndX = Math.min(...staves.map(s => {
                    try { return s.getNoteEndX() } catch { return maxNoteStartX + estimatedWidth - 40 }
                }))
                const availableWidth = noteEndX - maxNoteStartX - 10
                formatter.format(vfVoices, Math.max(availableWidth, 100))

                // Post-format: reposition articulations
                vfVoices.forEach(v => {
                    const isMulti = multiVoiceVoices.has(v)
                    if (!isMulti) return
                    const tickables = v.getTickables()
                    for (const t of tickables) {
                        const sn = t as StaveNote
                        try {
                            const stemDir = sn.getStemDirection()
                            const mods = sn.getModifiers()
                            for (const m of mods) {
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                const mod = m as any
                                if (mod.getCategory?.() === 'articulations' || mod.constructor?.name === 'Articulation') {
                                    if (mod.isFermata) continue
                                    const pos = stemDir === 1 ? 3 : 4
                                    mod.setPosition(pos)
                                    mod.setYShift(pos === 4 ? 2 : -2)
                                }
                            }
                        } catch { /* ignore */ }
                    }
                })

                // Draw
                vfVoices.forEach(v => v.draw(context, voiceStaveMap.get(v)!))
                measureBeams.forEach(b => b.setContext(context).draw())

                if (containerRef.current) {
                    const svgEl = containerRef.current.querySelector('svg')
                    vfTuplets.forEach(t => {
                        try {
                            const textCountBefore = svgEl ? svgEl.querySelectorAll('text').length : 0
                            t.setContext(context).draw()
                            if (svgEl) {
                                const allTexts = svgEl.querySelectorAll('text')
                                for (let i = textCountBefore; i < allTexts.length; i++) {
                                    const textEl = allTexts[i]
                                    const origX = parseFloat(textEl.getAttribute('x') || '0')
                                    const origY = parseFloat(textEl.getAttribute('y') || '0')
                                    textEl.setAttribute('transform', `scale(0.65)`)
                                    textEl.setAttribute('x', String(origX / 0.65))
                                    textEl.setAttribute('y', String((origY + 20) / 0.65))
                                    textEl.setAttribute('text-anchor', 'middle')
                                }
                            }
                        } catch { /* ignore */ }
                    })
                } else {
                    vfTuplets.forEach(t => {
                        try { t.setContext(context).draw() } catch { /* ignore */ }
                    })
                }
            }

            coordinateExtractors.forEach(extract => extract())
            beatXMap.set(measureNumber, measureBeatPositions)
            allNoteData.set(measureNumber, measureNoteData)
            
            currentX += estimatedWidth
            if (currentX > maxRowX) maxRowX = currentX
        }

        // Draw ties
        for (const tie of tieRequests) {
            try {
                new StaveTie({
                    firstNote: tie.firstNote,
                    lastNote: tie.lastNote,
                    firstIndexes: tie.firstIndices,
                    lastIndexes: tie.lastIndices,
                }).setContext(context).draw()
            } catch { /* ignore */ }
        }

        // Draw slurs
        for (const curve of allCurves) {
            try {
                curve.setContext(context).draw()
            } catch { /* ignore */ }
        }

        requestAnimationFrame(() => {
            if (!containerRef.current) return
            const cLeft = containerRef.current.getBoundingClientRect().left

            allNoteData.forEach((notes) => {
                for (const note of notes) {
                    if (!note.element) continue
                    note.element.style.transformBox = 'fill-box'
                    note.element.style.transformOrigin = 'center center'
                    note.element.style.transition = 'filter 0.1s'

                    const coreGroup = note.element.querySelector('.vf-note-core') as HTMLElement
                    if (coreGroup) {
                        coreGroup.style.transformBox = 'fill-box'
                        coreGroup.style.transformOrigin = 'center center'
                    }

                    if (note.pathsAndRects) {
                        note.pathsAndRects.forEach(p => {
                            p.style.transition = 'fill 0.1s, stroke 0.1s'
                        })
                    }

                    // Interactive Events
                    note.element.onmouseenter = (e: MouseEvent) => {
                        if (note.element) note.element.style.filter = 'drop-shadow(0 0 4px rgba(255,255,255,0.8))'
                        onNoteHover?.(note.id, e)
                    }
                    note.element.onmouseleave = (e: MouseEvent) => {
                        if (note.element) note.element.style.filter = ''
                        onNoteHover?.(null, e)
                    }
                    note.element.onclick = (e: MouseEvent) => {
                        onNoteClick?.(note.id, e)
                    }

                    const coreForX = note.element.querySelector('.vf-note-core') as HTMLElement
                    note.absoluteX = (coreForX || note.element).getBoundingClientRect().left - cLeft
                }
            })

            setIsRendered(true)

            if (onRenderComplete) {
                const systemYMap = {
                    top: STAVE_Y_TREBLE - 20,
                    height: paged ? (currentRow + 1) * SYSTEM_HEIGHT : SYSTEM_HEIGHT,
                    rowCount: currentRow + 1
                }
                
                // Final Resize to fit content perfectly
                if (rendererRef.current) {
                    rendererRef.current.resize(paged ? MAX_PAGE_WIDTH : maxRowX + 100, (currentRow + 1) * SYSTEM_HEIGHT + 100)
                }

                onRenderComplete({
                    measureXMap,
                    beatXMap,
                    noteMap: allNoteData,
                    systemYMap,
                    measureCount: measures.length,
                })
            }
        })

    }, [score, onRenderComplete, fontsLoaded, musicFont, darkMode])

    useEffect(() => {
        renderScore()
    }, [renderScore])

    useEffect(() => {
        const handleResize = () => setTimeout(() => renderScore(), 500)
        window.addEventListener('resize', handleResize)
        return () => window.removeEventListener('resize', handleResize)
    }, [renderScore])

    return (
        <div
            ref={containerRef}
            className="vexflow-container"
            style={{
                minWidth: '100%',
                minHeight: `${SYSTEM_HEIGHT}px`,
                opacity: isRendered ? 1 : 0,
                transition: 'opacity 0.2s',
            }}
        />
    )
}

export const VexFlowRenderer = React.memo(VexFlowRendererComponent)
export default VexFlowRenderer
