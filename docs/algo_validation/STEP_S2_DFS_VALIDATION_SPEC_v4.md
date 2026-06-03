# STEP S2.X — 多維度演算法驗證測試規格 v4（探索式即時抽樣 + 雙軍驗證 + 複用既有設施）

> **v4 與 v3 是方法論層級差異**。本版整合三輪 explorer 實證（STATESPACE / SETTLE_FREQ / REUSE）。
>
> 核心摘要：
> - **狀態空間 766**（256 佔用 × 3 SOC，扣空站壓縮）：FR-11 下 C4 對稱被打破，採 766 為主分母；另報 70 車類作診斷
> - **放棄離線路徑生成**：離場由系統自發（`vehicle.step()` soc≥target → `_trigger_departures()`，`simulation_engine.py:225-233`），測試無法預先排程
> - **探索式抽樣**：arrive-driven（測試控）+ passive-depart（系統決定）
> - **雙軍驗證**：穩態軍（被動等穩態，驗 L1/L2守恆/L4）+ 逐-tick 軍（每 tick 驗 L3/L2 relay 順序）
> - **大量複用 engine 既有設施**（REUSE explorer 定案，見 §4）：測試僅新建小薄層，不修改 production
> - **覆蓋率非通過判據**（觀察數據）：通過判據 = 走過的穩態 + 每個 tick 的 PASS
>
> **REUSE explorer 實證修正（本版關鍵）**：
> 1. **engine 無「乾淨穩態」查詢**（`_all_charging_complete()`，`simulation_engine.py:198-221` 只看 2 個 open 指標，不看 close）：真正的 4 指標彙總 `_all_pending_clear()` 只在 web 層（`web_session_engine.py:220`）→ 測試自建 `is_quiescent()`（~6 行）放 helper，**不碰 production**
> 2. **TrafficSimulator 不支援後期注入**（`__init__` 一次排出固定，`traffic_simulator.py:41`）→ arrive 改用底層 API 直呼
> 3. **export_csv 驗證失敗才不寫**（`vision_output.py:108-112`）→ trace 改用 `engine.snapshots` + `arrivals_log`
> 4. **validator 逐-tick 機制與 L4a ownership 鏡像已現成**（`validator.py:67-111`、`check()`/`_diff_pair`）→ 複用；但**不比對 relay_state**（`validator.py:98-109`）→ L4a 的 relay 鏡像連動由測試自建
> 5. **ChargingStation.validate()** 涵蓋 L2 連續區間 + 單一 ownership（`charging_station.py:87-119`）→ 複用；但不涵蓋 L3 §11 不變量 → L3 檢查內容由測試自建，搭配 validator 逐-tick 餘存

=== 指令開始 ===

## 1. 目標

在開發者無法預先規劃完整路徑的限制下，以「主動 arrive + 被動觀察 depart」長時間驅動系統走遍大量合法狀態，並以雙軍驗證演算法的自洽、合法、守恆。**最大化複用 engine 既有驗證設施，測試僅新建小薄層，不修改 production code。**

**核心限制（已實證）**：測試可控 arrive 時機/SOC，不可控 depart（系統自發）。

**定位**：線上 web/core 無錯誤回饋已驗常規路徑，本測試以長時間探索補足冷僻配置。

**不題**：不題 module_powers 是否為 SPEC 最佳值（無 oracle、無黃金樣本）；只題合法/守恆/自洽。

**Scope**：被測 = simulation 層，不經 FastAPI/前端；**不修改 production code**（含不在 engine 加公開方法——穩態判斷放測試 helper）。

---

## 2. 狀態空間（已實證）

### 2.1 狀態 `(O, L)`
- `O`：8-bit 佔用向量（bit i = 輸出 i 有車），0~255
- `L`：最後來車 SOC ∈ {低,中,高}，O=0 時 ⊥
  - L 無值或本位。測試自行追蹤、lossy（多車並行各佔用獨 SOC）
  - depart 不改變 L

### 2.2 SOC 分級
低 0~30%(代表15%) / 中 30~80%(55%) / 高 80~100%(90%)，代表值由 Claude Code 拍板。

### 2.3 節點總數 = 766（主分母）
1（空站 O=0,L=⊥）+ 765（255 佔用 × 3 L）= 766。
**為何 766 非 208**：C4 旋轉對稱下 Burnside 得 70 車類→208 節點，但前提是 MCU 共享 module_powers 才成立；FR-11（per-REC-BD 模組功率）打破對稱 → 採 766。每 MCU 內倆輸出本就不對稱（O0 鄰 G0、O1 鄰 G3，`mcu_control.py:28-38`）。另報 70 車類覆蓋作診斷。

