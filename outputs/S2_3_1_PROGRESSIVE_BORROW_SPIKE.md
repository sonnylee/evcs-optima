# S2.3.1 — Progressive + Borrow Spike

**Date:** 2026-05-08
**Author:** read-only spike (no code modified, no tests run)
**Trigger:** S2.2 unlocked dynamic `module_powers`; Test C
(`test_snapshot_n4_asymmetric_with_cross_bd_borrow`) xfails because port 1 ends
up with 100 kW allocated against a 250 kW request, raising the question of
whether the bug is in (a) the test assertion, (b) progressive engagement, or
(c) cross-BD borrow.

This spike answers three load-bearing questions before S2.5 begins.

---

## 1. 範圍與目的

| Q | 問題 | 為什麼重要 |
|---|---|---|
| Q1 | Test C 的 100 kW 是「mid-settle 中間態」還是 settle 收斂後的 final state? | 決定 S2.5 是否真的有 bug 要修;若 Test C 看到的是中間態,只要修 assertion 即可。 |
| Q2 | Progressive engagement 「+1 group」 的 trigger 條件是什麼?自身 BD 上限後會自動跨 BD 嗎? | 若自身達上限後就停止擴張,bug 就在 progressive trigger;若會跨 BD 但 100 kW 仍卡住,bug 在別處。 |
| Q3 | Cross-BD borrow 的 trigger 條件是什麼? | 與 Q2 連動 — 若 cross-BD 走相同 trigger,則 Q2 的觸發路徑同時涵蓋 Q3。 |

---

## 2. Q1 — Test C snapshot 時序

**回答:final state(settle 已收斂或已達 200-tick timeout)。**

**理由:**

1. Test C(`services/evcs-api/tests/test_snapshot_module_powers.py:137`)用
   `client.post("/api/v1/snapshot/compute", ...)` 呼叫 endpoint(line 62-67)。
2. Route handler `services/evcs-api/app/api/v1/snapshot.py:32-37` 是
   `async def compute(...)` 直接 `await compute_snapshot_async(...)`。
3. `compute_snapshot_async`(`state_calculation_service.py:29-49`)第一步:
   `engine = await WebSessionEngine.create(system, car_ports)`,然後才
   `engine.to_visual_snapshot()`。
4. `WebSessionEngine.create`(`web_session_engine.py:136-152`)的 contract:
   ```python
   instance = cls(system_config, car_ports)
   if any(p.max_required > 0 for p in instance._car_ports):
       await instance._settle_until_stable()
   return instance
   ```
   Test C 有一個 port `max_required=250 > 0`,所以 settle loop **一定會跑**。
5. `_settle_until_stable`(`web_session_engine.py:213-246`)迴圈條件:
   - 至多 `_CONVERGE_TIMEOUT_TICKS = 200` ticks(line 62)。
   - 早停條件:`cur == last and self._all_pending_clear()` 連續 5 次
     (`_CONVERGE_STABLE_WINDOW = 5`,line 63、236-239)。
6. `to_visual_snapshot` 是在 settle 結束後才執行,讀的是穩態硬體
   (`web_session_engine.py:262-411`,逐塊讀 `engine.station.boards[i]`)。

**結論:Test C 的 100 kW 是 final state。** 不是中間態。

---

## 3. Q2 — Progressive 「+1 group」 trigger

**回答:trigger 條件 = `Present > 0 AND |Present − Available| < 0.01 AND
demand > Available`,且必須連續成立 `_consecutive_threshold`(預設 3)個
ticks。**

**達到自身 BD 上限後:(b)會自動跨 BD,但需先在 local-first 的兩側都
exhausted 才會切到 cross-MCU。**

**實作位置:**

| 概念 | 函式 | 位置 |
|---|---|---|
| Trigger 判斷 | `_tick_borrow_condition` | `simulation/modules/mcu_control.py:195-212` |
| 觸發後嘗試擴張 | `_try_borrow_async` | `mcu_control.py:245-285` |
| 選擇下一個 group | `_find_expansion_target` | `mcu_control.py:751-781` |

**理由:**

- Trigger 條件具體在 `mcu_control.py:204-208`:
  ```python
  if (present > 0
      and abs(present - available) < 0.01
      and vehicle.max_require_power_kw > available + 0.01):
      state.borrow_counter += 1
  ```
  滿 `_consecutive_threshold` 才回傳 True(line 212)。

