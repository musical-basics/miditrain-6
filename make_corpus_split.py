"""
Create the train/validation split for the expanded corpus.

Deterministic and stratified: within each texture tier (chorale, essen,
mixed piano/demo), pieces are sorted by id and alternated train/val, so
both halves see every texture. Free-meter pieces are excluded entirely.

The split is committed (benchmarks/corpus_split.json) and never
regenerated casually — grid searches tune on "train"; run_benchmark.py
gates on "val" + the held-out Pathétique chunk. Re-running this script
after ADDING corpus pieces keeps existing assignments stable only by
accident of sorting — if the corpus grows, review the diff before
committing.

Usage: python3 make_corpus_split.py
"""
import csv
import json
import os

CORPUS = os.path.join("corpus files", "corpus_full")
SPLIT_FILE = os.path.join("benchmarks", "corpus_split.json")


def tier_of(pid):
    if pid.startswith("chorale_"):
        return "chorale"
    if pid.startswith("essenFolksong_"):
        return "essen"
    return "mixed"  # demo pieces + piano/quartet tier


def main():
    with open(os.path.join(CORPUS, "manifest.csv"), newline="") as f:
        rows = [r for r in csv.DictReader(f) if "?" not in r.get("meters", "")]

    tiers = {}
    for r in rows:
        tiers.setdefault(tier_of(r["id"]), []).append(r["id"])

    train, val = [], []
    for tier in sorted(tiers):
        ids = sorted(set(tiers[tier]))
        for i, pid in enumerate(ids):
            (train if i % 2 == 0 else val).append(pid)

    split = {"corpus": CORPUS, "train": sorted(train), "val": sorted(val)}
    os.makedirs(os.path.dirname(SPLIT_FILE), exist_ok=True)
    with open(SPLIT_FILE, "w") as f:
        json.dump(split, f, indent=1)

    print(f"{len(rows)} metered pieces → train={len(train)} val={len(val)}")
    for tier in sorted(tiers):
        n = len(set(tiers[tier]))
        print(f"  {tier}: {n} pieces")
    print(f"Split written to {SPLIT_FILE} — commit it.")


if __name__ == "__main__":
    main()
