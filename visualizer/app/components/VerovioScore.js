'use client';

/**
 * Verovio renderer — engraves a MusicXML file to SVG.
 *
 * Why this exists alongside the DreamFlow/VexFlow renderer: VexFlow is a
 * drawing library, so beam grouping, stem direction and spacing are whatever
 * the caller tells it (or whatever its heuristics guess). Verovio is a real
 * engraver — it applies notation rules to the MusicXML itself. Rendering the
 * SAME file through both is the honest way to see which differences come from
 * our data and which come from the renderer.
 *
 * Verovio ships as self-contained WASM, so nothing is fetched from a CDN.
 * The toolkit is heavy (~7MB) and single-instance, so it is created once and
 * shared across mounts.
 */

import React, { useEffect, useRef, useState } from 'react';

let toolkitPromise = null;

function getToolkit() {
  if (!toolkitPromise) {
    toolkitPromise = (async () => {
      const [{ default: createVerovioModule }, { VerovioToolkit }] =
        await Promise.all([
          import('verovio/wasm'),
          import('verovio/esm'),
        ]);
      const mod = await createVerovioModule();
      return new VerovioToolkit(mod);
    })().catch((e) => {
      toolkitPromise = null; // let a later mount retry
      throw e;
    });
  }
  return toolkitPromise;
}

/**
 * Strip the markings this comparison explicitly disregards (fingerings,
 * dynamics, articulations, slurs, ornaments, lyrics, directions).
 *
 * The reference is an "All Markings Version", and left alone it engraves a
 * thicket of fingering digits and dynamics that the pipeline never claims to
 * reconstruct — they bury the notes we are actually comparing. Done on the
 * MusicXML rather than by hiding SVG afterwards, so Verovio also reclaims the
 * vertical space those markings would have reserved.
 */
// NOT <notations>: that container also holds ties and tuplets, which ARE
// rhythm and must survive. Only the specific markings are removed.
const STRIP_TAGS = ['fingering', 'dynamics', 'articulations', 'ornaments',
  'slur', 'lyric', 'direction', 'technical', 'wedge', 'pedal'];

function stripMarkings(xml) {
  let out = xml;
  for (const tag of STRIP_TAGS) {
    out = out.replace(new RegExp(`<${tag}(\\s[^>]*)?>[\\s\\S]*?</${tag}>`, 'g'), '');
    out = out.replace(new RegExp(`<${tag}(\\s[^>]*)?/>`, 'g'), '');
  }
  return out;
}

export default function VerovioScore({
  url,
  scale = 40,
  spacingStaff = 8,
  spacingSystem = 6,
  stripExtras = true,
  onStatus,
}) {
  const hostRef = useRef(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const [tk, xml] = await Promise.all([
          getToolkit(),
          fetch(url).then((r) => {
            if (!r.ok) throw new Error(`could not fetch ${url}`);
            return r.text();
          }),
        ]);
        if (!alive) return;

        // Continuous layout: one long system, so this pane scrolls
        // horizontally like the VexFlow pane next to it.
        tk.setOptions({
          scale,
          adjustPageHeight: true,
          breaks: 'none',
          header: 'none',
          footer: 'none',
          spacingStaff,
          spacingSystem,
          pageMarginLeft: 20,
          pageMarginRight: 20,
          pageMarginTop: 20,
          pageMarginBottom: 20,
        });

        const ok = tk.loadData(stripExtras ? stripMarkings(xml) : xml);
        if (!ok) throw new Error('Verovio could not parse this MusicXML');

        const svg = tk.renderToSVG(1);
        if (!alive || !hostRef.current) return;
        hostRef.current.innerHTML = svg;
        onStatus?.({ ok: true, pages: tk.getPageCount() });
        setLoading(false);
      } catch (e) {
        if (!alive) return;
        setError(e.message || String(e));
        onStatus?.({ ok: false, error: e.message });
        setLoading(false);
      }
    })();

    return () => { alive = false; };
  }, [url, scale, spacingStaff, spacingSystem, stripExtras, onStatus]);

  return (
    <div style={{ width: '100%', height: '100%', overflowX: 'auto',
      overflowY: 'hidden', background: 'transparent' }}
      className="verovio-root">
      {loading && (
        <div style={{ padding: 20, fontSize: 13, color: '#6b7280' }}>
          Loading Verovio engraver…
        </div>
      )}
      {error && (
        <div style={{ padding: 20, fontSize: 13, color: '#b91c1c' }}>
          Verovio: {error}
        </div>
      )}
      <div ref={hostRef} style={{ display: error ? 'none' : 'block' }} />
    </div>
  );
}
