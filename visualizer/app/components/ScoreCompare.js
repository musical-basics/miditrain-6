'use client';

/**
 * Score Comparison GUI
 * ============================================================================
 * Generated MusicXML (MIDI -> MidiTrain engine -> back-propagated score)
 * vs. the human-authored reference MusicXML.
 *
 * NOTES ONLY. Dynamics, articulations, fingerings, slurs, ornaments and layout
 * are deliberately out of scope — both the renderer and the diff ignore them.
 *
 * Data comes from public/compare/<run>/ written by run_xml_compare.py:
 *   manifest.json          run config + headline accuracy
 *   generated_score.json   IntermediateScore from Phase 5B
 *   reference_score.json   IntermediateScore converted from the reference XML
 *   comparison.json        per-note matched / extra / missing
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import NotationView from './NotationView';

const RUNS_ENDPOINT = '/api/compare-runs';

const C = {
  bg: '#0d0d12',
  panel: '#15151d',
  panelAlt: '#1b1b25',
  border: '#2a2a38',
  text: '#e8e8f0',
  dim: '#8a8a9e',
  good: '#3ddc84',
  bad: '#ff5c6c',
  warn: '#ffb340',
  accent: '#6c8cff',
};

const pct = (x) => `${(x * 100).toFixed(1)}%`;

export default function ScoreCompare() {
  const [runs, setRuns] = useState([]);
  const [run, setRun] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [view, setView] = useState('stacked'); // stacked | generated | reference | table
  const [filter, setFilter] = useState('all'); // all | mismatch | extra | missing
  const [showDurations, setShowDurations] = useState(true);
  const [colorMode, setColorMode] = useState('diff'); // diff | harmonic

  // discover available runs
  useEffect(() => {
    let alive = true;
    fetch(RUNS_ENDPOINT)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('no runs endpoint'))))
      .then((j) => {
        if (!alive) return;
        setRuns(j.runs || []);
        const initial =
          new URLSearchParams(window.location.search).get('run') || (j.runs || [])[0];
        setRun(initial || null);
        if (!initial) setLoading(false);
      })
      .catch((e) => {
        if (alive) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  // load the selected run
  useEffect(() => {
    if (!run) return;
    let alive = true;
    setLoading(true);
    setError(null);

    const base = `/compare/${run}`;
    Promise.all([
      fetch(`${base}/manifest.json`).then((r) => r.json()),
      fetch(`${base}/generated_score.json`).then((r) => r.json()),
      fetch(`${base}/reference_score.json`).then((r) => r.json()),
      fetch(`${base}/comparison.json`).then((r) => r.json()),
    ])
      .then(([manifest, generated, reference, comparison]) => {
        if (!alive) return;
        setData({ manifest, generated, reference, comparison });
        setLoading(false);
      })
      .catch((e) => {
        if (!alive) return;
        setError(`could not load run "${run}": ${e.message}`);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [run]);

  const rows = useMemo(() => {
    if (!data) return [];
    const { comparison } = data;
    const out = [];
    for (const p of comparison.pairs || []) {
      const durOK = p.duration_match;
      const spellOK = p.spelling_match;
      out.push({
        kind: durOK && spellOK ? 'match' : 'mismatch',
        measure: p.gen_measure,
        onset: p.onset_q,
        gen: p.gen_name,
        ref: p.ref_name,
        genDur: p.gen_dur_q,
        refDur: p.ref_dur_q,
        spellOK,
        durOK,
      });
    }
    for (const e of comparison.extra || []) {
      out.push({
        kind: 'extra', measure: e.measure, onset: e.onset_q,
        gen: e.name, ref: '—', genDur: e.dur_q, refDur: null,
        spellOK: false, durOK: false,
      });
    }
    for (const m of comparison.missing || []) {
      out.push({
        kind: 'missing', measure: m.measure, onset: m.onset_q,
        gen: '—', ref: m.name, genDur: null, refDur: m.dur_q,
        spellOK: false, durOK: false,
      });
    }
    out.sort((a, b) => a.onset - b.onset || String(a.gen).localeCompare(String(b.gen)));
    return out;
  }, [data]);

  const filtered = useMemo(() => {
    if (filter === 'all') return rows;
    if (filter === 'mismatch') return rows.filter((r) => r.kind === 'mismatch');
    return rows.filter((r) => r.kind === filter);
  }, [rows, filter]);

  const onRunChange = useCallback((e) => {
    const v = e.target.value;
    setRun(v);
    const u = new URL(window.location.href);
    u.searchParams.set('run', v);
    window.history.replaceState({}, '', u);
  }, []);

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text,
      fontFamily: 'Inter, system-ui, sans-serif' }}>
      <Header
        runs={runs} run={run} onRunChange={onRunChange}
        view={view} setView={setView}
        manifest={data?.manifest}
      />

      {loading && <Centered>Loading…</Centered>}
      {error && !loading && <Centered tone={C.bad}>{error}</Centered>}
      {!loading && !error && !run && (
        <Centered>
          No comparison runs yet. Generate one:
          <pre style={{ marginTop: 12, color: C.dim, fontSize: 12 }}>
{`python3 run_xml_compare.py \\
  --midi "musicxmls/your.mid" \\
  --xml  "musicxmls/your.musicxml" \\
  --name yourname`}
          </pre>
        </Centered>
      )}

      {!loading && !error && data && (
        <>
          <Scorecard manifest={data.manifest} />

          {view !== 'table' && (
            <>
              <ColorLegend colorMode={colorMode} setColorMode={setColorMode} />
              <ScorePanes
                view={view}
                generated={data.generated}
                reference={data.reference}
                colorMode={colorMode}
                comparison={data.comparison}
                ticksPerQuarter={data.manifest.ticks_per_quarter || 4}
              />
            </>
          )}

          {view === 'table' && (
            <NoteTable
              rows={filtered} allRows={rows} filter={filter} setFilter={setFilter}
              showDurations={showDurations} setShowDurations={setShowDurations}
            />
          )}
        </>
      )}
    </div>
  );
}

function Centered({ children, tone }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '60vh', color: tone || C.dim, fontSize: 14 }}>
      {children}
    </div>
  );
}

function Header({ runs, run, onRunChange, view, setView, manifest }) {
  const tabs = [
    ['stacked', 'Both scores'],
    ['generated', 'Generated only'],
    ['reference', 'Reference only'],
    ['table', 'Note-by-note'],
  ];
  return (
    <div style={{ borderBottom: `1px solid ${C.border}`, background: C.panel,
      padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 20,
      flexWrap: 'wrap', position: 'sticky', top: 0, zIndex: 20 }}>
      <div style={{ fontWeight: 600, fontSize: 15, letterSpacing: 0.2 }}>
        Score Comparison
        <span style={{ color: C.dim, fontWeight: 400, marginLeft: 10, fontSize: 12 }}>
          generated vs. reference · notes only
        </span>
      </div>

      <select value={run || ''} onChange={onRunChange} style={selectStyle}>
        {runs.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>

      {manifest && (
        <span style={{ color: C.dim, fontSize: 12 }}>
          engine <b style={{ color: C.text }}>{manifest.engine}</b> · voices{' '}
          <b style={{ color: C.text }}>{manifest.phase2_model}</b> · key{' '}
          <b style={{ color: C.text }}>{manifest.key_algo}</b>
        </span>
      )}

      <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
        {tabs.map(([k, label]) => (
          <button key={k} onClick={() => setView(k)} style={{
            ...btnStyle,
            background: view === k ? C.accent : 'transparent',
            color: view === k ? '#0d0d12' : C.dim,
            fontWeight: view === k ? 600 : 400,
          }}>{label}</button>
        ))}
      </div>
    </div>
  );
}

function Scorecard({ manifest }) {
  const a = manifest.note_accuracy || {};
  const c = manifest.counts || {};
  const s = manifest.secondary || {};
  const perfect = c.extra_in_generated === 0 && c.missing_from_generated === 0;

  return (
    <div style={{ display: 'flex', gap: 12, padding: '16px 20px', flexWrap: 'wrap',
      borderBottom: `1px solid ${C.border}`, background: C.panelAlt }}>
      <Stat label="Note F1" value={pct(a.f1 ?? 0)}
        tone={a.f1 >= 0.999 ? C.good : a.f1 >= 0.9 ? C.warn : C.bad} big />
      <Stat label="Precision" value={pct(a.precision ?? 0)} />
      <Stat label="Recall" value={pct(a.recall ?? 0)} />
      <Divider />
      <Stat label="Matched" value={c.matched} tone={C.good} />
      <Stat label="Extra" value={c.extra_in_generated}
        tone={c.extra_in_generated ? C.bad : C.dim} />
      <Stat label="Missing" value={c.missing_from_generated}
        tone={c.missing_from_generated ? C.bad : C.dim} />
      <Divider />
      <Stat label="Spelling" value={pct(s.spelling_pct ?? 0)}
        tone={s.spelling_pct >= 0.99 ? C.good : C.warn} sub="not note identity" />
      <Stat label="Duration" value={pct(s.duration_pct ?? 0)}
        tone={s.duration_pct >= 0.99 ? C.good : C.warn} sub="not note identity" />

      {perfect && (
        <div style={{ marginLeft: 'auto', alignSelf: 'center', color: C.good,
          fontSize: 13, fontWeight: 600 }}>
          ✓ every note reconstructed
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone, sub, big }) {
  return (
    <div style={{ minWidth: 92 }}>
      <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.7,
        color: C.dim, marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: big ? 26 : 20, fontWeight: 600,
        color: tone || C.text, lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: C.dim, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

const Divider = () => (
  <div style={{ width: 1, background: C.border, alignSelf: 'stretch', margin: '0 4px' }} />
);

function ColorLegend({ colorMode, setColorMode }) {
  const swatches = colorMode === 'diff'
    ? [['rgba(232,232,240,0.92)', 'matches the reference'],
       [C.warn, 'right note, different duration/spelling'],
       [C.bad, 'not in the reference']]
    : [['linear-gradient(90deg,#ff004c,#ffb340,#3ddc84,#6c8cff)',
        'Phase 1 harmonic colour']];

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
      padding: '9px 20px', background: C.panelAlt,
      borderBottom: `1px solid ${C.border}` }}>
      <div style={{ display: 'flex', gap: 4 }}>
        {[['diff', 'Colour by difference'], ['harmonic', 'Colour by harmony']]
          .map(([k, label]) => (
            <button key={k} onClick={() => setColorMode(k)} style={{
              ...btnStyle,
              padding: '4px 10px', fontSize: 11.5,
              background: colorMode === k ? C.accent : 'transparent',
              color: colorMode === k ? '#0d0d12' : C.dim,
              fontWeight: colorMode === k ? 600 : 400,
            }}>{label}</button>
          ))}
      </div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        {swatches.map(([col, label]) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11.5, color: C.dim }}>
            <span style={{ width: 11, height: 11, borderRadius: 3, background: col,
              display: 'inline-block', border: `1px solid ${C.border}` }} />
            {label}
          </span>
        ))}
      </div>
      <span style={{ marginLeft: 'auto', fontSize: 11, color: C.dim }}>
        colouring applies to the generated stave
      </span>
    </div>
  );
}

/**
 * Recolor a score's notes by comparison status instead of Phase 1 harmonic hue.
 *
 * The generated score's vfId encodes pitch and start tick ("n-<pitch>-<tick>"),
 * so a note is looked up by (pitch, onset-in-quarters). Anything the diff did
 * not match is painted red; duration/spelling disagreements amber; exact
 * matches are left neutral so the eye goes to the problems.
 */
