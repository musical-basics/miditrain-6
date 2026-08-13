import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';

// Lists meter-diagnostic runs under public/meterdiag/. Same contract as
// /api/compare-runs: a directory counts as a run only if it holds a
// manifest.json; newest first.
export async function GET() {
  try {
    const root = path.join(process.cwd(), 'public', 'meterdiag');
    if (!fs.existsSync(root)) return Response.json({ runs: [] });

    const runs = fs.readdirSync(root, { withFileTypes: true })
      .filter(d => d.isDirectory())
      .map(d => {
        const manifest = path.join(root, d.name, 'manifest.json');
        if (!fs.existsSync(manifest)) return null;
        return { name: d.name, mtimeMs: fs.statSync(manifest).mtimeMs };
      })
      .filter(Boolean)
      .sort((a, b) => b.mtimeMs - a.mtimeMs)
      .map(r => r.name);

    return Response.json({ runs });
  } catch (e) {
    return Response.json({ runs: [], error: String(e) }, { status: 500 });
  }
}
