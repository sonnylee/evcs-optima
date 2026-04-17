# EVCS Optima — Unit Test 開發規格書

> **對應 Codebase**：`https://github.com/sonnylee/evcs-optima`  
> **範疇**：`simulation/` 套件全模組白箱單元測試

---

## 1. 測試策略總覽

### 1.1 測試層次

| 層次 | 描述 | 覆蓋目標 |
|------|------|----------|
| **Unit Test** | 單一 class / 函式，所有外部依賴皆 mock | 邏輯正確性、邊界條件 |
| **Integration Test** | 跨模組協作（mcu_control ↔ module_assignment ↔ relay） | 協議正確性、資料一致性 |

> 本規格書聚焦於 **Unit Test** 與部分 **Integration Test**

### 1.2 測試框架與工具

| 工具 | 用途 |
|------|------|
| `pytest` | 主測試框架 |
| `pytest-asyncio` | 非同步 Actor 協議測試 |
| `unittest.mock` (`MagicMock`, `AsyncMock`) | 依賴隔離 |
| `pytest-cov` | 覆蓋率報告（目標：核心模組 ≥ 80%） |

### 1.3 目錄結構（建議）

```
tests/
├── unit/
│   ├── hardware/
│   │   ├── test_relay.py
│   │   ├── test_smr_group.py
│   │   ├── test_rectifier_board.py
│   │   └── test_output.py
│   ├── data/
│   │   ├── test_module_assignment.py
│   │   └── test_relay_matrix.py
│   ├── utils/
│   │   └── test_topology.py
│   ├── log/
│   │   └── test_relay_event_log.py
│   └── modules/
│       ├── test_mcu_control_local.py
│       ├── test_mcu_control_borrow_return.py
│       ├── test_mcu_control_relay_phase.py
│       └── test_vehicle.py
├── integration/
│   ├── test_borrow_protocol.py
│   ├── test_return_protocol.py
│   └── test_cross_mcu_relay_sync.py
└── conftest.py
```

---

## 2. 共用 Fixtures（`conftest.py`）

```python
# tests/conftest.py

import pytest
from simulation.log.relay_event_log import RelayEventLog
from simulation.data.module_assignment import ModuleAssignment
from simulation.data.relay_matrix import RelayMatrix
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.modules.mcu_control import MCUControl


@pytest.fixture
def event_log():
    return RelayEventLog()


@pytest.fixture
def make_single_mcu_system(event_log):
    """1-MCU 最小可用系統 fixture，不含 ChargingStation。"""
    def _make(consecutive_threshold=1):
        rm = RelayMatrix(num_mcus=1)
        ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
        board = RectifierBoard(
            mcu_id=0, event_log=event_log,
            relay_matrix=rm, module_assignment=ma, num_mcus=1,
        )
        mcu = MCUControl(
            mcu_id=0, board=board, module_assignment=ma,
            relay_matrix=rm, event_log=event_log,
            num_mcus=1, consecutive_threshold=consecutive_threshold,
        )
        return mcu, board, ma, rm
    return _make


@pytest.fixture
def make_3mcu_system(event_log):
    """3-MCU 線性系統 fixture（標準開發驗證配置）。"""
    def _make(consecutive_threshold=1):
        from simulation.hardware.charging_station import ChargingStation
        from simulation.utils.config_loader import SimulationConfig
        # 直接呼叫 ChargingStation 初始化
        station = ChargingStation(mcu_id=0, event_log=event_log, num_mcus=3)
        station.initialize(dt_index=0)
        mcus = []
        for i in range(3):
            mcu = MCUControl(
                mcu_id=i,
                board=station.boards[i],
                module_assignment=station.module_assignment,
                relay_matrix=station.relay_matrix,
                event_log=event_log,
                station=station,
                num_mcus=3,
                consecutive_threshold=consecutive_threshold,
            )
            mcus.append(mcu)
        # 連結鄰居
        for i in range(3):
            mcus[i].right_neighbor = mcus[(i + 1) % 3] if i < 2 else None
            mcus[i].left_neighbor  = mcus[(i - 1) % 3] if i > 0 else None
        return station, mcus
    return _make


def make_vehicle(
    vehicle_id="V1",
    battery_kwh=75.0,
    initial_soc=20.0,
    target_soc=80.0,
    max_power_kw=250.0,
):
    from simulation.modules.vehicle import Vehicle
    curve = [(0.0, max_power_kw), (80.0, max_power_kw), (100.0, 0.0)]
    return Vehicle(vehicle_id, battery_kwh, curve, initial_soc, target_soc)
```

