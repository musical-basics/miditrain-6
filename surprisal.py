"""
surprisal.py: information-content accents (Pearce's IDyOM, made
deterministic and causal).

Your Temperature uses windowed interval ENTROPY, which measures variety.
What predicts perceived accent and boundary is INFORMATION CONTENT:
violation of the piece's own statistics so far. One shocking note in a
predictable stream barely moves entropy but spikes IC.

Online interpolated n-gram model (orders 0..2) over top-line intervals,
trained causally on the piece so far. IC(x) = -log2 p(x | context).
Votes where IC exceeds the running median.
"""
import math
from collections import defaultdict
from signals_common import top_line, tvote


class OnlineNgram:
    def __init__(self, max_order=2):
        self.max_order = max_order
        self.counts = [defaultdict(lambda: defaultdict(int))
                       for _ in range(max_order + 1)]
        self.ctx_tot = [defaultdict(int) for _ in range(max_order + 1)]
        self.alphabet = set()

    def prob(self, ctx, x):
        v = max(len(self.alphabet), 1)
        p = 1.0 / (v + 1)                       # order -1 floor
        for k in range(self.max_order + 1):
            c = tuple(ctx[-k:]) if k else ()
            tot = self.ctx_tot[k][c]
            lam = tot / (tot + 1.0)             # trust grows with evidence
            pk = (self.counts[k][c][x] + 0.5) / (tot + 0.5 * (v + 1))
            p = (1 - lam) * p + lam * pk
        return p

    def update(self, ctx, x):
        self.alphabet.add(x)
        for k in range(self.max_order + 1):
            c = tuple(ctx[-k:]) if k else ()
            self.counts[k][c][x] += 1
            self.ctx_tot[k][c] += 1


def ic_votes(notes, w=1.0, warmup=8):
    line = top_line(notes)
    if len(line) < warmup + 4:
        return []
    ivs = [b["pitch"] - a["pitch"] for a, b in zip(line, line[1:])]
    model = OnlineNgram()
    ics, votes = [], []
    ctx = []
    for i, x in enumerate(ivs):
        ic = -math.log2(model.prob(ctx, x))
        model.update(ctx, x)
        ctx.append(x)
        if i >= warmup:
            ics.append(ic)
            med = sorted(ics)[len(ics) // 2]
            excess = ic - med
            if excess > 0.5:
                votes.append(tvote(line[i + 1]["time_ms"],
                                   w * min(excess, 4.0)))
    return votes
