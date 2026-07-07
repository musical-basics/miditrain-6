"""
melodic_attraction.py: directed tension (Larson magnetism, Lerdahl
attraction, Meyer gap-fill, cadential bass schemata).

Your tension variables are scalars. These make tension a VECTOR: they
predict WHERE resolution lands, so a note arriving exactly at its
magnetic target is a high-confidence landing event, not just another
viscosity spike.

  attraction(p1 -> p2) = (s2 / s1) * 1 / d^2      (Lerdahl)

where s is tonal stability (Krumhansl-Schmuckler profile keyed to the
detected or supplied tonic) and d is semitone distance. Scale degree
7 -> 1 and 4 -> 3 dominate, exactly the leading-tone physics a pianist
feels in the hand.

Also: gap-fill closure (a leap opens registral tension, stepwise return
closes it) and bass cadence arrivals (falling fifth / rising fourth),
the strongest single downbeat schema in common practice.

Feed --tonic/--mode from Phase 1's H_tonic when available; otherwise a
built-in Krumhansl key finder runs on the notes.
"""
from signals_common import top_line, bass_line, tvote, median

KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66,
            2.29, 2.88]
KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69,
            3.34, 3.17]


def find_key(notes):
    pc = [0.0] * 12
    for n in notes:
        pc[n["pitch"] % 12] += (n["velocity"] / 127.0) * n["duration_ms"]
    tot = sum(pc) or 1.0
    pc = [x / tot for x in pc]

    def corr(profile, rot):
        prof = profile[-rot:] + profile[:-rot]
        mp = sum(prof) / 12.0
        mx = sum(pc) / 12.0
        num = sum((a - mx) * (b - mp) for a, b in zip(pc, prof))
        dp = (sum((a - mx) ** 2 for a in pc) *
              sum((b - mp) ** 2 for b in prof)) ** 0.5
        return num / dp if dp else 0.0

    best = (-2, 0, "major")
    for r in range(12):
        for mode, prof in (("major", KS_MAJOR), ("minor", KS_MINOR)):
            c = corr(prof, r)
            if c > best[0]:
                best = (c, r, mode)
    return best[1], best[2]


def stability(pitch, tonic_pc, mode):
    prof = KS_MAJOR if mode == "major" else KS_MINOR
    return prof[(pitch - tonic_pc) % 12]


def attraction_votes(notes, tonic_pc=None, mode=None, w=1.0, thresh=1.6):
    if tonic_pc is None:
        tonic_pc, mode = find_key(notes)
    line = top_line(notes)
    votes = []
    for a, b in zip(line, line[1:]):
        d = abs(b["pitch"] - a["pitch"])
        if d == 0 or d > 4:
            continue
        s1 = stability(a["pitch"], tonic_pc, mode)
        s2 = stability(b["pitch"], tonic_pc, mode)
        alpha = (s2 / s1) * (1.0 / (d * d))
        if alpha >= thresh:                    # realized magnetic pull
            votes.append(tvote(b["time_ms"], w * min(alpha, 4.0)))
    return votes


def gap_fill_votes(notes, leap=6, w=1.0):
    line = top_line(notes)
    votes = []
    open_gap = None                             # (origin_pitch, direction)
    for a, b in zip(line, line[1:]):
        dp = b["pitch"] - a["pitch"]
        if abs(dp) >= leap:
            open_gap = (a["pitch"], 1 if dp > 0 else -1)
        elif open_gap and dp != 0:
            origin, direction = open_gap
            if (dp > 0) != (direction > 0) and abs(dp) <= 2:
                if abs(b["pitch"] - origin) <= 2:      # gap closed
                    votes.append(tvote(b["time_ms"], w))
                    open_gap = None
    return votes


def bass_cadence_votes(notes, w=1.0):
    """Fifth-motion arrivals in the bass, gated by agogic marking: a
    true cadential arrival tends to be held, while mid-progression
    fifths in beat-level harmonic rhythm (chorales) are short. Weight
    scales with arrival duration relative to the local norm."""
    line = bass_line(notes)
    if len(line) < 3:
        return []
    med_dur = median([x["dur"] for x in line]) or 1.0
    votes = []
    for a, b in zip(line, line[1:]):
        dp = b["pitch"] - a["pitch"]
        hold = min(2.0, b["dur"] / med_dur)
        if hold < 0.9:
            continue                            # passing fifth, not a landing
        if dp in (-7, 5):                       # falling fifth / inversion
            votes.append(tvote(b["time_ms"], 2.5 * w * hold))
        elif dp in (-5, 7):                     # plagal-flavored arrival
            votes.append(tvote(b["time_ms"], 1.2 * w * hold))
    return votes


def all_votes(notes, tonic_pc=None, mode=None, w=1.0):
    return (attraction_votes(notes, tonic_pc, mode, w=w) +
            gap_fill_votes(notes, w=w) +
            bass_cadence_votes(notes, w=w))