---

## 3. 模組別測試規格

### 3.1 `simulation/utils/topology.py`

**測試檔案**：`tests/unit/utils/test_topology.py`

#### TC-TOPO-01：`is_ring()`

| Case | 輸入 `num_mcus` | 期望 |
|------|----------------|------|
| 單 MCU | 1 | `False` |
| 2 MCU（線性） | 2 | `False` |
| 3 MCU（環形邊界） | 3 | `True` |
| 4 MCU（環形邊界） | 4 | `True` |
| 8 MCU （環形邊界）| 8 | `True` |

#### TC-TOPO-02：`adjacent_pairs()`

| Case | 輸入 | 期望結果 |
|------|------|----------|
| 1 MCU | 1 | `[]` |
| 2 MCU（線性）| 2 | `[(0,1)]` |
| 3 MCU（環形） | 3 | `[(0,1),(1,2),(2,0)]` |
| 4 MCU（環形） | 4 | `[(0,1),(1,2),(2,3),(3,0)]` |

#### TC-TOPO-03：`ring_distance()`

| Case | a, b, num_mcus | 期望距離 |
|------|----------------|----------|
| 同一節點 | 0, 0, 3 | 0 |
| 相鄰（環形） | 0, 1, 3 | 1 |
| 非相鄰（環形，繞後較短） | 0, 2, 3 | 1 |
| 相鄰（環形） | 0, 3, 4 | 1 |
| 正反兩路等長（環形） | 0, 2, 4 | 2 |
| 線性相鄰（2 MCU） | 0, 1, 2 | 1 |

---

### 3.2 `simulation/log/relay_event_log.py`

**測試檔案**：`tests/unit/log/test_relay_event_log.py`

#### TC-LOG-01：append 與 get_events

```
初始狀態：空 log
append 3 個事件（relay_id 分別為 R1, R2, R1）
→ get_events() 回傳全部 3 個
→ get_events("R1") 回傳 2 個
→ get_events("R3") 回傳 []
```

#### TC-LOG-02：get_events_at

```
append 事件於 dt_index=5, 5, 10
→ get_events_at(5) 回傳 2 個
→ get_events_at(99) 回傳 []
```

#### TC-LOG-03：clear

```
append 若干事件 → clear() → len(log) == 0
```

---

### 3.3 `simulation/hardware/relay.py`

**測試檔案**：`tests/unit/hardware/test_relay.py`

#### TC-RELAY-01：初始狀態為 OPEN

```python
relay = Relay("R1", RelayType.INTER_GROUP, False, event_log, "G0", "G1")
assert relay.state == RelayState.OPEN
```

#### TC-RELAY-02：switch() — OPEN → CLOSED

```
switch(dt_index=1)
→ relay.state == CLOSED
→ event_log 有 1 個事件：dt_index=1, event_type="SWITCHED",
  from_state="OPEN", to_state="CLOSED"
```

#### TC-RELAY-03：switch() — CLOSED → OPEN

```
先 switch → CLOSED，再 switch(dt_index=2)
→ relay.state == OPEN
→ event_log 第 2 個事件：from_state="CLOSED", to_state="OPEN"
```

#### TC-RELAY-04：switch() 同步更新 RelayMatrix

```
relay_matrix mock，matrix_idx_a=0, matrix_idx_b=1
switch() → relay_matrix.set_state(0, 1, 1) 被呼叫一次（OPEN→CLOSED）
再 switch() → relay_matrix.set_state(0, 1, 0)（CLOSED→OPEN）
```

#### TC-RELAY-05：step() 為 no-op

```
relay.step(1.0) 不改變狀態，不產生 event
```

#### TC-RELAY-06：is_cross_mcu 屬性保留

```
Relay("BR", RelayType.INTER_GROUP, is_cross_mcu=True, ...)
→ relay.is_cross_mcu is True
```

