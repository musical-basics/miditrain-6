'use client';

import { useRef, useState, useEffect, useCallback } from 'react';
import { Sun, Moon } from 'lucide-react';
import {
  PITCH_MIN, PITCH_MAX, MAX_CANVAS_PX, RULER_HEIGHT,
  NOTE_NAMES, BLACK_KEYS,
  formatTime, hsl
} from './etme-constants';
import { renderPhase1Regimes, getPhase1NoteColor, renderPhase1DebugLabels, Phase1Legend } from './Phase1Renderer';
import { getPhase2NoteColor, Phase2Legend } from './Phase2Renderer';

// ===== MAIN COMPONENT =====
export default function ETMEVisualizer() {
  const canvasRef = useRef(null);
  const wrapperRef = useRef(null);
  const keyboardRef = useRef(null);

  const [data, setData] = useState(null);
  const [currentView, setCurrentView] = useState('phase1');
  const [midiFile, setMidiFile] = useState('pathetique_full_chunk');
  const [angleMap, setAngleMap] = useState('dissonance');
  const [breakModel, setBreakModel] = useState('hybrid');
  const [jaccardThreshold, setJaccardThreshold] = useState(0.5);
  const [minBreakMass, setMinBreakMass] = useState(0.75);
  const [hZoom, setHZoom] = useState(10);
  const [vZoom, setVZoom] = useState(10);
  const [tooltip, setTooltip] = useState(null);
  const [isDarkMode, setIsDarkMode] = useState(true);

  const [isEngineRunning, setIsEngineRunning] = useState(false);
  const [isEngineDone, setIsEngineDone] = useState(false);
  const [engineLogs, setEngineLogs] = useState([]);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  const [batchJobs, setBatchJobs] = useState([]);
  const [batchLog, setBatchLog] = useState([]);
  const [isBatchDone, setIsBatchDone] = useState(false);

  // Playback
  const [interactionMode, setInteractionMode] = useState('play'); // 'play' | 'mark'
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackPositionMs, setPlaybackPositionMs] = useState(0);
  const [bpm, setBpm] = useState(120);
  const bpmRef = useRef(120);
  const togglePlaybackRef = useRef(null); // always points to latest togglePlayback (avoids TDZ in kbd handler)
  const playbackPositionRef = useRef(0);
  const playbackStartAcTimeRef = useRef(0);
  const playbackOffsetRef = useRef(0);
  const audioContextRef = useRef(null);
  const scheduledNodesRef = useRef([]);
  const animFrameRef = useRef(null);
  const renderRef = useRef(null);

  const [isUploading, setIsUploading] = useState(false);
  const [midiOptions, setMidiOptions] = useState([
    { label: 'Pathetique Full Chunk', value: 'pathetique_full_chunk' }
  ]);

  // Marker state
  const [markers, setMarkers] = useState([]);
  const [markerHistory, setMarkerHistory] = useState([[]]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [selectedMarkerIds, setSelectedMarkerIds] = useState(new Set());
  const [markerMode, setMarkerMode] = useState('tier1');
  const [showComparison, setShowComparison] = useState(false);
  const [compTolerance, setCompTolerance] = useState(100);

  // Drag-select state
  const [dragSelect, setDragSelect] = useState(null); // { startX, currentX, y, active }

  const fileInputRef = useRef(null);
  const effectiveScaleRef = useRef(0.05);
  const logsEndRef = useRef(null);
  const markerIdCounter = useRef(0);
  const handlersRef = useRef({});
  const dragSelectRef = useRef(null); // mirrors dragSelect for mouse handlers

  const getBaseKey = useCallback(() => {
    if (midiFile && midiFile.startsWith('midis/')) return midiFile.split('/').pop().replace('.mid', '');
    return midiFile;
  }, [midiFile]);

  // Marker history management
  const updateMarkersWithHistory = useCallback((newMarkers) => {
    const newHistory = markerHistory.slice(0, historyIndex + 1);
    newHistory.push(newMarkers);
    setMarkerHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
    setMarkers(newMarkers);
    setSelectedMarkerIds(new Set());
  }, [markerHistory, historyIndex]);

  const undo = useCallback(() => {
    if (historyIndex > 0) {
      const newIndex = historyIndex - 1;
      setHistoryIndex(newIndex);
      setMarkers(markerHistory[newIndex]);
      setSelectedMarkerIds(new Set());
    }
  }, [historyIndex, markerHistory]);

  const redo = useCallback(() => {
    if (historyIndex < markerHistory.length - 1) {
      const newIndex = historyIndex + 1;
      setHistoryIndex(newIndex);
      setMarkers(markerHistory[newIndex]);
      setSelectedMarkerIds(new Set());
    }
  }, [historyIndex, markerHistory]);

  const canUndo = historyIndex > 0;
  const canRedo = historyIndex < markerHistory.length - 1;

  // Auto-scroll logs
  useEffect(() => {
    if (logsEndRef.current) logsEndRef.current.scrollIntoView();
  }, [engineLogs]);

  const runEngine = useCallback(async () => {
    setIsEngineRunning(true);
    setIsEngineDone(false);
    setEngineLogs([`Starting Phase 1 Engine for ${midiFile} (${angleMap}, ${breakModel}, ${jaccardThreshold}, mass=${minBreakMass})...`]);

    const runScript = async (script, args) => {
      const resp = await fetch('/api/run-python', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script, args })
      });
      if (!resp.body) return false;
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let buffer = '';
      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop();
          for (const part of parts) {
            const dataMatch = part.match(/data: (.*)/);
            const eventMatch = part.match(/event: (.*)/);
            if (dataMatch) {
              const msg = JSON.parse(dataMatch[1]);
              const eventPattern = eventMatch ? eventMatch[1].trim() : '';
              if (eventPattern === 'done') return msg.code === 0;
              if (msg.text) setEngineLogs(prev => [...prev, msg.text.trim()]);
              else if (msg.type === 'error' || eventPattern === 'error')
                setEngineLogs(prev => [...prev, 'ERROR: ' + (msg.text || JSON.stringify(msg))]);
            }
          }
        }
      }
      return false;
    };

    let s1;
    if (midiFile.startsWith('__optimized__:')) {
      // Optimized output — run Phase 2 only on the existing JSON
      const jsonFile = 'visualizer/public/' + midiFile.replace('__optimized__:', '');
      setEngineLogs(prev => [...prev, '\n[1/1] Running Phase 2 only on optimized output (run_phase2.py)...']);
      s1 = await runScript('run_phase2.py', [jsonFile]);
    } else {
      setEngineLogs(prev => [...prev, '\n[1/1] Running Phase 1 & 2 (export_etme_data.py)...']);
      s1 = await runScript('export_etme_data.py', [
        '--midi_key', midiFile,
        '--angle_map', angleMap,
        '--break_method', breakModel,
        '--jaccard', jaccardThreshold.toString(),
        '--min_break_mass', minBreakMass.toString()
      ]);
    }
    if (!s1) {
      setEngineLogs(prev => [...prev, '\nPipeline failed. Check logs above.']);
      setIsEngineDone(true);
      return;
    }

    setEngineLogs(prev => [...prev, '\nPipeline Complete! Dismiss to view results.']);
    setRefreshTrigger(prev => prev + 1);
    setIsEngineDone(true);
  }, [midiFile, angleMap, breakModel, jaccardThreshold, minBreakMass]);

  // ===== BATCH RUN ENGINE =====
  const BATCH_CONFIGS = [
    { breakModel: 'centroid',           label: 'Centroid (Angle)',        needsJaccard: false },
    { breakModel: 'histogram',          label: 'Histogram (Cosine)',      needsJaccard: false },
    { breakModel: 'hybrid',             label: 'Hybrid',                  needsJaccard: true },
    { breakModel: 'hybrid_split',       label: 'Hybrid-Split',            needsJaccard: true },
    { breakModel: 'hybrid_v2',          label: 'Hybrid-V2',               needsJaccard: true },
    { breakModel: 'hybrid_v2_split',    label: 'Hybrid-V2 Split',         needsJaccard: true },
    { breakModel: 'jaccard_only',       label: 'Jaccard-Only',            needsJaccard: true },
    { breakModel: 'jaccard_only_split', label: 'Jaccard-Only Split',      needsJaccard: true },
  ];
  const JACCARD_THRESHOLDS = [0.3, 0.5, 0.7];

  const runBatchEngine = useCallback(async () => {
    // Build full job list
    const jobs = [];
    for (const cfg of BATCH_CONFIGS) {
      if (cfg.needsJaccard) {
        for (const j of JACCARD_THRESHOLDS) {
          jobs.push({ id: `${cfg.breakModel}_${j}`, breakModel: cfg.breakModel, jaccard: j,
            label: `${cfg.label}  J=${j}`, status: 'pending' });
        }
      } else {
        jobs.push({ id: cfg.breakModel, breakModel: cfg.breakModel, jaccard: null,
          label: cfg.label, status: 'pending' });
      }
    }
    setBatchJobs(jobs);
    setBatchLog([`Batch run: ${jobs.length} jobs for ${midiFile} (${angleMap}, mass=${minBreakMass})`]);
    setIsBatchDone(false);
    setIsBatchRunning(true);

    const runScript = async (script, args, logFn) => {
      const resp = await fetch('/api/run-python', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script, args })
      });
      if (!resp.body) return false;
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let done = false; let buffer = '';
      while (!done) {
        const { value, done: rd } = await reader.read();
        done = rd;
        if (value) {
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n'); buffer = parts.pop();
          for (const part of parts) {
            const dm = part.match(/data: (.*)/);
            const em = part.match(/event: (.*)/);
            if (dm) {
              const msg = JSON.parse(dm[1]);
              const evt = em ? em[1].trim() : '';
              if (evt === 'done') return msg.code === 0;
              if (msg.text) logFn(msg.text.trim());
            }
          }
        }
      }
      return false;
    };

    const updatedJobs = [...jobs];
    for (let i = 0; i < updatedJobs.length; i++) {
      const job = updatedJobs[i];
      // Mark running
      updatedJobs[i] = { ...job, status: 'running' };
      setBatchJobs([...updatedJobs]);
      setBatchLog(prev => [...prev, `\n[${i+1}/${updatedJobs.length}] Running: ${job.label}...`]);

      const args = [
        '--midi_key', midiFile,
        '--angle_map', angleMap,
        '--break_method', job.breakModel,
        '--min_break_mass', minBreakMass.toString(),
        ...(job.jaccard !== null ? ['--jaccard', job.jaccard.toString()] : [])
      ];

      let ok = false;
      try {
        ok = await runScript('export_etme_data.py', args,
          (txt) => setBatchLog(prev => [...prev, txt]));
      } catch(e) {
        setBatchLog(prev => [...prev, `ERROR: ${e.message}`]);
      }

      updatedJobs[i] = { ...updatedJobs[i], status: ok ? 'done' : 'error' };
      setBatchJobs([...updatedJobs]);
    }

    setBatchLog(prev => [...prev, `\n✅ Batch complete! ${updatedJobs.filter(j => j.status === 'done').length}/${updatedJobs.length} succeeded.`]);
    setRefreshTrigger(prev => prev + 1);
    setIsBatchDone(true);
  }, [midiFile, angleMap, minBreakMass]);

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/upload-midi', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.filepath) {
        setMidiFile(data.filepath);
        setRefreshTrigger(prev => prev + 1);
      }
    } catch(err) { console.error(err); }
    finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = null;
    }
  };

  // Load midi options
  useEffect(() => {
    fetch('/api/list-midis')
      .then(r => r.json())
      .then(d => { if (d.midis) setMidiOptions(d.midis); })
      .catch(console.error);
  }, [refreshTrigger]);

  // Load data when any selector changes
  useEffect(() => {
    let etmeFile;
    if (midiFile.startsWith('__optimized__:')) {
      // Optimizer output — load the named JSON directly from public/
      etmeFile = midiFile.replace('__optimized__:', '');
    } else {
      const baseKey = getBaseKey();
      etmeFile = (['hybrid', 'hybrid_split', 'jaccard_only', 'jaccard_only_split', 'hybrid_v2', 'hybrid_v2_split'].includes(breakModel))
        ? `etme_${baseKey}_${angleMap}_${breakModel}_${jaccardThreshold}.json`
        : `etme_${baseKey}_${angleMap}_${breakModel}.json`;
    }

    fetch(`/${etmeFile}?t=${Date.now()}_${refreshTrigger}`)
      .then(r => { if (!r.ok) return null; return r.json(); })
      .then(d => {
        setData(d);
        if (!d || !d.notes || d.notes.length === 0) return;
        // Auto-fit H-Zoom so full piece is visible without hitting browser canvas limit.
        const maxTime = Math.max(...d.notes.map(n => n.onset + n.duration)) + 500;
        // msPxInput = 0.005 * hZoom  →  hZoom = msPxInput / 0.005
        // We want: maxTime * msPxInput <= MAX_CANVAS_PX
        // So:       msPxInput <= MAX_CANVAS_PX / maxTime
        const maxSafeMsPx = (MAX_CANVAS_PX - 50) / maxTime;  // small buffer
        const maxSafeZoom = maxSafeMsPx / 0.005;
        setHZoom(prev => {
          const needed = prev;
          if (needed > maxSafeZoom) {
            console.info(`[ETME] Auto-fitting H-Zoom: ${needed} → ${maxSafeZoom.toFixed(1)} to show full ${(maxTime/1000).toFixed(1)}s piece`);
            return Math.floor(maxSafeZoom);
          }
          return prev;
        });
      })
      .catch(() => setData(null));
  }, [midiFile, angleMap, breakModel, jaccardThreshold, refreshTrigger, getBaseKey]);

  // Load saved markers
  useEffect(() => {
    const baseKey = getBaseKey();
    fetch(`/api/load-markers?midiFile=${baseKey}`)
      .then(r => r.json())
      .then(d => { if (d.markers && d.markers.length) setMarkers(d.markers); })
      .catch(() => {});
  }, [getBaseKey]);

  // Sync scroll between keyboard and canvas
  useEffect(() => {
    const wrapper = wrapperRef.current;
    const keyboard = keyboardRef.current;
    if (!wrapper || !keyboard) return;
    const onScroll = () => { keyboard.scrollTop = wrapper.scrollTop; };
    wrapper.addEventListener('scroll', onScroll);
    return () => wrapper.removeEventListener('scroll', onScroll);
  }, []);

  // Rendering
  const noteHeight = vZoom;
  const msPxInput = 0.005 * hZoom;

  const render = useCallback(() => {
    if (!data || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const notes = data.notes;
    const regimes = data.regimes;
    const pitchRange = PITCH_MAX - PITCH_MIN + 1;

    const maxTime = Math.max(...notes.map(n => n.onset + n.duration)) + 500;
    const effectiveScale = msPxInput;
    effectiveScaleRef.current = effectiveScale;
    // Canvas width = full content, capped only by browser pixel limit.
    // No artificial time cap — the full piece is always accessible by zooming out.
    const canvasW = Math.min(Math.max(maxTime * effectiveScale, 1200), MAX_CANVAS_PX);
    if (maxTime * effectiveScale > MAX_CANVAS_PX) {
      console.warn(`[ETME] Canvas clipped at browser limit. Zoom out to see full piece. ` +
        `Need ${(maxTime * effectiveScale).toFixed(0)}px, max=${MAX_CANVAS_PX}px.`);
    }
    const rollH = pitchRange * noteHeight;
    const canvasH = rollH + RULER_HEIGHT;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasW * dpr;
    canvas.height = canvasH * dpr;
    canvas.style.width = canvasW + 'px';
    canvas.style.height = canvasH + 'px';
    ctx.scale(dpr, dpr);

    // Background
    ctx.fillStyle = '#0d0d12';
    ctx.fillRect(0, 0, canvasW, canvasH);

    // Grid rows
    for (let p = PITCH_MIN; p <= PITCH_MAX; p++) {
      const y = (PITCH_MAX - p) * noteHeight;
      const pc = p % 12;
      const isBlack = BLACK_KEYS.includes(pc);
      ctx.fillStyle = isBlack ? 'transparent' : 'rgba(255,255,255,0.015)';
      ctx.fillRect(0, y, canvasW, noteHeight);
      ctx.strokeStyle = 'rgba(255,255,255,0.04)';
      ctx.lineWidth = 0.5;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvasW, y); ctx.stroke();
    }

    // Beat grid + timestamp ruler
    ctx.fillStyle = '#111118';
    ctx.fillRect(0, rollH, canvasW, RULER_HEIGHT);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, rollH); ctx.lineTo(canvasW, rollH); ctx.stroke();

    for (let t = 0; t < maxTime; t += 100) {
      const x = t * effectiveScale;
      if (t % 1000 === 0) {
        ctx.strokeStyle = 'rgba(255,255,255,0.12)';
        ctx.lineWidth = 1;
      } else if (t % 500 === 0) {
        ctx.strokeStyle = 'rgba(255,255,255,0.07)';
        ctx.lineWidth = 0.75;
      } else {
        ctx.strokeStyle = 'rgba(255,255,255,0.03)';
        ctx.lineWidth = 0.5;
      }
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, rollH); ctx.stroke();

      const isMajor = t % 1000 === 0;
      const isMid = t % 500 === 0;
      if (isMajor || isMid) {
        const tickH = isMajor ? 8 : 4;
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, rollH); ctx.lineTo(x, rollH + tickH); ctx.stroke();
      }
      if (isMajor) {
        ctx.font = '9px Inter';
        ctx.fillStyle = 'rgba(255,255,255,0.45)';
        ctx.textAlign = 'center';
        ctx.fillText(formatTime(t), x, rollH + 18);
        ctx.textAlign = 'start';
      }
    }

    // Marker click zone label
    ctx.font = '8px Inter';
    ctx.fillStyle = 'rgba(255,255,255,0.15)';
    ctx.fillText('Click here to place markers', 8, rollH + RULER_HEIGHT - 4);

    // Phase 1: Regime blocks
    if (currentView === 'phase1') {
      renderPhase1Regimes(ctx, regimes, { effectiveScale, noteHeight, rollH, canvasW });
    }

    // Draw notes
    for (const n of notes) {
      const x = n.onset * effectiveScale;
      const w = Math.max(n.duration * effectiveScale, 2);
      const y = (PITCH_MAX - n.pitch) * noteHeight;

      let fillColor, strokeColor;

      if (currentView === 'raw') {
        const velAlpha = 0.4 + (n.velocity / 127) * 0.6;
        fillColor = hsl(220, 70, 60, velAlpha);
        strokeColor = hsl(220, 80, 70, 0.7);
      } else if (currentView === 'phase1') {
        const p1 = getPhase1NoteColor(n);
        fillColor = p1.fillColor;
        strokeColor = p1.strokeColor;
        if (p1.shadow) {
          ctx.shadowColor = p1.shadow.color;
          ctx.shadowBlur = p1.shadow.blur;
        }
      } else if (currentView === 'phase2') {
        const p2 = getPhase2NoteColor(n);
        fillColor = p2.fillColor;
        strokeColor = p2.strokeColor;
        if (p2.shadow) {
          ctx.shadowColor = p2.shadow.color;
          ctx.shadowBlur = p2.shadow.blur;
        }
      }

      ctx.fillStyle = fillColor;
      ctx.beginPath();
      ctx.roundRect(x, y + 1, w, noteHeight - 2, 2);
      ctx.fill();
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 0.5;
      ctx.stroke();
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;

      // Debug labels on Phase 1
      if (currentView === 'phase1') {
        renderPhase1DebugLabels(ctx, n, x, y);
      }
    }

    // ===== Draw comparison: model SPIKE boundaries as cyan lines =====
    if (showComparison && data.regimes) {
      const modelBoundaries = getModelBoundaries(data.regimes);
      for (const mb of modelBoundaries) {
        const x = mb * effectiveScale;
        ctx.strokeStyle = 'rgba(0, 220, 255, 0.6)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 3]);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, rollH); ctx.stroke();
        ctx.setLineDash([]);

        // Small diamond at top
        ctx.fillStyle = 'rgba(0, 220, 255, 0.85)';
        ctx.beginPath();
        ctx.moveTo(x, 4); ctx.lineTo(x + 4, 8); ctx.lineTo(x, 12); ctx.lineTo(x - 4, 8);
        ctx.closePath(); ctx.fill();
      }
    }

    // ===== Draw markers =====
    for (const marker of markers) {
      const x = marker.time_ms * effectiveScale;
      const isTier1 = marker.tier === 'tier1';
      const isSelected = selectedMarkerIds.has(marker.id);

      if (isTier1) {
        // Tier 1: solid red line, full height
        const baseColor = isSelected ? '#ffff00' : '#ff4444';
        ctx.strokeStyle = isSelected ? 'rgba(255, 255, 0, 1.0)' : 'rgba(255, 68, 68, 0.85)';
        ctx.lineWidth = isSelected ? 3.5 : 2;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, rollH); ctx.stroke();

        // Triangle handle in ruler (larger if selected)
        ctx.fillStyle = isSelected ? '#ffff00' : '#ff4444';
        const handleSize = isSelected ? 8 : 6;
        ctx.beginPath();
        ctx.moveTo(x, rollH + 2);
        ctx.lineTo(x - handleSize, rollH + 14);
        ctx.lineTo(x + handleSize, rollH + 14);
        ctx.closePath(); ctx.fill();

        // Selection glow
        if (isSelected) {
          ctx.strokeStyle = 'rgba(255, 255, 0, 0.5)';
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, rollH); ctx.stroke();
        }

        // T1 label
        ctx.font = isSelected ? 'bold 10px Inter' : 'bold 8px Inter';
        ctx.fillStyle = baseColor;
        ctx.textAlign = 'center';
        ctx.fillText(isSelected ? 'T1✓' : 'T1', x, rollH + 24);
        ctx.textAlign = 'start';
      } else {
        // Tier 2: dashed amber line, 80% height
        ctx.strokeStyle = isSelected ? 'rgba(255, 255, 0, 0.85)' : 'rgba(255, 136, 68, 0.65)';
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(x, rollH * 0.2); ctx.lineTo(x, rollH); ctx.stroke();
        ctx.setLineDash([]);

        // Circle handle in ruler (larger if selected)
        ctx.fillStyle = isSelected ? '#ffff00' : '#ff8844';
        const radius = isSelected ? 7 : 5;
        ctx.beginPath();
        ctx.arc(x, rollH + 8, radius, 0, Math.PI * 2);
        ctx.fill();

        // Selection glow
        if (isSelected) {
          ctx.strokeStyle = 'rgba(255, 255, 0, 0.5)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(x, rollH + 8, radius + 2, 0, Math.PI * 2);
          ctx.stroke();
        }

        // T2 label
        ctx.font = isSelected ? 'bold 10px Inter' : 'bold 8px Inter';
        ctx.fillStyle = isSelected ? '#ffff00' : '#ff8844';
        ctx.textAlign = 'center';
        ctx.fillText(isSelected ? 'T2✓' : 'T2', x, rollH + 24);
        ctx.textAlign = 'start';
      }
    }

    // ===== Draw drag-select rectangle =====
    if (dragSelect?.active) {
      const dsMinX = Math.min(dragSelect.startX, dragSelect.currentX);
      const dsMaxX = Math.max(dragSelect.startX, dragSelect.currentX);
      const dsW = dsMaxX - dsMinX;
      ctx.strokeStyle = 'rgba(100, 180, 255, 0.85)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(dsMinX, 0, dsW, rollH);
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(100, 180, 255, 0.08)';
      ctx.fillRect(dsMinX, 0, dsW, rollH);
    }

    // ===== Draw playback cursor =====
    {
      const cursorX = playbackPositionRef.current * effectiveScale;
      ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.9)';
      ctx.lineWidth = 2;
      ctx.shadowColor = 'rgba(255, 255, 255, 0.6)';
      ctx.shadowBlur = 6;
      ctx.beginPath(); ctx.moveTo(cursorX, 0); ctx.lineTo(cursorX, rollH); ctx.stroke();
      ctx.restore();
      // Triangle head at top
      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.beginPath();
      ctx.moveTo(cursorX - 6, 0); ctx.lineTo(cursorX + 6, 0); ctx.lineTo(cursorX, 10);
      ctx.closePath(); ctx.fill();
    }

  }, [data, currentView, msPxInput, noteHeight, markers, selectedMarkerIds, showComparison, dragSelect]);

  // Keep renderRef always pointing to the latest render function
  useEffect(() => { renderRef.current = render; }, [render]);
  useEffect(() => { render(); }, [render]);

  // Update handlers ref
  // NOTE: togglePlayback and interactionMode are intentionally excluded from deps
  // to avoid TDZ (they're defined later in the file). The keyboard handler only
  // reads from handlersRef.current at call-time, so it always gets the latest value
  // via the effect below that runs after all hooks are defined.
  useEffect(() => {
    handlersRef.current = { undo, redo, selectedMarkerIds, markerHistory, historyIndex };
  }, [undo, redo, selectedMarkerIds, markerHistory, historyIndex]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      const handlers = handlersRef.current;
      // Space = play/pause — fires regardless of focused element
      if (e.key === ' ') {
        if (e.target.matches('textarea')) return;
        e.preventDefault();
        togglePlaybackRef.current?.();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        handlers.undo?.();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
        e.preventDefault();
        handlers.redo?.();
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (handlers.selectedMarkerIds?.size > 0 && !e.target.matches('input, textarea, select')) {
          e.preventDefault();
          const ids = handlers.selectedMarkerIds;
          setMarkers(prev => {
            const newMarkers = prev.filter(m => !ids.has(m.id));
            const newHistory = handlers.markerHistory.slice(0, handlers.historyIndex + 1);
            newHistory.push(newMarkers);
            setMarkerHistory(newHistory);
            setHistoryIndex(newHistory.length - 1);
            setSelectedMarkerIds(new Set());
            return newMarkers;
          });
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Drag-select mouse handlers
  const handleCanvasMouseDown = useCallback((e) => {
    if (!data || e.button !== 0) return;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const pitchRange = PITCH_MAX - PITCH_MIN + 1;
    const rollH = pitchRange * noteHeight;

    // Only start drag in the piano roll area (not ruler)
    if (my >= rollH) return;

    // Check if clicking near an existing marker
    let nearestMarker = null;
    let nearestDist = Infinity;
    for (const m of markers) {
      const markerX = m.time_ms * effectiveScaleRef.current;
      const dist = Math.abs(markerX - mx);
      if (dist < nearestDist) { nearestMarker = m; nearestDist = dist; }
    }

    if (nearestMarker && nearestDist < 12) {
      // Shift-click: toggle marker in/out of selection
      if (e.shiftKey) {
        setSelectedMarkerIds(prev => {
          const next = new Set(prev);
          if (next.has(nearestMarker.id)) next.delete(nearestMarker.id);
          else next.add(nearestMarker.id);
          return next;
        });
      } else {
        // Normal click on marker: select only this one
        setSelectedMarkerIds(new Set([nearestMarker.id]));
      }
      return;
    }

    // Start drag selection
    const ds = { startX: mx, currentX: mx, y: my, active: true };
    dragSelectRef.current = ds;
    setDragSelect({ ...ds });
    if (!e.shiftKey) setSelectedMarkerIds(new Set());
  }, [data, noteHeight, markers]);

  const handleCanvasMouseMove2 = useCallback((e) => {
    if (!dragSelectRef.current?.active) return;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    dragSelectRef.current = { ...dragSelectRef.current, currentX: mx };
    setDragSelect(prev => prev ? { ...prev, currentX: mx } : null);
  }, []);

  const handleCanvasMouseUp = useCallback((e) => {
    const ds = dragSelectRef.current;
    if (!ds?.active) return;
    dragSelectRef.current = null;

    const minX = Math.min(ds.startX, ds.currentX);
    const maxX = Math.max(ds.startX, ds.currentX);
    const dragWidth = maxX - minX;

    if (dragWidth < 5) {
      // Treat as a click — place new marker in ruler area? No, this is in piano roll.
      // Just clear drag rect.
      setDragSelect(null);
      return;
    }

    // Select all markers whose x falls within [minX, maxX]
    const minTime = minX / effectiveScaleRef.current;
    const maxTime = maxX / effectiveScaleRef.current;
    const inRange = markers.filter(m => m.time_ms >= minTime && m.time_ms <= maxTime).map(m => m.id);

    if (e.shiftKey) {
      setSelectedMarkerIds(prev => {
        const next = new Set(prev);
        inRange.forEach(id => next.add(id));
        return next;
      });
    } else {
      setSelectedMarkerIds(new Set(inRange));
    }
    setDragSelect(null);
  }, [markers]);

  // Click handler — play mode: seek. Mark mode: place marker in ruler.
  const handleCanvasClick = useCallback((e) => {
    if (!data) return;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const pitchRange = PITCH_MAX - PITCH_MIN + 1;
    const rollH = pitchRange * noteHeight;
    const timeMs = mx / effectiveScaleRef.current;

    // PLAY MODE: any click seeks
    if (interactionMode === 'play') {
      seekToRef.current?.(timeMs);
      return;
    }

    // MARK MODE: ruler area only
    if (my < rollH) return;

    // Check if clicking near an existing marker handle
    let nearestMarker = null;
    let nearestDist = Infinity;
    for (const m of markers) {
      const markerX = m.time_ms * effectiveScaleRef.current;
      const dist = Math.abs(markerX - mx);
      if (dist < nearestDist) { nearestMarker = m; nearestDist = dist; }
    }
    if (nearestMarker && nearestDist < 15) {
      if (e.shiftKey) {
        setSelectedMarkerIds(prev => {
          const next = new Set(prev);
          if (next.has(nearestMarker.id)) next.delete(nearestMarker.id);
          else next.add(nearestMarker.id);
          return next;
        });
      } else {
        setSelectedMarkerIds(new Set([nearestMarker.id]));
      }
      return;
    }

    // Place new marker
    markerIdCounter.current += 1;
    const newMarker = {
      id: `m_${markerIdCounter.current}_${Date.now()}`,
      time_ms: Math.round(timeMs),
      tier: markerMode
    };
    updateMarkersWithHistory([...markers, newMarker].sort((a, b) => a.time_ms - b.time_ms));
  }, [data, noteHeight, markerMode, markers, updateMarkersWithHistory, interactionMode]);



  // Right-click to delete nearest marker
  const handleCanvasContextMenu = useCallback((e) => {
    e.preventDefault();
    if (!data || markers.length === 0) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const timeMs = mx / effectiveScaleRef.current;

    // Find nearest marker within 200ms
    let nearest = null;
    let nearestDist = Infinity;
    for (const m of markers) {
      const dist = Math.abs(m.time_ms - timeMs);
      if (dist < nearestDist) { nearest = m; nearestDist = dist; }
    }
    const pxDist = nearestDist * effectiveScaleRef.current;
    if (nearest && pxDist < 20) {
      updateMarkersWithHistory(markers.filter(m => m.id !== nearest.id));
    }
  }, [data, markers, updateMarkersWithHistory]);

  // ===== WEB AUDIO PIANO SYNTHESIS =====
  function playNoteAudio(ac, pitch, velocity, startTime, duration_ms) {
    const freq = 440 * Math.pow(2, (pitch - 69) / 12);
    const vol = (velocity / 127) * 0.35;
    const dur = Math.max(0.08, duration_ms / 1000);

    const gain = ac.createGain();
    gain.connect(ac.destination);
    gain.gain.setValueAtTime(0, startTime);
    gain.gain.linearRampToValueAtTime(vol, startTime + 0.006);     // 6ms attack
    gain.gain.exponentialRampToValueAtTime(vol * 0.35, startTime + 0.08); // decay
    gain.gain.exponentialRampToValueAtTime(0.0001, startTime + dur + 0.25); // release

    // Fundamental (sine)
    const o1 = ac.createOscillator();
    o1.type = 'sine';
    o1.frequency.value = freq;
    o1.connect(gain);
    o1.start(startTime);
    o1.stop(startTime + dur + 0.3);

    // Octave (triangle at lower vol for brightness)
    const g2 = ac.createGain();
    g2.gain.value = 0.12;
    g2.connect(ac.destination);
    const o2 = ac.createOscillator();
    o2.type = 'triangle';
    o2.frequency.value = freq * 2;
    o2.connect(g2);
    g2.gain.setValueAtTime(0, startTime);
    g2.gain.linearRampToValueAtTime(vol * 0.12, startTime + 0.004);
    g2.gain.exponentialRampToValueAtTime(0.0001, startTime + dur + 0.15);
    o2.start(startTime);
    o2.stop(startTime + dur + 0.2);

    return { gain, g2, o1, o2 };
  }

  // Stop all scheduled audio and the rAF loop
  const stopPlayback = useCallback(() => {
    setIsPlaying(false);
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    animFrameRef.current = null;
    const ac = audioContextRef.current;
    for (const node of scheduledNodesRef.current) {
      try {
        node.gain.gain.cancelScheduledValues(ac.currentTime);
        node.gain.gain.setValueAtTime(node.gain.gain.value, ac.currentTime);
        node.gain.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.04);
        node.o1.stop(ac.currentTime + 0.05);
        node.g2.gain.cancelScheduledValues(ac.currentTime);
        node.g2.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.04);
        node.o2.stop(ac.currentTime + 0.05);
      } catch(e) {}
    }
    scheduledNodesRef.current = [];
    renderRef.current?.(); // redraw cursor in paused position
  }, []);

  // Seek to a time position (ms) without starting playback
  const seekTo = useCallback((ms) => {
    const wasPlaying = isPlaying;
    stopPlayback();
    playbackPositionRef.current = ms;
    playbackOffsetRef.current = ms;
    setPlaybackPositionMs(ms);
    renderRef.current?.();
    // Re-auto-scroll to show the new cursor position
    const wrapper = wrapperRef.current;
    if (wrapper) {
      const x = ms * effectiveScaleRef.current;
      const targetLeft = x - wrapper.clientWidth / 2;
      wrapper.scrollTo({ left: Math.max(0, targetLeft), behavior: 'smooth' });
    }
  }, [isPlaying, stopPlayback]);

  // Schedule and play notes from the current offset
  const startPlayback = useCallback(() => {
    if (!data?.notes) return;
    if (!audioContextRef.current) audioContextRef.current = new AudioContext();
    const ac = audioContextRef.current;
    if (ac.state === 'suspended') ac.resume();

    const offset = playbackPositionRef.current;
    const acStart = ac.currentTime + 0.05;
    playbackStartAcTimeRef.current = acStart;
    playbackOffsetRef.current = offset;
    const rate = bpmRef.current / 120; // scale: 120 BPM = 1.0x

    // Schedule notes scaled by BPM rate
    const nodes = [];
    for (const note of data.notes) {
      const delay = ((note.onset - offset) / 1000) / rate;
      if (delay < -0.1) continue;
      const startAt = acStart + Math.max(0, delay);
      const n = playNoteAudio(ac, note.pitch, note.velocity, startAt, note.duration / rate);
      nodes.push(n);
    }
    scheduledNodesRef.current = nodes;
    setIsPlaying(true);

    // Animation loop — advance cursor at BPM rate
    const lastNoteEnd = data.notes.reduce((m, n) => Math.max(m, n.onset + n.duration), 0);
    const tick = () => {
      const r = bpmRef.current / 120;
      const elapsedSec = ac.currentTime - playbackStartAcTimeRef.current;
      const pos = playbackOffsetRef.current + elapsedSec * 1000 * r;
      if (pos >= lastNoteEnd + 200) { stopPlayback(); return; }
      playbackPositionRef.current = pos;
      renderRef.current?.();
      const wrapper = wrapperRef.current;
      if (wrapper) {
        const cursorX = pos * effectiveScaleRef.current;
        const viewRight = wrapper.scrollLeft + wrapper.clientWidth;
        if (cursorX > viewRight - wrapper.clientWidth * 0.2) {
          wrapper.scrollLeft = cursorX - wrapper.clientWidth * 0.3;
        }
      }
      animFrameRef.current = requestAnimationFrame(tick);
    };
    animFrameRef.current = requestAnimationFrame(tick);
  }, [data, stopPlayback]);

  const togglePlayback = useCallback(() => {
    if (isPlaying) stopPlayback();
    else startPlayback();
  }, [isPlaying, startPlayback, stopPlayback]);

  // Patch handlersRef with playback functions (defined after the main handlersRef effect above)
  useEffect(() => {
    handlersRef.current = { ...handlersRef.current, togglePlayback, interactionMode };
  }, [togglePlayback, interactionMode]);

  // Keep a ref to seekTo so handleCanvasClick can call it without declaring seekTo as a dep (TDZ fix)
  const seekToRef = useRef(null);
  useEffect(() => { seekToRef.current = seekTo; }, [seekTo]);
  // Keep bpmRef and togglePlaybackRef in sync
  useEffect(() => { bpmRef.current = bpm; }, [bpm]);
  useEffect(() => { togglePlaybackRef.current = togglePlayback; }, [togglePlayback]);

  // Tooltip handler
  const handleMouseMove = useCallback((e) => {
    if (!data) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const timeMs = mx / effectiveScaleRef.current;
    const pitch = PITCH_MAX - Math.floor(my / noteHeight);

    const hit = data.notes.find(n =>
      pitch === n.pitch && timeMs >= n.onset && timeMs <= n.onset + n.duration
    );

    if (hit) {
      const noteName = NOTE_NAMES[hit.pitch % 12] + (Math.floor(hit.pitch / 12) - 1);
      setTooltip({
        x: e.clientX + 14, y: e.clientY + 14,
        noteName, pitch: hit.pitch, velocity: hit.velocity,
        onset: hit.onset, duration: hit.duration,
        hue: hit.hue, sat: hit.sat, lightness: hit.lightness, tonal_distance: hit.tonal_distance,
        voice_tag: hit.voice_tag, id_score: hit.id_score
      });
    } else {
      setTooltip(null);
    }
  }, [data, noteHeight]);

  // Save markers
  const saveMarkers = async () => {
    const baseKey = getBaseKey();
    await fetch('/api/save-markers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ midiFile: baseKey, markers })
    });
  };

  // Scroll canvas to a given time_ms, centering it in the viewport.
  // If markerId is provided, also select that marker.
  const scrollToTime = useCallback((time_ms, markerId) => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const x = time_ms * effectiveScaleRef.current;
    const targetLeft = x - wrapper.clientWidth / 2;
    wrapper.scrollTo({ left: Math.max(0, targetLeft), behavior: 'smooth' });
    if (markerId) {
      setSelectedMarkerIds(new Set([markerId]));
    }
  }, []);

  // Export markers as JSON download
  const exportMarkers = () => {
    const blob = new Blob([JSON.stringify(markers, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `markers_${getBaseKey()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Keyboard
  const keyboardKeys = [];
  for (let p = PITCH_MAX; p >= PITCH_MIN; p--) {
    const pc = p % 12;
    const octave = Math.floor(p / 12) - 1;
    const isBlack = BLACK_KEYS.includes(pc);
    const isC = pc === 0;
    keyboardKeys.push(
      <div key={p} className={`key ${isBlack ? 'black' : 'white'} ${isC ? 'c-note' : ''}`} style={{ height: noteHeight }}>
        {isC ? `C${octave}` : ''}
      </div>
    );
  }

  // Legend
  const legendContent = () => {
    if (currentView === 'raw') return (
      <>
        <h3>Piano Roll</h3>
        <div className="legend-item"><div className="legend-swatch" style={{ background: hsl(220,70,60,0.5) }} />Quiet Note</div>
        <div className="legend-item"><div className="legend-swatch" style={{ background: hsl(220,70,60,1) }} />Loud Note</div>
      </>
    );
    if (currentView === 'phase2') return <Phase2Legend />;
    return (
      <Phase1Legend minBreakMass={minBreakMass} setMinBreakMass={setMinBreakMass} showComparison={showComparison} />
    );
  };

  const views = [
    { id: 'raw', label: 'Piano Roll', color: 'var(--accent-blue)' },
    { id: 'phase1', label: 'Phase 1 -- Harmonic Regimes', color: 'var(--accent-green)' },
    { id: 'phase2', label: 'Phase 2 -- Voice Threading', color: 'var(--accent-pink)' },
  ];

  // Comparison logic
  const comparisonStats = computeComparison(markers, data?.regimes, compTolerance);

  return (
    <>
      {/* HEADER */}
      <div className="header">
        <h1><span>ETME</span> Phase 1 Tester</h1>
        <div className="stats">
          <div>Notes<span className="stat-value">{data?.stats?.total_notes ?? '--'}</span></div>
          <div>Regimes<span className="stat-value">{data?.stats?.total_regimes ?? '--'}</span></div>
          {data?.stats?.voice_counts && Object.entries(data.stats.voice_counts).sort().map(([tag, count]) => (
            <div key={tag}>{tag}<span className="stat-value">{count}</span></div>
          ))}
          <div>Markers<span className="stat-value">{markers.length}</span></div>
        </div>
      </div>

      {/* TABS + CONTROLS */}
      <div className="view-tabs">
        {views.map(v => (
          <button
            key={v.id}
            className={`view-tab ${currentView === v.id ? 'active' : ''}`}
            onClick={() => setCurrentView(v.id)}
          >
            <span className="dot" style={{ background: v.color }} />
            {v.label}
          </button>
        ))}

        <button
          onClick={runEngine}
          style={{
            marginLeft: '16px', padding: '4px 12px', fontSize: '11px',
            background: '#2e7d32', color: '#fff', border: '1px solid #1b5e20',
            borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold'
          }}
        >
          Run Engine
        </button>
        <button
          onClick={runBatchEngine}
          title="Run all 8 break models × 3 Jaccard thresholds (20 jobs)"
          style={{
            marginLeft: '6px', padding: '4px 12px', fontSize: '11px',
            background: '#6a1b9a', color: '#fff', border: '1px solid #4a148c',
            borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold'
          }}
        >
          ⚡ Batch Run
        </button>
        <button
          onClick={() => setIsDarkMode(!isDarkMode)}
          style={{
            marginLeft: '8px', padding: '4px 8px',
            background: '#1a1a2e', color: '#fff', border: '1px solid #333',
            borderRadius: '4px', cursor: 'pointer'
          }}
        >
          {isDarkMode ? <Sun size={14} /> : <Moon size={14} />}
        </button>
        <div style={{ position: 'relative', marginLeft: '8px' }}>
          <button
            onClick={() => fileInputRef.current?.click()}
            style={{
              padding: '4px 12px', fontSize: '11px',
              background: '#0277bd', color: '#fff', border: '1px solid #01579b',
              borderRadius: '4px', cursor: isUploading ? 'not-allowed' : 'pointer', fontWeight: 'bold'
            }}
            disabled={isUploading}
          >
            {isUploading ? 'Uploading...' : 'Import MIDI'}
          </button>
          <input type="file" ref={fileInputRef} onChange={handleFileUpload} accept=".mid,.midi" style={{ display: 'none' }} />
        </div>
        <select value={midiFile} onChange={e => setMidiFile(e.target.value)}
          style={{ marginLeft: '8px', padding: '4px 8px', fontSize: '11px', background: '#1a1a2e', color: '#e0e0e0', border: '1px solid #333', borderRadius: '4px', cursor: 'pointer' }}
        >
          {midiOptions.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
        <select value={angleMap} onChange={e => setAngleMap(e.target.value)}
          style={{ marginLeft: '4px', padding: '4px 8px', fontSize: '11px', background: '#1a1a2e', color: '#e0e0e0', border: '1px solid #333', borderRadius: '4px', cursor: 'pointer' }}
        >
          <option value="dissonance">Dissonance Map</option>
          <option value="fifths">Circle of 5ths</option>
        </select>
        <select value={breakModel} onChange={e => setBreakModel(e.target.value)}
          style={{ marginLeft: '4px', padding: '4px 8px', fontSize: '11px', background: '#1a1a2e', color: '#e0e0e0', border: '1px solid #333', borderRadius: '4px', cursor: 'pointer' }}
        >
          <option value="centroid">Centroid (Angle)</option>
          <option value="histogram">Histogram (Cosine)</option>
          <option value="hybrid">Hybrid (Angle+Jaccard)</option>
          <option value="hybrid_split">Hybrid-Split</option>
          <option value="hybrid_v2">Hybrid-V2</option>
          <option value="hybrid_v2_split">Hybrid-V2 Split</option>
          <option value="jaccard_only">Jaccard-Only</option>
          <option value="jaccard_only_split">Jaccard-Only Split</option>
        </select>
        {(['hybrid', 'hybrid_split', 'jaccard_only', 'jaccard_only_split', 'hybrid_v2', 'hybrid_v2_split'].includes(breakModel)) && (
          <select value={jaccardThreshold} onChange={e => setJaccardThreshold(+e.target.value)}
            style={{ marginLeft: '4px', padding: '4px 8px', fontSize: '11px', background: '#1a1a2e', color: '#e0e0e0', border: '1px solid #333', borderRadius: '4px', cursor: 'pointer' }}
          >
            <option value={0.3}>J: 0.3</option>
            <option value={0.5}>J: 0.5</option>
            <option value={0.7}>J: 0.7</option>
          </select>
        )}
      </div>

      {/* MARKER TOOLBAR */}
      <div className="marker-toolbar">
        {/* Mode toggle */}
        <button
          onClick={() => { if(interactionMode!=='play'){stopPlayback(); setInteractionMode('play');}  }}
          className={`marker-mode-btn${interactionMode === 'play' ? ' active tier1' : ''}`}
          style={interactionMode === 'play' ? { background: 'rgba(255,255,255,0.1)', borderColor: '#fff', color: '#fff' } : {}}
        >
          🎵 Play
        </button>
        <button
          onClick={() => { if(interactionMode!=='mark') setInteractionMode('mark'); }}
          className={`marker-mode-btn${interactionMode === 'mark' ? ' active tier1' : ''}`}
        >
          ✏️ Mark
        </button>

        {/* Playback controls (always visible) */}
        <button
          onClick={togglePlayback}
          style={{
            padding: '4px 14px', borderRadius: 4, cursor: 'pointer', fontWeight: 700,
            border: '1px solid', fontSize: 13,
            borderColor: isPlaying ? '#ef4444' : '#4a9eff',
            background: isPlaying ? 'rgba(239,68,68,0.15)' : 'rgba(74,158,255,0.15)',
            color: isPlaying ? '#ef4444' : '#4a9eff',
          }}
        >
          {isPlaying ? '⏸' : '▶'}
        </button>
        <span style={{ fontSize: 10, color: 'var(--text-secondary)', minWidth: 60, fontVariantNumeric: 'tabular-nums' }}>
          {(playbackPositionMs / 1000).toFixed(2)}s
        </span>
        <button
          onClick={() => seekToRef.current?.(0)}
          style={{ padding: '3px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 11,
            border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)' }}
          title="Rewind to start"
        >
          ⏮
        </button>

        {/* BPM control */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginLeft: '4px' }} suppressHydrationWarning>
          <span style={{ fontSize: '10px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>BPM</span>
          <input
            type="number" min={20} max={300} step={1} value={bpm}
            onChange={e => setBpm(Math.max(20, Math.min(300, +e.target.value || 120)))}
            suppressHydrationWarning
            style={{
              width: '50px', padding: '2px 4px', background: '#1a1a2e',
              border: '1px solid #333', color: '#fff', borderRadius: '4px',
              fontSize: '11px', textAlign: 'center'
            }}
          />
          <input
            type="range" min={40} max={240} step={1} value={bpm}
            onChange={e => setBpm(+e.target.value)}
            suppressHydrationWarning
            style={{ width: '72px', accentColor: '#4a9eff', cursor: 'pointer' }}
            title={`${bpm} BPM`}
          />
        </div>

        <div style={{ width: 1, height: 16, background: 'var(--border)', margin: '0 4px' }} />

        {/* Marker controls (only meaningful in mark mode) */}
        <button className={`marker-mode-btn${markerMode === 'tier1' ? ' active tier1' : ''}`}
          onClick={() => setMarkerMode('tier1')} disabled={interactionMode !== 'mark'}
          style={{ opacity: interactionMode !== 'mark' ? 0.35 : 1 }}
        >T1 Downbeat+Harmonic</button>
        <button className={`marker-mode-btn${markerMode === 'tier2' ? ' active tier2' : ''}`}
          onClick={() => setMarkerMode('tier2')} disabled={interactionMode !== 'mark'}
          style={{ opacity: interactionMode !== 'mark' ? 0.35 : 1 }}
        >T2 Harmonic Spike</button>

        <div style={{ borderLeft: '1px solid var(--border)', height: 20, margin: '0 8px' }} />
        <button
          onClick={undo}
          disabled={!canUndo}
          className="marker-action-btn"
          style={{ opacity: canUndo ? 1 : 0.4, cursor: canUndo ? 'pointer' : 'not-allowed' }}
          title="Undo (Ctrl+Z)"
        >
          ↶ Undo
        </button>
        <button
          onClick={redo}
          disabled={!canRedo}
          className="marker-action-btn"
          style={{ opacity: canRedo ? 1 : 0.4, cursor: canRedo ? 'pointer' : 'not-allowed' }}
          title="Redo (Ctrl+Y)"
        >
          ↷ Redo
        </button>
        <div style={{ borderLeft: '1px solid var(--border)', height: 20, margin: '0 8px' }} />
        <button onClick={saveMarkers} className="marker-action-btn">Save</button>
        <button onClick={exportMarkers} className="marker-action-btn">Export JSON</button>
        {selectedMarkerIds.size > 0 && (
          <button
            onClick={() => {
              const ids = selectedMarkerIds;
              const newMarkers = markers.filter(m => !ids.has(m.id));
              const newHistory = markerHistory.slice(0, historyIndex + 1);
              newHistory.push(newMarkers);
              setMarkerHistory(newHistory);
              setHistoryIndex(newHistory.length - 1);
              setMarkers(newMarkers);
              setSelectedMarkerIds(new Set());
            }}
            className="marker-action-btn"
            style={{ color: '#ff6b35' }}
            title={`Delete ${selectedMarkerIds.size} selected marker(s)`}
          >
            Delete Selected ({selectedMarkerIds.size})
          </button>
        )}
        <button
          onClick={() => updateMarkersWithHistory([])}
          className="marker-action-btn"
          style={{ color: '#ef4444' }}
        >
          Clear All
        </button>
        <div style={{ borderLeft: '1px solid var(--border)', height: 20, margin: '0 8px' }} />
        <button
          className={`marker-mode-btn ${showComparison ? 'active compare' : ''}`}
          onClick={() => setShowComparison(!showComparison)}
        >
          Compare vs Model
        </button>
        {showComparison && comparisonStats && (
          <span style={{ marginLeft: 8, fontSize: 11, color: '#00ddff' }}>
            P:{comparisonStats.precision}% R:{comparisonStats.recall}% F1:{comparisonStats.f1}%
            (TP:{comparisonStats.tp} FP:{comparisonStats.fp} FN:{comparisonStats.fn})
          </span>
        )}
      </div>

      {/* ZOOM */}
      <div className="zoom-bar">
        <div className="zoom-group">
          <label>H-Zoom</label>
          <input type="range" min="1" max="100" value={hZoom} onChange={e => setHZoom(+e.target.value)} />
          <span className="zoom-value">{hZoom}</span>
        </div>
        <div className="zoom-group">
          <label>V-Zoom</label>
          <input type="range" min="4" max="30" value={vZoom} onChange={e => setVZoom(+e.target.value)} />
          <span className="zoom-value">{vZoom}</span>
        </div>
        {showComparison && (
          <div className="zoom-group">
            <label>Tolerance</label>
            <input type="range" min="25" max="500" step="25" value={compTolerance} onChange={e => setCompTolerance(+e.target.value)} />
            <span className="zoom-value">{compTolerance}ms</span>
          </div>
        )}
      </div>

      {/* PIANO ROLL */}
      <div className="roll-container" style={{ position: 'relative' }}>
        <div className="keyboard" ref={keyboardRef}>{keyboardKeys}</div>
        <div className="canvas-wrapper" ref={wrapperRef}>
          <canvas
            ref={canvasRef}
            onMouseDown={handleCanvasMouseDown}
            onMouseMove={(e) => { handleMouseMove(e); handleCanvasMouseMove2(e); }}
            onMouseUp={handleCanvasMouseUp}
            onMouseLeave={(e) => { setTooltip(null); handleCanvasMouseUp(e); }}
            onClick={handleCanvasClick}
            onContextMenu={handleCanvasContextMenu}
            style={{ cursor: dragSelect?.active ? 'col-resize' : 'crosshair' }}
          />
        </div>
      </div>

      {/* LEGEND */}
      <div className="legend">{legendContent()}</div>

      {/* COMPARISON PANEL */}
      {showComparison && comparisonStats && (
        <div className="comparison-panel">
          <h3 style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 1, color: 'var(--text-secondary)', marginBottom: 12 }}>
            Comparison: User vs Model
          </h3>
          <div style={{ fontSize: 11, marginBottom: 12, padding: '8px', background: 'rgba(0,220,255,0.05)', borderRadius: 6, border: '1px solid rgba(0,220,255,0.15)' }}>
            <div>Precision: <strong style={{ color: '#00ddff' }}>{comparisonStats.precision}%</strong></div>
            <div>Recall: <strong style={{ color: '#00ddff' }}>{comparisonStats.recall}%</strong></div>
            <div>F1 Score: <strong style={{ color: '#00ddff' }}>{comparisonStats.f1}%</strong></div>
            <div style={{ marginTop: 4, color: 'var(--text-muted)', fontSize: 10 }}>
              TP:{comparisonStats.tp} | FP:{comparisonStats.fp} | FN:{comparisonStats.fn}
            </div>
          </div>
          <div style={{ maxHeight: 'calc(100vh - 250px)', overflowY: 'auto' }}>
            {comparisonStats.details.map((d, i) => {
              const accent = d.type === 'tp' ? '#10b981' : d.type === 'fp' ? '#ef4444' : '#f59e0b';
              return (
                <div
                  key={i}
                  onClick={() => scrollToTime(d.time_ms, d.markerId)}
                  title="Click to navigate"
                  style={{
                    fontSize: 10, padding: '4px 6px', marginBottom: 2, borderRadius: 4,
                    background: d.type === 'tp' ? 'rgba(16,185,129,0.1)' : d.type === 'fp' ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.1)',
                    color: accent,
                    borderLeft: `3px solid ${accent}`,
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = d.type === 'tp' ? 'rgba(16,185,129,0.22)' : d.type === 'fp' ? 'rgba(239,68,68,0.22)' : 'rgba(245,158,11,0.22)'}
                  onMouseLeave={e => e.currentTarget.style.background = d.type === 'tp' ? 'rgba(16,185,129,0.1)' : d.type === 'fp' ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.1)'}
                >
                  {d.label}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* TOOLTIP */}
      {tooltip && (
        <div className="tooltip" style={{ display: 'block', left: tooltip.x, top: tooltip.y }}>
          <div className="tt-label">{tooltip.noteName} (MIDI {tooltip.pitch})</div>
          <div className="tt-detail">
            Velocity: {tooltip.velocity}<br />
            Onset: {tooltip.onset}ms<br />
            Duration: {tooltip.duration}ms<br />
            <br />
            <strong>4D Chord Color:</strong><br />
            H: {tooltip.hue} | S: {tooltip.sat}% | L: {tooltip.lightness}%<br />
            Tension: {tooltip.tonal_distance}
            {tooltip.voice_tag && (<><br /><br /><strong>Voice:</strong> {tooltip.voice_tag}</>)}
            {tooltip.id_score != null && (<><br />I<sub>d</sub> Score: {tooltip.id_score}</>)}
          </div>
        </div>
      )}

      {/* ENGINE MODAL */}
      {isEngineRunning && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)', zIndex: 9999,
          display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}>
          <div style={{
            background: '#0d0d12', width: '800px', height: '600px',
            border: '1px solid #333', borderRadius: '8px',
            display: 'flex', flexDirection: 'column', overflow: 'hidden',
            boxShadow: '0 20px 50px rgba(0,0,0,0.5)'
          }}>
            <div style={{ padding: '12px 16px', background: '#111118', borderBottom: '1px solid #222', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, color: '#e0e0e0', fontSize: '14px' }}>ETME Engine Output</h3>
              {!isEngineDone ? (
                <div style={{ width: 16, height: 16, border: '2px solid rgba(255,255,255,0.2)', borderTop: '2px solid #4caf50', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
              ) : (
                <button
                  onClick={() => setIsEngineRunning(false)}
                  style={{ background: '#d32f2f', color: '#fff', border: 'none', borderRadius: '4px', padding: '6px 16px', cursor: 'pointer', fontWeight: 'bold' }}
                >
                  Dismiss
                </button>
              )}
            </div>
            <div style={{ padding: '16px', overflowY: 'auto', flex: 1, fontFamily: 'monospace', fontSize: '12px', color: '#a0a0b0', whiteSpace: 'pre-wrap' }}>
              {engineLogs.map((log, i) => <div key={i} style={{ marginBottom: '4px' }}>{log}</div>)}
              <div ref={logsEndRef} />
            </div>
          </div>
          <style dangerouslySetInnerHTML={{__html: '@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }'}} />
        </div>
      )}

      {/* BATCH ENGINE MODAL */}
      {isBatchRunning && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.88)', zIndex: 9999,
          display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}>
          <div style={{
            background: '#0d0d12', width: '860px', height: '700px',
            border: '1px solid #333', borderRadius: '10px',
            display: 'flex', flexDirection: 'column', overflow: 'hidden',
            boxShadow: '0 20px 60px rgba(0,0,0,0.6)'
          }}>
            {/* Header */}
            <div style={{ padding: '12px 18px', background: '#111118', borderBottom: '1px solid #222', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ margin: 0, color: '#e0e0e0', fontSize: '14px' }}>⚡ Batch Engine Run</h3>
                <div style={{ fontSize: 10, color: '#666', marginTop: 2 }}>{midiFile} · {angleMap} · mass={minBreakMass}</div>
              </div>
              {isBatchDone ? (
                <button
                  onClick={() => setIsBatchRunning(false)}
                  style={{ background: '#6a1b9a', color: '#fff', border: 'none', borderRadius: '4px', padding: '6px 16px', cursor: 'pointer', fontWeight: 'bold' }}
                >
                  Dismiss
                </button>
              ) : (
                <div style={{ width: 16, height: 16, border: '2px solid rgba(255,255,255,0.2)', borderTop: '2px solid #ab47bc', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
              )}
            </div>
            {/* Job checklist */}
            <div style={{ padding: '12px 18px', borderBottom: '1px solid #1a1a2e', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 24px', maxHeight: 280, overflowY: 'auto' }}>
              {batchJobs.map(job => {
                const icon = job.status === 'pending' ? '○' : job.status === 'running' ? '⟳' : job.status === 'done' ? '✅' : '❌';
                const color = job.status === 'pending' ? '#555' : job.status === 'running' ? '#ab47bc' : job.status === 'done' ? '#4caf50' : '#ef5350';
                return (
                  <div key={job.id} style={{ fontSize: 11, color, display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' }}>
                    <span style={{ fontSize: 13 }}>{icon}</span>
                    <span>{job.label}</span>
                  </div>
                );
              })}
            </div>
            {/* Progress bar */}
            {batchJobs.length > 0 && (() => {
              const done = batchJobs.filter(j => j.status === 'done' || j.status === 'error').length;
              const pct = Math.round(done / batchJobs.length * 100);
              return (
                <div style={{ padding: '8px 18px', borderBottom: '1px solid #1a1a2e' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#666', marginBottom: 4 }}>
                    <span>{done}/{batchJobs.length} complete</span><span>{pct}%</span>
                  </div>
                  <div style={{ height: 4, background: '#222', borderRadius: 2 }}>
                    <div style={{ height: 4, width: `${pct}%`, background: 'linear-gradient(90deg, #6a1b9a, #ab47bc)', borderRadius: 2, transition: 'width 0.3s' }} />
                  </div>
                </div>
              );
            })()}
            {/* Log pane */}
            <div style={{ padding: '12px 18px', overflowY: 'auto', flex: 1, fontFamily: 'monospace', fontSize: '11px', color: '#a0a0b0', whiteSpace: 'pre-wrap' }}>
              {batchLog.map((l, i) => <div key={i} style={{ marginBottom: 3 }}>{l}</div>)}
              <div ref={logsEndRef} />
            </div>
          </div>
          <style dangerouslySetInnerHTML={{__html: '@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }'}} />
        </div>
      )}
    </>
  );
}


// ===== COMPARISON UTILITIES =====

function getModelBoundaries(regimes) {
  if (!regimes) return [];
  const boundaries = [];
  for (let i = 0; i < regimes.length; i++) {
    const curr = regimes[i];
    // Only count TRANSITION SPIKE! regimes as model boundaries.
    // Stable/Locked periods come AFTER the harmonic change has settled
    // and are not meaningful boundary signals.
    if (curr.state === 'TRANSITION SPIKE!') {
      boundaries.push(curr.start_time);
    }
  }
  return boundaries;
}

function computeComparison(markers, regimes, tolerance) {
  if (!markers.length || !regimes) return null;

  const modelBounds = getModelBoundaries(regimes);
  const userTimes = markers.map(m => m.time_ms);

  // MODEL boundaries = predictions, USER markers = ground truth
  const matchedUser = new Set();
  const matchedModel = new Set();
  const details = [];

  // Find true positives: for each model boundary, find its best matching user marker
  for (let mi = 0; mi < modelBounds.length; mi++) {
    let bestDist = Infinity;
    let bestUi = -1;
    for (let ui = 0; ui < userTimes.length; ui++) {
      if (matchedUser.has(ui)) continue;
      const dist = Math.abs(modelBounds[mi] - userTimes[ui]);
      if (dist < bestDist) { bestDist = dist; bestUi = ui; }
    }
    if (bestDist <= tolerance && bestUi >= 0) {
      matchedModel.add(mi);
      matchedUser.add(bestUi);
      details.push({
        type: 'tp',
        time_ms: modelBounds[mi],
        markerId: markers[bestUi].id,
        label: `MATCH: Model @${modelBounds[mi]}ms ↔ User ${markers[bestUi].tier.toUpperCase()} @${userTimes[bestUi]}ms (${bestDist}ms)`
      });
    }
  }

  // False positives: model boundaries with no user marker nearby
  for (let mi = 0; mi < modelBounds.length; mi++) {
    if (!matchedModel.has(mi)) {
      details.push({
        type: 'fp',
        time_ms: modelBounds[mi],
        markerId: null,
        label: `FP: Model @${modelBounds[mi]}ms -- no user marker nearby`
      });
    }
  }

  // False negatives: user markers with no model boundary nearby
  for (let ui = 0; ui < userTimes.length; ui++) {
    if (!matchedUser.has(ui)) {
      details.push({
        type: 'fn',
        time_ms: userTimes[ui],
        markerId: markers[ui].id,
        label: `FN: User ${markers[ui].tier.toUpperCase()} @${userTimes[ui]}ms -- no model boundary nearby`
      });
    }
  }

  const tp = matchedModel.size;
  const fp = modelBounds.length - tp;
  const fn = userTimes.length - matchedUser.size;
  const precision = tp + fp > 0 ? Math.round(tp / (tp + fp) * 100) : 0;
  const recall = tp + fn > 0 ? Math.round(tp / (tp + fn) * 100) : 0;
  const f1 = precision + recall > 0 ? Math.round(2 * precision * recall / (precision + recall)) : 0;

  return { tp, fp, fn, precision, recall, f1, details };
}

