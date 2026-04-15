"""Interactive terminal prompt for simulation parameters (SPEC §18)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SimParams:
    arrival_order: str          # "seq" | "rand"
    interval_mode: str          # "fixed" | "rand"
    interval_min: int           # minutes
    interval_max: int           # minutes (== interval_min when fixed)
    soc_init_mode: str          # "fixed" | "rand"
    soc_init_lo: int
    soc_init_hi: int            # == lo when fixed
    soc_tgt_mode: str
    soc_tgt_lo: int
    soc_tgt_hi: int


def _ask_choice(label: str, options: tuple[str, ...]) -> str:
    opts_upper = tuple(o.upper() for o in options)
    while True:
        raw = input(label).strip().upper()
        if raw in opts_upper:
            return raw
        print(f"  ! please enter one of {'/'.join(opts_upper)}")


def _ask_int(label: str, lo: int, hi: int) -> int:
    while True:
        raw = input(label).strip()
        try:
            v = int(raw)
        except ValueError:
            print(f"  ! please enter an integer in {lo}..{hi}")
            continue
        if lo <= v <= hi:
            return v
        print(f"  ! value must be within {lo}..{hi}")


def prompt_params() -> SimParams:
    print("=== EVCS Simulation Parameter Setup ===\n")

    # Q1 arrival order
    print("[Q1] Vehicle arrival order at charging guns")
    print("  A) Sequential")
    print("  B) Random")
    q1 = _ask_choice("Select [A/B]: ", ("A", "B"))
    arrival_order = "seq" if q1 == "A" else "rand"

    # Q2 arrival interval
    print("\n[Q2] Vehicle arrival interval")
    print("  A) Fixed")
    print("  B) Random")
    q2 = _ask_choice("Select [A/B]: ", ("A", "B"))
    if q2 == "A":
        interval_mode = "fixed"
        v = _ask_int("  [Q2-1] Enter fixed interval (1~15 minutes): ", 1, 15)
        interval_min = interval_max = v
    else:
        interval_mode = "rand"
        interval_min = _ask_int(
            "  [Q2-1] Enter minimum interval (1~14 minutes): ", 1, 14
        )
        interval_max = _ask_int(
            f"  [Q2-2] Enter maximum interval ({interval_min+1}~15 minutes): ",
            interval_min + 1, 15,
        )

    # Q3 initial SOC
    print("\n[Q3] Vehicle initial SOC")
    print("  A) Fixed")
    print("  B) Random")
    q3 = _ask_choice("Select [A/B]: ", ("A", "B"))
    if q3 == "A":
        soc_init_mode = "fixed"
        v = _ask_int("  [Q3-1] Enter fixed initial SOC (10~89): ", 10, 89)
        soc_init_lo = soc_init_hi = v
    else:
        soc_init_mode = "rand"
        soc_init_lo = _ask_int(
            "  [Q3-1] Enter initial SOC lower bound (10~89): ", 10, 89
        )
        soc_init_hi = _ask_int(
            f"  [Q3-2] Enter initial SOC upper bound ({soc_init_lo+1}~90): ",
            soc_init_lo + 1, 90,
        )

    max_initial = soc_init_hi

    # Q4 target SOC
    print("\n[Q4] Vehicle target SOC")
    print("  A) Fixed")
    print("  B) Random")
    q4 = _ask_choice("Select [A/B]: ", ("A", "B"))
    if q4 == "A":
        soc_tgt_mode = "fixed"
        v = _ask_int(
            f"  [Q4-1] Enter fixed target SOC ({max_initial+1}~90): ",
            max_initial + 1, 90,
        )
        soc_tgt_lo = soc_tgt_hi = v
    else:
        soc_tgt_mode = "rand"
        soc_tgt_lo = _ask_int(
            f"  [Q4-1] Enter target SOC lower bound ({max_initial+1}~89): ",
            max_initial + 1, 89,
        )
        soc_tgt_hi = _ask_int(
            f"  [Q4-2] Enter target SOC upper bound ({soc_tgt_lo+1}~90): ",
            soc_tgt_lo + 1, 90,
        )

    return SimParams(
        arrival_order=arrival_order,
        interval_mode=interval_mode,
        interval_min=interval_min,
        interval_max=interval_max,
        soc_init_mode=soc_init_mode,
        soc_init_lo=soc_init_lo,
        soc_init_hi=soc_init_hi,
        soc_tgt_mode=soc_tgt_mode,
        soc_tgt_lo=soc_tgt_lo,
        soc_tgt_hi=soc_tgt_hi,
    )


def _fmt_range(mode: str, lo: int, hi: int, unit: str = "") -> str:
    suffix = f" {unit}" if unit else ""
    if mode == "fixed" or mode == "seq":
        return f"Fixed {lo}{suffix}" if unit else f"Fixed {lo}"
    return f"Random {lo}~{hi}{suffix}" if unit else f"Random {lo}~{hi}"


def print_summary(p: SimParams) -> None:
    print("\n=== Parameter Summary ===")
    print(f"Arrival order  : {'Sequential' if p.arrival_order == 'seq' else 'Random'}")
    if p.interval_mode == "fixed":
        print(f"Arrival interval: Fixed {p.interval_min} min")
    else:
        print(f"Arrival interval: Random {p.interval_min}~{p.interval_max} min")
    if p.soc_init_mode == "fixed":
        print(f"Initial SOC    : Fixed {p.soc_init_lo}")
    else:
        print(f"Initial SOC    : Random {p.soc_init_lo}~{p.soc_init_hi}")
    if p.soc_tgt_mode == "fixed":
        print(f"Target SOC     : Fixed {p.soc_tgt_lo}")
    else:
        print(f"Target SOC     : Random {p.soc_tgt_lo}~{p.soc_tgt_hi}")


def confirm() -> bool:
    ans = _ask_choice("\nConfirm and run? [Y/N]: ", ("Y", "N"))
    return ans == "Y"


def prompt_until_confirmed() -> SimParams:
    while True:
        p = prompt_params()
        print_summary(p)
        if confirm():
            return p
        print("\n-- Re-entering parameters --\n")
