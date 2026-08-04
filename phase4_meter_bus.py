"""
meter_hypothesis.py: the evidence bus combiner.

One objective, not eight nudges. Every channel emits weighted votes;
this module does a joint (period, phase) argmax:

  score(P, phi) = prior(P) * sum_c  w_c * folded_mass_c(P, phi)
                             + w_par * parallelism_support(P, phi)

then a second argmax over measure grouping G in {2,3,4,6} and bar phase,
using the structurally strong channels (bass cadence, agogic, boundary,
surprisal, harmonic votes, parallelism at the bar lag), normalized per
grid line so different G compete fairly.

Anacrusis is handled by construction: phase is a free variable, so a
pickup simply means the winning phi is not at the first onset.

External channels (Phase 1 TRANSITION spikes, thermodynamic freezing
events) plug in with:  --votes harmonic=path/to/spikes.json
and get weight config key "extra:harmonic".

Output JSON is score_against_truth.py compatible.

Usage:
  python3 phase4_meter_bus.py --notes gt_or_etme.json --out pred.json
  python3 phase4_meter_bus.py --notes n.json --votes harmonic=spikes.json \
      --config weights.json --out pred.json
"""
import argparse
import json
import math

from signals_common import (load_notes, cluster_onsets, load_extra_votes,
                            top_line)
import accent_rhythm
import parallelism as par_mod
import surprisal as ic_mod
import melodic_attraction as att_mod

BIN_MS = 10.0

DEFAULT_WEIGHTS = {
    # tactus-level channel weights
    "onset_pulse": 0.35,       # Temperley's event rule: notes on beats
    "povel_essens": 1.0,
    "agogic": 1.2,
    "lbdm": 0.7,
    "velocity": 0.8,
    "surprisal": 0.8,
    "attraction": 0.9,
    "gap_fill": 0.5,
    # bass_cadence halved + measure extra_default 2.2→1.0 by corpus grid
    # search 2026-07-08 under channel_norm (train 967→807, val 949→867):
    # normalization unmasked the doc's original diagnosis — dense chorale
    # fifth-arrivals peak on the PRE-cadential beat and were locking the
    # grid one beat early.
    "bass_cadence": 0.9,
    "parallelism": 1.6,
    "extra_default": 1.8,      # Phase 1 spikes / freezes when supplied
    # measure-level multipliers (applied on top of channel weights)
    "measure": {"bass_cadence": 1.0, "agogic": 1.2, "lbdm": 0.8,
                "surprisal": 0.8, "attraction": 0.6, "povel_essens": 0.6,
                "onset_pulse": 0.15, "gap_fill": 0.5, "velocity": 0.8,
                "parallelism": 1.5, "extra_default": 1.0},
    # priors — sigma widths set by corpus grid search 2026-07-07 (were
    # 0.55/1.0 hand-set): train errors 1359→1270, val 1385→1368; the
    # narrow tactus prior was crushing legitimate slow tactus candidates.
    # See grid_search_bus.py --structural and docs/benchmarking.md.
    "tactus_prior_center_ms": 600.0,
    "tactus_prior_sigma_oct": 0.9,
    "measure_prior_center_ms": 1900.0,
    "measure_prior_sigma_oct": 1.4,
    "grouping_margin": 1.18,
    # 1 = normalize each channel's total vote mass to 1 before weighting,
    # so influence stops scaling with vote count and the channel weights
    # above regain leverage over dense vs sparse channels. Adopted by
    # corpus grid search 2026-07-08: train errors 1270→817, val 1368→872
    # — the largest single improvement in the project. (Dense soft
    # channels at default weight slightly hurt UNDER normalization;
    # they need their own weight sweep before joining the defaults.)
    "channel_norm": 1,
}


def log_gauss_prior(x, center, sigma_oct):
    return math.exp(-0.5 * (math.log2(x / center) / sigma_oct) ** 2)