- `_find_expansion_target`(line 751-781)排序:
  1. 優先 `right_v = interval_max + 1`,若 `_can_assign(allow_cross_mcu=False)` 通過 → 回傳。
  2. 否則 `left_v = interval_min - 1`,同樣 local-first(line 774)。
  3. 兩側 local 都 fail 時,才以 `allow_cross_mcu=True` 重試(line 776-780)。
  
  即「自身 BD 沒空 group」時會自動切到鄰居 BD;**前提**是
  `_tick_borrow_condition` 有觸發 + `_can_assign` 物理上允許。

- `_try_borrow_async` 拿到 cross-MCU target 後,`send_borrow_request` 給鄰居
  (line 271-273)、由鄰居自行切自己的 relays(SPEC §11)。

**重要的隱含 gate(直接影響 Test C):**

`_pre_step_guard`(`mcu_control.py:184-193`)在 borrow 邏輯之前先呼叫
`_advance_relay_phases`(line 439-491)。當一輛車剛抵達、`pending_*` 任何
一個非 0 時,`_pre_step_guard` 回傳 True → **borrow 邏輯整個 tick 被
跳過**,且 `borrow_counter` 被重置為 0(line 488-489)。

特別地,`_advance_relay_phases` 第 455-465 行:
```python
if state.pending_output_relay_close == 2:
    self._sync_output(i)
    if self._board.outputs[i].available_power_kw + 1e-9 >= MIN_START_POWER_KW:
        # close output relay, reset pending=0
        ...
```
若 `available < 125 kW`,**relay 不切換、pending 不歸零** — 下一 tick 會
再次走進這個分支,維持 `pending == 2`,使 `_pre_step_guard` 永遠回傳 True。

---

## 4. Q3 — Cross-BD borrow trigger

**回答:trigger 條件與 Q2 progressive 的 trigger **完全相同**。Cross-BD
不是另一個獨立 trigger,而是 progressive expansion 在 local-first 失敗後的
fallback 路徑。**

**實作位置:**`simulation/modules/mcu_control.py:245-285`(`_try_borrow_async`,
完整 cross-MCU 流程)+ `mcu_control.py:776-780`(在 `_find_expansion_target`
中切換 `allow_cross_mcu`)。

**理由:**

- Cross-MCU 入口仍是 `_tick_borrow_condition`(同 Q2)。
- 在 `_try_borrow_async` 中拿到 target 後,line 250 判斷
  `_is_local_group(target)`:若 True → 直接 `_apply_borrow`;若 False →
  `_get_neighbor_for_group` + `send_borrow_request`(line 254-273)。
- 鄰居端 `_handle_borrow_request`(line 373-389)用
  `_ma.assign_if_idle` 做原子授權,再 `_sync_foreign_relays(step_index)`
  自己切自己的 relays(SPEC §11 ownership)。
- `_can_assign`(`mcu_control.py:809-826`)在 `allow_cross_mcu=False` 時
  line 820 主動拒絕跨界 target;`allow_cross_mcu=True` 時放行。

換言之:**borrow trigger 本身不分 local / cross;分歧只在
expansion target 的選擇。** Q2 與 Q3 共用同一個 entry point。

---

## 5. Bonus B1 — Test C final state 真的卡在 100 kW 嗎?

**結論:是,而且根本原因不在 borrow trigger 本身,而在 `_pre_step_guard` /
`_advance_relay_phases` 把 borrow 機會吃掉的 SPEC §11 gating 互鎖。**

**推論鏈(基於 §2-§4,沒有跑 test):**

1. Test C 設定:BD1=[50,50,50,50],port 1 max_required=250(轉成 flat curve
   `[(0,250),(100,250)]`,`web_session_engine.py:157-158`)。
2. `SimulationEngine.__init__` 對 port 1 呼叫 `handle_vehicle_arrival(0)`
   (`simulation_engine.py:102-105`)。
3. `handle_vehicle_arrival`(`mcu_control.py:493-581`)為 output 0 設
   `interval = [G0, G1]`(line 495-497)、claim G0+G1、設
   `pending_intergroup_close = 1`(line 579)。此時 G0+G1 = 50+50 = 100 kW。
