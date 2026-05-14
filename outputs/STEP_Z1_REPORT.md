# Step Z.1 Report — Pre-flight Investigation for 方案 E 重寫

> 執行時間:2026-05-14 07:10 UTC
> 環境:commit `3306dc5` (main)
> Prototypes:`scripts/spike_e_demand_progression.py`(已加 debug log)、`scripts/spike_e_scenario3.py`(新建)
> Production code 與 tests 零變動,未 commit

---

## 任務 1:PRESENT_POWER 差距調查

### 判定結果
**(c) — mcu_control 真實行為:離散群組量化**(benign,SPEC-compliant)

### 證據

跑 `spike_e_demand_progression.py` 加 debug log 後的 step 0 breakdown:

```
snap.total_power_kw    = 600
snap.total_requested_kw = 550
Per-port car.allocated_kw:
  Port 1: allocated=300, max_required=300, status=Active     ← exact
  Port 3: allocated=200, max_required=150, status=Active     ← +50 kW over
  Port 5: allocated= 50, max_required= 50, status=Active     ← exact
  Port 7: allocated= 50, max_required= 50, status=Active     ← exact
  Sum(car.allocated_kw) = 600
Per-BD bd.power_kw:
  BD 1: power=250, used_packs=10/10
  BD 2: power=200, used_packs= 8/10   ← Port 3 占 8 packs = 200 kW
  BD 3: power= 50, used_packs= 2/10
  BD 4: power=100, used_packs= 4/10
  Sum(bd.power_kw) = 600
Pack ownership by port: P1=12 packs (300), P3=8 packs (200), P5=2 packs (50), P7=2 packs (50)
```

**關鍵點**:Port 3 user_max=150,但 mcu_control 實際分配 200(占 8 packs 等於 50+75+75)。**因為 SMR Group capacity 是離散的(50/75/75/50),mcu_control 一次只能借走整個 group,所以「達到 150」不存在,必須跳到下一個離散級 = 200**。

### total_power_kw 計算邏輯

`services/evcs-api/app/services/web_session_engine.py:382-411` —

```python
total_allocated = 0
for port_id in range(1, system.car_port_count + 1):
    ...
    output = board.outputs[local_idx]
    output_relay = board.output_relays[local_idx]
    ...
    allocated_kw = int(output.available_power_kw) if output_relay.state == RelayState.CLOSED else 0
    ...
    total_allocated += allocated_kw

return VisualSnapshot(
    ...
    total_power_kw=total_allocated,           # ← sum of per-port allocated
    total_requested_kw=sum(p.max_required for p in self._car_ports),   # ← sum of user max
    ...
)
```

`total_power_kw` = 每個 port 的 `output.available_power_kw`(整數化)之加總,**只計算 Output relay 已 CLOSED 的 ports**。`state_calculation_service.py` 是 thin wrapper(SPEC-WEB-API §3.2 rebuild-engine),沒有獨立的計算路徑。

### 對 Z 方案重寫的影響

- **不需改 production code**:`total_power_kw` 計算正確反映物理現實(實體 SMR group 已 commit 該 capacity)。
- **demo 解說要注意**:`total_power_kw` 與 `total_requested_kw` 會出現差距(過剩 0–75 kW per port),需在 demo 解說中強調「kW 是物理 commit 的容量,非車輛實際吸收量」,並可指向 `total_requested_kw` 作為「實際吸收」對照。
- **新增 demo 顯示欄位的想法**:Sprint 3 可考慮在前端同時顯示 `total_power_kw`(committed)與 `total_requested_kw`(drawn),減少觀眾混淆。

---

## 任務 2:test_control_steps.py 影響評估

### 統計

**26 個 test**(instruction 寫 24,實際檔案為 26 — 兩個額外 test 是 F14.4 補上的 dual-port 與 walkthrough 測試,不影響評估方法)。

| 命運分類 | 數量 |
|---|---|
| PASS_AS_IS | 18 |
| UPDATE_EXPECTED | 1 |
| REWRITE | 2 |
| UNCLEAR | 5 |
| **總計** | **26** |

**預估總改動工時:30-90 分鐘**(主要在 UNCLEAR 類的實際驗證)

### 逐 test 明細