---

### 3.4 `simulation/hardware/smr_group.py`

**測試檔案**：`tests/unit/hardware/test_smr_group.py`

#### TC-SMR-01：total_power_kw（2 個 SMR = 50kW）

```
SMRGroup("G0", num_smrs=2)
→ total_power_kw == 50.0（每個 SMR 25kW）
```

#### TC-SMR-02：SMR 停用後功率降低

```
group.smrs[0].enabled = False
→ total_power_kw == 25.0
```

#### TC-SMR-03：get_status 結構正確

```
status = group.get_status()
assert "group_id" in status
assert "total_power_kw" in status
assert len(status["smrs"]) == 2
```

---

### 3.5 `simulation/data/module_assignment.py`

**測試檔案**：`tests/unit/data/test_module_assignment.py`

#### TC-MA-01：初始化 — 單 MCU 全部可分配

```
ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
→ is_assignable(0, g) == True for g in [0,1,2,3]
→ is_assignable(1, g) == True for g in [0,1,2,3]
→ get_owner(g) == None for all g
```

#### TC-MA-02：初始化 — 3 MCU 非鄰居 Group 不可分配

```
ma = ModuleAssignment(num_outputs=6, num_groups=12, num_mcus=3)
# MCU0(O0,O1) 不可達 MCU2 的 G8~G11
→ is_assignable(0, 8) == False
→ is_assignable(0, 9) == False
# MCU0 可達自己 G0~G3 及鄰居 MCU1 的 G4~G7
→ is_assignable(0, 4) == True
```

#### TC-MA-03：assign_if_idle — 成功

```
ma.assign_if_idle(0, 0) → True
get_owner(0) == 0
```

#### TC-MA-04：assign_if_idle — 已被他人持有

```
ma.assign_if_idle(0, 0)
ma.assign_if_idle(1, 0) → False（G0 已屬於 O0）
```

#### TC-MA-05：assign_if_idle — 不可分配（-1 cell）

```
ma = ModuleAssignment(6, 12, 3)
ma.assign_if_idle(0, 8) → False（MCU0 不可達 G8）
```

#### TC-MA-06：release 後可重新 assign

```
ma.assign_if_idle(0, 0)
ma.release(0, 0)
get_owner(0) == None
ma.assign_if_idle(1, 0) → True
```

#### TC-MA-07：get_groups_for_output

```
ma.assign_if_idle(0, 0)
ma.assign_if_idle(0, 1)
→ get_groups_for_output(0) == [0, 1]
→ get_groups_for_output(1) == []
```

#### TC-MA-08：is_contiguous — 線性

```
assign G0, G1, G2 → is_contiguous(0) == True
assign G0, G2     → is_contiguous(0) == False
```

#### TC-MA-09：is_contiguous — ring wrap

```
ma = ModuleAssignment(2, 4, ...)
# 分配 G0, G3 (環形連續)
→ is_contiguous(0, ring=True) == True
→ is_contiguous(0, ring=False) == False
```

---

### 3.6 `simulation/data/relay_matrix.py`

**測試檔案**：`tests/unit/data/test_relay_matrix.py`

#### TC-RM-01：1 MCU 拓撲連結正確

```
rm = RelayMatrix(num_mcus=1)
# Inter-group: G0-G1, G1-G2, G2-G3
→ rm.is_legal(0, 1) == True
→ rm.is_legal(1, 2) == True
→ rm.is_legal(2, 3) == True
# Output: O0(idx=4)↔G0(idx=0), O1(idx=5)↔G3(idx=3)
→ rm.is_legal(4, 0) == True
→ rm.is_legal(5, 3) == True
# 非連接
→ rm.is_legal(0, 3) == False
→ rm.is_legal(4, 1) == False
```

#### TC-RM-02：3 MCU 橋接 relay 正確（線性，不環）

```
rm = RelayMatrix(num_mcus=3)
# Bridge: MCU0.G3 ↔ MCU1.G0 (idx 3 ↔ 4)
→ rm.is_legal(3, 4) == True
# Bridge: MCU1.G3 ↔ MCU2.G0 (idx 7 ↔ 8)
→ rm.is_legal(7, 8) == True
# 無 MCU2→MCU0 環形橋 (num_mcus=3 < 4)
→ rm.is_legal(11, 0) == False
```

