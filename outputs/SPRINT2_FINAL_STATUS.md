# Sprint 2 Final Status

**Sprint 2 起訖**:2026-05-08 ~ 2026-05-11
**最終 baseline**:
- backend pytest (`services/evcs-api/tests`):**92 passed, 1 xfailed, 2 deselected**
- simulation/ pytest (`tests/`):**241 passed**
- frontend tsc (`web/evcs-ui && npx tsc --noEmit`):**0 errors**

---

## 1. Sprint 2 主要 milestone

### 1.1 FR-10 — REC BD 數量動態化(dim B 的一部分)

- 解鎖範圍:`rec_bd_count ∈ [1, 12]`(N=1 → 單 MCU、N=2 → linear、N ≥ 3 → ring)。
- 達成 step:
  - **S2.1** — 後端 `WebSessionEngine` 接 `system_config.rec_bd_count` 透傳到 `SimulationConfig.num_mcus`
  - **S2.2** — `simulation/` 接受任意 `module_powers_per_mcu`
  - **S2.6** — 前端 `ConfigPanel` 把寫死的 placeholder 換掉,接 `RecBdCountInput`(`web/evcs-ui/src/components/config-panel/RecBdCountInput.tsx`)
- 驗證:`services/evcs-api/tests/test_snapshot_dynamic_n.py` 5 個 N 場景(N=1 / 2 / 3 / 5 / 6)。

### 1.2 FR-11 — 每 REC BD `module_powers` 動態化(dim B)

- 解鎖範圍:每 REC BD 獨立 `[a, b, c, d]`,值需是 25 的整數倍且 ∈ [50, 100]。**每 BD 固定 4 modules(dim A)鎖定到 Sprint 3**。
- 達成 step:
  - **S2.2** — `module_powers` 由 web config 流到 `RectifierBoard`(baseline byte-identical)
  - **S2.3** — `test_snapshot_module_powers.py` 加 5 個 test(uniform / asymmetric / cross-BD borrow / etc.)
  - **S2.6** — 前端 `ModulePowerInput` 每 BD 一個(debounced 400 ms validate-and-parse)
- 驗證:`test_snapshot_module_powers.py` 5 個 test 全綠。

### 1.3 SPEC §11 — Available Power gate 改為動態 per-Output 最小保證

- Sprint 1 行為:`Output.available_power_kw >= 125 kW`(寫死)。
- Sprint 2 行為:`Output.available_power_kw >= output_min_guarantee_kw(module_powers, output_local_idx)`。
- Helper 位置:`simulation/modules/mcu_control.py:24-39`。
- 公式:
  - O0(anchor 在 G0):`module_powers[0] + module_powers[1]`
  - O1(anchor 在 G3):`module_powers[3] + module_powers[2]`
- Default `[50,75,75,50]` 下兩 Output 都算出 125 kW(byte-identical against Sprint 1 hardcoded value)。
- 唯一 production caller:`MCUControl._advance_relay_phases:473-474`(SPEC §11 動態最小保證;default 配置下 = 125 kW)。
- 達成 step:**S2.5ab**(production + SPEC §11 docs)+ **S2.5c**(test refactor: 4 個 test 檔內把寫死的 125 局部變數改用 helper)。

### 1.4 FR-09 / FR-14 engine path 一致性(Sprint 2 spike 驗證)

- 兩種模式共用同一個 `WebSessionEngine._settle_until_stable()` engine loop。
- FR-14 = engine 跑兩次(`max_required = present`、`= target`)+ `step_planner` 後處理 snapshot diff。
- **`Vehicle.present_power_kw` 每 tick 由 `Vehicle.step(dt)` 重算**(`simulation/modules/vehicle.py:58-84`),結果 mirror 到 `Output.present_power_kw` 並驅動 `MCUControl._tick_borrow_condition`(SPEC §6.1 borrow counter,`mcu_control.py:216`)。
- **`Vehicle.max_require_power_kw` 在 FR-09 / FR-14 web path 為 flat curve**(`WebSessionEngine._flat_curve(port.max_required)` 構造的 2-point line,0-100% SOC 都對應 user 設的常數)。
- 驗證來源:`outputs/S2_8_PRESENT_POWER_LIFECYCLE.md` + `outputs/S2_8_SOC_CURVE_LIFECYCLE.md`。

---

## 2. Sprint 1 → Sprint 2 baseline 演化

