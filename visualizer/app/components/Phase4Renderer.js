'use client';

// ===== Phase 4: Meter Evidence Bus =====
// 'phase4' → bus barline grid overlaid on the piano roll. The heavy
// lifting reuses renderBarlineGrid from Phase3Renderer; this module owns
// the legend. Bus output: phase4_bus_*.json (see phase4_meter_bus.py and
// docs/phase4_signal_scaffold.md).

/**
 * Legend for the meter evidence bus view.
 */
export function Phase4BusLegend({ busData }) {
  const meter = busData?.meter;
  const dbg = busData?.debug;
  return (
    <>
      <h3>Phase 4 -- Meter Evidence Bus</h3>
      {meter ? (
        <>
          <div className="legend-item">
            <span style={{ color: '#64b5f6', fontWeight: 600 }}>{meter.time_signature}</span>
            &nbsp;Time Signature
          </div>
          <div className="legend-item">
            <span style={{ color: '#64b5f6', fontWeight: 600 }}>{meter.bpm_tactus} BPM</span>
            &nbsp;Tactus ({meter.beat_ms}ms)
          </div>
          {dbg && (
            <>
              <div className="legend-item" style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)' }}>
                grouping {dbg.grouping}{dbg.compound ? ' (compound)' : ''} ·
                bar phase {dbg.measure_phase_ms}ms
              </div>
              <div style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 8 }}>
                <div className="legend-item" style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)' }}>
                  Vote channels:
                </div>
                {Object.entries(dbg.channel_vote_counts || {}).map(([ch, n]) => (
                  <div key={ch} className="legend-item" style={{ fontSize: 10 }}>
                    <span style={{ color: ch.startsWith('extra:') ? '#ffb74d' : 'rgba(255,255,255,0.75)' }}>
                      {ch}: {n}
                    </span>
                  </div>
                ))}
                <div className="legend-item" style={{ fontSize: 10, color: 'rgba(255,255,255,0.75)' }}>
                  parallelism: {dbg.parallelism_votes} period votes
                </div>
              </div>
              <div style={{ marginTop: 8, fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>
                One joint (period, phase) argmax over all channels.
                Orange channels are this pipeline&apos;s Phase 1 spikes /
                Phase 3 freezes.
              </div>
            </>
          )}
        </>
      ) : <div style={{ color: 'rgba(255,255,255,0.4)' }}>No bus data. Run engine first.</div>}
    </>
  );
}
