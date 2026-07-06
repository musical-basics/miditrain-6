# Session Log

## 2026-07-05 — Phase 3 + Phase 4 ported from miditrain-4

**What was done**

Ported the downstream pipeline stages from miditrain-4 into this repo, with the
honest renumbering proposed in `plan for improvements.md` (thermodynamic meter
= Phase 3, quantize-and-notate = Phase 4; no more "Step 2.5"):

- `phase3_thermo_meter.py` (was miditrain-4 `thermodynamic_meter.py`, "Step 2.5")
  → writes `visualizer/public/phase3_thermo_{base_key}.json`
- `phase3_spike_meter.py` (was `phase3_meter.py`, "Phase 3A")
  → writes `visualizer/public/phase3_grid_{base_key}.json`
- `phase4_quantize.py` (was `phase3b_quantize.py`)
  → writes `visualizer/public/phase4_quantized_{...}.json`
- `phase4_notation.py` (was `phase3c_notation.py`; the misleading
  `osmd_ready` output prefix renamed to `phase4_notation_` — the renderer is
  VexFlow, not OSMD) → writes the DreamFlow IntermediateScore JSON
- All four are pure stdlib; no new entries in `requirements.txt`.

Visualizer:

- Added `dreamflow` local file dependency (`file:../../../UltimatePianist
  Repos/dreamflow` — the VexFlow fork; must exist at that path for
  `pnpm install`).
- Copied `app/components/dreamflow/` (VexFlowRenderer etc.) and
  `NotationView.js` from miditrain-4 (prop renamed `phase3cData` →
  `notationData`).
- New `Phase3Renderer.js` / `Phase4Renderer.js` following this repo's
  renderer-module pattern (extracted from miditrain-4's inline canvas code).
- `ETMEVisualizer.js`: four new views in a "Phase 3 / 4..." dropdown
  (`phase3` thermo overlay, `phase3_grid` barlines/density/ACF, `phase4a`
  quantized roll, `phase4b` VexFlow notation), fetches for the four new JSONs,
  runEngine extended to a 5-step chain (works for `__optimized__:` datasets
  too), key-algorithm select (Temperley/Krumhansl), notation layout toggle,
  quantized-coords tooltip. Header renamed to "ETME Pipeline Tester".
  Pre-edit backup in `_backup_files/ETMEVisualizer_pre_phase34_port.js`.

Docs ported: `docs/thermodynamic_meter_theory.md`,
`docs/phase3_spike_meter_history.md` (was phase3a_session_summary.md).

**Verified**: full Python chain ran end-to-end on
`etme_revolutionary_64s_chunk_dissonance_hybrid_0.5.json` (thermo → grid →
quantize → notation, detected key Eb); `tsc --noEmit` clean; `pnpm build`
clean; dev server served the page and all four new JSONs (all 200), then was
killed.

**Decisions made**

- Same wiring as miditrain-4: Phase 4 consumes the **spike grid**
  (`phase3_grid_*.json`), not the thermo meter's barlines. The thermo meter's
  `meter{}` block lacks `subdivision`, which the quantizer requires. Promoting
  thermo to grid source = add subdivision estimation to it (open decision).
- Kept both meter engines rather than replacing one (A/B testing rule): thermo
  is the canonical Phase 3 per the plan doc; the spike model is labeled
  "Legacy" in the UI.
- Did not port `test_temperley.py` (scratch test, hardcoded miditrain-3 path,
  duplicates `phase4_notation.py`'s detect_key).
- Test-generated Phase 3/4 JSONs for the revolutionary chunk left untracked,
  matching how the ETME datasets are currently handled.

**Left incomplete / known issues**

- Meter tuning is Pathétique-specific (miditrain-4 known issue): the
  Revolutionary chunk got 8/4 at questionable barlines. Expected — Phase 3 has
  no optimizer harness yet (the plan doc's "ground truth factory" is the fix).
- Measure numbering restarts per chunk (inherited TODO).
- The P1↔P2 relaxation loop (plan doc item 1: re-run P1 with V4 as true bass
  feed) is not implemented.
- See `docs/debt.md` for smaller inherited debts.
