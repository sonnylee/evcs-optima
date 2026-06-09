#!/usr/bin/env python3
"""Cross-seed coverage union (STEP S5).

Post-processing tool — NOT an exploration strategy. Given several visited-set
dumps produced by the exploration harness (run with ``EVCS_DUMP_VISITED=...``),
it reports the de-duplicated union, the per-seed contribution / diminishing-
returns curve, the core (visited by every non-degenerate seed), the frontier
(visited by exactly one), and what stays unvisited by any seed.

A "degenerate" run is a collapsed trajectory (e.g. an ε-greedy seed that
stagnated almost immediately): its visited set is far smaller than its peers. It
is listed in the per-seed table but excluded from union / core / frontier so it
does not drag those numbers down.

Usage:
    python tests/algo_validation/union_coverage.py FILE [FILE ...]
    python tests/algo_validation/union_coverage.py /tmp/sweep/visited_*.json
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from typing import Any

_SCHEMA = "evcs-visited-v1"
_DEGENERATE_FRACTION = 0.5  # |visited| < 0.5 * median(peers) → degenerate


def load_dump(path: str) -> dict[str, Any]:
    """Read one dump, validate its schema, return metadata + visited set."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema") != _SCHEMA:
        raise ValueError(
            f"{path}: bad schema {data.get('schema')!r} (expected {_SCHEMA!r})"
        )
    visited = {(int(o), str(L)) for o, L in data["visited"]}
    return {
        "path": path,
        "metadata": data.get("metadata", {}),
        "universe_size": int(data["universe_size"]),
        "visited": visited,
    }


def _mark_degenerate(dumps: list[dict[str, Any]]) -> None:
    """Flag dumps whose visited set is < 50% of the median of their peers."""
    for d in dumps:
        peers = [len(o["visited"]) for o in dumps if o is not d]
        if not peers:
            d["degenerate"] = False
            continue
        med = statistics.median(peers)
        d["degenerate"] = len(d["visited"]) < _DEGENERATE_FRACTION * med


def compute_union_stats(dumps: list[dict[str, Any]]) -> dict[str, Any]:
    universes = {d["universe_size"] for d in dumps}
    if len(universes) != 1:
        raise ValueError(f"inconsistent universe_size across files: {universes}")
    universe = universes.pop()

    _mark_degenerate(dumps)
    good = [d for d in dumps if not d["degenerate"]]
    good_sets = [d["visited"] for d in good]

    union: set = set().union(*good_sets) if good_sets else set()
    # Node -> number of non-degenerate seeds that visited it.
    freq: dict[tuple[int, str], int] = {}
    for s in good_sets:
        for node in s:
            freq[node] = freq.get(node, 0) + 1
    n_good = len(good)

    # Cumulative union (diminishing returns), in input order. Degenerate
    # seeds contribute 0.
    running: set = set()
    for d in dumps:
        before = len(running)
        if not d["degenerate"]:
            running |= d["visited"]
        d["new_to_union"] = len(running) - before
        d["cum_union"] = len(running)

    core = {n for n, c in freq.items() if c == n_good} if n_good else set()
    frontier = {n for n, c in freq.items() if c == 1}
    freq_threshold = max(2, n_good - 1)
    frequent = {n for n, c in freq.items() if c >= freq_threshold}

    return {
        "universe": universe,
        "dumps": dumps,
        "good": good,
        "n_good": n_good,
        "union": union,
        "core": core,
        "frequent": frequent,
        "frequent_threshold": freq_threshold,
        "frontier": frontier,
        "freq": freq,
        "still_unvisited": universe - len(union),
    }


def _occ_width(universe: int) -> int:
    # 766 = 1 empty + 255 occupancies x 3 SOC buckets -> occ in [0, 255] -> 8 bits.
    n_occ = (universe - 1) // 3
    return max(8, n_occ.bit_length())


