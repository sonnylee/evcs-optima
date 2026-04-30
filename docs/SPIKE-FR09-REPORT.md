# Phase 0 Spike 報告 — FR-09 Reactive 演算法可行性驗證

執行日期: 2026-04-30
執行環境: Python 3.13.5, pytest 9.0.3, pytest-asyncio 1.3.0
Spike 範圍: 18 個 scenario(14 靜態拓樸 + 4 動態場景)
Production code 變動: 無(只新增 `tests/integration/test_engine_for_web_spike.py` 與本報告)

---

## 摘要

- **總 scenario 數**: 18
- **收斂(passed)**: **18 / 18**
- **未收斂(timeout/failed)**: 0
- **總執行時間**: ~0.39 s(整個 pytest session)

---

## 結論建議

✅ **GO with caveats** — 主流程通過,可進 Phase 3 Step F09.1,但下列觀察會直接影響 FR-09 reactive 設計,實作前需先想清楚:

1. **SimulationEngine `__init__` 會把系統直接拉到穩態。** 所有 14 個 SPEC §16 靜態 scenario 都在 5 tick(= stable window 本身)內收斂、且 `event_count = 0`。原因不是「runner 跑得很快」,而是 `MCUControl.__init__` 末端會同步呼叫 `_apply_global_relay_state()` 把 inter-group 與 output relay 一次切到位,然後 `engine.__init__` 末尾呼叫 `event_log.clear()`。因此 spike 進入主迴圈時系統「已經穩定」,後續的 pending 狀態機 (`pending_intergroup_close=1` → 2 → fire → 0) 實際上是 no-op(目標 relay 都在目標位置,`r.state == OPEN` 守衛擋掉了 switch 呼叫)。 這代表只要 FR-09 的 demand 變動採「重建 engine」的策略,**反應速度 = engine 建構成本**,不需要等任何 tick 流逝;但若要「在 live engine 上微調」,就會吃到 SPEC §6.1/6.2 的 `consecutive_threshold` 延遲(預設 3 tick)。
2. **simulation core 沒有「demand=0 但車仍掛著」的概念。** 0 kW 必定走 departure 流程(`Vehicle.state = COMPLETE` → `_trigger_departures` → 兩階段開 relay → `disconnect_vehicle`)。如果 FR-09 想保留車輛圖示但顯示 0 kW,**核心無此狀態**;若要支援需要 web service 自行 mock,而不是 driving simulation core。
3. **dyn_02 progressive fill 必須 rebuild engine。** simulation core 沒有「對 live engine 加掛新車」的 SPEC §11-correct API,initial_vehicles 是 config 階段一次性參數。spike 的 14-step 漸進填滿是逐步重建 engine 完成的。FR-09 想做「漸進加車」也只能照樣 rebuild。
4. **overload(2400 kW vs 1000 kW 容量) 沒有 livelock。** 事件數在前 8 tick 累積到 8 之後完全停下,後 50 tick 增量為 0。表示借電優先級協調機制在不可能完全滿足需求時仍能達到不變式正確、靜止的局部最佳解。
5. **invariants 100% 通過**。沒有 group double-assign、所有 active output(closed + 有車)≥125 kW、總 active available ≤ 1000 kW、所有 `pending_*` counter 收斂為 0。

> 換句話說:Phase 3 Step F09.1 若採「demand 變動 → rebuild engine」的策略可以直接走;若要走「live engine 重新計算」,需要先補 mid-run vehicle attach API + 處理 `consecutive_threshold` 延遲(降低為 1 或改用同步路徑)。

---

## 靜態拓樸 14 scenario 詳細結果

每個 ON output 預設 `max_required = 125 kW`(讓 demand 等於 anchor 兩個 group 的容量),靜態車(curve flat 125)。

