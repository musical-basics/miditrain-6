'use client';

import React from 'react';

// ── palette ────────────────────────────────────────────────────────────
const C = {
  bg: '#0d0d12', panel: '#14141c', panel2: '#1a1a24', border: '#2a2a38',
  ink: '#e8e8f0', dim: '#9a9ab0', faint: '#5a5a70',
  gt: '#ffffff', bus: '#4a9eff', thermo: '#ff6b35', spike: '#ffd640',
  good: '#3ddc84', warn: '#ffb300', bad: '#ff5252',
};
const ENGINES = ['bus', 'thermo', 'spike'];
const ENGINE_COLOR = { bus: C.bus, thermo: C.thermo, spike: C.spike };

const PITCH_MIN = 21, PITCH_MAX = 108;

function tone(correctLevel, errors) {
  if (errors === 0) return C.good;
  if (correctLevel) return C.warn;
  return C.bad;
}

// ── page ───────────────────────────────────────────────────────────────
export default function MeterDiagnostic() {
  const [runs, setRuns] = React.useState([]);
  const [run, setRun] = React.useState(null);
  const [manifest, setManifest] = React.useState(null);
  const [pieceId, setPieceId] = React.useState(null);
  const [piece, setPiece] = React.useState(null);
  const [tierFilter, setTierFilter] = React.useState('all');
  const [sortBy, setSortBy] = React.useState('errors');
  const [error, setError] = React.useState(null);
  const [zoom, setZoom] = React.useState(1);

  // run list
  React.useEffect(() => {
    fetch('/api/meter-runs')
      .then(r => r.json())
      .then(j => {
        setRuns(j.runs || []);
        const qs = new URLSearchParams(window.location.search).get('run');
        const initial = (qs && j.runs?.includes(qs)) ? qs : j.runs?.[0];
        if (initial) setRun(initial);
        else setError('No diagnostic runs found. Run: python3 run_meter_diag.py');
      })
      .catch(e => setError(String(e)));
  }, []);

  // manifest for the selected run
  React.useEffect(() => {
    if (!run) return;
    setManifest(null); setPiece(null); setPieceId(null);
    fetch(`/meterdiag/${run}/manifest.json`)
      .then(r => r.json())
      .then(m => {
        setManifest(m);
        const worst = [...(m.pieces || [])].sort(
          (a, b) => (b.engines?.bus?.errors ?? 0) - (a.engines?.bus?.errors ?? 0));
        if (worst[0]) setPieceId(worst[0].id);
      })
      .catch(e => setError(String(e)));
  }, [run]);

  // the selected piece document
  React.useEffect(() => {
    if (!run || !pieceId) return;
    fetch(`/meterdiag/${run}/${pieceId}.json`)
      .then(r => r.json()).then(setPiece).catch(e => setError(String(e)));
  }, [run, pieceId]);

  const onRunChange = (name) => {
    setRun(name);
    const u = new URL(window.location.href);
    u.searchParams.set('run', name);
    window.history.replaceState({}, '', u);
  };

  const rows = React.useMemo(() => {
    if (!manifest) return [];
    let r = manifest.pieces || [];
    if (tierFilter !== 'all') r = r.filter(p => p.tier === tierFilter);
    const key = (p) => {
      if (sortBy === 'errors') return -(p.engines?.bus?.errors ?? 0);
      if (sortBy === 'ratio') return -Math.abs((p.engines?.bus?.ratio ?? 1) - 1);
      return p.id;
    };
    return [...r].sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0));
  }, [manifest, tierFilter, sortBy]);

  if (error) return <Centered>{error}</Centered>;
  if (!manifest) return <Centered>Loading…</Centered>;

  const tiers = ['all', ...new Set((manifest.pieces || []).map(p => p.tier))];

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.ink,
                  fontFamily: 'Inter, system-ui, sans-serif' }}>
      <Header run={run} runs={runs} onRunChange={onRunChange} manifest={manifest} />
      <Summary summary={manifest.summary} nPieces={manifest.n_pieces} />

      <div style={{ display: 'flex', gap: 16, padding: '0 20px 28px' }}>
        <PieceList rows={rows} pieceId={pieceId} onPick={setPieceId}
                   tiers={tiers} tierFilter={tierFilter} setTierFilter={setTierFilter}
                   sortBy={sortBy} setSortBy={setSortBy} />
        <div style={{ flex: 1, minWidth: 0 }}>
          {piece ? (
            <>
              <PieceHeader piece={piece} zoom={zoom} setZoom={setZoom} />
              <GridRoll piece={piece} zoom={zoom} />
              <PeriodCurve piece={piece} />
              <MeasureCurve piece={piece} />
            </>
          ) : <Panel><div style={{ color: C.dim }}>Select a piece.</div></Panel>}
        </div>
      </div>
    </div>
  );
}

