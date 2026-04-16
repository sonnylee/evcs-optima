# CLAUDE.md

We're building the evcs simulation engine described in @SPEC.md. Read that file for general architectural tasks.

Keep your replies extremely concise and focus on conveying the key information. No unmecessary fluff, no long code snippets.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**EVCS Optima** (智慧充電站電力管理系統) is a Python-based Electric Vehicle Charging Station (EVCS) power management simulation engine. It visualizes relay state transitions via Timing Diagrams across multi-MCU ring topologies. The core algorithms are designed to be portable to embedded C for real MCU hardware deployment.

The authoritative specification is `SPEC.md` (Traditional Chinese). Read it first when beginning any implementation work.

## Setup

```bash
pip install -r requirements.txt
```

The devcontainer is Node.js 20 + Python. `ANTHROPIC_API_KEY` is required as a devcontainer secret.

End-to-end check (all 14 scenarios, 4-MCU ring):

```bash
python3 demo_phase5.py   # writes CSV + boundary JSONL under associate/verify/scenarios/
```

> No formal lint/test suite yet. `demo_phase5.py` is the de-facto regression harness — expect every scenario to report `inconsistent=0  violations=0`.

Reference EV profile for development/validation: **2024 Tesla Cybertruck Cyberbeast** (325 kW peak). Charging curve data: `associate/ev_curve_data.csv` (SPEC §15).

Interactive runtime parameter setup follows SPEC §18 (`simulation/utils/interactive_prompt.py`): arrival order (sequential / random), arrival interval (fixed 1–15 min or random range), initial SOC (10–89, or range up to 90), target SOC (up to 90).

## Directory Structure

```
simulation/
├── environment/       # SimulationEngine, TimeController, VisionOutput
├── modules/           # Vehicle, TrafficSimulator, MCUControl, VehicleGenerator
├── hardware/          # ChargingStation, RectifierBoard, SMRGroup, SMR, Relay, Output
├── data/              # RelayMatrix, ModuleAssignment
├── communication/     # BorrowProtocol, ReturnProtocol
├── log/               # RelayEvent, RelayEventLog
└── utils/             # ConfigLoader, interactive_prompt, schedule_builder

associate/             # Reference data (ev_curve_data.csv — Tesla Cybertruck curve)
associate/verify/      # Regression artifacts — per-scenario CSV + boundary JSONL
demo_phase*.py         # Phase-by-phase demo runners (Phase 5 is the 14-scenario harness)
```

## Architecture

### Two-Layer Design

**Layer 1 — Simulation Environment** (no business logic):
- `SimulationEngine`: Main loop driver. Advances time by `dt` each step and calls `step(dt)` on all modules.
- `TimeController`: Heartbeat generator. Time advancement is the *only* driver — no external events bypass it.
- `VisionOutput`: Collects `get_status()` snapshots, runs the boundary-consistency check defined in SPEC §9 (compares `allocated_power` and `relay_state` across adjacent MCUs), then emits Timing Diagrams. Blocks output if validation fails. Log schema: JSON with a `conflicts[]` array; each entry is `{group, output, field, values: [mcu_a_val, mcu_b_val]}`.

**Layer 2 — Simulation Modules** (all equal, no hierarchy):
All modules receive `step(dt)` and return `get_status()`. No central coordinator.

| Module | Role |
|---|---|
| `Vehicle` | Holds SOC curve, updates SOC each dt, negotiates Present Power with MCU |
| `TrafficSimulator` | Decides *whether* to spawn a vehicle each step (arrival rate) and routes it to an Output |
| `VehicleGenerator` | Instantiates `Vehicle` objects from `vehicle_profiles`; called by `TrafficSimulator` |
| `MCUControl` | Business logic core — borrow/return power decisions, relay switching commands |
| `ChargingStation` | Global container (shell only, no logic) |
| `RectifierBoard` | Hardware abstraction for SMR groups + relays + outputs (state, no behavior) |
| `SMRGroup` | Manages N × 25kW SMR modules |
| `Relay` | Two types: (1) Output power-flow switch; (2) inter-Group series/disconnect |
| `RelayEventLog` | Singleton injected into all Relays at construction; records every `SWITCHED` event |
| `Output` | Charging gun endpoint |

### Hardware Topology (3-MCU reference)

```
O1   O2       O3   O4       O5   O6
 |    |        |    |        |    |
G1-R2-G2-R3-G3-R4-G4-R5-G5-R6-G6-R7-G7-R8-G8-R9-G9-R10-G10-R11-G11-R12-G12
|--- 50  75  75  50 ---|--- 50  75  75  50 ---|--- 50   75   75   50 ---|
       MCU1                   MCU2                     MCU3
```

- Each MCU: 4 SMR Groups (50/75/75/50 kW), 2 Outputs (O1↔G1, O2↔G4), Bridge Relays at MCU boundaries
- **Bridge Relays** (cross-MCU boundary): `R1`, `R5`, `R9` (SPEC §2.2)
- MCU2 = Local view; MCU1 and MCU3 = neighbors
- Discrete power levels per MCU: 50 / 125 / 200 / 250 kW
- Minimum guaranteed power to start charging: 125 kW
- Stage-1 target is the **4-MCU ring** (MCU1↔MCU2↔MCU3↔MCU4↔MCU1); stage-2 scales to 1–12 MCUs (SPEC §2.2)

### Core Data Structures

**Relay Matrix** (18×18 symmetric, 3-MCU): Defines physically legal connections.
- `0` = relay open, `1` = relay closed, `-1` = no physical wire (forever illegal)
- Node indices: Groups occupy `0–11`, Outputs occupy `12–17`.
- Per-MCU view: `LOCAL = 1`, neighbors `= 0, 2` (SPEC §5.1).