def normalize_channels(channels):
    """Scale each channel so its total vote mass is 1: a channel's
    influence then comes from its weight, not its vote count."""
    out = {}
    for name, votes in channels.items():
        total = sum(v["weight"] for v in votes)
        if total <= 0:
            out[name] = votes
            continue
        out[name] = [{"time_ms": v["time_ms"], "weight": v["weight"] / total}
                     for v in votes]
    return out


def collect_channels(notes, enabled, tonic_pc, mode):
    events = cluster_onsets(notes)
    ch = {}
    if "onset_pulse" in enabled:
        ch["onset_pulse"] = [{"time_ms": e["time_ms"], "weight": 1.0}
                             for e in events]
    if "povel_essens" in enabled:
        ch["povel_essens"] = accent_rhythm.povel_essens_votes(events)
    if "agogic" in enabled:
        ch["agogic"] = accent_rhythm.agogic_votes(events)
    if "lbdm" in enabled:
        ch["lbdm"] = accent_rhythm.lbdm_votes(events)
    if "velocity" in enabled:
        ch["velocity"] = accent_rhythm.velocity_votes(events)
    if "surprisal" in enabled:
        ch["surprisal"] = ic_mod.ic_votes(notes)
    if "attraction" in enabled:
        ch["attraction"] = att_mod.attraction_votes(notes, tonic_pc, mode)
    if "gap_fill" in enabled:
        ch["gap_fill"] = att_mod.gap_fill_votes(notes)
    if "bass_cadence" in enabled:
        ch["bass_cadence"] = att_mod.bass_cadence_votes(notes)
    return ch


def fold_best(votes, period, tol_ms):
    """Best circular-phase mass of time votes folded at `period`.
    Returns (best_mass, best_phase_ms)."""
    if not votes:
        return 0.0, 0.0
    nbins = max(1, int(period / BIN_MS))
    hist = [0.0] * nbins
    for v in votes:
        hist[int((v["time_ms"] % period) / BIN_MS) % nbins] += v["weight"]
    r = max(1, int(tol_ms / BIN_MS))
    best, best_b = -1.0, 0
    for b in range(nbins):
        m = sum(hist[(b + k) % nbins] for k in range(-r, r + 1))
        if m > best:
            best, best_b = m, b
    return best, best_b * BIN_MS


def par_support(pvotes, period, tol_frac=0.035, max_mult=4):
    """Mass of repeat lags consistent with `period` (or its multiples),
    plus phase votes from the repeat anchors."""
    mass, anchors = 0.0, []
    for v in pvotes:
        for m in range(1, max_mult + 1):
            implied = v["lag_ms"] / m
            if abs(implied - period) <= tol_frac * period:
                w = v["weight"] / m
                mass += w
                anchors.append({"time_ms": v["anchor_ms"], "weight": w})
                break
    return mass, anchors


def search_tactus(channels, pvotes, weights, pmin, pmax):
    periods = []
    p = pmin
    step = 2 ** (1 / 36)
    while p <= pmax:
        periods.append(p)
        p *= step

    total_par = sum(v["weight"] for v in pvotes) or 1.0
    best = None
    table = []
    for P in periods:
        tol = max(15.0, 0.04 * P)
        s = 0.0
        combined = []
        for name, votes in channels.items():
            w = weights.get(name, 1.0)
            if w <= 0 or not votes:
                continue
            for v in votes:
                combined.append({"time_ms": v["time_ms"],
                                 "weight": v["weight"] * w})
        pmass, anchors = par_support(pvotes, P)
        wpar = weights.get("parallelism", 1.0)
        for a in anchors:
            combined.append({"time_ms": a["time_ms"],
                             "weight": a["weight"] * wpar})
        mass, phase = fold_best(combined, P, tol)
        pfrac = pmass / total_par
        s = mass * (1.0 + wpar * pfrac)
        s *= log_gauss_prior(P, weights["tactus_prior_center_ms"],
                             weights["tactus_prior_sigma_oct"])
        table.append((round(P, 1), round(s, 2)))
        if best is None or s > best[0]:
            best = (s, P, phase)
    # Fine refinement: 0.1% steps in a +-3% window around the coarse
    # winner. A 1% period error accumulates into full phase smear over
    # 30+ bars, so the winner must be located precisely.
    _, P0, _ = best
    for step in range(-30, 31):
        P = P0 * (1 + step * 0.001)
        tol = max(15.0, 0.04 * P)
        combined = []
        for name, votes in channels.items():
            w = weights.get(name, 1.0)
            for v in votes:
                combined.append({"time_ms": v["time_ms"],
                                 "weight": v["weight"] * w})
        pmass, anchors = par_support(pvotes, P)
        wpar = weights.get("parallelism", 1.0)
        for a in anchors:
            combined.append({"time_ms": a["time_ms"],
                             "weight": a["weight"] * wpar})
        mass, phase = fold_best(combined, P, tol)
        s = mass * (1.0 + wpar * (pmass / total_par))
        s *= log_gauss_prior(P, weights["tactus_prior_center_ms"],
                             weights["tactus_prior_sigma_oct"])
        if s > best[0]:
            best = (s, P, phase)
    table.sort(key=lambda x: -x[1])
    return best[1], best[2], table[:6]