| ID | Label | ON outputs | 收斂 | Tick | Wall ms | Events | Inv. | Active | 備註 |
|---|---|---|---|---:|---:|---:|---|---|---|
| test_spec_01 | (3,1,0) | [0] | ✅ | 5 | 2.96 | 0 | ✅ | ✅ | — |
| test_spec_02 | (2,2,0) | [0,2] | ✅ | 5 | 0.84 | 0 | ✅ | ✅ | — |
| test_spec_03 | (3,0,1) | [0,1] | ✅ | 5 | 0.87 | 0 | ✅ | ✅ | — |
| test_spec_04 | (1,3,0) | [0,2,4] | ✅ | 5 | 0.74 | 0 | ✅ | ✅ | — |
| test_spec_05 | (2,1,1) | [0,1,2] | ✅ | 5 | 3.96 | 0 | ✅ | ✅ | — |
| test_spec_06 | (0,4,0) | [0,2,4,6] | ✅ | 5 | 0.83 | 0 | ✅ | ✅ | — |
| test_spec_07 | (1,2,1) | [0,1,2,4] | ✅ | 5 | 0.74 | 0 | ✅ | ✅ | — |
| test_spec_08 | (2,0,2) | [0,1,2,3] | ✅ | 5 | 0.99 | 0 | ✅ | ✅ | — |
| test_spec_09 | (0,3,1) | [0,1,2,4,6] | ✅ | 5 | 0.81 | 0 | ✅ | ✅ | — |
| test_spec_10 | (1,1,2) | [0,1,2,3,4] | ✅ | 5 | 0.79 | 0 | ✅ | ✅ | — |
| test_spec_11 | (0,2,2) | [0,1,2,3,4,6] | ✅ | 5 | 0.91 | 0 | ✅ | ✅ | — |
| test_spec_12 | (1,0,3) | [0,1,2,3,4,5] | ✅ | 5 | 3.73 | 0 | ✅ | ✅ | — |
| test_spec_13 | (0,1,3) | [0,1,2,3,4,5,6] | ✅ | 5 | 0.92 | 0 | ✅ | ✅ | — |
| test_spec_14 | (0,0,4) | [0,1,2,3,4,5,6,7] | ✅ | 5 | 1.00 | 0 | ✅ | ✅ | — |

**靜態結果觀察**: 每一條都是 5 tick + 0 event。原因見下方「觀察與發現 #1」。 不變式檢查 + 「ON output ≥125 kW / OFF output 沒車」全數通過。

---

## 動態場景 4 scenario 詳細結果

### test_dyn_01_grow_shrink — O0: 0 → 125 → 250 → 125 → 0

| 階段 | 收斂 | Tick | Wall ms | Events | Inv. |
|---|---|---:|---:|---:|---|
| 0 → 125(init build + settle) | ✅ | 5 | 7.92 | 0 | ✅ |
| 125 → 250(curve mutate,觸發借電) | ✅ | 11 | 13.51 | 2 | ✅ |
| 250 → 125(curve mutate,觸發還電) | ✅ | 11 | 2.36 | 2 | ✅ |
| 125 → 0(set state = COMPLETE → depart) | ✅ | 8 | 1.15 | 2 | ✅ |
| **累計** | — | **35** | **24.94** | **6** | ✅ |

`125→250` 與 `250→125` 各 11 tick 與 SPEC §6.1/6.2 的 `consecutive_threshold = 3` 一致(3 tick 偵測 + 2 tick 兩階段 close + 5 tick stable window ≈ 10~11)。每條切換產生 2 event(1 inter-group + 1 mirror-sync 旁邊 MCU 的 bridge / inter-group)。

### test_dyn_02_progressive_fill — SPEC §16 情境 1 → 14(rebuild engine 每步)

14 segments,每段 5 tick / 0 event(因為「重建」走 init synchronous path,理由同靜態)。
- 累計 ticks: 70
- 累計 wall ms: 17.18
- 累計 events: 0
- converged: ✅(全部 14 段)
- invariants: ✅(全部 14 段)

### test_dyn_03_engine_reuse — 同一 engine 連跑 100 → 200 → 100 → 0 → 150

