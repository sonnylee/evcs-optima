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

> No build/test/lint commands are configured yet — this project is in the implementation phase. Add commands here as they are established.

## Planned Directory Structure

```
simulation/
├── environment/       # SimulationEngine, TimeController, VisionOutput
├── modules/           # Vehicle, TrafficSimulator, MCUControl, VehicleGenerator
├── hardware/          # ChargingStation, RectifierBoard, SMRGroup, SMR, Relay, Output
├── data/              # RelayMatrix, ModuleAssignment
├── communication/     # BorrowProtocol, ReturnProtocol
├── log/               # RelayEvent, RelayEventLog
└── utils/             # Validator, ConfigLoader
```

## Architecture

### Two-Layer Design

**Layer 1 — Simulation Environment** (no business logic):
- `SimulationEngine`: Main loop driver. Advances time by `dt` each step and calls `step(dt)` on all modules.
- `TimeController`: Heartbeat generator. Time advancement is the *only* driver — no external events bypass it.
- `VisionOutput`: Collects `get_status()` snapshots, runs consistency validation, then emits Timing Diagrams. Blocks output if validation fails.

**Layer 2 — Simulation Modules** (all equal, no hierarchy):
All modules receive `step(dt)` and return `get_status()`. No central coordinator.

| Module | Role |
|---|---|
| `Vehicle` | Holds SOC curve, updates SOC each dt, negotiates Present Power with MCU |
| `TrafficSimulator` | Generates Vehicle instances at configurable arrival rates and routes them to Outputs |
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

- Each MCU: 4 SMR Groups (50/75/75/50 kW), 2 Outputs, Bridge Relays at MCU boundaries
- MCU2 = Local view; MCU1 and MCU3 = neighbors
- Discrete power levels per MCU: 50 / 125 / 200 / 250 kW
- Minimum guaranteed power to start charging: 125 kW

### Core Data Structures

**Relay Matrix** (18×18 symmetric, 3-MCU): Defines physically legal connections.
- `0` = relay open, `1` = relay closed, `-1` = no physical wire (forever illegal)

**Module Assignment** (Outputs × Groups): Tracks which Output owns which Groups.
- `0` = idle, `1` = in use, `-1` = cannot be assigned to this Output
- All Groups assigned to one Output must form a **contiguous interval** — no gaps.

### Key Business Logic Rules

- **Borrow trigger**: `Present Power == Available Power` for N consecutive steps → expand [MIN, MAX] interval by one Group
- **Return trigger**: `Available Power - Present Power >= 1 Group` for N steps → shrink interval from outside in
- **Borrow priority**: right neighbor > left neighbor > both sides
- **Return order**: always return cross-MCU Groups first, local Groups last; anchor Group is touched last
- **Conflict on new vehicle arrival**: detect via Module Assignment scan; notify borrowing Output to release conflicting Groups
- **Ring addressing**: `prev = (self_idx - 1 + N) % N`, `next = (self_idx + 1 + N) % N`

### Critical Constraints

| Constraint | Detail |
|---|---|
| DC Relay no hot-switching | Current must drop below 5A before any relay state change |
| Atomic relay events | Only `SWITCHED` state — no `COMMAND_ISSUED` or `FAILED` intermediates |
| Contiguous interval | All Groups for one Output must form an unbroken [MIN, MAX] range |
| Local-first | Use local MCU resources before borrowing from neighbors |
| `is_cross_mcu` | This is a Relay attribute — never compute it dynamically or pass it in messages |

## Recommended Implementation Order

1. **Phase 1**: `Vehicle`, `Output`, `ChargingStation` (no borrowing)
2. **Phase 2**: `Relay` + `RelayEventLog`, `ModuleAssignment`
3. **Phase 3**: `MCUControl` (single MCU)
4. **Phase 4**: Multi-MCU + Borrow/Return protocols
5. **Phase 5**: `Validator` + Visualization (Timing Diagrams)

## Recommended Architecture

Use **asyncio + Queue (Actor Model)** — each entity (EV, Output, MCU) has its own `asyncio.Queue` and processes messages independently. See SPEC.md §14 for skeleton code.

Use **TinyDB (in-memory)** with JSON to store simulation state snapshots.