| Step | backend passed | xfailed | 摘要 |
|---|---|---|---|
| Sprint 1 收尾 | 73 | 12 | 起點(`[50,75,75,50] × 4 MCU` 鎖定) |
| S2.1 | 78 | 12 | `num_mcus` 解鎖 + 5 N test |
| S2.1.1 | 85 | 3 | lock fallout(9 xfail 翻綠 + 2 刪) |
| S2.2 | 85 | 3 | `module_powers` 動態化(byte-identical) |
| S2.3 | 88 | 5 | dim B 驗證(Test C 揭露 SPEC §11 / borrow 議題) |
| S2.5ab | 90 | 3 | SPEC §11 production fix(動態最小保證 helper)+ lock fallout |
| S2.5c | 90 | 3 | test 內寫死的 125 改用 helper(byte-identical) |
| S2.4 階段 2 | 92 | 1 | Cluster C 處置(§B / §C 翻綠,§D 留) |
| **S2.6 + S2.8** | **92** | **1** | 前端動態 ConfigPanel + doc 收尾 |

Simulation `tests/`:整段 Sprint 2 維持 241 passed。Frontend tsc:0 errors。

---

## 3. Step 完整清單 + commit hash

| Step | 性質 | commit | 報告 / 文件 |
|---|---|---|---|
| S2.0 | read-only spike | e257714 | `outputs/S2_0_DYNAMIC_GROUPS_ASSESSMENT.md` |
| S2.1 | production | 1c1925c | (in chat report) |
| S2.1.1 | test patch | b3a8d70 | (in chat report) |
| S2.2 | production | a5c924f | (in chat report) |
| S2.3 | test (add) | 1c2b6f3 | (in chat report) |
| S2.3.1 | read-only spike | (報告先於本 commit) | `outputs/S2_3_1_PROGRESSIVE_BORROW_SPIKE.md` |
| S2.3.2 | read-only spike | (報告先於本 commit) | `outputs/S2_3_2_SPEC_125KW_LOCATIONS.md` |
| S2.5ab (production + SPEC §11) | production + SPEC | d9dc08b、de0f467 | (in chat report) |
| S2.5ab lock fallout | test patch | 83c035a | (in chat report) |
| S2.5c | test refactor | b875842 | (in chat report) |
| S2.4 階段 1 | read-only spike | (報告先於本 commit) | `outputs/S2_4_CLUSTER_C_ASSESSMENT.md` |
| S2.4 階段 2 | test patch | a05a3c6 | (in chat report) |
| S2.6 spike | read-only spike | (報告先於本 commit) | `outputs/S2_6_FRONTEND_SPIKE.md` |
| S2.6 | frontend | 4e93418 | (in chat report) |
| S2.8 vocab spike | read-only spike | (本 commit 一併收) | `outputs/S2_8_VOCAB_SPIKE.md` |
| S2.8 present_power lifecycle spike | read-only spike | (本 commit 一併收) | `outputs/S2_8_PRESENT_POWER_LIFECYCLE.md` |
| S2.8 SOC curve lifecycle spike | read-only spike | (本 commit 一併收) | `outputs/S2_8_SOC_CURVE_LIFECYCLE.md` |
| S2.8 doc 收尾 | docs + central index | (本 commit) | (本檔) |

(Read-only spike 報告若在本 commit 之前已 untracked / 已 commit,僅列出 commit hash 的是已合入 main 的;標「(報告先於本 commit)」者代表報告檔已存在於 `outputs/`,但具體 commit 經 `git log` 比對未直接落到單一 hash — 可由 `git log --follow outputs/<file>` 進一步比對。)

---

## 4. Sprint 3 啟動準備

### 4.1 已知議題 / 留下的 xfail

- **§D `test_oversubscribed_emits_warnings`** — `services/evcs-api/tests/test_snapshot.py`。Per-port shortfall warning policy gap:當 station 在 SPEC §11 minimum guarantee 累加下達到 capacity(範例:port_1 user_max=200 + port_2 user_max=200,合計 400 kW > 1 REC BD 容量 250 kW;engine 給每 port 125 kW = 共 250 kW),engine 不發 per-port shortfall warning。SPEC FR-08 / FR-14 未明確定義此類 warning 是否該發。
  - **Sprint 3 product decision**:
    - **option A** — 在 `WebSessionEngine` / `state_calculation_service` 加 per-port shortfall warning emission(production 改動)
    - **option B** — 改 test 為「engine gracefully clamps」(去掉 warning assertion,保留 `total_power_kw == 250` invariant)
  - 詳見 `outputs/S2_4_CLUSTER_C_ASSESSMENT.md §D`。

### 4.2 dim A 解鎖(group count 可變)

Sprint 2 只動 dim B。dim A 等於 Sprint 3 的核心題目。`outputs/S2_0_DYNAMIC_GROUPS_ASSESSMENT.md` 列出大約 50 處需動點,主要是:

