import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export async function GET(request) {
  try {
    const { searchParams } = new URL(request.url);
    const midiFile = searchParams.get('midiFile');

    if (!midiFile) {
      return NextResponse.json({ markers: [] });
    }

    const sanitized = midiFile.replace(/[^a-zA-Z0-9_-]/g, '_');
    const filepath = path.resolve(process.cwd(), '..', 'markers', `${sanitized}_markers.json`);

    try {
      const content = await fs.readFile(filepath, 'utf-8');
      const data = JSON.parse(content);
      return NextResponse.json({ markers: data.markers || [] });
    } catch {
      return NextResponse.json({ markers: [] });
    }
  } catch (e) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
