# Step Z.2 Phase 1 Report — Region 5 Rewrite

> 執行時間:2026-05-14 07:30 UTC
> 環境:commit `3306dc5` (main, before Z.2)
> Phase 1 commit:`399cc47`

## 1. 變動清單

### 修改檔案
- `services/evcs-api/app/adapters/step_planner.py`(主要重寫)
- `services/evcs-api/app/adapters/evcs_core_adapter.py`(1 行:`await` 補上)

### 刪除函式(全部位於原 region 5)
- `_schedule_flips`
- `_order_within_port`
- `_engage_key`
- `_disengage_key`
- `_negate_relay_id`
- `_build_schedule`

### 新增函式(取代 region 5)
- `_progressive_demand(initial, step_index)` — 算第 N 步漸進 max_required
- `_target_reached(ports)` — 終止條件
- `_generate_progressive_snapshots(system, car_ports)` async — 走漸進序列、每步 `WebSessionEngine.create()` 取 snapshot
- `_dedup_snapshots(snapshots)` — 去除連續同 `(relay_state, pack_owner)` 的 snapshot

### 改寫函式
- `plan_transition` — 從 sync 改為 **async**。介面參數簽名不變;`initial_state`/`final_state` 接收但不再內部依賴(每個漸進 snapshot 都是 mcu_control settle 後的合法穩態)。

### 保留(未動)
- Region 1: `_Phase`、`_phase_of`、`_prio_key`
- Region 2: `_RelayFlip`、`_relay_diff`
- Region 3: 拓樸 helper 5 個
- Region 4: `_attribute_flip`、`_adjacent_pack_owners`
- Region 6: `_stitch_snapshot`、`_resolve_pack_owner`(**未刪,但目前 dead code**;按指示「不刪區塊 6-7 的任何函式」保留)
- Region 7: `_describe`

### 配套改動
- `evcs_core_adapter.py:145` —
  ```python
  # before
  steps = step_planner.plan_transition(...)
  # after
  steps = await step_planner.plan_transition(...)
  ```

## 2. 行數變化

| 指標 | 改動前 | 改動後 | 差 |
|---|---|---|---|
| `step_planner.py` 總行數 | 635 | 595 | −40 |
| Region 5 刪除函式行數 | ~123 (lines 237–359) | 0 | −123 |
| 新增漸進邏輯行數 | 0 | ~85 (lines 234–319) | +85 |
| `plan_transition` 行數 | 48 | 49 | +1 |
| Top docstring | 28 行 | 27 行 | −1 |

淨刪除 40 行,主因:`_schedule_flips`/`_order_within_port` 的 phase 排序與 sort key helper 拿掉,改用更精簡的漸進 + dedup。

## 3. Smoke test

### 3.1 Import + 結構
```
$ python -c "from app.adapters import step_planner; ..."
plan_transition is async: True       ✓
has _build_schedule: False           ✓ (已刪除)
has _generate_progressive_snapshots: True   ✓
```

### 3.2 Spike script(WebSessionEngine 路徑沒壞)
```
$ python scripts/spike_e_demand_progression.py
Total snapshots: 13
Unique snapshots (after dedup): 8
Total elapsed: 32 ms
Final state: 4/4 ✓ (M1.O1 Open, M2.O1 Open, M3.O1 Closed, M4.O1 Closed)
```

### 3.3 End-to-end via `generate_control_steps`(scenario 2)
- total_steps = **13**(預期 6-15 區間 ✓)
- 前 8 步 description:
  ```
  Step 0: Open M2.R3 (Port 3 releasing)
  Step 1: Close M3.R2 (Port 5 expanding to 125 kW)
  Step 2: Close M4.R2 (Port 7 expanding to 125 kW)
  Step 3: Open B_4_1 (Port 1 releasing)
  Step 4: Open M1.R4 (Port 1 releasing)
  Step 5: Open M2.R2 (Port 3 releasing)
  Step 6: Close M3.R3 (Port 5 expanding to 200 kW)
  Step 7: Close M4.R3 (Port 7 expanding to 200 kW)
  ```
- 後 5 步:
  ```
  Step 8:  Open M2.O1 (Port 3 disengaged)
  Step 9:  Open M1.R3 (Port 1 releasing)
  Step 10: Close M3.R4 (Port 5 expanding to 250 kW)
  Step 11: Open M1.R2 (Port 1 releasing)
  Step 12: Open M1.O1 (Port 1 disengaged)
  ```

**SPEC §11 順序觀察**:
- Port 3 退場:M2.R3 (step 0) → M2.R2 (step 5) → **M2.O1 (step 8)** ✓ Output last
- Port 1 退場:B_4_1 (step 3) → M1.R4 (step 4) → M1.R3 (step 9) → M1.R2 (step 11) → **M1.O1 (step 12)** ✓ Output last

## 4. 進入 Phase 2 前的 blocker

**無**。架構運作正常,Phase 2 可以開始跑 test 套件對焦。

## 5. 給 Sonny 的問題

**1 個 minor 提示**:

- `_stitch_snapshot` 與 `_resolve_pack_owner` 在 Z.2 後變成 dead code(`plan_transition` 不再呼叫)。按 Z.2 instruction 「不刪區塊 6-7」保留。**Phase 3 結束後可考慮刪除**(或留待 Sprint 3 cleanup)。

**1 個 instruction 落差需確認**(已自決,寫進 Phase 3 報告即可):

- Instruction §5.2 預期看到「Close M3.O1、Close M4.O1」四個關鍵 description。但場景 2 中 Port 5/7 是「partial gain」(present=50, target=250/200),其 Output relay 在 present 狀態下已經 Closed(因為 50 kW 已過 SPEC §11 close-time gate 的工程行為),所以漸進過程**不會**出現 `Close M3.O1` / `Close M4.O1`。**這是預期行為,Phase 3 視覺驗證會以 invariant 為準而非 literal match**。

---

*Phase 1 完成。介面行為:scenario 2 跑出 13 step、SPEC §11 順序自然湧現。等候 Sonny 確認後進 Phase 2。*