- `simulation/modules/mcu_control.py` — 14 處 `GROUPS_PER_MCU` + L46 `ANCHOR_GROUP_LOCAL_IDX = (0, GROUPS_PER_MCU - 1)`
- `simulation/utils/topology.py` / `simulation/data/relay_matrix.py` / `simulation/data/module_assignment.py` — 多處 `* GROUPS_PER_MCU` 與 hard-coded 4
- `simulation/hardware/rectifier_board.py` — L52 `4 * num_mcus`、L57 `range(3)`(group-spans-3 假設)、L72 `[0, 3]`(anchor pair)、L97-101 cross-MCU label 字串、L114-126 Phase 1 partition
- `simulation/environment/vision_output.py:159` — `["OFF"] * 4` 預設 row(per-MCU 4 inter-group columns)

### 4.3 SPEC §11 helper 在 dim A 下的演化

Sprint 2 helper(`output_min_guarantee_kw`)寫了 4-modules 假設(`module_powers[0]+[1]` for O0,`module_powers[3]+[2]` for O1)。Sprint 3 dim A 開放時公式應變為:

- O0(anchor 在 first):`module_powers[0] + module_powers[1]`
- O1(anchor 在 last):`module_powers[-1] + module_powers[-2]`

`len(module_powers) >= 2` 是新公式的最小前提。

### 4.4 Engine architecture 觀察(Sprint 2 spike 驗證)

#### 4.4.1 Legacy CLI 與 web settle path 是 parallel implementation

- `SimulationEngine.run()`(`_run_sync` / `_driver_loop`)與 `WebSessionEngine._settle_until_stable()` 是兩條 parallel implementation。
- 共用相同 per-tick semantics(`vehicle.step(dt)`、`mcu.send(Tick)`、`station.step(dt)`、`tc.tick()`)但各自實作。
- **Sprint 3 若動 vehicle.step 或 borrow trigger logic,必須在兩處 mirror 改動**,或考慮重構共用 helper。
- 詳見 `outputs/S2_8_PRESENT_POWER_LIFECYCLE.md §4`。

#### 4.4.2 Web service 使用 flat SOC curve;CSV path 對 web 而言是死代碼

- `Vehicle.max_require_power_kw` 在 FR-09 / FR-14 web path 由 `WebSessionEngine._flat_curve(port.max_required)` 構造,interpolator 對任意 SOC 都回傳 user 設的 `max_required` 常數。
- 真實 EV charging curve `associate/ev_curve_data.csv` + `ConfigLoader.load_csv()` 僅由 `simulation/utils/schedule_builder.py:31` 呼叫(CLI / demo 用),web service code 從不走到。
- 兩條 parallel curve provider share `VehicleProfile` shape 但 caller graph 完全不交集。
- **Sprint 3 若要做真實 EV 充電行為模擬**,需 web service 接上 CSV path(或 web 自己提供一條更合理的 curve)。
- 詳見 `outputs/S2_8_SOC_CURVE_LIFECYCLE.md §2-§6`。

#### 4.4.3 `_tick_return_condition` 在 SPEC §11 動態化下未驗證

- S2.5ab 把 `_tick_borrow_condition` 對應的 SPEC §11 gate 改成 dynamic per-Output 最小保證(透過 `output_min_guarantee_kw` helper)。
- `_tick_return_condition` 讀的是 `Vehicle.max_require_power_kw` 直接判斷(不直接讀 SPEC §11 最小保證),理論上不依賴 helper;但 Sprint 3 dim A 解鎖時 group return path 是否仍正確,值得 spike 驗證。
- 詳見 `outputs/S2_8_PRESENT_POWER_LIFECYCLE.md §6`。

### 4.5 其他 Sprint 3+ 觀察

- **`MIN_ENGAGE_KW` 已刪**:S2.5ab 刪了 `step_planner.py` 內的死代碼常數。Sprint 3 若補 step_planner per-port 最小保證 logic,需重新從 `output_min_guarantee_kw` helper 讀,**不要再寫死 125**。
- **前端 0 個 Vitest test**:S2.6 spike Q6 揭露 — `find web/evcs-ui -name '*.test.*'` 完全沒命中。Sprint 3 / chore 補。
- **5 個 pytest unknown mark warning**(`@pytest.mark.spike`):自 S2.0 起就有,可在 `pyproject.toml` 註冊解決。

---

## 5. Sprint 2 vocabulary canonical(Sprint 3 reader 的 source of truth)

> 舊代碼 / 舊報告中出現過的非正式術語(test-local 變數除外)在正式 doc 中**一律避免**;改用下表的精確變數名 + SPEC §4.1 / §11 對應名詞。詳細的 deprecated 名單見 `outputs/S2_8_VOCAB_SPIKE.md` §8。

