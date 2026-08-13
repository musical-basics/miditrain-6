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

import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import NotationView from './NotationView';
import VerovioScore from './VerovioScore';

const RUNS_ENDPOINT = '/api/compare-runs';

// Light palette — a score is read on paper, and the point of this page is
// comparing engravings, so the staves get a white ground like real sheet music.
const C = {
  bg: '#ffffff',
  panel: '#f6f7f9',
  panelAlt: '#fbfbfd',
  border: '#e1e4ea',
  text: '#1b1d23',
  dim: '#6b7280',
  good: '#0f8a4f',
  bad: '#c62828',
  warn: '#b26a00',
  accent: '#2f5fd0',
};

const pct = (x) => `${(x * 100).toFixed(1)}%`;

export default function ScoreCompare() {
  const [runs, setRuns] = useState([]);
  const [run, setRun] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [view, setView] = useState('stacked'); // stacked | generated | reference | table
  const [filter, setFilter] = useState('problems'); // problems | hand | rhythm | all
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
      fetch(`${base}/decisions.json`).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([manifest, generated, reference, comparison, decisions]) => {
        if (!alive) return;
        setData({ manifest, generated, reference, comparison, decisions });
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

  // One row per note, carrying every decision we can check on it.
  const rows = useMemo(() => {
    if (!data) return [];
    const { comparison, decisions } = data;
    const wrongHand = new Map();
    for (const w of decisions?.wrong_hand || []) {
      wrongHand.set(`${w.pitch}@${Number(w.onset_q).toFixed(4)}`,
        `staff ${w.generated_staff} → ${w.reference_staff}`);
    }
    const out = [];
    for (const p of comparison.pairs || []) {
      const hand = wrongHand.get(`${p.pitch}@${Number(p.onset_q).toFixed(4)}`);
      out.push({
        measure: p.gen_measure,
        onset: p.onset_q,
        gen: p.gen_name,
        ref: p.ref_name,
        genDur: p.gen_dur_q,
        refDur: p.ref_dur_q,
        durOK: p.duration_match,
        handErr: hand || null,
      });
    }
    out.sort((a, b) => a.onset - b.onset || String(a.gen).localeCompare(String(b.gen)));
    return out;
  }, [data]);

  const filtered = useMemo(() => {
    if (filter === 'hand') return rows.filter((r) => r.handErr);
    if (filter === 'rhythm') return rows.filter((r) => !r.durOK);
    if (filter === 'problems') return rows.filter((r) => r.handErr || !r.durOK);
    return rows;
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
                decisions={data.decisions}
                ticksPerQuarter={data.manifest.ticks_per_quarter || 4}
                base={`/compare/${run}`}
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
    ['stacked', 'Compare scores'],
    ['renderers', 'Compare renderers'],
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

const tone3 = (x) => (x >= 0.97 ? C.good : x >= 0.85 ? C.warn : C.bad);

function Scorecard({ manifest }) {
  const c = manifest.counts || {};
  const d = manifest.decisions || {};
  const h = d.hands, b = d.beaming, du = d.durations, db = d.downbeats;

  return (
    <div style={{ borderBottom: `1px solid ${C.border}`, background: C.panelAlt }}>
      <div style={{ display: 'flex', gap: 14, padding: '15px 20px', flexWrap: 'wrap',
        alignItems: 'flex-start' }}>
        {db && (
          <>
            <Stat label="Downbeats F1" value={pct(db.f1)} tone={tone3(db.f1)} big
              sub={`${db.errors} errors · ±${db.tolerance_ms}ms`} />
            <Stat label="Time sig"
              value={db.predicted_time_signature || '—'}
              tone={db.predicted_time_signature === db.reference_time_signature
                ? C.good : C.bad}
              sub={`reference ${db.reference_time_signature || '?'}`} />
            <Divider />
          </>
        )}
        {h && (
          <Stat label="Hands (L/R)" value={pct(h.accuracy)} tone={tone3(h.accuracy)} big
            sub={`${h.correct}/${h.total}${h.mapping_is_swapped ? ' · swapped' : ''}`} />
        )}
        {h?.per_hand?.RH && (
          <Stat label="Right hand" value={pct(h.per_hand.RH.accuracy)}
            tone={tone3(h.per_hand.RH.accuracy)}
            sub={`${h.per_hand.RH.correct}/${h.per_hand.RH.notes}`} />
        )}
        {h?.per_hand?.LH && (
          <Stat label="Left hand" value={pct(h.per_hand.LH.accuracy)}
            tone={tone3(h.per_hand.LH.accuracy)}
            sub={`${h.per_hand.LH.correct}/${h.per_hand.LH.notes}`} />
        )}
        <Divider />
        {b && b.accuracy != null && (
          <Stat label="Beaming" value={pct(b.accuracy)} tone={tone3(b.accuracy)} big
            sub={`${b.agree}/${b.considered_adjacent_pairs} pairs`} />
        )}
        {du && (
          <Stat label="Rhythm" value={pct(du.accuracy)} tone={tone3(du.accuracy)} big
            sub={`${du.correct}/${du.total} notated durations`} />
        )}
      </div>

      <div style={{ padding: '0 20px 12px', fontSize: 11.5, color: C.dim,
        display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span style={{ color: C.warn }}>note</span>
        <span>
          all {c.reference} notes align on pitch + onset, but that is an{' '}
          <b style={{ color: C.text }}>alignment check, not a result</b> — the MIDI
          was rendered from this score, so the notes were never in question. The
          numbers above are what the engine actually decides.
        </span>
      </div>
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
    ? [['#111318', 'engraved as the reference does'],
       [C.warn, 'wrong notated rhythm'],
       [C.bad, 'assigned to the wrong hand']]
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
        colouring applies to the VexFlow pane — Verovio engraves the raw MusicXML
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
function recolorByStatus(score, comparison, decisions, divisionsPerQuarter) {
  if (!score?.measures || !comparison) return score;

  const key = (pitch, onsetQ) => `${pitch}@${Number(onsetQ).toFixed(4)}`;
  const status = new Map();
  for (const p of comparison.pairs || []) {
    status.set(key(p.pitch, p.onset_q), p.duration_match ? 'match' : 'soft');
  }
  // wrong hand outranks a rhythm difference — it is the worse error
  for (const w of decisions?.wrong_hand || []) {
    status.set(key(w.pitch, w.onset_q), 'hard');
  }

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
            const tone = s ? TONE[s] : null; // unknown => leave neutral
            // neutral must be INK on a light page, not the dark-mode grey
            return { ...n, color: tone || '#111318' };
          }),
        })),
      })),
    })),
  };
}