| # | Test 名稱 | Assertion 類型 | Z 後命運 | 工時 | 註 |
|---|---|---|---|---|---|
| 1 | test_identity_no_change_required | step_count=0 | PASS_AS_IS | 0 | total_steps == 0 不變 |
| 2 | test_target_exceeds_capacity_warns_does_not_raise | warning_emission | PASS_AS_IS | 0 | warning 邏輯獨立 |
| 3 | test_priorities_insufficient_raises | exception_path | PASS_AS_IS | 0 | validator 短路,不進 step_planner |
| 4 | test_arrival_holds_output_open_until_125kw | relay_state_invariant + description literal | **UNCLEAR** | medium | walk 所有 step 檢查 `alloc < floor → Output Open`。Z 在離散量化下也應通過,但需驗證 description `"Close M1.O1"` 仍會出現(Z 的 description 由 `_describe` 區塊 7 生成,理論上不變)|
| 5 | test_arrival_below_125kw_never_closes_output | relay_state_invariant | **UNCLEAR** | medium | 此 test 預期「demand 75 kW 時 alloc 會 over-provision 到 125 kW;期間 alloc < 125 時 Output Open」。在 Z 漸進模型下,小 demand 進站的中間 snapshot 可能呈現 alloc=50, Output Closed(見 §任務 3 觀察)。**有違反風險** |
| 6 | test_full_departure_opens_output_last | relay_state_invariant(最後一步前 inter-group 已開) | PASS_AS_IS | 0 | Z 場景 2 的 Port 1/3 退場已驗證該模式 ✓ |
| 7 | test_partial_release_keeps_output_closed | relay_state_invariant | PASS_AS_IS | 0 | 200→125 不歸零,Output 始終 Closed |
| 8 | test_priority_drives_arrival_order | step_index_compare + description literal | **UNCLEAR** | small | Port 3 (priority 1) 必須先 engaged。Z 在 `WebSessionEngine` placement order 已注入 priority。但 description 順序需驗證 |
| 9 | test_unreasonable_present_warns_does_not_abort | warning_emission | PASS_AS_IS | 0 | sum-overflow warning 路徑獨立 |
| 10 | test_ring_wrap_borrow_4_rec_bds | final_state(bridge closed) | PASS_AS_IS | 0 | 只看最後 snapshot,跟順序無關 |
| 11 | **test_schedule_phase_ordering** | **call `step_planner._build_schedule()` 直接** | **REWRITE** | medium | `_build_schedule` 是 region 5 私有函式,Z 重寫後**會消失**。需改成 invariant-based assertion 或刪除 |
| 12 | test_apply_is_deterministic | sequence equality | PASS_AS_IS | 0 | Z 仍 deterministic(同 input → 同 progressive sequence) |
| 13 | test_apply_4mcu_latency_under_500ms | performance(<500ms) | **UPDATE_EXPECTED** | small | Z 一次 plan 跑 ~13 次 create(scenario 2 為 36ms;scenario 3 為 31ms)。500ms 預算仍綽綽有餘,**理論可 PASS**,但保守估計可放寬至 1000ms |
| 14 | test_route_apply_and_generate_persists_sequence | route_integration | PASS_AS_IS | 0 | total_steps >= 1 即可,不挑剔具體值 |
| 15 | test_route_apply_and_generate_404_for_missing_session | route_integration | PASS_AS_IS | 0 | |
| 16 | test_route_apply_and_generate_target_over_capacity_warns | route_integration | PASS_AS_IS | 0 | |
| 17 | test_route_apply_and_generate_422_priorities_insufficient | route_integration | PASS_AS_IS | 0 | |
| 18 | test_route_get_control_steps | route_integration | PASS_AS_IS | 0 | |
| 19 | test_route_get_control_steps_404_when_no_sequence | route_integration | PASS_AS_IS | 0 | |
| 20 | test_route_step_player_wraps_at_ends | route_integration | PASS_AS_IS | 0 | wrap 邏輯在 route 層,獨立 |
| 21 | test_route_patch_invalidates_step_sequence | route_integration | PASS_AS_IS | 0 | |
| 22 | **test_ring_borrow_closes_bridge_before_output** | step_index_compare 「`bridge_idx < output_idx`」 | **REWRITE** | large | 詳見 §任務 3:Z 在進站場景下,Output 因 engagement floor 滿足而**先**關閉,bridge 待 demand 漲到跨 MCU 才關閉。**Z 違反「bridge before output on arrival」字面意義**。需在 Z.2 設計階段討論 |
| 23 | test_mixed_departure_then_arrival_phase_ordering | step_index_compare(`Open M1.O1` < `Close M3.O1`)| **UNCLEAR** | medium | Phase A 全部先於 Phase C 是區塊 5 的承諾;Z 漸進模型下兩者會交錯(release 與 acquire 同步進行)。需驗證 description literal 仍存在於序列中且順序正確 |
| 24 | test_full_load_apply_completes_within_budget | performance(<500ms,8 ports) | **UNCLEAR** | small | 8 ports × 125 kW 都進站,Z 漸進步距 25 kW × 5 step ≈ 5 × 1 engine create ≈ 5–50 ms;預期 PASS |
| 25 | test_route_apply_then_full_player_walkthrough | route_integration | PASS_AS_IS | 0 | |
| 26 | test_dual_port_per_bd_stitched_final_matches_engine_final | final_state pack ownership + description "Port 2" literal | **UNCLEAR** | medium | 最後 snapshot pack ownership 必須等於 target_engine.snapshot — Z 用最終 step 對應 target snapshot,理論 PASS;但「any 'Port 2' in s.description」依賴 Z 的 description 對特定 port 標記,需驗證 |