### 2.4 邊
arrive（O 某 bit 0→1，測試指定），depart（O 某 bit 1→0，系統自發），各使恰好一 bit 變。

---

## 3. 探索策略

### 3.1 控制權
測試控 arrive 時機+SOC，系統自發 depart（soc≥target → `_trigger_departures()`）。

### 3.2 時間模型
dt = 1.0 秒（`config_loader.py:25`，可快轉），模擬時間上限 24h = 86,400 步（D-8）。終止基於模擬時間/步數，非注入次數——注入多被控住飽和不準。

### 3.3 arrive 挑選（覆蓋導向）
觀察 (O,L) → 列舉可行 arrive（空位×3 SOC）→ 貪心選得未訪節點 → O 滿則跳過、直推進等 depart。每隔 K=5 arrive 空轉 M 秒讓系統沉澱（D-11）。

### 3.4 終止（回到原點）
24h（86,400 步） ∥ 節點覆蓋 60% ∥ 連續 500 步無新節點。

### 3.5 可重現
固定 seed=12345（D-12），同 seed 同車跡。

---

## 4. 複用既有設施 vs 測試新建（REUSE explorer 定案）

### 4.1 複用 engine 既有設施（不重頭）

| 既有設施 | 位置 | v4 用途 |
|---|---|---|
| `validator.check(step_idx)` | `validator.py` | 逐-tick 餘存（搭 v4 逐-tick 軍）+ L4a ownership 鏡像（`_diff_pair` 已完整、逐-tick） |
| `ChargingStation.validate()` | `charging_station.py:87-119` | L2 連續區間 + 單一 ownership 檢查 |
| `engine.snapshots` | TinyDB（每 tick 快照） | trace 與 (O,L) 車跡來源（含 vehicles[].current_soc 與 output 連接） |
| `arrivals_log` | `traffic_simulator` | arrive 事件記錄 |
| arrive 底層 API | output / mcu_control | 同步注入 arrive（見 4.3） |

### 4.2 測試新建（薄層）小

| 新建項 | 內容 | 為何不能複用 |
|---|---|---|
| `is_quiescent()`（~6 行） | 彙總全部 4 個 pending 指標多乾淨穩態 | engine 的 `_all_charging_complete` 只看 2 個 open 指標，4 指標彙總只在 web 層；不 import web → 測試自行複製 ~6 行放 helper |
| L4a relay 鏡像（連動） | 相鄰 MCU 對 relay_state 鏡像比對 | validator `_diff_pair` 只比對 ownership cell，不比對 relay_state（`validator.py:98-109`） |
| L3 §11 不變量檢查內容 | min-guarantee gating、充電中 relay 須 Closed、relay 開關順序 | ChargingStation.validate 不涵蓋 SPEC §11，機制搭 validator 逐-tick 餘存，內容自建 |
| `arrival_scheduler` | 覆蓋導向選車 | 新邏輯 |
| `coverage_tracker` | 節點/766、車類/70、邊 + C4 分級 | 新邏輯 |

> **不新建整支 `stable_detect.py`**（REUSE explorer）部分必要 → 縮為 `is_quiescent()` ~6 行。
> **不碰 production**：`is_quiescent()` 放測試 helper，不加進 engine 公開層。

### 4.3 arrive 同步注入（底層 API，取代 TrafficSimulator）

TrafficSimulator `__init__` 一次排出固定。`step()` 只 pop，無運行中新增 arrival 方法（`traffic_simulator.py:41,47-51`）。v4 改用其 `_spawn` 內部的三步底層 API 直呼：

```
output.connect_vehicle(v)
mcu_controls[idx].handle_vehicle_arrival(local_idx)
engine.vehicles.append(v)
```
（參 `traffic_simulator.py:59-80`）`initial_soc` 可任意設 → 直接映射低/中/高（`vehicle.py:33`）

### 4.4 穩態判斷（is_quiescent）

穩態 = 4 個 pending 指標（`pending_intergroup_close` / `pending_output_relay_close` / `pending_intergroup_open` / `pending_output_relay_open`，於 `mcu._output_states`）皆數空，且連續 `_CONVERGE_STABLE_WINDOW` tick 無新 RelayEventLog。

- 收斂窗口常數 `_CONVERGE_STABLE_WINDOW` **import 自產品**（不寫死）
- 4 指標彙總邏輯由測試 helper 自行複製（~6 行），**不 import web、不碰 engine**
- **不搬主動 settle 迴圈**：系統 ≤18 步自動穩態（SETTLE_FREQ explorer 實證 91~96% step 穩態）

