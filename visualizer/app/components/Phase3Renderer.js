'use client';

import { hsl, VOICE_COLORS, RULER_HEIGHT } from './etme-constants';

// ===== Phase 3: Meter Rendering =====
// Two meter engines are visualized:
//  - 'phase3'      → thermodynamic meter overlay (T/η/P lanes, freezing events)
//  - 'phase3_grid' → legacy spike-anchored barline grid (feeds Phase 4)

/**
 * Voice-colored notes for Phase 3 views. Dimmed so the overlays dominate.
 */
export function getPhase3NoteColor(n, view) {
  const vc = VOICE_COLORS[n.voice_tag] || VOICE_COLORS['Overflow (Chord)'];
  const alpha = view === 'phase3' ? 0.4 : 0.5;
  return {
    fillColor: hsl(vc.h, vc.s, vc.l, alpha),
    strokeColor: hsl(vc.h, vc.s, Math.min(vc.l + 25, 80), alpha + 0.1),
    shadow: null,
  };
}

/**
 * Barline grid overlay from phase3_grid_*.json (spike meter output).
 * Draws beat ticks, sub-tactus ticks, barlines with measure numbers and
 * drift annotations, the spike-density strip, and the ACF curve in the ruler.
 */
export function renderBarlineGrid(ctx, gridData, { effectiveScale, rollH, canvasW, maxTime, showTopLabels = false }) {
  if (!gridData) return;
  const barlines = gridData.barlines || [];
  const tactusMs = gridData.tactus_ms || 500;
  const subdivision = gridData.subdivision || 1;
  const subTactusMs = gridData.sub_tactus_ms || tactusMs;
  const measureMs = gridData.measure_ms || 1000;
  const beatsPerMeasure = gridData.beats_per_measure || 2;
  const beatMs = measureMs / beatsPerMeasure;

  // Beat tick lines (tactus pulses) between barlines
  for (let t = 0; t < maxTime; t += beatMs) {
    const x = t * effectiveScale;
    const isMeasureBound = barlines.some(b => Math.abs(b.time_ms - t) < beatMs * 0.2);
    if (!isMeasureBound) {
      ctx.strokeStyle = 'rgba(255, 210, 60, 0.15)';
      ctx.lineWidth = 0.75;
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(x, RULER_HEIGHT); ctx.lineTo(x, rollH); ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // Sub-tactus tick marks in ruler
  if (subdivision > 1) {
    for (let t = 0; t < maxTime; t += subTactusMs) {
      const x = t * effectiveScale;
      ctx.strokeStyle = 'rgba(255,210,60,0.06)';
      ctx.lineWidth = 0.5;
      ctx.beginPath(); ctx.moveTo(x, rollH + RULER_HEIGHT * 0.55); ctx.lineTo(x, rollH); ctx.stroke();
    }
  }

  // Barlines
  for (const b of barlines) {
    const x = b.time_ms * effectiveScale;
    const isSnapped = b.snapped;

    ctx.strokeStyle = isSnapped ? 'rgba(255, 210, 60, 0.5)' : 'rgba(255, 210, 60, 0.2)';
    ctx.lineWidth = isSnapped ? 1.5 : 1;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, rollH); ctx.stroke();

    // Ruler tick
    ctx.strokeStyle = isSnapped ? 'rgba(255,210,60,0.9)' : 'rgba(255,210,60,0.4)';
    ctx.lineWidth = isSnapped ? 2 : 1;
    ctx.beginPath(); ctx.moveTo(x, rollH); ctx.lineTo(x, rollH + 10); ctx.stroke();

    // Measure number label (bottom)
    ctx.font = `bold ${isSnapped ? 10 : 9}px Inter`;
    ctx.fillStyle = isSnapped ? 'rgba(255, 220, 80, 0.95)' : 'rgba(255, 210, 60, 0.5)';
    ctx.textAlign = 'center';
    ctx.fillText(`M${b.measure}`, x, rollH + 21);

    // Measure number label (top)
    if (showTopLabels) {
      ctx.fillStyle = 'rgba(255, 220, 80, 0.7)';
      ctx.fillText(`M${b.measure}`, x + 12, 16);
    }
    ctx.textAlign = 'start';

    // Drift annotation
    if (isSnapped && b.drift_ms !== 0) {
      ctx.font = '7px Inter';
      ctx.fillStyle = 'rgba(255,180,60,0.6)';
      ctx.textAlign = 'center';
      ctx.fillText(`${b.drift_ms > 0 ? '+' : ''}${b.drift_ms}ms`, x, rollH - 4);
      ctx.textAlign = 'start';
    }

    // Spike indicator dot at top
    if (isSnapped) {
      ctx.fillStyle = 'rgba(255, 220, 80, 0.8)';
      ctx.beginPath();
      ctx.arc(x, 8, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // ── Spike Density Envelope (bottom strip) ─────────────────────
  const DENSITY_H = 28;
  const density = gridData.spike_density || [];
  if (density.length > 0) {
    const maxCount = Math.max(...density.map(d => d.count), 1);
    ctx.fillStyle = 'rgba(255, 140, 20, 0.05)';
    ctx.fillRect(0, rollH - DENSITY_H, canvasW, DENSITY_H);
    for (const { t_ms, count } of density) {
      const x = t_ms * effectiveScale;
      const barH = (count / maxCount) * (DENSITY_H - 4);
      const alpha = 0.3 + (count / maxCount) * 0.5;
      ctx.fillStyle = `rgba(255, 150, 40, ${alpha})`;
      ctx.fillRect(x - 1, rollH - barH - 2, Math.max(2, effectiveScale * 50 - 1), barH);
    }
    ctx.font = '8px Inter';
    ctx.fillStyle = 'rgba(255,150,40,0.5)';
    ctx.fillText('spike density', 4, rollH - DENSITY_H + 9);
  }

  // ── Autocorrelation Curve (in ruler) ──────────────────────────
  const autocorr = gridData.autocorr || [];
  if (autocorr.length > 0) {
    const acfH = RULER_HEIGHT - 12;
    const acfTop = rollH + 2;

    ctx.fillStyle = 'rgba(255,140,20,0.04)';
    ctx.fillRect(0, acfTop, canvasW, acfH);

    ctx.beginPath();
    ctx.strokeStyle = 'rgba(255, 165, 40, 0.6)';
    ctx.lineWidth = 1;
    let first = true;
    for (const { lag_ms, score } of autocorr) {
      const x = lag_ms * effectiveScale;
      const y = acfTop + acfH - score * acfH;
      if (first) { ctx.moveTo(x, y); first = false; }
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Mark the autocorr peak (= detected measure_ms)
    const peakMs = gridData.autocorr_peak_ms;
    const peakEntry = autocorr.find(a => a.lag_ms === peakMs);
    if (peakEntry) {
      const px = peakMs * effectiveScale;
      const py = acfTop + acfH - peakEntry.score * acfH;
      ctx.fillStyle = 'rgba(255, 220, 60, 0.95)';
      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = '7px Inter';
      ctx.fillStyle = 'rgba(255,220,60,0.8)';
      ctx.textAlign = 'center';
      ctx.fillText(`${peakMs}ms`, px, acfTop - 1);
      ctx.textAlign = 'start';
    }
    ctx.font = '8px Inter';
    ctx.fillStyle = 'rgba(255,165,40,0.5)';
    ctx.fillText('acf', 4, acfTop + 8);
  }
}

/**
 * Thermodynamic overlay from phase3_thermo_*.json:
 * T/η/P waveform lanes, phase-census bands, freezing-event markers,
 * and the E(t) energy-accumulator curve.
 */
export function renderThermoOverlay(ctx, thermoData, { effectiveScale, rollH, canvasW }) {
  if (!thermoData) return;
  const gridSample = thermoData.grid_sample || [];
  const freezeEvents = thermoData.freezing_events || [];

  // ── Three-lane strip at bottom of piano roll ──────────────────
  const LANE_H = 32;
  const LANE_GAP = 2;
  const TOTAL_STRIP_H = LANE_H * 3 + LANE_GAP * 2 + 16;
  const stripTop = rollH - TOTAL_STRIP_H;

  ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
  ctx.fillRect(0, stripTop, canvasW, TOTAL_STRIP_H);

  let maxT = 0, maxEta = 0, maxP = 0;
  for (const g of gridSample) {
    if (g.T > maxT) maxT = g.T;
    if (g.eta > maxEta) maxEta = g.eta;
    if (g.P > maxP) maxP = g.P;
  }
  maxT = maxT || 1; maxEta = maxEta || 1; maxP = maxP || 1;

  const lanes = [
    { key: 'T',   label: 'T (Temperature)', max: maxT,   color: 'rgba(255, 80, 40',  top: stripTop },
    { key: 'eta', label: 'η (Viscosity)',    max: maxEta, color: 'rgba(40, 160, 255', top: stripTop + LANE_H + LANE_GAP },
    { key: 'P',   label: 'P (Pressure)',     max: maxP,   color: 'rgba(200, 80, 255', top: stripTop + (LANE_H + LANE_GAP) * 2 },
  ];

  for (const lane of lanes) {
    const laneTop = lane.top;

    ctx.fillStyle = lane.color + ', 0.04)';
    ctx.fillRect(0, laneTop, canvasW, LANE_H);

    ctx.font = '8px Inter';
    ctx.fillStyle = lane.color + ', 0.7)';
    ctx.fillText(lane.label, 4, laneTop + 9);

    if (gridSample.length > 1) {
      // Filled area
      ctx.beginPath();
      ctx.moveTo(gridSample[0].t_ms * effectiveScale, laneTop + LANE_H);
      for (const g of gridSample) {
        const x = g.t_ms * effectiveScale;
        const val = lane.key === 'eta' ? g.eta : (lane.key === 'P' ? g.P : g.T);
        const h = (val / lane.max) * (LANE_H - 2);
        ctx.lineTo(x, laneTop + LANE_H - h);
      }
      ctx.lineTo(gridSample[gridSample.length - 1].t_ms * effectiveScale, laneTop + LANE_H);
      ctx.closePath();
      ctx.fillStyle = lane.color + ', 0.15)';
      ctx.fill();

      // Top edge stroke
      ctx.beginPath();
      let first = true;
      for (const g of gridSample) {
        const x = g.t_ms * effectiveScale;
        const val = lane.key === 'eta' ? g.eta : (lane.key === 'P' ? g.P : g.T);
        const h = (val / lane.max) * (LANE_H - 2);
        const y = laneTop + LANE_H - h;
        if (first) { ctx.moveTo(x, y); first = false; }
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = lane.color + ', 0.6)';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  // ── Phase color bands across the piano roll ───────────────────
  const PHASE_COLORS = {
    frozen_solid: 'rgba(40, 160, 255, 0.06)',
    crystal:      'rgba(100, 200, 255, 0.04)',
    liquid:       'rgba(80, 255, 120, 0.02)',
    gas:          'rgba(255, 80, 40, 0.04)',
  };
  for (let i = 0; i < gridSample.length - 1; i++) {
    const g = gridSample[i];
    const gNext = gridSample[i + 1];
    const x = g.t_ms * effectiveScale;
    const w = Math.max((gNext.t_ms - g.t_ms) * effectiveScale, 1);
    const col = PHASE_COLORS[g.phase] || 'transparent';
    if (col !== 'transparent') {
      ctx.fillStyle = col;
      ctx.fillRect(x, 0, w, stripTop);
    }
  }

  // ── Freezing Event markers ────────────────────────────────────
  const sortedMags = [...freezeEvents].sort((a, b) => a.magnitude - b.magnitude);
  const tercile1 = sortedMags.length > 2 ? sortedMags[Math.floor(sortedMags.length / 3)].magnitude : 0;
  const tercile2 = sortedMags.length > 2 ? sortedMags[Math.floor(sortedMags.length * 2 / 3)].magnitude : Infinity;

  for (const ev of freezeEvents) {
    const x = ev.time_ms * effectiveScale;
    const isStrong = ev.magnitude >= tercile2;
    const isMedium = ev.magnitude >= tercile1 && ev.magnitude < tercile2;

    const alpha = isStrong ? 0.7 : (isMedium ? 0.45 : 0.25);
    const lineWidth = isStrong ? 2 : (isMedium ? 1.5 : 1);
    const color = ev.phase_to === 'frozen_solid'
      ? `rgba(40, 180, 255, ${alpha})`
      : `rgba(100, 220, 255, ${alpha})`;

    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.setLineDash(isStrong ? [] : [4, 3]);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, rollH);
    ctx.stroke();
    ctx.setLineDash([]);

    // Diamond marker at top
    const dSize = isStrong ? 6 : (isMedium ? 4 : 3);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, 6 - dSize);
    ctx.lineTo(x + dSize, 6);
    ctx.lineTo(x, 6 + dSize);
    ctx.lineTo(x - dSize, 6);
    ctx.closePath();
    ctx.fill();

    // Duration bar at top (how long the solid phase lasts)
    const durW = Math.max(ev.duration_ms * effectiveScale, 2);
    ctx.fillStyle = color.replace(/[\d.]+\)$/, '0.15)');
    ctx.fillRect(x, 0, durW, 3);

    if (isStrong || isMedium) {
      ctx.font = '7px Inter';
      ctx.fillStyle = color;
      ctx.textAlign = 'center';
      const magLabel = ev.magnitude >= 1000
        ? `${(ev.magnitude / 1000).toFixed(1)}k`
        : ev.magnitude.toFixed(0);
      ctx.fillText(magLabel, x, 20);

      ctx.font = '6px Inter';
      ctx.fillStyle = color.replace(/[\d.]+\)$/, '0.5)');
      ctx.fillText(ev.phase_from === 'gas' ? 'gas→solid' : 'liq→solid', x, 27);
      ctx.textAlign = 'start';
    }
  }

  // ── Energy accumulator curve (overlaid on viscosity lane) ─────
  if (gridSample.length > 1) {
    let maxE = 0;
    for (const g of gridSample) { if (g.E > maxE) maxE = g.E; }
    if (maxE > 0) {
      const eLaneTop = lanes[1].top;
      ctx.beginPath();
      let first = true;
      for (const g of gridSample) {
        const x = g.t_ms * effectiveScale;
        const h = (g.E / maxE) * (LANE_H - 2);
        const y = eLaneTop + LANE_H - h;
        if (first) { ctx.moveTo(x, y); first = false; }
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = 'rgba(255, 220, 40, 0.4)';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 2]);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.font = '7px Inter';
      ctx.fillStyle = 'rgba(255, 220, 40, 0.5)';
      ctx.fillText('E(t)', canvasW - 30, eLaneTop + 9);
    }
  }
}

/**
 * Legend for the thermodynamic meter view.
 */
export function Phase3ThermoLegend({ thermoData }) {
  return (
    <>
      <h3>Phase 3 -- Thermodynamic Meter</h3>
      {thermoData ? (
        <>
          <div className="legend-item">
            <div className="legend-swatch" style={{ background: 'rgba(40, 180, 255, 0.7)' }} />
            Freeze (Frozen Solid)
          </div>
          <div className="legend-item">
            <div className="legend-swatch" style={{ background: 'rgba(100, 220, 255, 0.6)' }} />
            Freeze (Crystal)
          </div>
          <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 8 }}>
            <div className="legend-item">
              <div className="legend-swatch" style={{ background: 'rgba(255, 80, 40, 0.6)' }} />
              T -- Temperature (disorder)
            </div>
            <div className="legend-item">
              <div className="legend-swatch" style={{ background: 'rgba(40, 160, 255, 0.6)' }} />
              &eta; -- Viscosity (inertia)
            </div>
            <div className="legend-item">
              <div className="legend-swatch" style={{ background: 'rgba(200, 80, 255, 0.6)' }} />
              P -- Pressure (urgency)
            </div>
            <div className="legend-item">
              <div className="legend-swatch" style={{ background: 'transparent', border: '1px dashed rgba(255, 220, 40, 0.5)' }} />
              E(t) -- Energy accumulator
            </div>
          </div>
          <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 8 }}>
            <div className="legend-item" style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)' }}>
              Phase Census:
            </div>
            {Object.entries(thermoData.phase_census || {}).map(([phase, pct]) => (
              <div key={phase} className="legend-item" style={{ fontSize: 10 }}>
                <span style={{ color: phase === 'frozen_solid' ? '#28a0ff' : phase === 'crystal' ? '#64dcff' : phase === 'gas' ? '#ff5028' : '#50ff78' }}>
                  {phase}: {pct}%
                </span>
              </div>
            ))}
          </div>
          {thermoData.meter && (
            <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 8 }}>
              <div className="legend-item">
                <span style={{ color: '#ff6b35', fontWeight: 600 }}>{thermoData.meter.time_signature}</span>
                &nbsp;({thermoData.meter.meter_type})
              </div>
              <div className="legend-item">
                <span style={{ color: '#ff6b35', fontWeight: 600 }}>{thermoData.meter.bpm_tactus} BPM</span>
              </div>
              <div className="legend-item" style={{ color: 'rgba(255,255,255,0.5)', fontSize: 10 }}>
                {thermoData.freezing_events?.length} freezing events
              </div>
            </div>
          )}
        </>
      ) : <div style={{ color: 'rgba(255,255,255,0.4)' }}>No thermo data. Run engine first.</div>}
    </>
  );
}