def render_report(stats: dict[str, Any]) -> str:
    dumps = stats["dumps"]
    universe = stats["universe"]
    union = stats["union"]
    n_good = stats["n_good"]
    width = _occ_width(universe)
    degen = [d for d in dumps if d["degenerate"]]

    out: list[str] = []
    out.append("=== Cross-seed coverage union ===")
    degen_note = (
        f" ({len(degen)} degenerate: "
        + ", ".join(f"{d['path']} with visited={len(d['visited'])}" for d in degen)
        + ")"
        if degen else ""
    )
    out.append(f"Files:    {len(dumps)}{degen_note}")
    out.append(f"Universe: {universe} nodes")
    out.append("")
    out.append("Per-seed:")
    out.append(
        f"  {'file':<34} {'seed':>6} {'ε':>4} {'steps':>6} "
        f"{'termination':<14} {'visited':>10} {'new_to_union':>13}"
    )
    for d in dumps:
        m = d["metadata"]
        tag = "  (degenerate)" if d["degenerate"] else ""
        out.append(
            f"  {d['path']:<34} {m.get('seed', '?'):>6} "
            f"{m.get('epsilon', '?'):>4} {m.get('steps_run', '?'):>6} "
            f"{m.get('termination', '?'):<14} "
            f"{len(d['visited']):>6}/{universe:<3} {d['new_to_union']:>13}{tag}"
        )
    out.append("")
    pct = 100.0 * len(union) / universe
    out.append(
        f"Union:    {len(union)}/{universe} ({pct:.1f}%)"
        f"        (over {n_good} non-degenerate seed(s))"
    )
    out.append("")
    out.append(f"Overlap (over {n_good} non-degenerate seed(s)):")
    cu = len(union) or 1
    out.append(
        f"  Core (visited by all {n_good}):     {len(stats['core']):>4} "
        f"({100.0 * len(stats['core']) / cu:.0f}% of union)"
    )
    out.append(
        f"  Frequent (visited by ≥{stats['frequent_threshold']}):       "
        f"{len(stats['frequent']):>4}"
    )
    out.append(
        f"  Frontier (visited by 1 only):  {len(stats['frontier']):>4} "
        f"({100.0 * len(stats['frontier']) / cu:.0f}% of union)"
    )
    out.append(
        f"  Still unvisited by any seed:   {stats['still_unvisited']:>4} "
        f"({100.0 * stats['still_unvisited'] / universe:.1f}% of universe)"
    )
    out.append("")
    out.append("Diminishing returns (cumulative union after each seed):")
    for d in dumps:
        seed = d["metadata"].get("seed", "?")
        if d["degenerate"]:
            extra = "  (degenerate, +0)"
        else:
            extra = f"  (+{d['new_to_union']})"
        out.append(f"  +seed={seed:<8} → {d['cum_union']}{extra}")
    out.append("")

    # Top-10 frontier nodes (visited by exactly one non-degenerate seed).
    out.append("Top-10 frontier nodes (visited by exactly 1 seed):")
    seed_of_node: dict[tuple[int, str], Any] = {}
    for d in stats["good"]:
        for node in d["visited"]:
            if stats["freq"].get(node) == 1:
                seed_of_node[node] = d["metadata"].get("seed", "?")
    for node in sorted(stats["frontier"])[:10]:
        occ, L = node
        out.append(
            f"  occ={format(occ, f'0{width}b')}  L={L:<4}  only seed={seed_of_node.get(node, '?')}"
        )
    if not stats["frontier"]:
        out.append("  (none)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-seed coverage union (S5).")
    parser.add_argument("files", nargs="+", help="visited dump JSON files (globs ok)")
    args = parser.parse_args(argv)

    paths: list[str] = []
    for pattern in args.files:
        matched = glob.glob(pattern)
        paths.extend(matched if matched else [pattern])
    paths = sorted(dict.fromkeys(paths))  # de-dupe, stable

    if not paths:
        print("error: no input files", file=sys.stderr)
        return 2
    try:
        dumps = [load_dump(p) for p in paths]
        stats = compute_union_stats(dumps)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(render_report(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
