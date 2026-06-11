# Scheduler Core Concept — Read-Only Spike Report

> Read-only spike for the manager report (slide 6). No production or test code was
> modified. Source of truth: `tests/algo_validation/helpers/arrival_scheduler.py`
> plus its call site in `tests/algo_validation/test_exploration.py` and fixtures in
> `tests/algo_validation/conftest.py`.

## TL;DR (slide 6 speaker notes)

The scheduler is **not** a coverage-score argmax. Each tick it reads the current
occupancy bitmask, enumerates every `(empty output × SOC level)` candidate, **keeps
only the candidates that would land on an as-yet-unvisited coverage node**, and then
picks **uniformly at random** from that unvisited pool (seeded RNG, for
reproducibility). So it is a *coverage filter + random pick*, not a "maximize a
coverage score" optimizer. The optional ε-greedy branch (S4, off by default,
`EVCS_EPSILON=0.2` to enable) replaces that filtered pick with a fully random legal
arrival to escape local optima. The "greedy is budget-optimal at 4000 steps" line in
the draft is **not supported by the repo docs** — they say the opposite: pure greedy
*stalls* in a local optimum (binding limiter is stagnation, not the step budget).

## Section A — What greedy actually does (code-grounded)

### Function signature

Arrival event object (`Arrive`, frozen dataclass, lines 24-27):

```python
24	@dataclass(frozen=True)
25	class Arrive:
26	    output_idx: int
27	    soc_level: str
```

Class + constructor (`ArrivalScheduler`, lines 30-37):

```python
31	    def __init__(
32	        self,
33	        num_outputs: int = 8,
34	        seed: int = 12345,
35	        idle_every: int = 5,
36	        epsilon: float = 0.0,
37	    ) -> None:
```

Main entry point (line 60), returns `Optional[Arrive]`:

```python
60	    def choose(self, occupancy: int, tracker) -> Optional[Arrive]:
```

### Candidate set

- **Schema** of an arrival: `output_idx: int` (an unoccupied output index in
  `[0, num_outputs)`, default 8) and `soc_level: str` ∈ `_SOC_LEVELS = ("low", "mid",
  "high")` (line 21). Demand / `max_kw` is *not* part of the node key — it is set
  downstream by the harness.
- **Legal conditions** gating an arrival:
  1. Output must be unoccupied (bit `i` clear in the `occupancy` bitmask):
     ```python
     72	        empty = [i for i in range(self.num_outputs) if not (occupancy >> i) & 1]
     73	        if not empty:
     74	            return None  # station full → idle, wait for a departure
     ```
  2. Periodic settle beat — every `idle_every` successful arrivals, deliberately skip one:
     ```python
     77	        if self._since_idle >= self.idle_every:
     78	            self._since_idle = 0
     79	            return None
     ```
  3. Coverage preference — prefer `(output, SOC)` pairs reaching an unvisited node:
     ```python
     86	                if (new_occ, lvl) not in tracker.visited_nodes:
     87	                    unvisited.append(Arrive(i, lvl))
     ```
- **Generation strategy:** the greedy `choose` path is **enumerate-all-then-sample-one**
  — it builds the full cross-product of every empty output × every SOC level, filters
  to unvisited, then samples one. (The ε-branch helper `_random_legal_arrival` is
  **sample-one**: one random unoccupied output × one random SOC.)

### Decision rule (verbatim code + prose)

The full greedy block (`choose`, lines 72-93 — everything after the ε short-circuit at
lines 67-70):

```python
72	        empty = [i for i in range(self.num_outputs) if not (occupancy >> i) & 1]
73	        if not empty:
74	            return None  # station full → idle, wait for a departure
75	
76	        # Periodic settle beat (D-11): every K successful arrivals, skip one.
77	        if self._since_idle >= self.idle_every:
78	            self._since_idle = 0
79	            return None
80	
81	        # Greedy: prefer (output, SOC) that lands on an as-yet-unvisited node.
82	        unvisited: list[Arrive] = []
83	        for i in empty:
84	            for lvl in _SOC_LEVELS:
85	                new_occ = occupancy | (1 << i)
86	                if (new_occ, lvl) not in tracker.visited_nodes:
87	                    unvisited.append(Arrive(i, lvl))
88	        pool = unvisited if unvisited else [
89	            Arrive(i, lvl) for i in empty for lvl in _SOC_LEVELS
90	        ]
91	        choice = self._rng.choice(pool)
92	        self._since_idle += 1
93	        return choice
```

