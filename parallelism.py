"""
parallelism.py: the motivic repetition channel (GTTM MPR 1).

Parallel material prefers parallel metrical placement. When a motive
repeats at lag L, that repeat is simultaneously evidence for period L
(and its integer divisors) AND for phase anchored at the motive's
onsets. This is the only channel that votes on (period, phase) jointly,
which is why it disambiguates cases pure accent counting cannot
(syncopated ragtime, homogeneous chorale rhythm).

Method: hash overlapping n-grams of (interval, IOI-bin) tokens from the
top line; every pair of occurrences of the same n-gram emits a period
vote. Deterministic, causal-friendly (hashes only ever accumulate).
"""
from collections import defaultdict
from signals_common import top_line, pvote


def tokens(line, ioi_bin_ms=25):
    toks = []
    for a, b in zip(line, line[1:]):
        dp = max(-14, min(14, b["pitch"] - a["pitch"]))
        ioi = int(round((b["time_ms"] - a["time_ms"]) / ioi_bin_ms))
        toks.append((dp, ioi))
    return toks


def period_votes(notes, n=4, min_lag=280, max_lag=9000, w=1.0,
                 max_pairs_per_gram=6):
    line = top_line(notes)
    if len(line) < n + 2:
        return []
    toks = tokens(line)
    grams = defaultdict(list)
    for i in range(len(toks) - n + 1):
        grams[tuple(toks[i:i + n])].append(line[i]["time_ms"])

    votes = []
    for starts in grams.values():
        if len(starts) < 2:
            continue
        pairs = 0
        for i in range(len(starts) - 1):
            for j in range(i + 1, len(starts)):
                lag = starts[j] - starts[i]
                if lag < min_lag or lag > max_lag:
                    continue
                votes.append(pvote(lag, starts[i], w))
                pairs += 1
                if pairs >= max_pairs_per_gram:
                    break
            if pairs >= max_pairs_per_gram:
                break
    return votes