**Module Assignment** (Outputs × Groups): Tracks which Output owns which Groups.
- `0` = idle, `1` = in use, `-1` = cannot be assigned to this Output
- All Groups assigned to one Output must form a **contiguous interval** — no gaps.
- Index conversion: `mcu_idx = Gx // 4`, `pos_in_mcu = Gx % 4` (SPEC §5.2, §7.1).

**Anchor Point (錨點)**: the fixed Group each Output is wired to via the Relay Matrix. It is the starting point for all borrow/return logic and is always touched **last** on return.

### Key Business Logic Rules

- **Local vs Absolute coordinates (SPEC §6 preamble)** — each MCU is autonomous and talks to others only via protocol. Group-increment/decrement is always reasoned in **local (relative) coordinates** where MCU1 = self, MCU0 = left neighbor, MCU2 = right neighbor. When the decision needs to cross a boundary, the relative index is converted to an **absolute** one (e.g. in a 4-MCU ring, self=MCU1 → left=MCU4, right=MCU2), and all protocol payloads carry **absolute** indices. This is what keeps the code MCU-count-agnostic (1–12 supported) without conditional branches.
- **Borrow trigger**: `Present Power == Available Power` for N consecutive steps.
- **Borrow steps (SPEC §6.1)**: 1) find anchor via Relay Matrix → 2) determine initial `[MIN, MAX]` around anchor → 3) expand **local-first** — never cross an MCU boundary while local Groups remain → 4) when local is exhausted, cross using the SPEC §2.2 priority: **right neighbor > left neighbor > both sides**.
- **Return trigger**: `Available Power - Present Power >= 1 Group` for N consecutive steps.
- **Return steps (SPEC §6.2)** — 4-case decision:
  1. Both MIN and MAX external → shrink from MIN (MIN→right).
  2. Only MIN external → shrink from MIN.
  3. Only MAX external → shrink from MAX (MAX→left).
  4. Both local → if MIN is the anchor shrink from MAX, else from MIN.
  Anchor Group is always touched last.
- **Conflict protocol (SPEC §6.3)** — two sides:
  - *Initiator* (new vehicle arrives): find anchor → determine initial interval → scan Module Assignment for occupied Groups → notify the holder to release.
  - *Responder* (receives release notice for `Gx`): find own anchor → if `anchor < Gx` return from MAX end, if `anchor > Gx` return from MIN end → switch relays.
- **Ring addressing (SPEC §7.1)**: `prev = (self_idx - 1 + N) % N`, `next = (self_idx + 1 + N) % N`. The `+N` form is defensive for C-portability (avoids negative-modulo behavior); each MCU only needs its own index. Hardware lives on a CAN bus (SPEC §7.2) — the formula maps directly to neighbor CAN IDs.
- **Ring-wrap borrow (N ≥ 3)**: in ring topology, borrow may cross the wrap seam — e.g. on a 4-MCU ring, M1.O1 (anchor G0) extending left reaches M4.G3 via M1.R1 (the M4↔M1 bridge). Internally `MCUControl` uses "virtual" group indices that may go below 0 or beyond `4N − 1`; `_wrap(g) = g mod (4N)` maps them back to physical groups (see `simulation/modules/mcu_control.py`). Linear topologies (N ≤ 2) skip wrapping.

### Critical Constraints

| Constraint | Detail |
|---|---|
| Atomic relay events | Only `SWITCHED` state — no `COMMAND_ISSUED` or `FAILED` intermediates |
| Contiguous interval | All Groups for one Output must form an unbroken [MIN, MAX] range |
| Local-first | Use local MCU resources before borrowing from neighbors |
| Output relay close timing | Output relay may close only after ≥125kW is prepared for the EV (SPEC §11) |
| Output relay open guard | Output relay must stay Closed while the EV has not yet met its charging requirement — it cannot be opened mid-charge (SPEC §11) |
| EV arrival relay sequence | On arrival/borrow: close inter-Group / bridge relays first, then close Output |
| EV departure relay sequence | On departure (after EV meets requirement): open inter-Group / bridge relays first, then open Output (SPEC §11) |

## Recommended Implementation Order

1. **Phase 1**: `Vehicle`, `Output`, `ChargingStation` (no borrowing)
2. **Phase 2**: `Relay` + `RelayEventLog`, `ModuleAssignment`
3. **Phase 3**: `MCUControl` (single MCU)
4. **Phase 4**: Multi-MCU + Borrow/Return protocols
5. **Phase 5**: `Validator` + Visualization (Timing Diagrams)

## Validation

Acceptance target is the **14-scenario test matrix** in SPEC §16 (combinations of active Outputs across MCUs). Notation `(a,b,c)` = count of MCUs with 0 / 1 / 2 active Outputs respectively across the 4-MCU matrix.

Trace output must match the **CSV format** defined in SPEC §17. Columns: `Step | Time | Event | Outputs Ops | Relays Ops | [per MCU: O1, O2, R1–R4, per-EV Available Power / Max Require Power / SOC]`. Per-MCU relay columns: **R1 = left bridge** (= previous MCU's right bridge), **R2/R3/R4 = inter-group relays** (G0-G1 / G1-G2 / G2-G3) — see `simulation/environment/vision_output.py::_build_relay_labels`. Boundary-consistency logs land alongside the CSV as `*_boundary.jsonl`.

## Recommended Architecture

Recommended (optional, per SPEC §14): **asyncio + Queue (Actor Model)** — each entity (EV, Output, MCU) has its own `asyncio.Queue` and processes messages independently. Use **TinyDB (in-memory)** with JSON to store simulation state snapshots. Keep this stack in mind from Phase 1 onward.