function ScorePanes({ view, generated, reference, colorMode, comparison,
                      decisions, ticksPerQuarter, base }) {
  const genScore = useMemo(
    () => (colorMode === 'diff'
      ? recolorByStatus(generated, comparison, decisions, ticksPerQuarter)
      : generated),
    [colorMode, generated, comparison, decisions, ticksPerQuarter]);

  // Three panes, two renderers. Rendering the generated and the reference
  // MusicXML through the SAME engraver (Verovio) is the controlled
  // comparison — any difference there is ours. The VexFlow pane is kept
  // alongside because it is what the rest of the app uses, so renderer
  // artefacts stay visible instead of being silently attributed to the data.
  const ALL = {
    genVerovio: {
      title: 'Generated — MidiTrain engine · Verovio',
      tone: C.accent, kind: 'verovio', url: `${base}/generated.musicxml`,
    },
    refVerovio: {
      title: 'Reference — your MusicXML · Verovio',
      tone: C.good, kind: 'verovio', url: `${base}/reference.musicxml`,
    },
    genVexflow: {
      title: 'Generated — MidiTrain engine · VexFlow (DreamFlow)',
      tone: C.accent, kind: 'vexflow', score: genScore,
    },
    refVexflow: {
      title: 'Reference — your MusicXML · VexFlow (DreamFlow)',
      tone: C.good, kind: 'vexflow', score: reference,
    },
  };

  const LAYOUTS = {
    stacked: ['genVerovio', 'refVerovio', 'genVexflow'],
    renderers: ['genVerovio', 'genVexflow'],
    generated: ['genVerovio'],
    reference: ['refVerovio'],
  };
  const panes = (LAYOUTS[view] || LAYOUTS.stacked).map((k) => ALL[k]);
  const paneHeight = panes.length >= 3 ? 280 : panes.length === 2 ? 340 : 560;

  // Both staves scroll horizontally through the same music, so lock their
  // scroll positions together — comparing bar 20 against bar 3 is useless.
  const refs = React.useRef([]);
  const syncing = React.useRef(false);
  // bumped when a pane's scroll extent changes after render (see VexflowPane),
  // so the sync handlers rebind against the corrected widths
  const [layoutTick, setLayoutTick] = useState(0);
  const bumpLayout = useCallback(() => setLayoutTick((t) => t + 1), []);

  // store the wrapper; the actual scroller (.notation-view-root) is created by
  // NotationView, so resolve it when we bind rather than at ref time.
  const attach = useCallback((idx) => (el) => { refs.current[idx] = el; }, []);

  useEffect(() => {
    let handlers = [];
    // VexFlow renders asynchronously; retry briefly until both scrollers exist.
    const bind = () => {
      const nodes = refs.current
        .filter(Boolean)
        .map((el) => el.querySelector('.notation-view-root')
          || el.querySelector('.verovio-root') || el);
      if (nodes.length < 2) return false;
      // don't bind until every pane has actually laid out its music,
      // otherwise a not-yet-rendered pane reports scrollWidth 0 and the
      // others snap back to 0 on the first scroll event
      if (nodes.some((n) => n.scrollWidth <= n.clientWidth)) return false;
      handlers = nodes.map((node) => {
        const h = () => {
          if (syncing.current) return;
          syncing.current = true;
          // Sync by FRACTION of the music, not by pixels: Verovio engraves the
          // same piece ~5.7k px wide while VexFlow lays it out ~100k px wide,
          // so matching scrollLeft directly would put the panes bars apart.
          const max = node.scrollWidth - node.clientWidth;
          const frac = max > 0 ? node.scrollLeft / max : 0;
          for (const other of nodes) {
            if (other === node) continue;
            const omax = other.scrollWidth - other.clientWidth;
            if (omax > 0) other.scrollLeft = Math.round(frac * omax);
          }
          requestAnimationFrame(() => { syncing.current = false; });
        };
        node.addEventListener('scroll', h, { passive: true });
        return [node, h];
      });
      return true;
    };

    // Verovio compiles WASM on first use, so allow a generous window (~30s)
    let tries = 0;
    const timer = setInterval(() => {
      if (bind() || ++tries > 150) clearInterval(timer);
    }, 200);

    return () => {
      clearInterval(timer);
      handlers.forEach(([n, h]) => n.removeEventListener('scroll', h));
    };
  }, [view, generated, reference, layoutTick]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {panes.map((pane, i) => (
        <div key={pane.title} style={{ borderBottom: `1px solid ${C.border}` }}>
          <div style={{ padding: '7px 20px', fontSize: 11, fontWeight: 600,
            letterSpacing: 0.5, textTransform: 'uppercase', color: pane.tone,
            background: C.panel, borderLeft: `3px solid ${pane.tone}`,
            display: 'flex', alignItems: 'center', gap: 10 }}>
            {pane.title}
            <RendererTag kind={pane.kind} />
            {i === 0 && panes.length > 1 && (
              <span style={{ marginLeft: 'auto', color: C.dim, fontWeight: 400,
                textTransform: 'none', letterSpacing: 0, fontSize: 10.5 }}>
                scroll any stave — the rest follow
              </span>
            )}
          </div>
          <div ref={attach(i)} style={{ height: paneHeight, background: '#fff' }}>
            {pane.kind === 'verovio'
              ? <VerovioScore url={pane.url} />
              : <VexflowPane score={pane.score} onResize={bumpLayout} />}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * VexFlow pane wrapper.
 *
 * The DreamFlow renderer always allocates a 99999px-wide SVG regardless of how
 * much music it draws, so the pane reports a ~100k scroll width for ~6k of
 * actual notation. Left alone the pane looks blank at any scroll position and
 * cannot be synced against Verovio. After it renders we measure the real
 * content extent and crop the SVG to it.
 */
function VexflowPane({ score, onResize }) {
  const hostRef = useRef(null);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return undefined;
    let tries = 0;
    const timer = setInterval(() => {
      const svg = el.querySelector('svg');
      if (svg && svg.childElementCount > 0) {
        try {
          // Real extent of what was actually drawn. The renderer allocates a
          // fixed 99999x11500 canvas regardless of content, so both axes need
          // correcting — and width/height must agree with the viewBox or the
          // music is scaled to near-invisibility inside an oversized box.
          const box = svg.getBBox();
          const pad = 12;
          const x = Math.floor(box.x - pad);
          const y = Math.floor(box.y - pad);
          const w = Math.ceil(box.width + pad * 2);
          const h = Math.ceil(box.height + pad * 2);
          if (w > 0 && h > 0 && w < Number(svg.getAttribute('width'))) {
            svg.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
            svg.setAttribute('width', String(w));
            svg.setAttribute('height', String(h));
            svg.style.width = `${w}px`;
            svg.style.height = `${h}px`;
            // the scroll extent just changed under the sync handlers; tell
            // them to rebind against the new width
            onResize?.();
          }
          clearInterval(timer);
          return;
        } catch { /* getBBox throws while the node is still detached */ }
      }
      if (++tries > 60) clearInterval(timer);
    }, 150);
    return () => clearInterval(timer);
  }, [score, onResize]);

  return (
    <div ref={hostRef} style={{ width: '100%', height: '100%' }}>
      <NotationView notationData={score} darkMode={false}
        layoutMode="horizontal" />
    </div>
  );
}

function RendererTag({ kind }) {
  const isVerovio = kind === 'verovio';
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4, padding: '1px 6px',
      borderRadius: 9, textTransform: 'uppercase',
      color: isVerovio ? '#0f5132' : '#6b3f00',
      background: isVerovio ? '#d6f0e0' : '#ffe9c7',
      border: `1px solid ${isVerovio ? '#a9dcc0' : '#f0cf9a'}`,
    }}>
      {isVerovio ? 'engraver' : 'drawing lib'}
    </span>
  );
}