---

## 5. 雙軍驗證

### 5.1 為何雙軍
SETTLE_FREQ explorer（91~96% step 處於穩態），但部分驗證是「每-tick 性質」：穩態或切換 transient 都要。故分性質分流。

### 5.2 穩態軍（is_quiescent 為真時驗）
- **L1 狀態**：O 對應 bit 翻轉（arrive 後 L=新車 SOC、depart 後 L 不變、O=0 時 ⊥；L 測試追蹤）
- **L2 守恆**：功率守恆（Σ module_powers == 實際投入，≤額定）、借貸總帳守恆（Σ 借出==Σ 借入）
- **L2 連續區間/ownership**：複用 `ChargingStation.validate()`
- **L4a ownership 鏡像**：複用 `validator._diff_pair`（已逐-tick、相鄰對、cell 完整）
- **L4a relay 鏡像**：測試自建連動（relay_state 相鄰 MCU 鏡像）
- **L4b 借貸閉環對帳**：borrow_record == lent_record
- **L2-C 往返可逆（條件式）**：自然走回 (O=0,L=⊥) 時驗等價乾淨初始態

### 5.3 逐-tick 軍（每 tick 驗，搭 validator.check 餘存）
- **L3 不變量（每-tick 性質，測試自建內容）**：
  - I1 Σ module_powers ≤ 額定
  - I2 active output 滿足 output_min_guarantee_kw 下限
  - I3 pending 指標管理正常（無永久卡死）
  - I4 relay_states 與 module_assignment 一致
  - I5 離場後 allocated_power=0
  - **I6 SPEC §11「充電中 Output relay 須恆為 Closed」**（transient 關鍵：穩態恆滿）
- **L2 relay 切換順序**：離站不得先開 Output 後開 inter-group 等順序錯誤（DC relay 不得 ≥5A 帶切換，讓 RelayEventLog 逐 tick 歷記）

> monitor 成本 O(1)/step（~0.3µs），259k 步 <0.1 秒。

---

## 6. 覆蓋率追蹤

- **節點（主 KPI）分母 766**：key=(occupancy_byte, L_code)，來源 `engine.snapshots`，報告含 L/N 分布
- **車類（診斷）分母 70**：C4 車類分級後計數
- **邊（診斷）**：記錄轉移總數
- **未訪節點前 20**：(O,L)、Hamming distance、推測原因（行為觀察，非錯誤）
- trace 來源 = `engine.snapshots` + `arrivals_log`（**不用 export_csv**——驗證失敗才不寫）

---

## 7. 測試組織

```
tests/algo_validation/
├── conftest.py                 # fixtures（engine, scheduler, tracker）
├── test_exploration.py         # 主測試（雙軍）
└── helpers/
    ├── quiescence.py           # is_quiescent() ~6行（4指標彙總，不import web）
    ├── arrival_scheduler.py    # 覆蓋導向 arrive（底層 API 注入）
    ├── coverage_tracker.py     # 節點/766 車類/70 邊（讀 snapshots）
    ├── tick_checks.py          # 逐-tick 軍（L3 §11 內容 + L2 relay 順序，搭 validator 餘存）
    ├── steady_checks.py        # 穩態軍（L2 守恆 + L4a relay 鏡像化 + L4b）
    └── reuse_adapters.py       # 薄封裝：validator.check / ChargingStation.validate / snapshots 函數
```

**不建**：stable_detect.py（縮為 quiescence.py）、generate_dfs_path.py、events.json、獨立 mcu_consistency.py（L4a ownership 複用 validator）。

### 主迴圈骨架
```python
def test_exploration(engine, scheduler, tracker):
    initial = capture_clean_state(engine)
    while not should_terminate(tracker):
        action = scheduler.choose_next_arrive(current_state(engine), tracker)
        if action is not None:
            inject_arrive(engine, action)   # output.connect_vehicle + handle_vehicle_arrival + append
        for _ in range(step_budget):
            engine.step(1.0)
            # 逐-tick 軍（搭 validator 餘存 + 自建 L3/L2relay）
            run_tick_checks(engine)
            # 穩態軍
            if is_quiescent(engine):
                state = read_state_from_snapshot(engine)   # 讀 snapshots
                tracker.record(prev, events_since_last(engine), state)
                run_steady_checks(engine)   # L1 + L2守恆 + ChargingStation.validate + validator._diff_pair + relay鏡像化 + L4b
                if state == (O==0, L==⊥):
                    assert_reversible(engine, initial)
                break
    tracker.report()
```

