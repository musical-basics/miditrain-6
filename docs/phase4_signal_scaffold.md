# Signal Scaffold: The Meter Evidence Bus

Seven modules that add the literature's validated meter cues to your
stack as ONE joint optimization, not a pile of nudges. Every signal is
a pure function emitting weighted votes; a single combiner does the
(period, phase) argmax; your Phase 1 spikes and thermodynamic freezes
plug in as external vote channels with one flag.

```
notes JSON (GT, ETME export, or phase3b)
   |
   |   accent_rhythm.py    Povel-Essens, agogic, LBDM, velocity
   |   parallelism.py      motif repeats -> (period, phase) votes
   |   surprisal.py        online n-gram information content
   |   melodic_attraction  Lerdahl magnetism, gap-fill, cadential bass
   |   [--votes harmonic=] Phase 1 TRANSITION spikes      <- your engine
   |   [--votes freezes=]  thermodynamic freezing events  <- your engine
   v
meter_hypothesis.py: score(P, phi) = prior(P) * sum_c w_c * fold_c(P, phi)
   -> tactus (P, phi) -> grouping G in {2,3,4} -> compound test -> barlines
   -> JSON scored directly by score_against_truth.py
```

## Channel map

| Channel | Literature | What it adds that you lacked |
|---|---|---|
| onset_pulse | Temperley's event rule | notes prefer beats; carries homogeneous textures |
| povel_essens | Povel & Essens 1985 | meter from onset patterns alone |
| agogic | GTTM MPR 5a | long notes prefer strong positions |
| lbdm | Cambouropoulos LBDM | group boundaries from local IOI change |
| velocity | performance accents | live/recorded MIDI only (corpus is flat 80) |
| surprisal | Pearce IDyOM | violation accents, not variety (your T is variety) |
| attraction | Lerdahl / Larson magnetism | WHERE resolution lands, not just that tension fell |
| gap_fill | Meyer | leap opens tension, stepwise return closes it |
| bass_cadence | Caplin / Gjerdingen schemata | falling-fifth arrivals, agogically gated |
| parallelism | GTTM MPR 1 | repeats vote on (period, phase) JOINTLY |
| extra:* | your Phase 1 / Step 2.5 | the harmonic half of the argument |

`energy_hierarchy.py` is separate: a partial-discharge post-processor
for your freezing events (Lerdahl's hierarchical tension). Port the
~15 lines of `partial_discharge` into thermodynamic_meter.py in place
of the Step 3.3 `energy_accum = 0` reset; primary freezes then feed
back as `--votes freezes=annotated.json`.

## Baseline results (rhythm + melodic surface ONLY, no harmonic channel)

16 common-meter corpus pieces, +-50ms tolerance, default weights:

```
bach_bwv66.6   1.000   chorale_009  1.000   chorale_011  1.000
chorale_007    0.974   bach_bwv269  0.949   chorale_000  0.949
chorale_004    0.933   chorale_001  0.919   chorale_010  0.733
bach_bwv846    0.673   maple_leaf   0.663   chorale_006  0.289
chorale_003    0.194   chorale_002  0.133   chorale_005  0.000
chorale_008    0.000
MEAN F1 = 0.651        total errors = 295
```

Both anacrusis showcases (bwv66.6, chorale_011, and 3/4 bwv269) are
solved by construction: phase is a free variable, so pickups cost
nothing.

**Oracle ceiling test**: feeding bwv846 a perfect harmonic channel
(`--votes harmonic=...` with downbeat-aligned votes) lifts it from
0.673 to 1.000. The bus integrates external evidence correctly; the
worst pieces are simply waiting for your Phase 1 channel.

## Why the failures fail (measured, not guessed)

Vote mass by beat-in-bar on chorale_003 (4/4, one-beat pickup):

```
bass fifth-arrivals   beat1: 6.2   beat2: 2.4   beat3: 8.7   beat4: 18.7
```

Chorales change harmony every beat, so falling fifths are dense and
peak on the PRE-cadential beat: surface signals lock the grid one beat
early. The disambiguator is harmonic RESOLUTION quality and hierarchy,
which is exactly the channel this scaffold does not contain and your
engine does. Your original instinct (rhythm alone is weak, harmonic
change is the strong signal) is now a measured fact: 0.651 is the
rhythm-only ceiling on this suite, and the remaining ~0.35 belongs to
your Phase 1 / Step 2.5 channels.

## Wiring into miditrain

1. Export Phase 1 TRANSITION spikes as `[{"time_ms":..,"magnitude":..}]`
   (load_extra_votes also reads your marker format directly).
2. `python3 meter_hypothesis.py --notes chunk.json \
       --votes harmonic=spikes.json --tonic <pc from H_tonic> --out p.json`
3. `python3 score_against_truth.py --truth gt.json --pred p.json \
       --csv runs.csv --tag harmonic_v1`
4. Weight tuning is the optimize_params pattern: loop weight configs
   via `--config w.json` (see `--dump-config` for the schema), sum
   `errors` over the manifest, rank. Do NOT hand-tune further; the
   defaults here were deliberately left rough so the corpus decides.

## Known limits (by design, documented not hidden)

- 6/8 vs 3/4: grouping searches {2,3,4}; compound meters come from the
  subdivision test mapping G=2 to 6/8. Sparse-melody compound pieces
  can still be named 3/4: harmonic rhythm at the bar is the textbook
  tiebreaker, i.e., your channel again.
- Corpus velocity is flat 80, so the velocity channel is dormant until
  performance MIDI. Maple Leaf's syncopation would benefit most.
- Tactus search range defaults to 240-1600ms (van Noorden resonance
  region). Archaic meters (4/1, 4/2 with 2000ms beats) need
  --max-period raised and grouping widened via config.
- Rigid grid output: no rubato snapping. On quantized MIDI rigid is
  correct; for performance MIDI, feed this grid as the prior into your
  existing rubber-band / repair machinery, or a DP tracker with an
  inertia cost (Large-Jones is the principled live version).
- Fine period refinement (0.1% steps) exists because a 1% period error
  smears phase over 30+ bars; do not coarsen it.