| 階段 | 收斂 | Tick | Wall ms | Events | Inv. |
|---|---|---:|---:|---:|---|
| init → 100 | ✅ | 5 | 1.43 | 0 | ✅ |
| 100 → 200(curve mutate,借電 1 group) | ✅ | 8 | 1.05 | 1 | ✅ |
| 200 → 100(curve mutate,還電) | ✅ | 8 | 3.98 | 1 | ✅ |
| 100 → 0(state=COMPLETE → depart) | ✅ | 8 | 0.96 | 2 | ✅ |
| 0 → 150(connect new vehicle + handle_vehicle_arrival) | ✅ | 10 | 1.23 | 3 | ✅ |
| **累計** | — | **39** | **8.65** | **7** | ✅ |

Live-engine reuse 可行。注意 `100 kW` 在 borrow/return 觸發條件下表現安靜(demand < anchor 125 kW,不會借電也不會還電,因此 init→100 的 segment 沒有 event)。`0→150` re-arrival 必須手動 attach vehicle + 呼叫 `handle_vehicle_arrival(local_idx)` —— 這也是 simulation core 唯一可用的 API。

### test_dyn_04_overload — 4 outputs × 600 kW vs 1000 kW 系統容量

- tick_count: 200(完整跑完 timeout)
- wall_time_ms: 97.36
- total_events_added: **8**
- events_in_last_50_ticks: **0**(== 沒有 livelock)
- samples first 10: `[0, 0, 0, 0, 2, 2, 2, 4, 4, 4]`
- samples last 10: `[8, 8, 8, 8, 8, 8, 8, 8, 8, 8]`
- invariants: ✅(僅 4 個 anchor 區間穩定占用 8 個 group,沒有違反任何不變式)

**過載時 borrow 競爭迅速進入死局並停手**(各 output 試了一次借電就放棄,因為左右鄰居也在借)。沒有反覆 borrow→return→borrow 的震盪。從 reactive 演算法角度看是好事:即使使用者不斷加 demand,系統不會 livelock。但也代表「過載時超出 125 kW 的需求**靜默被忽略**」—— FR-09 必須在 web layer 自行偵測並對 user 報「Target 超過總容量」。

---

## 觀察與發現

### 1. SimulationEngine `__init__` 已經把系統推到穩態(影響 FR-09 設計)

實際 trace(scenario 01,單一 ON output):

```
Pre-loop event_log size: 0
Pre-loop output relay 0 state: CLOSED   ← 重點:已 CLOSED
Pre-loop R_01 state: CLOSED
Pre-loop pending: pending_intergroup_close=1, pending_output_relay_close=0
Tick 1..8: events=0  O0relay=CLOSED  R01=CLOSED  pend 演化 (1,0)→(2,0)→(0,2)→(0,0)→...
```

- `RectifierBoard.initialize_relays()` 把 R_01 / R_23 切 CLOSED。
- `MCUControl.__init__` 末端呼叫 `_apply_global_relay_state(include_output=True)`(line 124),把 output relay 也切 CLOSED(此時 MA 已經被 `Output.connect_vehicle` 寫入 anchor groups,所以 interval 已存在)。
- `engine.__init__` 末端 `event_log.clear()` 把上述 8+ 個 event 全部抹除。
- `handle_vehicle_arrival` 後續被呼叫時,relay 都已就位,只負責設 `pending_intergroup_close=1`。
- spike 主迴圈跑時,pending 狀態機照常演化(1→2→fire→0,然後 pending_output_relay_close=1→2→fire→0),但 fire 函數內部的 `if r.state == RelayState.OPEN: r.switch(...)` 一律不觸發(relay 已經是目標狀態)→ 0 events。

**對 FR-09 的意義**: 若採「demand 變 → rebuild engine」策略,FR-09 reactive 反應幾乎是零延遲(<10 ms 的 engine 建構成本),完全不必處理 tick 演化。SPEC §6.1/6.2 的 `consecutive_threshold` 也不會吃到。

### 2. `consecutive_threshold = 3` 對 spike 的影響(live-engine 路徑)

當在 live engine 上 mutate vehicle curve 來改 demand,borrow / return 觸發要等 3 個 consecutive tick 才會 fire。 加上後續 2 階段 close(or open)、再加 stable window 5 tick,單一 demand-change 約需 8~11 tick 才能 settle —— 與 dyn_01、dyn_03 的觀察吻合。

