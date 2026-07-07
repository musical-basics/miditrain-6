"""
accent_rhythm.py: the pure-rhythm channel (Phase 4 signals).

No pitch, no harmony. Three validated accent families:

1. Povel & Essens (1985) accent rules on the onset stream:
   - an isolated onset is accented
   - the second of a two-onset cluster is accented
   - the first and last of a run of 3+ are accented
2. Agogic accents: notes markedly longer than the local norm, plus a
   small vote on the event AFTER a long gap (group-start accent).
3. LBDM-flavored boundary strength (Cambouropoulos): normalized local
   change in the IOI sequence marks group boundaries; group starts
   lean toward strong positions.

Emits time votes only.
"""
from signals_common import cluster_onsets, iois, median, tvote


def povel_essens_votes(events, run_ratio=1.5, w=1.0):
    if len(events) < 3:
        return []
    gaps = iois(events)
    med = median(gaps) or 1.0
    thresh = run_ratio * med

    # Segment into runs: consecutive events joined by short IOIs
    runs, cur = [], [0]
    for i, g in enumerate(gaps):
        if g <= thresh:
            cur.append(i + 1)
        else:
            runs.append(cur)
            cur = [i + 1]
    runs.append(cur)

    votes = []
    for run in runs:
        if len(run) == 1:
            votes.append(tvote(events[run[0]]["time_ms"], w))       # isolated
        elif len(run) == 2:
            votes.append(tvote(events[run[1]]["time_ms"], w))       # second
        else:
            votes.append(tvote(events[run[0]]["time_ms"], w))       # first
            votes.append(tvote(events[run[-1]]["time_ms"], w))      # last
    return votes


def agogic_votes(events, long_ratio=1.6, w=1.0):
    if not events:
        return []
    med_dur = median([e["max_dur"] for e in events]) or 1.0
    gaps = iois(events)
    med_gap = median(gaps) or 1.0
    votes = []
    for i, e in enumerate(events):
        r = e["max_dur"] / med_dur
        if r >= long_ratio:
            votes.append(tvote(e["time_ms"], w * min(r, 3.0)))
        # group-start accent after a long silence
        if i > 0 and gaps[i - 1] >= 1.8 * med_gap:
            votes.append(tvote(e["time_ms"], 0.5 * w))
    return votes


def lbdm_votes(events, w=1.0):
    """Boundary strength from normalized IOI change. A boundary BEFORE
    event i means i starts a group; group starts get the vote."""
    if len(events) < 4:
        return []
    g = iois(events)
    votes = []
    for i in range(1, len(g)):
        a, b = g[i - 1], g[i]
        if a + b <= 0:
            continue
        change = abs(b - a) / (a + b)          # 0..1
        strength = change * (b / (median(g) or 1.0))
        if strength > 0.5:
            votes.append(tvote(events[i + 1]["time_ms"],
                               w * min(strength, 2.5)))
    return votes


def velocity_votes(events, ratio=1.25, w=1.0):
    """Dynamic accents. No-op on corpus MIDIs (flat velocity); live on
    performance MIDI."""
    vels = [e["vel"] for e in events]
    med_v = median(vels) or 1.0
    if max(vels) <= ratio * med_v:
        return []
    return [tvote(e["time_ms"], w * (e["vel"] / med_v))
            for e in events if e["vel"] >= ratio * med_v]


def all_votes(notes, w=1.0):
    events = cluster_onsets(notes)
    votes = []
    votes += povel_essens_votes(events, w=w)
    votes += agogic_votes(events, w=w)
    votes += lbdm_votes(events, w=w)
    votes += velocity_votes(events, w=w)
    return votes
