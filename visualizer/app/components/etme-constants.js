// ===== SHARED CONSTANTS =====
export const PITCH_MIN = 21;
export const PITCH_MAX = 108;
// Browser canvas hard limit is ~32767px. We use 32000 as a safe ceiling.
// There is NO artificial time-based cap — the canvas always reflects the full piece.
export const MAX_CANVAS_PX = 32000;
export const RULER_HEIGHT = 40; // Taller ruler for marker click zone
export const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
export const BLACK_KEYS = [1,3,6,8,10];
export const NOTE_NAMES_FLAT = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B'];

export function midiNoteName(pitch) {
  const name = NOTE_NAMES_FLAT[pitch % 12];
  const octave = Math.floor(pitch / 12) - 1;
  return `${name}${octave}`;
}

export function formatTime(ms) {
  const totalSec = ms / 1000;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return min > 0 ? `${min}:${sec.toFixed(1).padStart(4, '0')}` : `${sec.toFixed(1)}s`;
}

// ===== COLOR HELPERS =====
export function hsl(h, s, l, a = 1) {
  return `hsla(${h}, ${s}%, ${l}%, ${a})`;
}