| 概念 | 程式中變數 | Lifecycle | 說明 |
|---|---|---|---|
| **`CarPortInput.max_required`** | `services/evcs-api/app/schemas/car_port.py:20` | user input,session-persisted | API 層 user-declared 每 port 上限(int kW [0, 600], 25 倍數)。FR-09 與 FR-14 都用此值餵 engine。**不是** `Vehicle.max_require_power_kw`(後者是 engine 的 float kW 並走 SOC curve interpolation)。 |
| **`CarPortInput.present`** | `services/evcs-api/app/schemas/car_port.py:21` | user input,只在 FR-14 用 | API 層 user-declared transition 起點(int kW [0, 600])。**不是** `Vehicle.present_power_kw`。FR-09 完全不消費。 |
| **`CarPortInput.target`** | `services/evcs-api/app/schemas/car_port.py:22` | user input,只在 FR-14 用 | API 層 user-declared transition 終點。 |
| **`Vehicle.max_require_power_kw`** | engine field — float kW(`simulation/modules/vehicle.py:36, 80`) | 每 tick 由 `Vehicle.step(dt)` 透過 `_interpolate_power(current_soc)` 對 per-vehicle `soc_power_curve` 插值 | **在 FR-09 / FR-14 web path 中,curve 由 `WebSessionEngine._flat_curve(port.max_required)` 構造(0-100% SOC 都回傳 user 設的常數)**。CLI / demo path(`ConfigLoader.load_csv → associate/ev_curve_data.csv`)提供真實 SOC-dependent CSV curve,**但 web code path 從不走到**。對應 SPEC §4.1 「Max Require Power」概念。 |
| **`Vehicle.present_power_kw`** | engine field — float kW(`simulation/modules/vehicle.py:37, 83`) | 每 tick 由 `Vehicle.step(dt)` 重算 | `= min(self.max_require_power_kw, self.output.available_power_kw)`,結果同時 mirror 到 `output.present_power_kw`;後者被 `MCUControl._tick_borrow_condition`(`simulation/modules/mcu_control.py:216`)每 tick 讀取以驅動 SPEC §6.1 borrow counter。FR-09 與 FR-14 engine path 行為一致(同一個 `_settle_until_stable` loop)。對應 SPEC §4.1 「Present Power」概念。 |
| **`Output.available_power_kw`** | engine field — float kW(`simulation/hardware/output.py:29`) | 每 tick 由 `MCUControl._sync_output`(`mcu_control.py:962-991`)依據 currently-connected SMR groups 更新 | MCU Control 評估自身餘裕後產出的「現在最多能給多少」;反映「目前已連接的 SMR groups 加總」,**不是**靜態 max,**也不是** SPEC §11 per-Output 最小保證閾值本身。對應 SPEC §4.1 「Available Power」概念。`web_session_engine.py:209` 印 log 用的 print-time 別名只是這個 field 的另一個顯示名,不是另一個概念。 |
| **`output_min_guarantee_kw(module_powers, output_local_idx)`** | helper at `simulation/modules/mcu_control.py:24-39` | derived constant per (config, output_idx) | SPEC §11 per-Output minimum guarantee。公式:O0 = `module_powers[0] + module_powers[1]`、O1 = `module_powers[3] + module_powers[2]`。Default `[50,75,75,50]` 下兩 Output 都算出 125 kW(即 Sprint 1 寫死 125 的來源)。**唯一 production caller**:`MCUControl._advance_relay_phases:473-474`。正式 doc 一律寫 `output_min_guarantee_kw` 或「per-Output 最小保證」;test 檔內的 local 變數另計。 |
| **`CarSnapshot.allocated_kw`** | engine → snapshot — int kW | 每 snapshot 輸出 | 由 `WebSessionEngine.to_visual_snapshot` 從 `Output.available_power_kw` int 化而成。**`allocated_kw` 是 MCU 配給的 Available Power,不是 Vehicle 實際吃的 Present Power**。兩者在 `Vehicle.max_require_power_kw < Output.available_power_kw` 時可見差異(例:flat curve 下 max_require = 75 但 SPEC §11 minimum guarantee 把 Output.available 拉到 125)。 |

### 5.1 詳細 spike 報告

- `outputs/S2_8_VOCAB_SPIKE.md` — vocab 初版 catalogue。**注意**:此檔對 vehicle 每 tick method 的名字引用是錯的;正確 method 名是 `Vehicle.step(dt)`(於 `simulation/modules/vehicle.py:58`)。歷史保留,不修。
- `outputs/S2_8_PRESENT_POWER_LIFECYCLE.md` — `Vehicle.present_power_kw` 每 tick lifecycle + FR-09 / FR-14 engine 對稱性 + borrow trigger 因果鏈。
- `outputs/S2_8_SOC_CURVE_LIFECYCLE.md` — `Vehicle.max_require_power_kw` 來源(flat curve vs CSV curve)+ web service / CLI 兩條 parallel curve provider 觀察。