#### TC-RM-03：4 MCU 環形橋接存在

```
rm = RelayMatrix(num_mcus=4)
→ rm.is_legal(15, 0) == True  # MCU3.G3 ↔ MCU0.G0
```

#### TC-RM-04：set_state / get_state

```
rm.set_state(0, 1, 1)   # close
→ rm.get_state(0, 1) == 1
→ rm.get_state(1, 0) == 1  # 對稱

rm.set_state(0, 1, 0)   # open
→ rm.get_state(0, 1) == 0
```

#### TC-RM-05：set_state 非法連接拋 AssertionError

```
pytest.raises(AssertionError): rm.set_state(0, 3, 1)
```

---

### 3.7 `simulation/hardware/output.py`

**測試檔案**：`tests/unit/hardware/test_output.py`

#### TC-OUT-01：connect_vehicle / disconnect_vehicle

```
output.connect_vehicle(vehicle)
→ output.connected_vehicle is vehicle
→ vehicle.output is output

output.disconnect_vehicle()
→ output.connected_vehicle is None
→ vehicle.output is None
→ output.present_power_kw == 0.0
```

#### TC-OUT-02：connect_vehicle 呼叫 module_assignment.assign_if_idle

```
ma = MagicMock()
output = Output(..., module_assignment=ma, output_idx=0, group_indices=[0,1])
output.connect_vehicle(vehicle)
→ ma.assign_if_idle.call_count == 2
→ ma.assign_if_idle.call_args_list 包含 (0,0) 與 (0,1)
```

---

### 3.8 `simulation/modules/vehicle.py`

**測試檔案**：`tests/unit/modules/test_vehicle.py`

#### TC-VEH-01：_interpolate_power — 曲線端點

```
curve = [(0, 250), (80, 250), (100, 0)]
vehicle.current_soc = 0   → max_require_power_kw == 250
vehicle.current_soc = 100 → _interpolate_power(100) == 0
```

#### TC-VEH-02：_interpolate_power — 線性內插

```
curve = [(0, 0), (100, 200)]
→ _interpolate_power(50) ≈ 100.0
```

#### TC-VEH-03：step() 更新 SOC

```
vehicle.state = CHARGING
vehicle.present_power_kw = 100.0  (100kW)
vehicle.step(dt=3600)  (1 小時)
delta_soc = (100 * 1 / 75) * 100 ≈ 133... → clamped to target_soc
```

#### TC-VEH-04：step() 達到 target_soc → COMPLETE

```
initial_soc = 79.9, target_soc = 80.0
vehicle.present_power_kw = 大值
vehicle.step(dt=3600)
→ vehicle.state == VehicleState.COMPLETE
→ vehicle.present_power_kw == 0.0
```

#### TC-VEH-05：step() output is None → no-op

```
vehicle.output = None
vehicle.step(1.0)  # 不應報錯，不應改變狀態
```

---

### 3.9 `simulation/modules/mcu_control.py` — 本地邏輯

**測試檔案**：`tests/unit/modules/test_mcu_control_local.py`

> **注意**：以下所有 TC 使用 `make_single_mcu_system(consecutive_threshold=1)` fixture（threshold=1 使條件一步內即觸發）。

#### TC-MCU-L-01：`_local_to_global` / `_global_to_local`

```
mcu_id=1（group_base=4）
→ _local_to_global(0) == 4
→ _local_to_global(3) == 7
→ _global_to_local(4) == 0
→ _global_to_local(7) == 3
```

#### TC-MCU-L-02：`_wrap` — 非環形不 wrap

```
mcu（num_mcus=3，_ring_enabled=False）
→ _wrap(-1) == -1
→ _wrap(12)  == 12
```

#### TC-MCU-L-03：`_wrap` — 環形正確 mod

```
mcu（num_mcus=4，_ring_enabled=True，num_groups_total=16）
→ _wrap(-1)  == 15
→ _wrap(16)  == 0
→ _wrap(17)  == 1
```

