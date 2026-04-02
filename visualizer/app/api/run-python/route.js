import { spawn } from 'child_process';
import path from 'path';

export const dynamic = 'force-dynamic';

export async function POST(request) {
  try {
    const body = await request.json();
    const { script, args = [] } = body;

    if (!script) {
      return new Response(JSON.stringify({ error: 'Missing script parameter' }), { status: 400 });
    }

    // Resolve the python script relative to the miditrain-3 root (one level above visualizer)
    const pythonScriptPath = path.resolve(process.cwd(), '..', script);
    const projectRoot = path.resolve(process.cwd(), '..');

    // Use venv python if available, fall back to system python3
    const venvPython = path.join(projectRoot, '.venv', 'bin', 'python3');
    const pythonBin = (() => {
      try { require('fs').accessSync(venvPython); return venvPython; } catch { return 'python3'; }
    })();
    
    // Create a Transform stream for Server-Sent Events
    const stream = new TransformStream();
    const writer = stream.writable.getWriter();
    
    const encoder = new TextEncoder();
    
    // We run from the root of miditrain-3 to preserve relative paths like "visualizer/public/..." inside the python script
    const pyProcess = spawn(pythonBin, [pythonScriptPath, ...args], {
      cwd: projectRoot
    });

    // Helper to write to SSE stream
    const sendEvent = async (event, data) => {
      await writer.write(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
    };

    pyProcess.stdout.on('data', async (data) => {
      const output = data.toString();
      await sendEvent('message', { type: 'stdout', text: output });
    });

    pyProcess.stderr.on('data', async (data) => {
      const output = data.toString();
      await sendEvent('message', { type: 'stderr', text: output });
    });

    pyProcess.on('close', async (code) => {
      await sendEvent('done', { code });
      await writer.close();
    });

    pyProcess.on('error', async (err) => {
      await sendEvent('error', { text: err.toString() });
      await writer.close();
    });

    return new Response(stream.readable, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });

  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }
}
