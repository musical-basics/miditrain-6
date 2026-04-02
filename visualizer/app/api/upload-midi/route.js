import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export async function POST(request) {
  try {
    const formData = await request.formData();
    const file = formData.get('file');

    if (!file) {
      return NextResponse.json({ error: 'No file uploaded' }, { status: 400 });
    }

    const bytes = await file.arrayBuffer();
    const buffer = Buffer.from(bytes);

    // Save one level up relative to Next.js project
    const rootDir = path.resolve(process.cwd(), '..');
    const uploadsDir = path.join(rootDir, 'midis');
    
    // Ensure dir exists
    await fs.mkdir(uploadsDir, { recursive: true });

    // Sanitize filename
    const safeName = file.name.replace(/[^a-zA-Z0-9_\-\.]/g, '_');
    const filepath = path.join(uploadsDir, safeName);
    
    await fs.writeFile(filepath, buffer);

    // Return the relative path that the python backend can resolve
    return NextResponse.json({ success: true, filepath: `midis/${safeName}`, filename: safeName });
  } catch (error) {
    console.error('Upload error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