function NoteTable({ rows, allRows, filter, setFilter, showDurations, setShowDurations }) {
  const counts = useMemo(() => ({
    problems: allRows.filter((r) => r.handErr || !r.durOK).length,
    hand: allRows.filter((r) => r.handErr).length,
    rhythm: allRows.filter((r) => !r.durOK).length,
    all: allRows.length,
  }), [allRows]);

  const filters = [
    ['problems', 'All problems'],
    ['hand', 'Wrong hand'],
    ['rhythm', 'Wrong rhythm'],
    ['all', 'Every note'],
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
                <Th>Issue</Th><Th>Measure</Th><Th>Beat (q)</Th><Th>Note</Th>
                <Th>Hand</Th>
                {showDurations && <><Th>Written</Th><Th>Should be</Th></>}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 2000).map((r, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${C.border}`,
                  background: i % 2 ? 'transparent' : 'rgba(255,255,255,0.015)' }}>
                  <Td><IssueChip handErr={r.handErr} durOK={r.durOK} /></Td>
                  <Td>{r.measure}</Td>
                  <Td>{r.onset}</Td>
                  <Td>{r.gen}</Td>
                  <Td tone={r.handErr ? C.bad : C.dim}>{r.handErr || 'ok'}</Td>
                  {showDurations && <>
                    <Td tone={r.durOK ? C.dim : C.warn}>{r.genDur ?? '—'}</Td>
                    <Td tone={r.durOK ? C.dim : C.warn}>{r.refDur ?? '—'}</Td>
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

function IssueChip({ handErr, durOK }) {
  const [label, tone] = handErr && !durOK ? ['hand + rhythm', C.bad]
    : handErr ? ['wrong hand', C.bad]
      : !durOK ? ['rhythm', C.warn]
        : ['ok', C.good];
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