如果 FR-09 走 live-engine 路徑(而不是 rebuild),要決定:
- 把 `consecutive_threshold` 改 1(犧牲 SPEC §6 抗抖能力)
- 或把每次 demand-change 都當作 "config rebuild"。

### 3. dyn_03 `100 → 200` 之間,`init→100` 完全沒有 event 是因為 100 < 125

當 `max_required = 100 kW` 時:`present = min(100, 125) = 100`,`available = 125`,demand `100 < available`。所以 borrow 觸發條件 `present == available` 永遠不成立 → 不會借電。系統就停在 anchor 兩個 group(125 kW 容量,僅給 100 kW)的初始狀態。這是 simulation core 的「demand 低於 anchor 容量時零動作」性質。

### 4. demand=0 流程依賴 `Vehicle.state = COMPLETE`(沒有「降到 0 但保持掛車」的路徑)

spike 的 dyn_01、dyn_03 把 demand 降到 0 都是用 `vehicle.state = VehicleState.COMPLETE`,讓 `engine._trigger_departures` 啟動兩階段 open。 完成後 `output.connected_vehicle = None`、`vehicle.output = None`,vehicle 物件留在 `engine.vehicles` list 但被 `vehicle.step()` 的 `state == COMPLETE` 守衛擋掉。

這代表 FR-09 的「Max Required = 0 → 該路 Relay 全斷開、車輛圖示變灰」如果直接餵到 simulation core,**車輛會被「卸下」**(`connected_vehicle = None`)。要再次 demand>0 必須走 re-arrival(spike dyn_03 是這樣處理 `0 → 150`)。 如果 FR-09 想保留「車仍在但 0 kW」的中間狀態,**core 沒這個概念,需 web service 層自己模擬**。

### 5. overload 不 livelock,但會「靜默裁切」

dyn_04 末段 50 tick 完全沒新 event。全部 4 個 output 都停在 anchor 兩個 group(125 kW),沒有任何借電完成。這是因為左右鄰居都想借 → conflict release → 借電被拒 → borrow_counter 重設。沒有反覆 borrow→return 的震盪,但**也沒有「公平分配剩餘容量」的機制**。FR-09 的 Apply-and-Generate 必須先檢查 Target 總和 ≤ 系統容量,**核心不會幫你檢查**。

### 6. `event_log.clear()` 在 init 末尾的副作用

這是 spike 一開始的「先入為主誤解來源」:看到 event_count=0 會以為「engine 沒做任何事」,事實上是「在 spike loop 外做完了」。對 FR-09 reactive 設計者的提醒:**spike 結果的 wall_time_ms 不包含 engine 建構成本**(SpikeRunner 啟動才開始計時),如果 FR-09 採 rebuild 策略,要把 engine 建構成本(觀察 1 ~ 4 ms 級別)算進反應時間預算。

---

## 收斂判定的實作細節

採用「**事件數 + pending counters 雙重門檻**」:

```python
if cur_event_count == last_event_count:
    stable_streak += 1
    if stable_streak >= 5 and all_pending_clear():
        converged = True
```

- **第一個門檻**(連續 5 tick `len(event_log)` 不變)是 user 規格指定的「5 tick 沒新 event」。
- **第二個門檻**(`pending_intergroup_close / output_relay_close / intergroup_open / output_relay_open` 全部歸 0)補一個邊界 case:有時候 `pending` 已經設好但這 tick 還沒 fire(例如剛剛呼叫 `handle_vehicle_arrival`),event_log 也沒長,看起來「穩」但下一 tick 會放煙火。雙重門檻避免假收斂。
- **timeout 200 tick**:所有 scenario 實際都遠低於這個值,最大值是 dyn_04(intentional overload,跑滿 200)和 dyn_03 / dyn_01 的某個 segment(11 tick 上下)。

