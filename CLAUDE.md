# CLAUDE.md

We're building the evcs simulation engine described in @SPEC.md. Read that file for general architectural tasks.

Keep your replies extremely concise and focus on conveying the key information. No unmecessary fluff, no long code snippets.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**EVCS Optima** (智慧充電站電力管理系統) is a Python-based Electric Vehicle Charging Station (EVCS) power management simulation engine. It visualizes relay state transitions via Timing Diagrams across multi-MCU ring topologies. The core algorithms are designed to be portable to embedded C for real MCU hardware deployment.

The authoritative specification is `SPEC.md` (Traditional Chinese). Read it first when beginning any implementation work.

## Key Specs (load on demand)
- Web & API service: @docs/SPEC-WEB-API.md
- Full spec reference: @docs/SPEC.md

## Setup

```bash
pip install -r requirements.txt
```

Reference EV profile for development/validation: **2024 Tesla Cybertruck Cyberbeast** (325 kW peak). Charging curve data: `associate/ev_curve_data.csv` (SPEC §15).

Interactive runtime parameter setup follows SPEC §18 (`simulation/utils/interactive_prompt.py`): number of MCUs (1–12), arrival order (sequential / random), arrival interval (fixed 1–15 min or random range), initial SOC (10–89, or range up to 90), target SOC (up to 90).

## Directory Structure

```
simulation/
├── environment/       # SimulationEngine, TimeController, VisionOutput, Actor (SPEC §14 base)
├── modules/           # Vehicle, TrafficSimulator, MCUControl, VehicleGenerator
├── hardware/          # ChargingStation, RectifierBoard, SMRGroup, SMR, Relay, Output
├── data/              # RelayMatrix, ModuleAssignment
├── communication/     # BorrowProtocol, ReturnProtocol, messages
├── log/               # RelayEvent, RelayEventLog
└── utils/             # ConfigLoader, validator, topology, interactive_prompt, schedule_builder

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
| `TrafficSimulator` | Decides *whether* to spawn a vehicle each step (arrival rate) and routes it to an Output; does not intervene after connection |
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
- **Topology rules (SPEC §2.2)**: `N == 1` → single MCU, no Bridge Relay; `N == 2` → linear, one bridge (MCU1↔MCU2); `N >= 3` → ring (head↔tail close the loop)
- Stage-1 target is the **4-MCU ring** (MCU1↔MCU2↔MCU3↔MCU4↔MCU1); stage-2 scales to 1–12 MCUs (SPEC §2.2)

### Core Data Structures

**Per-MCU ownership (SPEC §10)**: each MCU holds its **own** `RelayMatrix` and `ModuleAssignment` instance — they are *not* shared global structures. Cross-MCU consistency comes from protocol exchange (SPEC §6.3, §7), not from a shared table.

**Relay Matrix** (18×18 symmetric in the 3-MCU dev view): Defines physically legal connections.
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
| Relay ownership | Relay switching may be executed **only by the owning (local) MCU** — no external MCU may invoke another MCU's relays. Cross-MCU effects must go through borrow/return protocol messages (SPEC §6, §10, §11). |
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

Trace output must match the **CSV format** defined in SPEC §17. Columns: `Step | Time | Event | Outputs Ops | Relays Ops | [per MCU: O1, O2, R1–R4, per-EV Available Power / Max Require Power]`. Per-MCU relay columns: **R1 = left bridge** (= previous MCU's right bridge), **R2/R3/R4 = inter-group relays** (G0-G1 / G1-G2 / G2-G3) — see `simulation/environment/vision_output.py::_build_relay_labels`. Boundary-consistency logs land alongside the CSV as `*_boundary.jsonl`. Note: code currently also emits an extra `SOC` column per EV that SPEC §17 does not list — keep this in mind when comparing.

## Recommended Architecture

Recommended (optional, per SPEC §14): **asyncio + Queue (Actor Model)** — each entity (EV, Output, MCU) has its own `asyncio.Queue` and processes messages independently. Use **TinyDB (in-memory)** with JSON to store simulation state snapshots. Keep this stack in mind from Phase 1 onward.

## Testing

See `associate/TEST-SPEC.md` for the full test specification (SPEC §19).

## Web & API Layer (planned — full spec: docs/SPEC-WEB-API.md)

Three-tier architecture wrapping the existing Python simulation core. **Neither `services/evcs-api/` nor `web/evcs-ui/` exists in the repo yet** — when implementing, create these trees (layout below is prescriptive, per SPEC-WEB-API §5).

1. **Bun Web UI** (`web/evcs-ui/`, React + TypeScript) — MCU topology view, config panel, Car Port input panel, step player. Entry points: `src/api/evcsApiClient.ts`, `src/stores/evcsStore.ts`, `src/components/{topology, config-panel, car-port-panel, step-player}/`.
2. **FastAPI Service** (`services/evcs-api/`) — REST facade + validation + session store + core adapter. Routes under `app/api/v1/`: `health`, `constants`, `sessions`, `validation`, `snapshot`, `control_steps`. Pydantic schemas in `app/schemas/`; core integration in `app/adapters/evcs_core_adapter.py`.
3. **Python Core** (existing `simulation/`) — unchanged. The FastAPI adapter translates Web Input → Core Input and Core Output → API Step Sequence.

### Domain terms (SPEC-WEB-API §3.1)

| Term | Meaning |
|---|---|
| **Max Required** | EV-declared per-port power ceiling. 0~600 kW, 25 kW steps. |
| **Present** | Current actual output per port — *starting point* for step generation. |
| **Target** | Desired output per port — *endpoint*. `Apply and Generate` diffs Present→Target into a control-step sequence. |

### Functional requirements at a glance (FR-01…FR-16)

- **Display (FR-01…06)**: REC BD color ID + live kW, 25 kW pack coloring matches owning REC BD, relay closed=red / open=white, car icon blue=charging / gray=idle, per-port Max Required label.
- **Interaction (FR-07, 12…15)**: ±25 kW buttons, manual Max Required / Present / Target input (with validation + 25 kW rounding), Apply-and-Generate, forward/back step player (wraps at ends).
- **Configuration (FR-10, 11, 16)**: REC BD count 1~12 (default 4, each → 2 Car Ports), per-REC-BD module-power list like `"50,75,75,50"` (each value a 25 kW multiple, 50~100 kW), per-Car-Port unique priority 1..N where N = 2 × REC BD count.
- **Logic / Behavior (FR-08, 09)**: 0~600 kW hard clamp in 25 kW steps, instant global recompute of REC BD / pack / relay / car / Max Required visuals on any change.

### Development phases (SPEC-WEB-API §4)

1. **FastAPI Foundation** — project skeleton, `/health` `/constants` `/palette`, Pydantic schemas, validation service, session store.
2. **Topology & Visual Snapshot API** — REC BD / 25 kW Pack / Relay / Car snapshot, priority validation. Exit: any Max Required change returns a complete `VisualSnapshot`.
3. **Python Core Adapter** — `EvcsCoreAdapter` maps Present→Target to step sequence; unreasonable-Present warning; Target-over-capacity check.
4. **Bun/React UI** — topology view, config panel, car-port input panel, Apply-and-Generate flow, step player, error display.

### Behavior that is load-bearing for the core adapter

- Control steps must obey the existing hardware constraints (SPEC §11): ≥125 kW before closing Output relay, Output relay stays Closed mid-charge, inter-Group / bridge relays close before Output on arrival and open before Output on departure. The adapter cannot bypass these — they are enforced by the core `MCUControl`.
- Priority (FR-16) replaces the default top-down Car-ID allocation order; the adapter must feed it into the allocation strategy, not just record it.