#### TC-MCU-L-04：`_is_local_group`

```
mcu_id=1（group_base=4）
→ _is_local_group(4) == True
→ _is_local_group(7) == True
→ _is_local_group(3) == False
→ _is_local_group(8) == False
```

#### TC-MCU-L-05：`_tick_borrow_condition` — 累積邏輯

```
threshold=3
output.present_power_kw = 125.0
output.available_power_kw = 125.0
vehicle.max_require_power_kw = 200.0

call 1 → counter=1, return False
call 2 → counter=2, return False
call 3 → counter=3, return True

# 條件不再成立時 counter 歸零
output.present_power_kw = 100.0
call 4 → counter=0, return False
```

#### TC-MCU-L-06：`_tick_return_condition` — present ≈ available 不觸發 return

```
output.available_power_kw = 125.0
vehicle.max_require_power_kw = 125.0
state.return_counter = 999  # 人為設定

_tick_return_condition(state, output, pre_available=125.0)
→ return_counter 歸零（edge_group power=75，125-125=0 < 75）
→ return False
```

#### TC-MCU-L-07：`_tick_return_condition` — 觸發 return（surplus >= edge_power）

```
output.available_power_kw = 200.0  # 已借 1 group
vehicle.max_require_power_kw = 100.0
# edge_group = G1（75kW），surplus = 200-100 = 100 >= 75

threshold=1：
call 1 → return True
```

#### TC-MCU-L-08：`_find_expansion_target` — 右側優先

```
state.interval_min = 0, state.interval_max = 1  (anchor=0)
G2 idle → target == 2 （右）
G2 busy, G-1 is local idle → target == -1（左）...但 -1 是 out of range → None
```

#### TC-MCU-L-09：`_find_shrink_target` — 不縮到 anchor

```
state = {interval_min=0, interval_max=2, anchor_group_idx=0}
→ _find_shrink_target(prefer_cross_mcu=False) == 2  (max side, not anchor)

state = {interval_min=0, interval_max=0}  # 只剩 anchor
→ None
```

#### TC-MCU-L-10：`_apply_borrow` 更新 interval 與 relay

```
初始 interval [0, 1]，呼叫 _apply_borrow(state, target=2)
→ interval_max == 2
→ event_log 有 switch 事件（R_12 relay 閉合）
→ output.available_power_kw == 200.0（G0+G1+G2 = 50+75+75）
```

#### TC-MCU-L-11：`_apply_return` 更新 interval 與 relay

```
初始 interval [0, 2]，呼叫 _apply_return(state, target=2)
→ interval_max == 1
→ module_assignment.release(output_idx, 2) 被呼叫
→ R_12 relay 開路
```

#### TC-MCU-L-12：`_force_return_group` — 從 max 端釋放

```
state.interval=[0,3], anchor=0, target=3
→ 釋放 G3，interval_max == 2

state.interval=[0,3], anchor=0, target=2
→ 釋放 G3, G2，interval_max == 1
```

#### TC-MCU-L-13：`get_status` 結構正確

```
status = mcu.get_status()
assert status["mcu_id"] == 0
assert len(status["outputs"]) == 2
assert "interval" in status["outputs"][0]
```

---

### 3.10 `simulation/modules/mcu_control.py` — Relay 相位狀態機

**測試檔案**：`tests/unit/modules/test_mcu_control_relay_phase.py`

#### TC-PHASE-01：vehicle arrival — 三相啟動 relay 序列

```
mcu.handle_vehicle_arrival(output_local_idx=0)

# Tick T（arrival）：inter-group relay 尚未切換，output relay 未切換
→ pending_intergroup_close == 1
→ pending_output_relay_close == 0

# Tick T+1：advance_relay_phases()
→ inter-group relay 閉合（R_01）
→ pending_intergroup_close == 0
→ pending_output_relay_close == 1

# Tick T+2：advance_relay_phases()，available >= 125kW
→ output relay 閉合（R_O0）
→ pending_output_relay_close == 0
```

#### TC-PHASE-02：available < 125kW 時 output relay 不閉合

```
# board.outputs[0].available_power_kw = 50.0（人為設定）
Tick T+2 的 advance_relay_phases()
→ output relay 仍為 OPEN
→ pending_output_relay_close 仍為 2（等待下次）
```