def grid_mass_per_line(votes, period, phase, t0, t1, tol):
    mass = 0.0
    for v in votes:
        d = (v["time_ms"] - phase) % period
        if d <= tol or period - d <= tol:
            mass += v["weight"]
    lines = max(1, int((t1 - t0) / period) + 1)
    return mass / lines


def search_measure(channels, pvotes, weights, P, phi_t, t0, t1):
    mw = weights["measure"]
    total_par = sum(v["weight"] for v in pvotes) or 1.0
    best_per_g = {}
    for G in (2, 3, 4):
        M = G * P
        prior = log_gauss_prior(M, weights["measure_prior_center_ms"],
                                weights["measure_prior_sigma_oct"])
        pmass, _ = par_support(pvotes, M, max_mult=2)
        pfrac = pmass / total_par
        for k in range(G):
            phi = (phi_t + k * P) % M
            tol = max(25.0, 0.03 * M)
            s = 0.0
            for name, votes in channels.items():
                w = weights.get(name, 1.0) * mw.get(
                    name, mw.get("extra_default", 1.0)
                    if name.startswith("extra:") else 0.5)
                if w <= 0 or not votes:
                    continue
                s += w * grid_mass_per_line(votes, M, phi, t0, t1, tol)
            s *= (1.0 + mw.get("parallelism", 1.0) * pfrac)
            s *= prior
            if G not in best_per_g or s > best_per_g[G][0]:
                best_per_g[G] = (s, G, phi)
    # Parsimony: a composite grouping must beat its divisor by a margin,
    # otherwise the simpler level wins (2-bar phrases masquerade as bars)
    margin = weights.get("grouping_margin", 1.18)
    for big, small in ((4, 2),):
        if big in best_per_g and small in best_per_g:
            if best_per_g[big][0] < margin * best_per_g[small][0]:
                best_per_g[big] = (0.0, big, best_per_g[big][2])
    best = max(best_per_g.values(), key=lambda x: x[0])
    return best[1], best[2]


def compound_test(notes, P):
    """Duple vs triple subdivision of the tactus from top-line IOIs."""
    line = top_line(notes)
    duple = triple = 0
    for a, b in zip(line, line[1:]):
        ioi = b["time_ms"] - a["time_ms"]
        if abs(ioi - P / 2) <= 0.12 * P / 2:
            duple += 1
        if abs(ioi - P / 3) <= 0.12 * P / 3:
            triple += 1
    return triple >= 1.4 * max(duple, 1)


def derive_ts(G, P, is_compound):
    if is_compound:
        return f"{G * 3}/8", G * P
    if P >= 900:
        den = 2
    elif P <= 280:
        den = 8
    else:
        den = 4
    return f"{G}/{den}", G * P


