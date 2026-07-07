"""
signals_common.py: shared substrate for the meter evidence bus.

Every signal module consumes normalized notes and emits VOTES:
  time votes    [{"time_ms": t, "weight": w}]        "something lands here"
  period votes  [{"lag_ms": L, "anchor_ms": t, "weight": w}]
                                        "this material repeats at lag L"

The combiner (meter_hypothesis.py) never knows what a signal means,
only how strongly it votes. New signals = new module + one weight.

Note loading sniffs the same shapes as score_against_truth.py, so
ground truth files, ETME exports, and phase3b JSONs all load.
"""
import json

ONSET_KEYS = ("onset_ms", "onset", "start_ms", "time_ms")
DUR_KEYS = ("duration_ms", "duration", "dur_ms")
VOICE_KEYS = ("voice_id", "voice_tag", "voice", "gt_voice")


def load_notes(path):
    with open(path) as f:
        data = json.load(f)
    raw = data.get("notes", data) if isinstance(data, dict) else data
    notes = []
    for n in raw:
        if not isinstance(n, dict) or "pitch" not in n:
            continue
        onset = next((n[k] for k in ONSET_KEYS if k in n), None)
        if onset is None:
            continue
        dur = next((n[k] for k in DUR_KEYS if k in n), 100)
        voice = next((str(n[k]) for k in VOICE_KEYS if n.get(k) is not None),
                     None)
        notes.append({
            "onset_ms": float(onset),
            "duration_ms": float(dur),
            "pitch": int(n["pitch"]),
            "velocity": int(n.get("velocity", 80)),
            "voice": voice,
        })
    notes.sort(key=lambda x: (x["onset_ms"], -x["pitch"]))
    return notes


def cluster_onsets(notes, window_ms=30):
    """Group near-simultaneous notes into onset events (keyframes)."""
    events = []
    cur = None
    for n in notes:
        if cur is None or n["onset_ms"] - cur["time_ms"] > window_ms:
            cur = {"time_ms": n["onset_ms"], "notes": [n]}
            events.append(cur)
        else:
            cur["notes"].append(n)
    for e in events:
        ns = e["notes"]
        e["n"] = len(ns)
        e["max_dur"] = max(x["duration_ms"] for x in ns)
        e["lo"] = min(x["pitch"] for x in ns)
        e["hi"] = max(x["pitch"] for x in ns)
        e["vel"] = max(x["velocity"] for x in ns)
    return events


def top_line(notes, gap_reset_ms=2500):
    """Melody proxy: highest pitch at each onset event."""
    line = []
    for e in cluster_onsets(notes):
        line.append({"time_ms": e["time_ms"], "pitch": e["hi"],
                     "dur": e["max_dur"]})
    return line


def bass_line(notes):
    """Bass proxy: lowest pitch at each onset event (same proxy Phase 1
    uses; swap in Phase 2's V4 when available for better accuracy)."""
    return [{"time_ms": e["time_ms"], "pitch": e["lo"], "dur": e["max_dur"]}
            for e in cluster_onsets(notes)]


def iois(events):
    return [b["time_ms"] - a["time_ms"] for a, b in zip(events, events[1:])]


def median(xs):
    s = sorted(xs)
    return s[len(s) // 2] if s else 0.0


def tvote(t, w):
    return {"time_ms": float(t), "weight": float(w)}


def pvote(lag, anchor, w):
    return {"lag_ms": float(lag), "anchor_ms": float(anchor),
            "weight": float(w)}


def load_extra_votes(path):
    """Adapter for external time-vote files: Phase 1 TRANSITION spikes,
    thermodynamic freezing events, marker files. Sniffs time and weight."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        for k in ("events", "spikes", "freezes", "markers", "votes"):
            if k in data and isinstance(data[k], list):
                data = data[k]
                break
    votes = []
    for x in data:
        if isinstance(x, (int, float)):
            votes.append(tvote(x, 1.0))
        elif isinstance(x, dict):
            t = next((x[k] for k in ("time_ms", "time", "t_ms", "onset_ms")
                      if k in x), None)
            if t is None:
                continue
            w = next((x[k] for k in ("weight", "magnitude", "strength")
                      if k in x), 1.0)
            votes.append(tvote(t, w))
    return votes
