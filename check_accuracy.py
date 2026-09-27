#!/usr/bin/env python3
import argparse
import os
import random
import time

for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

import pandas as pd

import main as server
from pipeline.gate import FormatGate
from pipeline.mining import mask_line
from train_gate import GENS, UNKNOWN, make_corpus


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-family", type=int, default=250)
    ap.add_argument("--unknown-per-family", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    gate_clf = FormatGate()
    if not gate_clf.loaded:
        print("ERROR: models/gate.pkl missing - run python train_gate.py first")
        return 1

    random.seed(args.seed)
    server.template_tier.reset()

    X, y = make_corpus(args.n_per_family, GENS)
    t0 = time.perf_counter()
    results = [server.process_record(l) for l in X]
    server_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    gate_rows = [gate_clf.inspect(mask_line(l)) for l in X]
    gateeval_s = time.perf_counter() - t0

    df = pd.DataFrame({
        "family": y,
        "mode": [r["mode"] for r in results],
        "latency_ms": [r["latency_ms"] for r in results],
        "gate_novel": [g["novel"] for g in gate_rows],
        "gate_family": [g["family_guess"] for g in gate_rows],
        "signature": [r["format"] for r in results],
    })
    fam_acc = (df["gate_family"] == df["family"]).mean()

    modes = df.groupby(["family", "mode"]).size().unstack(fill_value=0)
    summary = df.groupby("family").agg(
        lines=("family", "size"),
        mean_ms=("latency_ms", "mean"),
        p50_ms=("latency_ms", "median"),
        novel_rate=("gate_novel", "mean"),
        fam_acc=("gate_family", lambda s: (s == df.loc[s.index, "family"]).mean()),
    ).round(4)
    out = summary.join(modes).fillna(0).astype({"lines": int})

    server.template_tier.reset()
    server.parser.cache.clear()
    Xu, yu = make_corpus(args.unknown_per_family, UNKNOWN)
    res_u = [server.process_record(l) for l in Xu]
    gate_rows_u = [gate_clf.inspect(mask_line(l)) for l in Xu]
    du = pd.DataFrame({
        "family": yu,
        "mode": [r["mode"] for r in res_u],
        "gate_novel": [g["novel"] for g in gate_rows_u],
        "signature": [r["format"] for r in res_u],
    })
    unknown_catch = du["gate_novel"].mean()
    per_unknown = du.groupby("family")["gate_novel"].mean().round(3)

    known_flag_rate = df["gate_novel"].mean()
    prec = (du["gate_novel"].sum() / (du["gate_novel"].sum() + df["gate_novel"].sum())) \
        if (du["gate_novel"].sum() + df["gate_novel"].sum()) else float("nan")

    tier_stats = dict(server.template_tier.stats)
    mode_share = (df["mode"].value_counts(normalize=True) * 100).round(2)
    tier = gate_clf.info

    print("=" * 70)
    print(f"corpus: {len(X)} lines / {df['family'].nunique()} known families "
          f"+ {len(Xu)} lines / {du['family'].nunique()} never-seen families")
    print(f"server loop: {server_s:.1f}s -> {server_s/len(X)*1000:.2f} ms/line mean "
          f"(heuristic discovery, no LLM key)")
    print(f"format-family classification (gate): {fam_acc*100:.2f}% over known families")
    print(f"novel-format detection: recall {unknown_catch*100:.1f}% on never-seen families, "
          f"precision {prec*100:.1f}% (known-family false-alarm {known_flag_rate*100:.2f}%)")
    print(f"mode mix: {mode_share.to_dict()}")
    print(f"tier stats: {tier_stats}")
    print("=" * 70)
    print("\nper-family breakdown (known families):")
    print(out.to_string())
    print("\nnever-seen families (novelty recall per family):")
    print(per_unknown.round(3).to_frame("catch_rate").to_string())
    print(f"\ngate artifact: {tier['n_train']} training lines, threshold {tier['threshold']:.4f}, "
          f"sklearn {tier.get('sklearn_version_expected')}, trained {tier['trained_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