def main():
    ap = argparse.ArgumentParser(description="Evidence-bus meter engine")
    ap.add_argument("--notes", required=True)
    ap.add_argument("--votes", action="append", default=[],
                    metavar="name=path",
                    help="external time-vote channels (harmonic spikes, "
                         "freezes)")
    ap.add_argument("--config", default=None, help="weights JSON")
    ap.add_argument("--dump-config", action="store_true")
    ap.add_argument("--channels", default="all")
    ap.add_argument("--tonic", type=int, default=None,
                    help="tonic pitch class 0-11 (from Phase 1 H_tonic)")
    ap.add_argument("--mode", default=None, choices=["major", "minor"])
    ap.add_argument("--min-period", type=float, default=240.0)
    ap.add_argument("--max-period", type=float, default=1600.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    weights = json.loads(json.dumps(DEFAULT_WEIGHTS))
    if args.config:
        with open(args.config) as f:
            user = json.load(f)
        for k, v in user.items():
            if k == "measure" and isinstance(v, dict):
                weights["measure"].update(v)
            else:
                weights[k] = v
    if args.dump_config:
        print(json.dumps(weights, indent=1))
        return

    notes = load_notes(args.notes)
    if not notes:
        raise SystemExit("no notes loaded")
    t0 = notes[0]["onset_ms"]
    t1 = max(n["onset_ms"] for n in notes)

    all_internal = ["onset_pulse", "povel_essens", "agogic", "lbdm",
                    "velocity", "surprisal", "attraction", "gap_fill",
                    "bass_cadence"]
    enabled = (all_internal if args.channels == "all"
               else [c.strip() for c in args.channels.split(",")])

    channels = collect_channels(notes, enabled, args.tonic, args.mode)
    for spec in args.votes:
        name, path = spec.split("=", 1)
        key = f"extra:{name}"
        channels[key] = load_extra_votes(path)
        weights.setdefault(key, weights["extra_default"])

    pvotes = (par_mod.period_votes(notes)
              if args.channels == "all" or "parallelism" in enabled else [])

    if weights.get("channel_norm"):
        channels = normalize_channels(channels)

    P, phi_t, top = search_tactus(channels, pvotes, weights,
                                  args.min_period, args.max_period)
    G, phi_m = search_measure(channels, pvotes, weights, P, phi_t, t0, t1)
    is_comp = compound_test(notes, P)
    ts, M = derive_ts(G, P, is_comp)

    barlines = []
    k = 0
    t = phi_m
    while t < t0 - 30:
        k += 1
        t = phi_m + k * M
    measure_num = 1
    while t <= t1 + 30:
        barlines.append({"time_ms": int(round(t)), "measure": measure_num})
        measure_num += 1
        k += 1
        t = phi_m + k * M

    # Grid-source contract for Phase 5 quantize (ticks_per_measure =
    # beats_per_measure * subdivision). Subdivision is a texture-neutral
    # default here; the corpus grid search owns refining it.
    numerator, denominator = (int(x) for x in ts.split("/"))
    out = {
        "meter": {"time_signature": ts,
                  "measure_ms": int(round(M)),
                  "beat_ms": int(round(P)),
                  "bpm_at_convention": round(60000.0 / P, 2),
                  "beats_per_measure": numerator,
                  "denominator": denominator,
                  "subdivision": 2 if is_comp else 4,
                  "tactus_ms": int(round(P)),
                  "bpm_tactus": round(60000.0 / P),
                  "barlines": barlines},
        "barlines": barlines,
        "debug": {
            "tactus_ms": round(P, 2),
            "tactus_phase_ms": round(phi_t, 1),
            "grouping": G,
            "measure_phase_ms": round(phi_m, 1),
            "compound": is_comp,
            "top_periods": top,
            "channel_vote_counts": {k: len(v) for k, v in channels.items()},
            "parallelism_votes": len(pvotes),
        },
    }
    text = json.dumps(out, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        d = out["debug"]
        print(f"tactus={d['tactus_ms']}ms grouping={G} ts={ts} "
              f"barlines={len(barlines)} phase={d['measure_phase_ms']}ms "
              f"-> {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
