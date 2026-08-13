import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';

/**
 * Lists the comparison runs written by run_xml_compare.py into
 * public/compare/<run>/. A run counts only if it carries a manifest, so a
 * half-written directory never shows up in the picker.
 */
export async function GET() {
  try {
    const dir = path.join(process.cwd(), 'public', 'compare');
    if (!fs.existsSync(dir)) {
      return Response.json({ runs: [] });
    }
    const runs = fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .filter((d) => fs.existsSync(path.join(dir, d.name, 'manifest.json')))
      .map((d) => ({
        name: d.name,
        mtime: fs.statSync(path.join(dir, d.name, 'manifest.json')).mtimeMs,
      }))
      .sort((a, b) => b.mtime - a.mtime)
      .map((r) => r.name);

    return Response.json({ runs });
  } catch (err) {
    return Response.json({ runs: [], error: String(err) }, { status: 500 });
  }
}
