# Technical Debt

Items noticed while working on something else. Documented here per operating
instructions; ask before fixing.

## From the Phase 3/4 port (2026-07-05)

- **`run_phase2.py` hardcodes the greedy threader** (`VoiceThreader`, line ~50).
  When the user selects "P2: Beam Search" in the UI and runs an
  `__optimized__:` dataset, the re-run still uses greedy. Fix: add a
  `--phase2_model` arg mirroring `export_etme_data.py`.
- ~~**Thermo meter output lacks `subdivision`**~~ — RESOLVED 2026-07-05:
  `phase3_thermo_meter.py` now estimates subdivision from note-onset IOIs and
  the thermo file is selectable as Phase 4's grid source ("Grid: Thermo" in
  the UI). Remaining weakness: when freeze events are sparse the thermo
  tactus degenerates to the measure length (e.g. Revolutionary chunk:
  tactus=measure=4000ms, ratio 33 → subdivision falls back to 1). The tactus
  estimator itself needs the corpus harness to tune.
- **`dreamflow` is a local file: dependency** (`visualizer/package.json`) on
  `/Users/lionelyu/Documents/UltimatePianist Repos/dreamflow`. Fresh clones on
  another machine will fail `pnpm install` unless that repo is present at the
  same relative path (or the dep is vendored/published).
- **Measure numbering restarts at 1 per chunk** (inherited miditrain-4 TODO):
  chunk 2 of a piece should continue from chunk 1's numbering.
- **Notation hover→tooltip mapping is loose**: miditrain-4's
  `handleNoteHover` matched notes by pitch + approximate tick-time with
  hardcoded 120 BPM assumptions; not ported to miditrain-6 (Phase 4B view has
  no note hover). Wire vfId → note identity properly if needed.