#### TC-PHASE-03：vehicle departure — 兩相離開 relay 序列

```
mcu.initiate_vehicle_departure(0)

# 設定 vehicle.state = COMPLETE
# Tick T+1：inter-group relay 開路（R_01）
# Tick T+2：output relay 開路，groups/interval 釋放
→ board.outputs[0].connected_vehicle is None
→ event_log 包含對應開路事件
```

#### TC-PHASE-04：departure 時共用 relay 不被開路

```
# O0 和 O1 都使用 R_01（O0 借到 G2 時）
# O0 離開不應開路 R_01（O1 仍需要）
→ 驗證 still_needed 正確排除共用 relay
```

#### TC-PHASE-05：pending 期間 borrow/return counter 歸零

```
state.pending_intergroup_close = 2
→ _advance_relay_phases(state) 返回 True
→ state.borrow_counter == 0
→ state.return_counter == 0
```

---

### 3.11 `simulation/modules/mcu_control.py` — 借電 / 還電

**測試檔案**：`tests/unit/modules/test_mcu_control_borrow_return.py`

#### TC-BR-01：`_try_borrow_local` — 成功借本地 G2

```
O0 初始 [0,1]，G2 idle
_try_borrow_local(state_O0)
→ state.interval_max == 2
→ ma.get_owner(2) == output_O0_idx
→ event_log switch event 存在
```

#### TC-BR-02：`_try_borrow_local` — 無可用 group 時 no-op

```
O0 持有 [0,1]，O1 持有 [2,3]，G2/G3 均被佔
_try_borrow_local(state_O0)
→ state.interval_max == 1（未變）
→ event_log 無新事件
```

#### TC-BR-03：`_try_return_local` — 還 G2

```
O0 持有 [0,2]，surplus 足夠
_try_return_local(state_O0)
→ state.interval_max == 1
→ ma.get_owner(2) == None
```

#### TC-BR-04：`_try_borrow_local` 不嘗試 cross-MCU group

```
# 3-MCU，O0 在 MCU0，G4 屬於 MCU1
# allow_cross_mcu=False
_find_expansion_target(state, allow_cross_mcu=False)
→ 不回傳 G4（is_local_group(4) == False）
```

#### TC-BR-05：`handle_vehicle_arrival` — 衝突 force return

```
# 場景：O1 已借走 G1（跨入 O0 領域）
# O0 新車到來 → force_return_group 強制 O1 釋放 G1
→ ma.get_owner(1) 最終 == O0_idx
→ 舊 O1 interval 縮短
```

---

### 3.12 `simulation/utils/validator.py`

**測試檔案**：`tests/unit/utils/test_validator.py`（或 integration）

#### TC-VAL-01：無違規時 has_failures() == False

```
3-MCU 初始化後立即 validator.check(0)
→ has_failures() == False
```

#### TC-VAL-02：multiple-owner 衝突觸發 violations_log

```
手動設定 ma._matrix[0][5] = 1 且 ma._matrix[1][5] = 1（G5 同時被 O0 O1 持有）
validator.check(1)
→ len(validator.violations_log) > 0
```

#### TC-VAL-03：boundary_check 記錄每個步驟的鄰居對

```
3-MCU validator.check(5)
→ boundary_log 包含 2 個條目：mcu_pair [0,1] 和 [1,2]
```

---

## 4. Integration Test 規格

### 4.1 BorrowRequest 協議（跨 MCU）

**測試檔案**：`tests/integration/test_borrow_protocol.py`

#### TC-INT-BR-01：MCU0 向 MCU1 借 G4，MCU1 自動授權

```python
@pytest.mark.asyncio
async def test_cross_mcu_borrow_granted(make_3mcu_system):
    station, mcus = make_3mcu_system()
    mcu0, mcu1, _ = mcus
    # G4 屬於 MCU1，初始 idle
    state = mcu0._output_states[0]
    state.interval_min = 0
    state.interval_max = 3  # 剛好到 MCU0 邊界

    await mcu0._try_borrow_async(state)

    assert station.module_assignment.get_owner(4) == mcu0._output_base + 0
    assert state.interval_max == 4
```

