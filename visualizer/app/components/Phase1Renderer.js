'use client';

import { midiNoteName } from './etme-constants';

// ===== Phase 1: Harmonic Regime Rendering =====

/**
 * Draw Phase 1 regime background blocks on the canvas.
 */
export function renderPhase1Regimes(ctx, regimes, { effectiveScale, noteHeight, rollH, canvasW }) {
  for (const r of regimes) {
    const x = r.start_time * effectiveScale;
    const w = Math.max((r.end_time - r.start_time) * effectiveScale, 1);
    const avgHue = r.hue || 0;
    const avgSat = r.saturation || 0;

    if (r.state === 'Silence' || r.state === 'Undefined / Gray Void') {
      ctx.fillStyle = 'rgba(30,30,40,0.15)';
    } else {
      ctx.fillStyle = `hsla(${avgHue}, ${Math.min(avgSat, 80)}%, 45%, 0.06)`;
    }
    ctx.fillRect(x, 0, w, rollH);

    ctx.strokeStyle = `hsla(${avgHue}, ${Math.min(avgSat, 70)}%, 55%, 0.15)`;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, rollH); ctx.stroke();

    let stateColor, stateLabel;
    if (r.state === 'TRANSITION SPIKE!') {
      stateColor = 'hsla(60, 95%, 60%, 0.8)';
      stateLabel = 'Spike';
    } else if (r.state === 'Regime Locked') {
      stateColor = 'hsla(120, 80%, 50%, 0.8)';
      stateLabel = 'Locked';
    } else if (r.state === 'Silence' || r.state === 'Undefined / Gray Void') {
      stateColor = 'rgba(80, 80, 100, 0.4)';
      stateLabel = r.state === 'Silence' ? 'Silence' : 'Void';
    } else {
      stateColor = `hsla(${avgHue}, 70%, 55%, 0.6)`;
      stateLabel = 'Stable';
    }
    ctx.fillStyle = stateColor;
    ctx.fillRect(x, 0, w, 3);

    if (w > 30) {
      ctx.font = '9px Inter';
      ctx.fillStyle = stateColor;
      ctx.fillText(stateLabel, x + 4, 14);
    }
  }
}

/**
 * Return { fillColor, strokeColor, shadow } for a note in Phase 1 view.
 */
export function getPhase1NoteColor(n) {
  const h = n.hue || 0;
  const s = Math.min(n.sat || 30, 100);
  const rawL = n.lightness || 50;
  const l = 20 + (rawL / 100) * 60;

  let fillColor, strokeColor, shadow = null;

  if (n.regime_state === 'TRANSITION SPIKE!') {
    fillColor = `hsla(${h}, ${Math.max(s, 70)}%, ${l}%, 0.95)`;
    strokeColor = `hsla(${h}, 95%, ${Math.min(l + 15, 85)}%, 1)`;
    shadow = { color: `hsla(${h}, 90%, 50%, 0.4)`, blur: 4 };
  } else if (n.regime_state === 'Regime Locked') {
    fillColor = `hsla(${h}, ${s}%, ${l}%, 0.9)`;
    strokeColor = `hsla(${h}, ${s}%, ${Math.min(l + 10, 80)}%, 0.95)`;
  } else if (n.regime_state === 'Silence' || n.regime_state === 'Undefined / Gray Void') {
    fillColor = 'rgba(80, 80, 100, 0.4)';
    strokeColor = 'rgba(100, 100, 130, 0.6)';
  } else {
    fillColor = `hsla(${h}, ${s}%, ${l}%, 0.8)`;
    strokeColor = `hsla(${h}, ${s}%, ${Math.min(l + 10, 80)}%, 0.9)`;
  }

  return { fillColor, strokeColor, shadow };
}

/**
 * Render Phase 1 debug labels on a note (particle contributions, diff info).
 */
export function renderPhase1DebugLabels(ctx, n, x, y) {
  if (!n.debug || !n.debug.particles) return;

  ctx.font = '9px monospace';
  const noteName = midiNoteName(n.pitch);
  const parts = n.debug.particles;
  const label = parts.map(p => {
    const iv = p.int || p.interval;
    return `${iv}:${(p.m ?? p.mass)?.toFixed(2)}`;
  }).join(' ');
  const diffLabel = `d${n.debug.diff} pm=${n.debug.pmass?.toFixed(2)} rm=${n.debug.rmass?.toFixed(2)} th=${n.debug.threshold?.toFixed(2)}`;

  ctx.fillStyle = 'rgba(100,220,255,0.9)';
  ctx.fillText(noteName, x + 2, y - 2);
  ctx.fillStyle = 'rgba(255,255,255,0.6)';
  ctx.fillText(label, x + 2 + ctx.measureText(noteName + ' ').width, y - 2);
  ctx.fillStyle = 'rgba(255,200,100,0.6)';
  ctx.fillText(diffLabel, x + 2, y - 10);
}

/**
 * Phase 1 Legend React component.
 */
export function Phase1Legend({ minBreakMass, setMinBreakMass, showComparison }) {
  return (
    <>
      <h3>Phase 1 -- Harmonic Regimes</h3>
      <div className="legend-item"><div className="legend-swatch" style={{ background: 'hsla(0,70%,45%,0.6)' }} />Stable (by hue)</div>
      <div className="legend-item"><div className="legend-swatch" style={{ background: 'hsla(120,80%,50%,0.75)' }} />Locked</div>
      <div className="legend-item"><div className="legend-swatch" style={{ background: 'hsla(60,95%,60%,0.9)', boxShadow: '0 0 6px hsla(60,90%,50%,0.5)' }} />Spike</div>
      <div className="legend-item"><div className="legend-swatch" style={{ background: 'rgba(80,80,100,0.4)' }} />Silence / Void</div>
      <div style={{ marginTop: 12, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 10 }}>
        <div className="legend-item"><div className="legend-swatch" style={{ background: '#ff4444' }} />T1 Marker (Downbeat+Harmonic)</div>
        <div className="legend-item"><div className="legend-swatch" style={{ background: '#ff8844' }} />T2 Marker (Harmonic Spike)</div>
        {showComparison && (
          <div className="legend-item"><div className="legend-swatch" style={{ background: 'rgba(0,220,255,0.7)' }} />Model Boundary</div>
        )}
      </div>
      <div style={{ marginTop: 12, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 10 }}>
        <label style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)', display: 'block', marginBottom: 4 }}>
          Min Break Mass: <strong style={{ color: '#fff' }}>{minBreakMass}</strong>
        </label>
        <input
          type="range" min="0.1" max="1.5" step="0.05"
          value={minBreakMass}
          onChange={e => setMinBreakMass(parseFloat(e.target.value))}
          style={{ width: '100%', accentColor: 'var(--accent-green)' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'rgba(255,255,255,0.35)' }}>
          <span>0.1 (sensitive)</span>
          <span>1.5 (conservative)</span>
        </div>
        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', marginTop: 4 }}>
          Re-run engine to apply
        </div>
      </div>
    </>
  );
}
