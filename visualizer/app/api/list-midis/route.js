import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export async function GET() {
  try {
    const rootDir = path.resolve(process.cwd(), '..');
    const midisFiles = await fs.readdir(path.join(rootDir, 'midis'), { withFileTypes: true }).catch(() => []);
    const publicFiles = await fs.readdir(path.join(process.cwd(), 'public'), { withFileTypes: true }).catch(() => []);

    const allMidis = [];
    allMidis.push({ label: 'Pathetique Full Chunk', value: 'pathetique_full_chunk' });
    allMidis.push({ label: 'Pathetique 64s Chunk',  value: 'pathetique_64s_chunk' });
    allMidis.push({ label: 'Pathetique 16s Chunk',  value: 'pathetique_16s_chunk' });
    allMidis.push({ label: 'Revolutionary 64s Chunk', value: 'revolutionary_64s_chunk' });

    for (const f of midisFiles) {
      if (f.isFile() && f.name.endsWith('.mid')) {
        const key = f.name.replace('.mid', '');
        if (key === 'pathetique_full_chunk') continue;
        allMidis.push({ label: `Uploaded: ${f.name}`, value: 'midis/' + f.name });
      }
    }

    // Detect optimizer output files: etme_*_optimized_N.json  (same-chunk optimizer)
    const optimizedFiles = publicFiles
      .filter(f => f.isFile() && f.name.match(/^etme_.+_optimized_\d+\.json$/))
      .sort((a, b) => a.name.localeCompare(b.name));

    for (const f of optimizedFiles) {
      const match = f.name.match(/_optimized_(\d+)\.json$/);
      const rank = match ? match[1] : '?';
      let label = `🏆 Opt #${rank}`;
      try {
        const raw = await fs.readFile(path.join(process.cwd(), 'public', f.name), 'utf-8');
        const parsed = JSON.parse(raw);
        const meta = parsed?.optimizer_meta;
        if (meta) {
          const errors = (meta.total_errors ?? (meta.fp + meta.fn));
          label = `🏆 Opt #${rank} — errors=${errors} (FP=${meta.fp} FN=${meta.fn}) P=${meta.precision?.toFixed(0)}% R=${meta.recall?.toFixed(0)}%`;
        }
      } catch (_) {}
      allMidis.push({ label, value: `__optimized__:${f.name}` });
    }

    // Detect cross-validated files: etme_*_16s_opt_N.json  (16s params → other chunk)
    const crossFiles = publicFiles
      .filter(f => f.isFile() && f.name.match(/^etme_.+_16s_opt_\d+\.json$/))
      .sort((a, b) => a.name.localeCompare(b.name));

    for (const f of crossFiles) {
      const match = f.name.match(/_16s_opt_(\d+)\.json$/);
      const rank = match ? match[1] : '?';
      let label = `✅ 16s-Opt #${rank} (cross-val)`;
      try {
        const raw = await fs.readFile(path.join(process.cwd(), 'public', f.name), 'utf-8');
        const parsed = JSON.parse(raw);
        const meta = parsed?.optimizer_meta;
        if (meta) {
          const spikes = meta.spikes_on_64s ?? '?';
          const p = meta.precision?.toFixed(0);
          const r = meta.recall?.toFixed(0);
          label = `✅ 16s-Opt #${rank} — ${spikes} spikes  (16s: P=${p}% R=${r}%)`;
        }
      } catch (_) {}
      allMidis.push({ label, value: `__optimized__:${f.name}` });
    }

    return NextResponse.json({ midis: allMidis });
  } catch (e) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}

