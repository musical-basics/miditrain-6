'use client';

import { hsl, VOICE_COLORS } from './etme-constants';

// ===== Phase 2: Voice Threading Rendering =====

/**
 * Return { fillColor, strokeColor, shadow } for a note in Phase 2 view.
 */
export function getPhase2NoteColor(n) {
  const vc = VOICE_COLORS[n.voice_tag] || VOICE_COLORS['Overflow (Chord)'];
  const fillColor = hsl(vc.h, vc.s, vc.l, 0.85);
  const strokeColor = hsl(vc.h, vc.s, Math.min(vc.l + 25, 80), 0.95);

  let shadow = null;
  if (n.voice_tag === 'Voice 1' || n.voice_tag === 'Voice 4') {
    shadow = { color: hsl(vc.h, 90, 50, 0.4), blur: 5 };
  }

  return { fillColor, strokeColor, shadow };
}

/**
 * Phase 2 Legend React component.
 */
export function Phase2Legend() {
  return (
    <>
      <h3>Phase 2 -- Voice Threading</h3>
      {Object.entries(VOICE_COLORS).map(([key, vc]) => (
        <div key={key} className="legend-item">
          <div className="legend-swatch" style={{ background: hsl(vc.h, vc.s, vc.l) }} />
          {vc.label}
        </div>
      ))}
    </>
  );
}