---

## 8. 不在範圍
- ❌ web/前端整合、多車序、演算法內部中間步驟驗證
- ❌ **修改任何 production code**（含不在 engine 加公開方法）
- ❌ 離線預生成路徑（v3）已棄
- ❌ 保證 100% 節點覆蓋（改觀察數據）
- ❌ L2 oracle / 黃金樣本
- ❌ 主動觸發 depart（系統自發）
- ❌ 主動 settle 迴圈（被動偵測穩態）
- ❌ import web 層 `_all_pending_clear`（自行複製 ~6 行）
- ❌ 用 TrafficSimulator 注入（不支援後期，改底層 API）
- ❌ 用 export_csv 當 trace（失敗不寫，改 snapshots）
- ❌ 關閉 FR-11 以使對稱化簡成立（採真實配置，分母 766）

---

## 9. 完成判定 (DoD)

1. ✅ `quiescence.py` 的 `is_quiescent()` 彙總 4 指標、未 import web、收斂常數 import 自產品
2. ✅ arrive 用底層 API 同步注入（未用 TrafficSimulator）
3. ✅ 逐-tick 軍搭 `validator.check` 餘存，自建 L3 §11 + L2 relay 順序內容
4. ✅ 穩態軍複用 `ChargingStation.validate` + `validator._diff_pair`，自建 relay 鏡像化 + L4b
5. ✅ 覆蓋追蹤讀 `engine.snapshots`，未用 export_csv
6. ✅ `test_exploration.py` 雙軍可執行，**所有穩態 + 所有 tick 皆 PASS**（通過判據）
7. ✅ depart 全由系統自發，未 mock 核心演算法
8. ✅ **production code 未改**（git status 確認只新增測試檔）
9. ✅ 失敗訊息含車標籤 + sim_time + state(O,L) + layer + seed
10. ✅ 報告輸出：終止條件、節點覆蓋(L/N分布)、車類覆蓋(/70)、邊覆蓋、未訪前20、穩態比例實測、最長無穩態、複用設施數量、新建項數量、seed、L4 relay 鏡像本位

**覆蓋率非通過判據**：低覆蓋率為觀察，非失敗。

---

## 10. 決策點

| ID | 決策 | 預設 | 備註 |
|---|---|---|---|
| D-1 | SOC 代表值 | 低15/中55/高90% | 可調 |
| D-4 | 穩態判斷 | 測試自建 is_quiescent（4指標），不碰 production | (甲)，放 helper |
| D-6 | 離場目標車 | 系統自發 | v4 核心 |
| D-8 | 模擬時間上限 | 24h=86,400 步 | 可調 |
| D-9 | 覆蓋率門檻（終止用） | 60% | 觀察用 |
| D-10 | 停滯閾值 | 500 步無新節點 | 可調 |
| D-11 | 空轉節奏 | 每 K=5 arrive 空轉 M=? 秒 | 依沉澱時間微調 |
| D-12 | seed | 12345 | 可重現 |
| D-13 | 逐-tick monitor 範圍 | L3 全部(含 I6) + L2 relay 順序 | explorer 建議 |
| D-14 | arrive 注入 | 底層 API（connect_vehicle + handle_vehicle_arrival + append） | TrafficSimulator 不支援後期 |
| D-15 | trace 來源 | engine.snapshots + arrivals_log | export_csv 失敗不寫 |

---

## 11. 報告格式

```
=== STEP S2.X v4 完成報告 ===

[執行]
- 總步數/模擬時間 / 終止條件 / seed / wall-clock

[穩態軍]
- 穩態比例(實測)% / 最長無穩態步數
- L1 / L2守恆 / ChargingStation.validate / L4a(ownership複用+relay自建) / L4b 通過數
- L2-C 觸發次數

[逐-tick 軍]
- 總 tick 數 / L3 I1~I6 通過 / L2 relay 順序通過

[節點覆蓋（觀察，766）]
- 已訪/766 % / L 分布 / N 分布 / 未訪前20

[車類覆蓋（診斷，70）] / [邊覆蓋]

[複用 vs 新建確認]
- 複用: validator.check / _diff_pair / ChargingStation.validate / snapshots / arrivals_log
- 新建: is_quiescent / L4a relay鏡像化 / L3§11內容 / arrival_scheduler / coverage_tracker
- import web 層: NO / 改 production: NO / 用 TrafficSimulator: NO / 用 export_csv: NO

[L4 relay 鏡像本位]: ___
[未解/建議]: 覆蓋率分佈指標推測與下輪方向
```

=== 指令結束 ===