4. Settle loop tick 0:`_advance_relay_phases` 將
   `pending_intergroup_close` 從 1 升為 2(line 452-453),`_pre_step_guard`
   回傳 True → 跳過 borrow。
5. Settle loop tick 1:`pending_intergroup_close == 2` → 關 inter-group
   relay、加 event log、`pending_intergroup_close = 0`、
   `pending_output_relay_close = 1`(line 448-451);同 tick 接著 1 → 2
   (line 464-465)。回傳 True → 跳過 borrow。
6. Settle loop tick 2 起:`pending_output_relay_close == 2` → check
   `available_power_kw (100) >= 125 kW` ?**否**,所以 relay 不切、pending
   **不歸零**(line 458-463 沒有 `else` 分支)。
7. 之後每個 tick 都重複 step 6。`_pre_step_guard` 永遠回傳 True → borrow
   邏輯永遠不執行 → `borrow_counter` 永遠在 0(line 488-489)。
8. Settle 終止條件 `_all_pending_clear()` 永遠 False
   (`web_session_engine.py:248-258`),所以 stable_streak 永遠不到 5。
9. Settle 跑滿 200 ticks 後 fall-through(line 222 `for _ in range(200)`)。
10. `to_visual_snapshot` 讀:`output_relay.state == OPEN` →
    `allocated_kw = 0`(`web_session_engine.py:388`)。Test C 斷言
    `125 <= allocated <= 250` 失敗 → xfail strict pass。

**注:** Test C xfail 訊息中提到「output_relay=CLOSED」,但這個訊息來自
`__init__` 內 `_log_engagement_state` 的 print(`web_session_engine.py:192-209`),
列印時 `_advance_relay_phases` **尚未執行任何 tick**,初始 output relay 狀態
是 OPEN 才對。xfail 訊息文字可能是早期版本或筆誤;無論如何,從邏輯推
**最終 final state 的 output_relay 仍是 OPEN**(SPEC §11 ≥125 kW gate 阻止
關閉)。

**Bug 定位:**
- **不在** Q2/Q3 的 trigger 條件(它們本身設計合理)。
- **在** `_advance_relay_phases` 與 `_pre_step_guard` 的互鎖:當
  `pending_output_relay_close == 2` 且 `available < 125 kW` 時,系統陷入
  「等 relay 關 ⇄ 等 borrow 增 available」的死結 — borrow 因為 guard 永遠
  跑不到,available 因此永遠 < 125。
- 換句話說:**progressive engagement 在 settle 期間需要在 output relay
  尚未閉合的狀態下「先 borrow 到 ≥125 kW、再閉合 relay」,但目前 guard
  的設計把 borrow 也擋掉了。**

---

## 6. Bonus B2 — Cluster C 3 個 xfail 跟這個議題的關聯

| Test | 與 Test C 議題的關聯 |
|---|---|
| **`test_port_two_anchors_at_far_end`**(`test_snapshot.py:91-97`) | **不同類**。`_cfg(1)`、port 2、75 kW(3 packs)。考的是 anchor 位置(`handle_vehicle_arrival` 對 output 1 設 `[G2, G3]`)以及 pack-level 排列。沒有 borrow、沒有 ≥125 gate 互鎖議題;它的 xfail 原因是 `_SPRINT1_REASON`(N=1 時 Sprint-1 envelope 鎖定 4 MCU × [50,75,75,50])。 |
| **`test_priority_determines_allocation_order`**(`test_snapshot.py:177-192`) | **不同類**。`_cfg(2)`,兩個 port 都要 300 kW(12 packs)、總 supply 20 packs。重點考 priority-based 飢餓排序;與 Test C 的 SPEC §11 gate 死結無關。同樣以 `_SPRINT1_REASON` 標 xfail,代表是 Sprint-1 envelope 限制,非 progressive/borrow logic bug。 |
| **`test_oversubscribed_emits_warnings`**(`test_snapshot.py:225-231`) | **可能同類(無法從 read-only 完全確定)**。`_cfg(1)`,兩個 port 各 200 kW、1 REC BD 250 kW total。N=1 沒有鄰居,所以 cross-BD borrow 路徑天然不可達。但兩個 port 都會試圖擴張到 200(超過自身 BD 一半 125),會在自身 BD 內互搶 group → 觸發 conflict release。**若**這條路徑也碰到「avail<125 → guard 死結」,則同類;但因為 N=1 + [50,75,75,50] 下 anchor 區段已是 50+75=125 或 75+50=125,理論上滿 125 gate,死結不會觸發 — 所以較可能是「starvation 警告未發」這個獨立 bug。**判斷需要實測確認**。 |