function recolorByStatus(score, comparison, divisionsPerQuarter) {
  if (!score?.measures || !comparison) return score;

  const status = new Map();
  const key = (pitch, onsetQ) => `${pitch}@${Number(onsetQ).toFixed(4)}`;
  for (const p of comparison.pairs || []) {
    status.set(key(p.pitch, p.onset_q),
      p.duration_match && p.spelling_match ? 'match' : 'soft');
  }
  for (const e of comparison.extra || []) status.set(key(e.pitch, e.onset_q), 'hard');

  const TONE = { match: null, soft: C.warn, hard: C.bad };

  return {
    ...score,
    measures: score.measures.map((m) => ({
      ...m,
      staves: m.staves.map((st) => ({
        ...st,
        voices: st.voices.map((v) => ({
          ...v,
          notes: v.notes.map((n) => {
            if (n.isRest) return n;
            const mt = /^n-(\d+)-(\d+)$/.exec(n.vfId || '');
            if (!mt) return n;
            const pitch = Number(mt[1]);
            const onsetQ = Number(mt[2]) / divisionsPerQuarter;
            const s = status.get(key(pitch, onsetQ));
            const tone = s ? TONE[s] : C.bad; // unknown => unmatched
            return tone ? { ...n, color: tone }
                        : { ...n, color: 'rgba(232,232,240,0.92)' };
          }),
        })),
      })),
    })),
  };
}