**Inputs read:** `occupancy` (bitmask of busy outputs), `self.num_outputs`,
`self._since_idle` / `self.idle_every` (settle-beat counter), `tracker.visited_nodes`
(coverage tracker's set of seen `(occupancy, soc_level)` keys), `_SOC_LEVELS`, and
`self._rng` (used only for the final tie-break pick).

**Prose:** compute the empty outputs; if none, idle. Honor the periodic settle beat
(return `None` every `idle_every` arrivals). Otherwise enumerate every
`(empty output, SOC level)` pair, form its resulting node key `(occupancy | (1<<i),
lvl)`, and keep only those **not** already in `tracker.visited_nodes`. If any unvisited
candidate exists, the pool is those; else the pool is all legal pairs. Finally pick
**uniformly at random** from the pool via the seeded RNG, bump the settle counter, and
return that `Arrive`.

**Category: (D) Other — coverage *filter* + uniform random pick.**
It *does* query visited-state data (unlike B, priority-sorted first-legal), but it
computes **no per-candidate score and takes no max** (unlike A, coverage-driven
argmax), and does **no next-step probability lookahead** (unlike C, novelty/lookahead).
It partitions candidates into unvisited vs. visited and random-picks from the unvisited
subset.

## Section B — What ε-greedy does

### When activated

- ε is the constructor parameter `epsilon` (line 36, default `0.0`).
- Its real value is fed from `conftest.py`, which reads the env var **`EVCS_EPSILON`**:
  ```python
  conftest.py:19	EPSILON = float(os.environ.get("EVCS_EPSILON", "0.0"))
  conftest.py:33	    return ArrivalScheduler(num_outputs=NUM_MCUS * 2, seed=SEED, epsilon=EPSILON)
  ```
- Default `0.0` ⇒ pure greedy. Opt in with `EVCS_EPSILON=0.2`. Per
  `conftest.py:17-18`, `ε=0.0` is documented as **byte-identical to the pre-S4 greedy
  behaviour** (a regression safety net).
- **RNG source:** a self-owned `random.Random(seed)` (Python stdlib, *not* numpy):
  ```python
  arrival_scheduler.py:43	        self._rng = random.Random(seed)
  conftest.py:16	SEED = int(os.environ.get("EVCS_SEED", "12345"))
  ```

### Branch logic

When enabled, with probability ε the scheduler short-circuits the greedy block and
returns a fully random legal arrival via `_random_legal_arrival` (which applies only
the "output must be unoccupied" filter — SOC is unconstrained), to break out of greedy
local optima (stagnation). With probability `1 − ε` it runs the Section A greedy block.
The trigger is at lines 67-70 (`if self.epsilon > 0.0 and self._rng.random() <
self.epsilon: ... return self._random_legal_arrival(occupancy)`).

## Section C — Call site (when scheduler is invoked)

There is **no** `exploration_driver.py`; the tick loop lives in
`tests/algo_validation/test_exploration.py`.

**Call graph:**

```
main loop (while not should_terminate())
  └─ occ, _ = read_state_from_snapshot(engine)      # occupancy bitmask from live snapshot
  └─ action = scheduler.choose(occ, tracker)        # Arrive | None  ← scheduler invoked here
       └─ if action: inject_arrive(engine, action.output_idx, action.soc_level, max_kw=...)
            └─ output.connect_vehicle / engine.vehicles.append / mcu.handle_vehicle_arrival
  └─ for _ in range(_SETTLE_BUDGET): driver.tick()  # advance engine until quiescent
```

The scheduler is called **once per outer main-loop iteration, before the settle/tick
burst** — not inside `tick()`.

**Scheduler call site** (`test_exploration.py:92-105`):

```python
        while not should_terminate():
            occ, _ = read_state_from_snapshot(engine)
            action = scheduler.choose(occ, tracker)
            if action is not None:
                max_kw = (
                    _LOW_DEMAND_KW if arrival_count % _LOW_DEMAND_EVERY == 0
                    else _HIGH_DEMAND_KW
                )
                arrival_count += 1
                inject_arrive(
                    engine, action.output_idx, action.soc_level,
                    max_kw=max_kw, battery_kwh=_EXPLORE_BATTERY_KWH,
                )
                tracker.note_arrival(action.soc_level)
```

**`_MAX_STEPS`** — definition (`test_exploration.py:40`):

```python
_MAX_STEPS = 4000
```

Check site, inside `should_terminate()` (`test_exploration.py:77-78`):

```python
        tc = engine.time_controller
        if tc.step_index >= _MAX_STEPS:
            return True
```

**Termination conditions** (loop ends on any of):
1. `tc.step_index >= _MAX_STEPS` (max_steps = 4000 — the CI budget).
2. `tracker.node_fraction() >= _COVERAGE_TARGET` (coverage ≥ 60%).
3. `tracker.stagnation(tc.step_index) >= _STAGNATION` (stagnation ≥ 500 steps since
   last new visit) — **a stagnation-based termination exists**, keyed on steps-since-
   last-new-visit, not a raw consecutive-tick counter.
4. `driver.is_finished()` (sim clock exhausted or all charging complete).

## Section D — Why greedy is "budget-optimal" at `_MAX_STEPS=4000`

⚠ **Stop-and-report finding: the "budget-optimal" claim is NOT supported by the repo.**

The draft assertion — *"under `_MAX_STEPS=4000`, greedy is already budget-optimal, and
ε=0.2 lowered a single seed from 263 to 259"* — has no documentary basis, and the docs
that exist argue the **opposite**:

- **263** is the ε=0.0 regression *baseline*, not an optimum.
  `docs/algo_validation/STEP_S4_EPSILON_GREEDY_MULTISEED_INSTRUCTIONS.md:99`:
  > "比對 §11 報告:**steps=4007、seed=12345、epsilon=0.0、coverage=263/766、N=63
  > ticks/55 states、relay_events=1672**(對應 F1 commit `7ac4599` 之後、
  > `_MAX_STEPS=4000` 設定的紀錄)"

- **259** is merely *one per-seed ε=0.2 observation* in an S5 sweep, never compared to
  263 as a "lowering". `docs/algo_validation/STEP_S5_CROSS_SEED_UNION_INSTRUCTIONS.md:3`:
  > "手動 5-seed sweep 看到 visited 數字分別是 261 / 22 / 255 / 259 / 259——這些是
  > **局部觀察**"
  Same sweep table (`STEP_S5_...:116-117`) shows `259/766` for seeds 12345 and 67890
  under ε=0.2 — union (not single-seed) is the intended success metric.

- The docs frame the **step budget as non-binding**: pure greedy stalls in a local
  optimum and the binding limiter is **stagnation ≥ 500**, with unvisited states all
  Hamming-distance 0/1 away (`STEP_S4_...:3`). ε=0.2 is introduced precisely to *raise*
  coverage ("同 seed 預期覆蓋拉到 50%+", line 6), i.e. ε is expected to **increase**,
  not lower, coverage.

- **"byte-identical at ε=0.0"** is real and sourced — `conftest.py:17-18`:
  > "ε-greedy exploration rate (S4). Default 0.0 = pure greedy = byte-identical to /
  > pre-S4 behaviour (regression safety net); opt in with EVCS_EPSILON=0.2."
  and `STEP_S4_...:74`: "**Greedy 路徑不動**:確保 `epsilon=0.0` 時整支函式行為
  byte-identical 於本任務前".

**Gaps (no evidence found):** (a) "greedy is budget-optimal" — none; docs treat greedy
as stuck in a local optimum. (b) "ε=0.2 lowered a seed 263→259" — none; 263 is the ε=0.0
baseline, 259 is an ε=0.2 per-seed datum, never juxtaposed as a causal lowering. (c) a
quantified budget-vs-ε threshold ("below N greedy wins, above N ε wins") — none.

## Section E — Implications for slide 6 wording

### Current draft (demo draft original):
> Scheduler 是 greedy:每次選 arrival 挑「最大化覆蓋分數」的選項

### Verdict
- [ ] Accurate — keep as-is
- [x] **Inaccurate — needs rewriting**
- [ ] Partially accurate — main conclusion right but mechanism wrong

Reason: the scheduler does **not** "maximize a coverage score" (no per-candidate score,
no argmax). It **filters** candidates to those landing on an *unvisited* coverage node,
then picks **uniformly at random** among them (seeded). "Greedy" in the sense of
*coverage-preferring* is defensible; "挑最大化覆蓋分數的選項" (pick the max-score option)
is not — category (D), not (A).

### Proposed alternative wording

**Option 1 (precise, recommended):**
> Scheduler 是 coverage-greedy:每個 tick 枚舉所有合法 arrival,**過濾出會踏進「尚未訪問
> 狀態」的候選**,再從這個未訪問池中**等機率隨機挑一個**(seeded RNG,可重現)。不是對覆蓋
> 分數取 argmax,而是「未訪問優先 + 隨機選一」。

**Option 2 (concise, for a one-liner):**
> Scheduler 是 coverage-filter greedy:優先挑「能到達未訪問狀態」的 arrival,並在這些候選
> 中隨機選一個(非最大化分數)。可選的 ε-greedy(預設關閉)以機率 ε 改採全隨機合法 arrival
> 來跳出局部最優。

> Also drop or rephrase any "budget-optimal at 4000 steps" claim on the slide — see
> Section D; it is unsupported, and the docs say the binding limiter is stagnation, not
> the step budget.

## Section F — Files read (audit trail)

| Path | Lines read | Lines total (approx) |
|------|-----------|------------|
| `tests/algo_validation/helpers/arrival_scheduler.py` | full (1-93) | ~93 |
| `tests/algo_validation/test_exploration.py` | tick loop + termination + call site (~21-162) | ~165 |
| `tests/algo_validation/conftest.py` | env-var fixtures (16-33) | ~35 |
| `tests/algo_validation/helpers/arrive_inject.py` | `inject_arrive` (~72-74) | — |
| `docs/algo_validation/STEP_S4_EPSILON_GREEDY_MULTISEED_INSTRUCTIONS.md` | §3, line 6, 74, 99 | — |
| `docs/algo_validation/STEP_S5_CROSS_SEED_UNION_INSTRUCTIONS.md` | line 3, 116-117 | — |

### Stop-and-report gates encountered
- **ε source nuance:** ε reaches the scheduler as the **constructor param `epsilon`**;
  its ultimate source is env var `EVCS_EPSILON` read in `conftest.py` and passed into
  the fixture. (Not read directly inside `arrival_scheduler.py`.) Not a blocker — noted.
- **No `exploration_driver.py`:** driver/tick-loop is in `test_exploration.py`. Noted.
- **Section D claim unsupported:** flagged above; documented honestly rather than
  fabricated. No code/test changed.