---

## 7. S2.5 範圍建議

基於 §2-§6 推論,S2.5 應該針對的是:

> **「Test C 真卡在 100 kW + bug 在 progressive trigger 的 SPEC §11 gating
> 互鎖」** — 具體位置在 `simulation/modules/mcu_control.py` 的
> `_advance_relay_phases`(line 439-491)+ `_pre_step_guard`(line 184-193)
> 兩個方法的互動邏輯。

不需要(本 spike 範圍內)動的:

- `_tick_borrow_condition`(Q2 trigger 條件)— 設計合理。
- `_find_expansion_target`(Q2 local-first / cross-MCU 切換)— 設計合理。
- `_try_borrow_async` / `send_borrow_request`(Q3 cross-BD 路徑)— 設計合理。
- Test C assertion 本身 — 它測的是 SPEC 預期的合法行為,不是錯的 assertion。

需要動的核心命題(僅描述「該動哪」,不寫 patch):

1. **打破死結**:當 `pending_output_relay_close == 2` 且 `available < 125 kW`
   時,允許 borrow 邏輯仍然執行,讓 progressive 把 available 拉到 ≥125。
   可能的方向:
   - 在 `_pre_step_guard` 加一個「output relay 等 125 kW 中」的特例,放行
     borrow tick。
   - 或在 `handle_vehicle_arrival` 把初始 group 數做成 `module_powers`-aware
     (確保 anchor + 初始 groups ≥125 kW),例如 BD1=[50,50,50,50] 時開
     [G0..G2] 而不是 [G0..G1]。
2. 兩種方向都要重新驗證 SPEC §11(「Output relay 必須在 ≥125 kW 才能閉合」)
   仍然成立。

Bonus B2 中 `test_oversubscribed_emits_warnings` 是否同源,**建議在 S2.5
途中加一個 instrumented test 確認**(本次 read-only 無法定論)。

其餘兩個 Cluster C xfail(`test_port_two_anchors_at_far_end`、
`test_priority_determines_allocation_order`)屬於 Sprint-1 envelope 解鎖
任務,**與本 spike 主題不相干**,應在 S2 別的 step 處理。

---

## 8. 附錄:讀過的檔案與重要行號

| 檔案 | 行號 | 看了什麼 |
|---|---|---|
| `services/evcs-api/tests/test_snapshot_module_powers.py` | 1-229(全) | Test C 全文 + xfail 訊息 |
| `services/evcs-api/app/api/v1/snapshot.py` | 1-52(全) | 兩個 snapshot route handler 都 await async |
| `services/evcs-api/app/services/state_calculation_service.py` | 1-62(全) | `compute_snapshot_async` 中 `await WebSessionEngine.create(...)` |
| `services/evcs-api/app/services/web_session_engine.py` | 1-422(全) | `create()` 一定觸發 settle、`_settle_until_stable` 200-tick + 5-stable cap、`to_visual_snapshot` 讀的是穩態 |
| `simulation/modules/mcu_control.py` | 1-200, 200-490, 751-826, 945-1090 | 借電 trigger / find expansion / cross-MCU 流程 / `handle_vehicle_arrival` / `_advance_relay_phases` 互鎖 |
| `simulation/modules/vehicle.py` | 50-95 | `vehicle.step` 設 `present = min(max_req, available)`,不 gate on relay state |
| `simulation/environment/simulation_engine.py` | 85-115 | `handle_vehicle_arrival` 在 `__init__` 結束前被呼叫 |
| `simulation/utils/topology.py` | 1-74(全) | ring/linear 規則(本 spike 未直接用,僅確認 N=4 = ring) |
| `services/evcs-api/tests/test_snapshot.py` | 1-60, 75-235 | `_SPRINT1_REASON`、Cluster C 三個 xfail 上下文 |