// ── header + rollup ────────────────────────────────────────────────────
function Header({ run, runs, onRunChange, manifest }) {
  return (
    <div style={{ position: 'sticky', top: 0, zIndex: 20, background: C.panel,
                  borderBottom: `1px solid ${C.border}`, padding: '10px 20px',
                  display: 'flex', alignItems: 'center', gap: 14 }}>
      <h1 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>
        Meter Diagnostic <span style={{ color: C.faint, fontWeight: 400 }}>
          · which level did each engine lock onto?</span>
      </h1>
      <select value={run || ''} onChange={e => onRunChange(e.target.value)}
              style={selectStyle}>
        {runs.map(r => <option key={r} value={r}>{r}</option>)}
      </select>
      <Badge>{manifest.n_pieces} pieces</Badge>
      <Badge>±{manifest.tolerance_ms}ms</Badge>
      <Badge>split: {manifest.split_key}</Badge>
      <a href="/compare" style={{ marginLeft: 'auto', ...linkStyle }}>/compare →</a>
      <a href="/" style={linkStyle}>/ visualizer →</a>
    </div>
  );
}

function Summary({ summary, nPieces }) {
  if (!summary) return null;
  return (
    <div style={{ display: 'flex', gap: 12, padding: '14px 20px 6px', flexWrap: 'wrap' }}>
      {ENGINES.map(eng => {
        const s = summary[eng];
        if (!s) return null;
        const pct = s.pct_wrong_level;
        return (
          <div key={eng} style={{ ...panelStyle, flex: '1 1 260px', padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ width: 10, height: 10, borderRadius: 2,
                             background: ENGINE_COLOR[eng] }} />
              <strong style={{ fontSize: 13 }}>{eng}</strong>
              <span style={{ marginLeft: 'auto', fontSize: 18, fontWeight: 700 }}>
                {s.total_errors}
              </span>
              <span style={{ fontSize: 10, color: C.dim }}>errors</span>
            </div>
            <div style={{ marginTop: 8, height: 6, borderRadius: 3,
                          background: C.panel2, overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: C.bad }} />
            </div>
            <div style={{ marginTop: 6, fontSize: 11, color: C.dim }}>
              <strong style={{ color: C.bad }}>{pct}%</strong> from wrong metrical level
              &nbsp;({s.errors_from_wrong_level}) · {s.errors_from_phase_or_jitter} phase/jitter
            </div>
            <div style={{ marginTop: 3, fontSize: 10, color: C.faint }}>
              level correct on {s.pieces_correct_level}/{nPieces} pieces ·
              wrong on {s.pieces_wrong_level} · no prediction {s.pieces_no_prediction}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── piece list ─────────────────────────────────────────────────────────
function PieceList({ rows, pieceId, onPick, tiers, tierFilter, setTierFilter,
                     sortBy, setSortBy }) {
  return (
    <div style={{ ...panelStyle, width: 340, flexShrink: 0, padding: 0,
                  maxHeight: 'calc(100vh - 190px)', overflowY: 'auto' }}>
      <div style={{ position: 'sticky', top: 0, background: C.panel,
                    borderBottom: `1px solid ${C.border}`, padding: 8,
                    display: 'flex', gap: 6 }}>
        <select value={tierFilter} onChange={e => setTierFilter(e.target.value)}
                style={{ ...selectStyle, flex: 1 }}>
          {tiers.map(t => <option key={t} value={t}>{t === 'all' ? 'all tiers' : t}</option>)}
        </select>
        <select value={sortBy} onChange={e => setSortBy(e.target.value)}
                style={{ ...selectStyle, flex: 1 }}>
          <option value="errors">by errors</option>
          <option value="ratio">by |ratio−1|</option>
          <option value="id">by name</option>
        </select>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr style={{ color: C.faint }}>
            <Th style={{ textAlign: 'left' }}>piece</Th>
            <Th>bus</Th><Th>ratio</Th><Th>thm</Th><Th>spk</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map(p => {
            const b = p.engines?.bus || {};
            const sel = p.id === pieceId;
            return (
              <tr key={p.id} onClick={() => onPick(p.id)}
                  style={{ cursor: 'pointer', background: sel ? C.panel2 : 'transparent',
                           borderLeft: `3px solid ${sel ? C.bus : 'transparent'}` }}>
                <Td style={{ textAlign: 'left', color: sel ? C.ink : C.dim }}>
                  {p.id.replace('essenFolksong_altdeu10_', 'essen_')
                       .replace('schumann_clara_', 'schumann_')}
                  <div style={{ fontSize: 9, color: C.faint }}>
                    {p.gt_ts} · {p.gt_measure_ms}ms
                  </div>
                </Td>
                <Td style={{ color: tone(b.correct_level, b.errors), fontWeight: 600 }}>
                  {b.errors}
                </Td>
                <Td style={{ color: b.correct_level ? C.good : C.bad }}>
                  {b.ratio == null ? '—' : b.ratio.toFixed(2)}
                </Td>
                <Td style={{ color: C.faint }}>{p.engines?.thermo?.errors ?? '—'}</Td>
                <Td style={{ color: C.faint }}>{p.engines?.spike?.errors ?? '—'}</Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── selected piece: scorecard ──────────────────────────────────────────
function PieceHeader({ piece, zoom, setZoom }) {
  const gt = piece.ground_truth;
  return (
    <Panel>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 14 }}>{piece.id}</strong>
        <Badge>{piece.tier}</Badge>
        {gt.meter_changes && <Badge tone={C.warn}>meter changes</Badge>}
        <span style={{ fontSize: 11, color: C.dim }}>
          truth: <strong style={{ color: C.gt }}>{gt.time_signature}</strong> ·
          measure {gt.measure_ms}ms · beat {gt.beat_ms}ms ·
          {gt.downbeats.length} downbeats · anacrusis {gt.anacrusis_ms}ms
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 10, color: C.faint }}>zoom</span>
          <input type="range" min="0.25" max="4" step="0.25" value={zoom}
                 onChange={e => setZoom(+e.target.value)} style={{ width: 110 }} />
        </span>
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 12, flexWrap: 'wrap' }}>
        {ENGINES.map(eng => {
          const d = piece.engines?.[eng];
          if (!d) return null;
          if (d.error) return (
            <div key={eng} style={{ ...cardStyle, borderColor: C.border }}>
              <div style={{ color: ENGINE_COLOR[eng], fontWeight: 700, fontSize: 12 }}>{eng}</div>
              <div style={{ fontSize: 10, color: C.bad, marginTop: 4 }}>{d.error}</div>
            </div>
          );
          const t = tone(d.correct_level, d.errors);
          return (
            <div key={eng} style={{ ...cardStyle, borderColor: t }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                <span style={{ color: ENGINE_COLOR[eng], fontWeight: 700, fontSize: 12 }}>{eng}</span>
                <span style={{ marginLeft: 'auto', fontSize: 16, fontWeight: 700, color: t }}>
                  {d.errors}
                </span>
              </div>
              <div style={{ fontSize: 10, color: C.dim, marginTop: 5 }}>
                {d.time_signature} · {d.measure_ms}ms · F1 {(d.f1 * 100).toFixed(0)}%
              </div>
              <div style={{ fontSize: 10, marginTop: 3 }}>
                <span style={{ color: C.faint }}>ratio </span>
                <strong style={{ color: t }}>{d.ratio?.toFixed(2) ?? '—'}</strong>
                {d.level && <span style={{ color: C.faint }}> · {d.level}</span>}
              </div>
              <div style={{ fontSize: 9, color: C.faint, marginTop: 2 }}>
                {d.tp}TP {d.fp}FP {d.fn}FN · {d.barlines?.length} barlines
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ── the roll: notes + four barline rows on one timeline ────────────────
function GridRoll({ piece, zoom }) {
  const notes = piece.notes || [];
  const gt = piece.ground_truth;
  const maxT = Math.max(
    ...notes.map(n => n.o + n.d),
    ...(gt.downbeats.length ? [gt.downbeats[gt.downbeats.length - 1]] : [0]),
    1000);
  const W = Math.max(900, Math.min(24000, (maxT / 1000) * 60 * zoom));
  const scale = W / maxT;

  const pitches = notes.map(n => n.p);
  const lo = Math.max(PITCH_MIN, Math.min(...pitches, 60) - 3);
  const hi = Math.min(PITCH_MAX, Math.max(...pitches, 72) + 3);
  const rollH = 190, laneH = 22;
  const lanes = [{ key: 'gt', label: 'ground truth', color: C.gt,
                   lines: gt.downbeats },
                 ...ENGINES.map(e => ({ key: e, label: e, color: ENGINE_COLOR[e],
                                        lines: piece.engines?.[e]?.barlines || [] }))];
  const H = rollH + lanes.length * laneH + 22;
  const y = (p) => rollH - ((p - lo) / Math.max(1, hi - lo)) * (rollH - 10) - 4;

  return (
    <Panel>
      <Caption>
        Notes with every grid overlaid on one timeline. A picket fence against
        sparse white lines = wrong metrical level; a uniform sideways shift =
        phase error.
      </Caption>
      <div style={{ overflowX: 'auto', overflowY: 'hidden', marginTop: 8 }}>
        <svg width={W} height={H} style={{ display: 'block', background: C.bg }}>
          {/* second gridlines */}
          {Array.from({ length: Math.floor(maxT / 1000) + 1 }, (_, i) => (
            <line key={i} x1={i * 1000 * scale} x2={i * 1000 * scale} y1={0} y2={rollH}
                  stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
          ))}
          {/* notes */}
          {notes.map((n, i) => (
            <rect key={i} x={n.o * scale} y={y(n.p)}
                  width={Math.max(1.5, n.d * scale)} height={4} rx={1}
                  fill={`hsla(210,70%,62%,${0.35 + (n.v / 127) * 0.5})`} />
          ))}
          {/* barline lanes */}
          {lanes.map((lane, li) => {
            const top = rollH + li * laneH;
            return (
              <g key={lane.key}>
                <rect x={0} y={top} width={W} height={laneH - 3}
                      fill="rgba(255,255,255,0.025)" />
                <text x={4} y={top + 13} fontSize={9} fill={lane.color}
                      style={{ fontWeight: 600 }}>{lane.label}</text>
                {lane.lines.map((t, i) => (
                  <line key={i} x1={t * scale} x2={t * scale}
                        y1={top + 2} y2={top + laneH - 5}
                        stroke={lane.color}
                        strokeWidth={lane.key === 'gt' ? 1.6 : 1.1}
                        opacity={lane.key === 'gt' ? 0.95 : 0.8} />
                ))}
                {/* GT lines continue faintly through the roll for alignment */}
                {lane.key === 'gt' && lane.lines.map((t, i) => (
                  <line key={`g${i}`} x1={t * scale} x2={t * scale} y1={0} y2={rollH}
                        stroke="rgba(255,255,255,0.22)" strokeWidth={1} />
                ))}
              </g>
            );
          })}
          {/* seconds ruler */}
          {Array.from({ length: Math.floor(maxT / 5000) + 1 }, (_, i) => (
            <text key={i} x={i * 5000 * scale + 2} y={H - 5} fontSize={9} fill={C.faint}>
              {i * 5}s
            </text>
          ))}
        </svg>
      </div>
      {piece.notes_truncated && (
        <div style={{ fontSize: 10, color: C.warn, marginTop: 4 }}>
          Note display truncated; grids and scores use the full piece.
        </div>
      )}
    </Panel>
  );
}

// ── the why: tactus period objective ───────────────────────────────────
function PeriodCurve({ piece }) {
  const rows = piece.curves?.tactus || [];
  if (!rows.length) return null;
  const prior = piece.curves.prior;
  const W = 900, H = 210, padL = 44, padB = 26, padT = 10;
  const xs = rows.map(r => Math.log2(r.period_ms));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const X = (ms) => padL + ((Math.log2(ms) - x0) / (x1 - x0)) * (W - padL - 12);
  const maxS = Math.max(...rows.map(r => r.score), 1e-9);
  const maxE = Math.max(...rows.map(r => r.evidence), 1e-9);
  const Y = (v, m) => padT + (1 - v / m) * (H - padT - padB);

  const busTactus = piece.engines?.bus?.tactus_ms;
  const gtBeat = piece.ground_truth.beat_ms;
  const inRange = (ms) => ms >= prior.search_min_ms && ms <= prior.search_max_ms;

  const path = (key, m) => rows.map((r, i) =>
    `${i ? 'L' : 'M'}${X(r.period_ms).toFixed(1)},${Y(r[key], m).toFixed(1)}`).join('');

  return (
    <Panel>
      <Caption>
        <strong>Tactus objective</strong> — score vs candidate beat period
        (log axis). Blue = final score, grey = raw evidence before the prior,
        dashed = the prior envelope itself. Where the chosen line and the
        truth marker disagree, this shows whether evidence or prior decided it.
      </Caption>
      <svg width={W} height={H} style={{ display: 'block', marginTop: 6 }}>
        {[250, 500, 1000, 1600].filter(inRange).map(ms => (
          <g key={ms}>
            <line x1={X(ms)} x2={X(ms)} y1={padT} y2={H - padB}
                  stroke="rgba(255,255,255,0.06)" />
            <text x={X(ms)} y={H - 10} fontSize={9} fill={C.faint} textAnchor="middle">
              {ms}ms
            </text>
          </g>
        ))}
        <path d={path('evidence', maxE)} fill="none" stroke={C.faint} strokeWidth={1} />
        <path d={rows.map((r, i) =>
          `${i ? 'L' : 'M'}${X(r.period_ms).toFixed(1)},${Y(r.prior * maxS, maxS).toFixed(1)}`
        ).join('')} fill="none" stroke={C.dim} strokeWidth={1} strokeDasharray="3 3" />
        <path d={path('score', maxS)} fill="none" stroke={C.bus} strokeWidth={1.8} />

        {busTactus && inRange(busTactus) && (
          <Marker x={X(busTactus)} H={H} padT={padT} padB={padB} color={C.bus}
                  label={`bus ${busTactus}ms`} />
        )}
        {gtBeat && inRange(gtBeat) && (
          <Marker x={X(gtBeat)} H={H} padT={padT} padB={padB} color={C.gt}
                  label={`truth beat ${gtBeat}ms`} dash />
        )}
        {gtBeat && !inRange(gtBeat) && (
          <text x={padL + 6} y={padT + 14} fontSize={11} fill={C.bad}>
            truth beat {gtBeat}ms is OUTSIDE the {prior.search_min_ms}–
            {prior.search_max_ms}ms search range — unreachable by construction
          </text>
        )}
        <text x={4} y={padT + 8} fontSize={9} fill={C.faint}>score</text>
      </svg>
      <div style={{ fontSize: 10, color: C.faint, marginTop: 2 }}>
        prior: centre {prior.tactus_center_ms}ms, σ {prior.tactus_sigma_oct} oct ·
        search {prior.search_min_ms}–{prior.search_max_ms}ms
      </div>
    </Panel>
  );
}

// ── the why: measure grouping objective ────────────────────────────────
function MeasureCurve({ piece }) {
  const rows = piece.curves?.measure || [];
  if (!rows.length) return null;
  const prior = piece.curves.prior;
  const gtM = piece.ground_truth.measure_ms;
  const best = Math.max(...rows.map(r => r.score), 1e-9);
  return (
    <Panel>
      <Caption>
        <strong>Measure grouping</strong> — the second argmax: how many tactus
        beats per bar. The bus can only choose 2, 3, or 4, so if the truth needs
        a different multiple of its chosen beat, no grouping here can reach it.
      </Caption>
      <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
        {rows.map(r => {
          const chosen = r.grouping === piece.engines?.bus?.grouping;
          const reachesTruth = Math.abs(r.measure_ms - gtM) <= 0.06 * gtM;
          return (
            <div key={r.grouping} style={{ ...cardStyle, minWidth: 150,
                 borderColor: chosen ? C.bus : reachesTruth ? C.good : C.border }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                <strong style={{ fontSize: 12 }}>G = {r.grouping}</strong>
                {chosen && <Badge tone={C.bus}>chosen</Badge>}
                {reachesTruth && !chosen && <Badge tone={C.good}>= truth</Badge>}
              </div>
              <div style={{ fontSize: 10, color: C.dim, marginTop: 5 }}>
                measure {Math.round(r.measure_ms)}ms
              </div>
              <div style={{ marginTop: 6, height: 5, background: C.panel2, borderRadius: 3 }}>
                <div style={{ width: `${(r.score / best) * 100}%`, height: '100%',
                              background: chosen ? C.bus : C.faint, borderRadius: 3 }} />
              </div>
              <div style={{ fontSize: 9, color: C.faint, marginTop: 3 }}>
                score {r.score} · prior {r.prior}
              </div>
            </div>
          );
        })}
        <div style={{ ...cardStyle, minWidth: 150, borderColor: C.gt }}>
          <strong style={{ fontSize: 12, color: C.gt }}>truth</strong>
          <div style={{ fontSize: 10, color: C.dim, marginTop: 5 }}>
            measure {gtM}ms
          </div>
          <div style={{ fontSize: 9, color: C.faint, marginTop: 8 }}>
            {rows.some(r => Math.abs(r.measure_ms - gtM) <= 0.06 * gtM)
              ? 'reachable from the chosen tactus'
              : 'NOT reachable from the chosen tactus at G∈{2,3,4}'}
          </div>
        </div>
      </div>
      <div style={{ fontSize: 10, color: C.faint, marginTop: 6 }}>
        measure prior: centre {prior.measure_center_ms}ms, σ {prior.measure_sigma_oct} oct
      </div>
    </Panel>
  );
}

// ── bits ───────────────────────────────────────────────────────────────
function Marker({ x, H, padT, padB, color, label, dash }) {
  return (
    <g>
      <line x1={x} x2={x} y1={padT} y2={H - padB} stroke={color} strokeWidth={1.4}
            strokeDasharray={dash ? '4 3' : undefined} opacity={0.9} />
      <text x={x + 4} y={padT + 10} fontSize={9} fill={color}>{label}</text>
    </g>
  );
}

const panelStyle = { background: C.panel, border: `1px solid ${C.border}`,
                     borderRadius: 8, padding: 14 };
const cardStyle = { background: C.panel2, border: '1px solid', borderRadius: 6,
                    padding: 10, minWidth: 160 };
const selectStyle = { background: C.panel2, color: C.ink, border: `1px solid ${C.border}`,
                      borderRadius: 4, padding: '4px 8px', fontSize: 11 };
const linkStyle = { color: C.dim, fontSize: 11, textDecoration: 'none',
                    border: `1px solid ${C.border}`, borderRadius: 4, padding: '4px 8px' };

function Panel({ children }) {
  return <div style={{ ...panelStyle, marginBottom: 12 }}>{children}</div>;
}
function Caption({ children }) {
  return <div style={{ fontSize: 11, color: C.dim, lineHeight: 1.5 }}>{children}</div>;
}
function Badge({ children, tone }) {
  return <span style={{ fontSize: 10, color: tone || C.dim, border: `1px solid ${tone || C.border}`,
                        borderRadius: 3, padding: '1px 6px' }}>{children}</span>;
}
function Th({ children, style }) {
  return <th style={{ padding: '6px 6px', fontWeight: 600, textAlign: 'right',
                      fontSize: 10, ...style }}>{children}</th>;
}
function Td({ children, style }) {
  return <td style={{ padding: '5px 6px', textAlign: 'right',
                      borderTop: `1px solid ${C.border}`, ...style }}>{children}</td>;
}
function Centered({ children }) {
  return <div style={{ background: C.bg, color: C.dim, minHeight: '100vh',
                       display: 'flex', alignItems: 'center', justifyContent: 'center',
                       fontFamily: 'Inter, sans-serif', fontSize: 13 }}>{children}</div>;
}
