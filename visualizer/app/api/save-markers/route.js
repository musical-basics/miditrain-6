import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export async function POST(request) {
  try {
    const body = await request.json();
    const { midiFile, markers } = body;

    if (!midiFile) {
      return NextResponse.json({ error: 'midiFile is required' }, { status: 400 });
    }

    const sanitized = midiFile.replace(/[^a-zA-Z0-9_-]/g, '_');
    const markersDir = path.resolve(process.cwd(), '..', 'markers');

    await fs.mkdir(markersDir, { recursive: true });

    const filepath = path.join(markersDir, `${sanitized}_markers.json`);
    await fs.writeFile(filepath, JSON.stringify({ midiFile, markers, savedAt: new Date().toISOString() }, null, 2));

    return NextResponse.json({ success: true, filepath });
  } catch (e) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