#### TC-INT-BR-02：MCU1 拒絕 G4 借電（G4 已被 MCU1 本地 O2 持有）

```
預先 assign G4 給 MCU1 的 O2
MCU0 發送 BorrowRequest(group_idx=4)
→ MCU1 的 assign_if_idle 回傳 False
→ MCU0 的 interval 不變
```

#### TC-INT-BR-03：ReturnNotify — MCU0 還 G4 給 MCU1

```
先完成跨 MCU 借電
MCU0 呼叫 _try_return_async(state) with prefer_cross_mcu=True
→ send_return_notify 被送出
→ MCU1 收到 ReturnNotify，response.set_result(True)
→ G4 回到 idle（get_owner(4) == None）
```

#### TC-INT-BR-04：_sync_foreign_relays 正確更新 MCU1 的 bridge relay

```
MCU0 借入 G4（MCU1 領域邊界）
→ MCU1._sync_foreign_relays 被呼叫
→ MCU1.board.right_bridge_relay（或 MCU0 的 bridge）狀態與 interval 一致
```

---

### 4.2 ConflictRelease 協議

**測試檔案**：`tests/integration/test_return_protocol.py`

#### TC-INT-CR-01：新車衝突觸發 ConflictRelease

```
場景：MCU0 O0 借入 G4（MCU1 的 anchor），MCU1 O2 新車到來需要 G4
→ MCU1 對 MCU0 發送 ConflictRelease(group_idx=4)
→ MCU0 強制還回 G4
→ G4 轉讓給 MCU1 O2
→ MCU0 interval_max 縮短
```

---

## 5. 邊界條件與負面測試

### 5.1 Ring Wrap 邊界

| TC | 場景 | 驗證 |
|----|------|------|
| TC-NEG-01 | 4-MCU 環形，MCU3 借入 MCU0 的 G0（wrap） | `_wrap(16) == 0`，interval=[15, 16]，phys target=0 |
| TC-NEG-02 | `_virtual_interval_contains` 在 ring 模式下正確判斷 | g=0, vmin=15, vmax=16 → True |

### 5.2 Interval 邊界保護

| TC | 場景 | 驗證 |
|----|------|------|
| TC-NEG-03 | interval 擴張到覆蓋全 ring（num_groups 個） | span_guard 阻止，right_v 設 None |
| TC-NEG-04 | `_find_shrink_target` interval 已為最小（min==max） | 回傳 None |

### 5.3 ModuleAssignment 雙重持有防護

| TC | 場景 | 驗證 |
|----|------|------|
| TC-NEG-05 | 連續呼叫兩次 `assign_if_idle(0, g)` | 第 2 次回傳 False，不拋錯 |
| TC-NEG-06 | `assign()` 已被他人持有 → AssertionError | pytest.raises(AssertionError) |

---

## 6. 覆蓋率目標

| 模組 | 目標行覆蓋率 |
|------|-------------|
| `simulation/utils/topology.py` | 100% |
| `simulation/log/relay_event_log.py` | 100% |
| `simulation/hardware/relay.py` | 100% |
| `simulation/hardware/smr_group.py` | 100% |
| `simulation/data/module_assignment.py` | ≥ 95% |
| `simulation/data/relay_matrix.py` | ≥ 95% |
| `simulation/hardware/output.py` | ≥ 90% |
| `simulation/modules/vehicle.py` | ≥ 90% |
| `simulation/modules/mcu_control.py` | ≥ 85% |
| `simulation/utils/validator.py` | ≥ 85% |

執行覆蓋率：
```bash
pytest tests/ --cov=simulation --cov-report=html --cov-report=term-missing
```

---

## 7. 測試執行指南

### 7.1 環境建立

```bash
cd evcs-optima
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov
```

### 7.2 執行全部測試

```bash
pytest tests/ -v
```

### 7.3 執行特定模組

```bash
pytest tests/unit/modules/test_mcu_control_local.py -v
pytest tests/integration/ -v
```

### 7.4 asyncio 模式設定（`pytest.ini` 或 `pyproject.toml`）

```ini
[pytest]
asyncio_mode = auto
```

---