function ScorePanes({ view, generated, reference, colorMode, comparison,
                      ticksPerQuarter }) {
  const genScore = useMemo(
    () => (colorMode === 'diff'
      ? recolorByStatus(generated, comparison, ticksPerQuarter)
      : generated),
    [colorMode, generated, comparison, ticksPerQuarter]);

  const panes = view === 'stacked'
    ? [['Generated — MIDI through the engine', genScore, C.accent],
       ['Reference — your MusicXML', reference, C.good]]
    : view === 'generated'
      ? [['Generated — MIDI through the engine', genScore, C.accent]]
      : [['Reference — your MusicXML', reference, C.good]];

  // Both staves scroll horizontally through the same music, so lock their
  // scroll positions together — comparing bar 20 against bar 3 is useless.
  const refs = React.useRef([]);
  const syncing = React.useRef(false);

  // store the wrapper; the actual scroller (.notation-view-root) is created by
  // NotationView, so resolve it when we bind rather than at ref time.
  const attach = useCallback((idx) => (el) => { refs.current[idx] = el; }, []);

  useEffect(() => {
    let handlers = [];
    // VexFlow renders asynchronously; retry briefly until both scrollers exist.
    const bind = () => {
      const nodes = refs.current
        .filter(Boolean)
        .map((el) => el.querySelector('.notation-view-root') || el);
      if (nodes.length < 2) return false;
      handlers = nodes.map((node) => {
        const h = () => {
          if (syncing.current) return;
          syncing.current = true;
          for (const other of nodes) {
            if (other !== node) other.scrollLeft = node.scrollLeft;
          }
          requestAnimationFrame(() => { syncing.current = false; });
        };
        node.addEventListener('scroll', h, { passive: true });
        return [node, h];
      });
      return true;
    };

    let tries = 0;
    const timer = setInterval(() => {
      if (bind() || ++tries > 20) clearInterval(timer);
    }, 100);

    return () => {
      clearInterval(timer);
      handlers.forEach(([n, h]) => n.removeEventListener('scroll', h));
    };
  }, [view, generated, reference]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {panes.map(([title, score, tone], i) => (
        <div key={title} style={{ borderBottom: `1px solid ${C.border}` }}>
          <div style={{ padding: '7px 20px', fontSize: 11, fontWeight: 600,
            letterSpacing: 0.5, textTransform: 'uppercase', color: tone,
            background: C.panel, borderLeft: `3px solid ${tone}`,
            display: 'flex', alignItems: 'center', gap: 10 }}>
            {title}
            {view === 'stacked' && i === 0 && (
              <span style={{ marginLeft: 'auto', color: C.dim, fontWeight: 400,
                textTransform: 'none', letterSpacing: 0, fontSize: 10.5 }}>
                scroll either stave — both follow
              </span>
            )}
          </div>
          <div ref={attach(i)} style={{ height: view === 'stacked' ? 300 : 560 }}>
            <NotationView notationData={score} darkMode layoutMode="horizontal" />
          </div>
        </div>
      ))}
    </div>
  );
}