### 高風險 test(REWRITE 類)詳述

**#11 — `test_schedule_phase_ordering`**
- 直接呼叫 `step_planner._build_schedule(ports)`,這是區塊 5 的私有函式
- Z 重寫會徹底拿掉 `_build_schedule` / `_schedule_flips` / `_order_within_port` / `_engage_key` / `_disengage_key`,所以這個 test **import 階段就會壞**
- 修法選一:
  - (a) 直接刪除這個 unit test(它測的是被淘汰的內部結構)
  - (b) 改寫成 black-box test:對整個 `plan_transition` 結果驗證「全部 Phase A port 的最後一步 index < 任何 Phase C port 的第一步 index」

**#22 — `test_ring_borrow_closes_bridge_before_output`**
- 字面意義 SPEC §11「bridge 先關 → Output 後關」
- 但 Z 漸進模型下,**EV 被建模為「以 25 kW 步距漸進到 max」**,Output 在 demand 剛達 floor(125 kW)時就會被決定關閉,而 bridge 直到 demand > 250 kW(local MCU 滿載)才會關閉
- 兩種因應:
  - (b1) Z.2 在 step_planner 對「同一個 plan 內 final_state 涉及跨 MCU 的 port」**直接從 target_state engine 取最終 snapshot 作為第一個 step**(跳過漸進,因為這是真正的「進站」場景而非「漸進升載」)
  - (b2) 接受 SPEC §11 字面違反,把 test 改寫成「**最終 snapshot** bridge & Output 都 Closed」(only final state matters)。但這個改動需要 Sonny 與主管確認

### UNCLEAR 類的處理計畫

5 個 UNCLEAR test 都依賴 description literal(`"Close M1.O1"`、`"Port 2"` 等)或具體 step 順序。Step Z.2 重寫完成後,**第一步應該是跑這 5 個 test 看實際結果**,再決定:
- 若全 PASS → 列入 PASS_AS_IS
- 若部分 FAIL → 修 description format 或改 invariant-based assertion

---

## 任務 3:場景 3 sanity check(Ring Wrap Borrow)

### 執行結果

| 指標 | 結果 |
|---|---|
| 總 snapshot 數 | 15 |
| Unique snapshot 數 | 7 |
| Final state Port 1 allocated | **375 kW**(預期 350) |
| Final state M1.O1 | Closed ✓ |
| Final state B_4_1 | **Closed** ✓ |
| 總執行時間 | 31 ms |
| P95 per create | 3.2 ms |

`375 kW`(預期 350)同樣是離散量化 — Port 1 = BD1 完整 250 + BD4 兩個 group (75+50 = 125) = 375 kW。

### §11 自然湧現驗證

- [✗] **Port 1 Output relay (M1.O1) 是否在累積功率 ≥ 125 kW 之後才 Close?**
  - **NO**:M1.O1 在 **step 1 (P1 alloc=50 kW)** 就 Closed
  - **解釋**:`output.available_power_kw`(engagement avail)在 close 決策時為 125 kW(§11 floor)。引擎判斷可關 → 關閉 → 隨後在穩態 release 多餘 group → snapshot 顯示 alloc=50 kW Closed
  - **這跟 SPEC §11 字面衝突**(`alloc < floor` 時 Output 不應 Closed),但跟 mcu_control 既有行為一致(`test_arrival_below_125kw_never_closes_output` 既有 comment 已承認 engine "over-provisions to 125 kW even when user demand is below it"——但 snapshot 卻顯示 alloc=50,沒有 over-provision)
  - **潛在 bug**:`available_power_kw` 在 close 後是否該維持 125 而非降到 50?這是 mcu_control 行為議題,**不在 Z.1 修補範圍**,留報告請 Sonny 確認

