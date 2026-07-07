'use client';

import { hsl, VOICE_COLORS } from './etme-constants';

// ===== Phase 5: Quantize + Notation Rendering =====
// 'phase5a' → quantized piano roll (notes snapped to the Phase 3 grid)
// 'phase5b' → VexFlow notation (rendered by NotationView, not the canvas)

/**
 * Map a quantized note back to snapped pixel geometry using the barline grid.
 * Returns { x, w } in ms-scaled pixels, or null if the note has no
 * quantization data (caller falls back to raw onset/duration).
 */
export function getQuantizedGeometry(n, gridData, { effectiveScale }) {
  if (!n.quantized) return null;
  const barlines = gridData?.barlines || [];
  const measure_ms = gridData?.measure_ms || 1000;
  const ticks_per_measure = (gridData?.beats_per_measure || 4) * (gridData?.subdivision || 4);

  const getMsForTick = (absTick) => {
    if (!barlines.length) return absTick * (measure_ms / ticks_per_measure);
    const first_measure = barlines[0].measure;
    const target_measure = first_measure + Math.floor(absTick / ticks_per_measure);
    const remainder = absTick % ticks_per_measure;

    let m_start_ms;
    const matched_b = barlines.find(b => b.measure === target_measure);
    if (matched_b) {
      m_start_ms = matched_b.time_ms;
    } else {
      m_start_ms = barlines[0].time_ms + (target_measure - first_measure) * measure_ms;
    }
    return m_start_ms + (remainder * (measure_ms / ticks_per_measure));
  };

  const snapped_onset = getMsForTick(n.quantized.abs_tick_start);
  const snapped_offset = getMsForTick(n.quantized.abs_tick_end);
  return {
    x: snapped_onset * effectiveScale,
    w: Math.max((snapped_offset - snapped_onset) * effectiveScale, 3),
  };
}

/**
 * Bright voice colors for the quantized view (outer voices glow).
 */
export function getPhase5NoteColor(n) {
  const vc = VOICE_COLORS[n.voice_tag] || VOICE_COLORS['Overflow (Chord)'];
  const fillColor = hsl(vc.h, vc.s, Math.min(vc.l + 10, 80), 0.95);
  const strokeColor = hsl(vc.h, vc.s, Math.min(vc.l + 25, 80), 1);

  let shadow = null;
  if (n.voice_tag === 'Voice 1' || n.voice_tag === 'Voice 4') {
    shadow = { color: hsl(vc.h, 90, 50, 0.7), blur: 8 };
  }

  return { fillColor, strokeColor, shadow };
}

/**
 * Legend for the quantized view.
 */
export function Phase5QuantizeLegend({ gridData }) {
  return (
    <>
      <h3>Phase 5A -- Micro-Quantize</h3>
      {Object.entries(VOICE_COLORS).map(([key, vc]) => (
        <div key={key} className="legend-item">
          <div className="legend-swatch" style={{ background: hsl(vc.h, vc.s, vc.l) }} />
          {vc.label}
        </div>
      ))}
      <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 8, fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>
        Notes drawn at their grid-snapped positions.
        {gridData
          ? <> Grid: {gridData.time_signature}, {gridData.subdivision}× subdivision.</>
          : <> No grid data -- run engine first.</>}
      </div>
    </>
  );
}

/**
 * Legend for the notation view.
 */
export function Phase5NotationLegend({ notationData }) {
  return (
    <>
      <h3>Phase 5B -- Notation Map</h3>
      {notationData?.measures?.length ? (
        <>
          <div className="legend-item" style={{ fontSize: 11 }}>
            <span style={{ color: '#4caf50', fontWeight: 600 }}>{notationData.measures.length}</span>
            &nbsp;measures
          </div>
          {notationData.measures[0]?.keySignature && (
            <div className="legend-item" style={{ fontSize: 11 }}>
              Key: <span style={{ color: '#4caf50', fontWeight: 600 }}>&nbsp;{notationData.measures[0].keySignature}</span>
            </div>
          )}
          <div style={{ marginTop: 8, fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>
            Diagnostic display -- barline/meter errors upstream show up as
            insane ties and durations here. That is the point.
          </div>
        </>
      ) : <div style={{ color: 'rgba(255,255,255,0.4)' }}>No notation data. Run engine first.</div>}
    </>
  );
}