替代方案考慮過:
- **「snapshot 比對」**: 比對前後 `station.get_status()` 完全相等。比 event-count 嚴謹,但實作成本高(deepcompare nested dict)。捨棄。
- **「等到 `_all_charging_complete()`」**: 不適用 —— FR-09 不關心車是否充飽,只關心 relay 狀態穩定。捨棄。

實際選的方案在 18 個 scenario 都正確判定,且每段 wall time 都 < 100 ms,可接受。

---

## 不變式驗證情況

`assert_engine_invariants(engine)` 內 4 條全數通過,**沒有放寬**:

| # | 不變式 | 通過 scenario |
|---|---|---|
| 1 | 跨 board MA 沒有 group 雙重 owner | 18 / 18 |
| 2 | 每個 active output(relay closed + 有車)`available_power_kw ≥ 125 kW` | 18 / 18 |
| 3 | 所有 active output 的 `available_power_kw` 加總 ≤ 1000 kW(系統總容量) | 18 / 18 |
| 4 | 所有 `pending_*` counter == 0(無在途 relay phase) | 18 / 18 |

額外的「**靜態 scenario 對 ON / OFF 期望**」也全通(每個 ON output 真的有 vehicle 且 ≥125 kW,每個 OFF output 真的沒車)。

---

## 若要從 spike 結果推到 Phase 3 Step F09.1 實作

建議路徑(按 risk 由低到高):

1. **rebuild-engine 路徑(推薦)**: web service 收到 `Apply and Generate` → 把 web 端 `system_config + car_ports[]` 翻成 `SimulationConfig` → `SimulationEngine(cfg)` → 直接讀 `station / mcu_controls / event_log` 的當下狀態。 不需要驅動 tick 迴圈。 風險最低,因為 spike 已驗證 engine 建構期會自動把 relay 切到位、不變式都成立。
2. **rebuild + diff 路徑**: rebuild current state 與 target state 兩份 engine,從兩份 `station.get_status()` 之間的 diff 產生 control step 序列。風險偏低,主要靠 `event_log` 的順序就能拼出 `ControlStepSequence`。
3. **live-engine 路徑(不建議)**: 在 live engine 上 mutate vehicle curve / state。 spike 已驗證可行(dyn_03),但會吃 `consecutive_threshold` × 多階段 close 約 8~11 tick 的延遲,且要小心 demand=0 走 departure 後 vehicle 物件被卸下。額外風險:Phase 3 既有的 `step_planner.py` 已經是 snapshot post-processing 路線(CLAUDE.md 標明「不 invoke time-driven core」),走這條等於推翻既有設計。

**spike 沒有評估到的部分**(F09.1 實作時要再驗):
- 多 demand-change 在 1 個 user transaction 內的 step ordering 是否符合 FR-14 的「Apply→產生 step sequence」期望
- `event_log` 的順序是否能直接還原 SPEC §11 的「inter-group 先 / output 後」開關時序
- `palette` / 顏色與 snapshot 的同步(spike 完全沒測 UI 那層)

---

## 附錄 A — 怎麼跑

```bash
pytest tests/integration/test_engine_for_web_spike.py -v -m spike -s
```

`-s` 才看得到收尾印出的 `SPIKE_RESULT::<name>::<json>` 行(每個 scenario 一行),報告中的數字直接從那段 stdout 取得。

`pytest.mark.spike` 沒在 `pytest.ini` 註冊,會印 5 個 `PytestUnknownMarkWarning` —— 不影響執行。 (沒在 spike 階段去動 pytest.ini,因為 user 限制只能新增 2 個檔案。)

## 附錄 B — 18 個 scenario 的 raw JSON

執行後從 stdout 抓 `SPIKE_RESULT::` 行即可,範例(Tick=200 的 overload):

```
SPIKE_RESULT::test_dyn_04_overload::{
  "tick_count": 200,
  "wall_time_ms": 97.36,
  "total_events_added": 8,
  "events_in_last_50_ticks": 0,
  "samples_first_10": [0, 0, 0, 0, 2, 2, 2, 4, 4, 4],
  "samples_last_10":  [8, 8, 8, 8, 8, 8, 8, 8, 8, 8],
  "invariants_ok": true,
  "err": ""
}
```