- [✗] **Bridge B_4_1 是否在 inter-group relay 之前 Close?**
  - **NO**:B_4_1 在 **step 11** 才 Close,inter-group `M1.R2`(step 3)、`M1.R3`(step 6)、`M1.R4`(step 9)都先於 bridge
  - **為什麼**:Z 漸進模型把進站當成「demand 從 0 慢慢爬到 350」,bridge 只有 demand 超過 local MCU 容量(250)時才需要,所以晚到
  - **這跟 SPEC §11「bridge close before output on arrival」嚴重衝突**

- [ ] **沒有任何 step 違反 §11 invariant?**
  - 違反 ×2(見上)

### 結論

**FAIL** — 場景 3 在 Z 漸進模型下產生的步驟序列,**與 SPEC §11 對「跨 MCU 進站」的字面要求不符**。
具體:
1. M1.O1 在 alloc < 125 kW 時 Closed
2. Bridge B_4_1 在 Output 已關之後才 Closed

這兩點對 demo 場景 3 是**致命的**(主管可當場挑戰 SPEC §11 violation)。

### 對 Z.2 設計的影響

Z 方案需要在「漸進升載」與「進站」之間做 model split:

| 場景 | model |
|---|---|
| Demo 場景 2 — Present (port 在線) → Target (port 退站 / 升載) | **漸進 demand 序列**(Z 原案) |
| Demo 場景 3 — Present (port 離線 = 0) → Target (port 進站 350 kW) | **進站場景 = 一步式 target snapshot**(跳過漸進)|

**判定門檻**:某 port `present == 0 且 target > 0` → 該 port 用 target-state engine 的最終 snapshot 直接表示,不走漸進

實作上 Z.2 可這樣設計區塊 5:
1. 分類每個 port:`departure / partial_release / partial_gain / arrival(cold)`
2. 對 `arrival(cold)` port:從 target_engine 直接讀 final snapshot,作為一個 step
3. 對其他 port:走 Z 漸進序列
4. 兩者按 SPEC §11 phase ordering(arrivals 跟在 departures 後面)合併

---

## 整合判斷:Step Z.2 是否可進行?

### 三個任務的判定

- **任務 1**(PRESENT_POWER 差距):**(c) 離散量化,benign**
- **任務 2**(test 影響評估):2 個 REWRITE + 5 個 UNCLEAR + 1 個 UPDATE,總工時估計 60–120 分鐘(視 UNCLEAR 實測結果)
- **任務 3**(場景 3 sanity check):**FAIL**(SPEC §11 字面違反 ×2)

### 對 Step Z.2 的建議

**CONDITIONAL GO** — 在以下條件成立後可進 Z.2:

1. **Z.2 必須採 hybrid model**:
   - cold arrival port(present=0, target>0)→ 從 target_engine 直接取 snapshot,**不走漸進**
   - 其他變化(departure / partial release / partial gain)→ 走 Z 漸進序列
   - 兩者按 phase ordering 合併
   - 這個 split 在實作工時上需要從 Z 原案的「~120 行重寫」放大到「~200 行重寫 + 區塊 5 重新切割」
2. **Sonny 需要確認 mcu_control 行為**:
   - 「Output 在 alloc < floor 時 Closed」(scenario 3 step 1)是 mcu_control 既有行為。是 spec compliant 還是 bug?
   - 如果是 spec compliant(close-time gate 而非 ongoing invariant),`test_arrival_below_125kw_never_closes_output` 的 invariant 寫太嚴,可放寬
   - 如果是 bug,需在 Z.2 同步修(scope 進一步放大)
3. **接受 2 個 test REWRITE**(`#11 _build_schedule`、`#22 ring_borrow_bridge_before_output`)
4. **接受 UPDATE_EXPECTED ×1**(`#13` 延遲 budget 從 500ms 放寬到 1000ms,保留 4 倍 SPEC budget 餘裕)

---

## Sonny 接下來要做的事

1. **貼此報告回 Claude(網頁 chat)** — 取得對 hybrid model 的設計回饋,特別是 cold arrival 走 target_engine 一步式的可行性
2. **決定 §任務 3「Output 在 alloc < floor 時 Closed」是 bug 還是 by design** — 影響 Z.2 是否需同步動 mcu_control
3. **(可選)在 Z.2 前先確認 demo 場景的 narrative tolerance** — 場景 3 中 bridge 晚於 Output close 是否可接受作為 demo 敘事(「EV 慢慢加大需求,系統逐步加 group」)而非主管期望的「進站一次接通」

---

*Step Z.1 完成。Prototypes 在 `scripts/` 下(throwaway),production code 與 tests 零變動,未 commit。*