/**
 * Legend for the legacy spike-grid meter view.
 */
export function Phase3GridLegend({ gridData }) {
  return (
    <>
      <h3>Phase 3 -- Spike Grid (Legacy Meter)</h3>
      {gridData ? (
        <>
          <div className="legend-item">
            <div className="legend-swatch" style={{ background: 'rgba(255,210,60,0.8)', boxShadow: '0 0 4px rgba(255,210,60,0.4)' }} />
            Barline (Spike-Snapped)
          </div>
          <div className="legend-item">
            <div className="legend-swatch" style={{ background: 'rgba(255,210,60,0.3)', border: '1px solid rgba(255,210,60,0.5)' }} />
            Barline (Dead-Reckoned)
          </div>
          <div className="legend-item" style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 8 }}>
            <span style={{ color: '#ffd640', fontWeight: 600 }}>{gridData.time_signature}</span>
            &nbsp;Time Signature
          </div>
          <div className="legend-item">
            <span style={{ color: '#ffd640', fontWeight: 600 }}>{gridData.bpm_tactus} BPM</span>
            &nbsp;Tactus
          </div>
          {gridData.subdivision > 1 && (
            <div className="legend-item">
              <span style={{ color: '#ffaa30', fontWeight: 600 }}>{gridData.subdivision}×</span>
              &nbsp;subdivision ({gridData.sub_tactus_ms}ms → {gridData.tactus_ms}ms)
            </div>
          )}
          <div className="legend-item" style={{ color: 'rgba(255,255,255,0.5)', fontSize: 10, marginTop: 4 }}>
            {gridData.barlines?.filter(b => b.snapped).length}/{gridData.barlines?.length} barlines snapped
          </div>
          <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 8 }}>
            <div className="legend-item">
              <div className="legend-swatch" style={{ background: 'rgba(255,150,40,0.7)', borderRadius: 1 }} />
              Spike Density (bottom strip)
            </div>
            <div className="legend-item">
              <div className="legend-swatch" style={{ background: 'transparent', border: '1px solid rgba(255,165,40,0.6)' }} />
              ACF curve (ruler)
            </div>
            {gridData.autocorr_peak_ms && (
              <div className="legend-item" style={{ color: 'rgba(255,220,60,0.9)', fontSize: 10, marginTop: 4 }}>
                ACF peak: <strong>{gridData.autocorr_peak_ms}ms</strong>
                &nbsp;= {gridData.beats_per_measure} beats × {gridData.tactus_ms}ms
              </div>
            )}
          </div>
        </>
      ) : <div style={{ color: 'rgba(255,255,255,0.4)' }}>No grid data. Run engine first.</div>}
    </>
  );
}