function NoteTable({ rows, allRows, filter, setFilter, showDurations, setShowDurations }) {
  const counts = useMemo(() => ({
    all: allRows.length,
    mismatch: allRows.filter((r) => r.kind === 'mismatch').length,
    extra: allRows.filter((r) => r.kind === 'extra').length,
    missing: allRows.filter((r) => r.kind === 'missing').length,
  }), [allRows]);

  const filters = [
    ['all', 'All notes'],
    ['mismatch', 'Spelling/duration differs'],
    ['extra', 'Extra in generated'],
    ['missing', 'Missing from generated'],
  ];

  return (
    <div style={{ padding: '14px 20px' }}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, alignItems: 'center',
        flexWrap: 'wrap' }}>
        {filters.map(([k, label]) => (
          <button key={k} onClick={() => setFilter(k)} style={{
            ...btnStyle,
            background: filter === k ? C.accent : 'transparent',
            color: filter === k ? '#0d0d12' : C.dim,
            fontWeight: filter === k ? 600 : 400,
          }}>
            {label} <span style={{ opacity: 0.7 }}>({counts[k]})</span>
          </button>
        ))}
        <label style={{ marginLeft: 'auto', fontSize: 12, color: C.dim,
          display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={showDurations}
            onChange={(e) => setShowDurations(e.target.checked)} />
          show durations
        </label>
      </div>

      {rows.length === 0 && (
        <div style={{ color: C.good, fontSize: 13, padding: '24px 0' }}>
          Nothing in this category — the generated score matches the reference here.
        </div>
      )}

      {rows.length > 0 && (
        <div style={{ overflowX: 'auto', border: `1px solid ${C.border}`,
          borderRadius: 6 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5,
            fontVariantNumeric: 'tabular-nums' }}>
            <thead>
              <tr style={{ background: C.panel, textAlign: 'left' }}>
                <Th>Status</Th><Th>Measure</Th><Th>Onset (q)</Th>
                <Th>Generated</Th><Th>Reference</Th>
                {showDurations && <><Th>Gen dur</Th><Th>Ref dur</Th></>}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 2000).map((r, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${C.border}`,
                  background: i % 2 ? 'transparent' : 'rgba(255,255,255,0.015)' }}>
                  <Td><StatusChip kind={r.kind} spellOK={r.spellOK} durOK={r.durOK} /></Td>
                  <Td>{r.measure}</Td>
                  <Td>{r.onset}</Td>
                  <Td tone={r.kind === 'missing' ? C.dim : C.text}>{r.gen}</Td>
                  <Td tone={r.kind === 'extra' ? C.dim : C.text}>{r.ref}</Td>
                  {showDurations && <>
                    <Td tone={r.durOK ? C.text : C.warn}>{r.genDur ?? '—'}</Td>
                    <Td tone={r.durOK ? C.text : C.warn}>{r.refDur ?? '—'}</Td>
                  </>}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 2000 && (
            <div style={{ padding: 10, color: C.dim, fontSize: 11.5 }}>
              showing the first 2000 of {rows.length} rows
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusChip({ kind, spellOK, durOK }) {
  const map = {
    match: ['match', C.good],
    mismatch: [!spellOK ? 'spelling' : 'duration', C.warn],
    extra: ['extra', C.bad],
    missing: ['missing', C.bad],
  };
  const [label, tone] = map[kind] || ['?', C.dim];
  return (
    <span style={{ color: tone, border: `1px solid ${tone}44`, background: `${tone}18`,
      padding: '1px 7px', borderRadius: 10, fontSize: 10.5, fontWeight: 600 }}>
      {label}
    </span>
  );
}

const Th = ({ children }) => (
  <th style={{ padding: '8px 12px', fontSize: 10, textTransform: 'uppercase',
    letterSpacing: 0.6, color: C.dim, fontWeight: 600 }}>{children}</th>
);

const Td = ({ children, tone }) => (
  <td style={{ padding: '6px 12px', color: tone || C.text }}>{children}</td>
);

const btnStyle = {
  border: `1px solid ${C.border}`, borderRadius: 5, padding: '5px 11px',
  fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
};

const selectStyle = {
  background: C.panelAlt, color: C.text, border: `1px solid ${C.border}`,
  borderRadius: 5, padding: '5px 9px', fontSize: 12.5, fontFamily: 'inherit',
};
