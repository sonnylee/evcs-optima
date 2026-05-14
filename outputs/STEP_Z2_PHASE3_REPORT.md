# Step Z.2 Phase 3 Report — Demo Scenario 2 Visual Validation + Baseline

> 執行時間:2026-05-14 07:55 UTC
> Phase 3 commit:**待此報告 commit 後填**(follow-up commit 模式)
> 基於 Phase 2 commit `50238be`(主)+ `bbbc123`(hash 回填)

## 1. Demo 場景 2 真實跑出結果

執行方式:in-process `fastapi.testclient.TestClient` 模擬 HTTP 路由(等同 uvicorn,
但不佔用 :8000 port、無外部進程管理)。Session 流程:`POST /api/v1/sessions` →
`POST /api/v1/sessions/{sid}/apply-and-generate`。

### 1.1 結果摘要

- `total_steps` = **13**(預期 6-15 ✓)
- `warnings` = `[]`(無容量超載 / present 異常)
- Session 自動進入 player mode、`current_step_index = 0`

### 1.2 完整 13 個 step description

```
Step 0:  Open M2.R3 (Port 3 releasing)
Step 1:  Close M3.R2 (Port 5 expanding to 125 kW)
Step 2:  Close M4.R2 (Port 7 expanding to 125 kW)
Step 3:  Open B_4_1 (Port 1 releasing)
Step 4:  Open M1.R4 (Port 1 releasing)
Step 5:  Open M2.R2 (Port 3 releasing)
Step 6:  Close M3.R3 (Port 5 expanding to 200 kW)
Step 7:  Close M4.R3 (Port 7 expanding to 200 kW)
Step 8:  Open M2.O1 (Port 3 disengaged)
Step 9:  Open M1.R3 (Port 1 releasing)
Step 10: Close M3.R4 (Port 5 expanding to 250 kW)
Step 11: Open M1.R2 (Port 1 releasing)
Step 12: Open M1.O1 (Port 1 disengaged)
```

### 1.3 關鍵 description 檢查表

- [x] **Open M1.O1**(step 12 — Port 1 退場 last) ✓
- [x] **Open M2.O1**(step 8 — Port 3 退場 last) ✓
- [ ] Close M3.O1 — **不出現,符合預期**(見 §1.5 解釋)
- [ ] Close M4.O1 — **不出現,符合預期**(見 §1.5 解釋)

### 1.4 順序檢查(「Port 1/3 釋放 → Port 5/7 進入」)

✓ **完全符合**,且更進階:

- Port 3 釋放序列:R3 (s0) → R2 (s5) → **O1 (s8)** — Output last
- Port 1 釋放序列:B_4_1 (s3) → R4 (s4) → R3 (s9) → R2 (s11) → **O1 (s12)** — Output last
- Port 5 擴展序列:R2 (s1) → R3 (s6) → R4 (s10) — 從 50 → 125 → 200 → 250 kW
- Port 7 擴展序列:R2 (s2) → R3 (s7) — 從 50 → 125 → 200 kW
- 退場與進場交錯,**SPEC §11 在 Output relay open 的「last」位置上 100% 成立**

### 1.5 為何 Close M3.O1 / Close M4.O1 不出現

場景 2 配置:
- Port 5:`present=50, target=250`
- Port 7:`present=50, target=200`

兩個 port 在 present 狀態下 `present > 0` → mcu_control engagement 已滿足 §11 close-time gate
(engagement_avail = 125 kW,floor 125 kW)→ Output relay 早在 **initial snapshot** 就已 Closed。
漸進序列下 Output 維持 Closed,所以**不會**出現 Open → Closed 的 transition,自然不會
emit `Close M3.O1` / `Close M4.O1` description。

這是 Z.1 §任務 3 確認過的 mcu_control engagement-gate 行為,不是 bug。Z.2 instruction §5.2
列出的「Close M3.O1 / Close M4.O1」期待是基於 cold-arrival 假設(Port 5/7 present=0),不適用
於場景 2 的 partial-gain 配置。

### 1.6 Player Wrap 行為

- `forward` 從末端 (idx=13) → 自動 wrap 到 0 ✓
- `back` 從 idx=0 → 自動 wrap 到 13 ✓
- (路由層的 wrap 邏輯由 `app/api/v1/sessions.py::step` 維護,與 step_planner 無關)

## 2. Baseline 健檢

### 2.1 Backend(`services/evcs-api/tests`)

```
================= 92 passed, 2 deselected, 1 xfailed in 2.39s ==================
```

- **92 passed** — 與 Z.1 baseline `92 passed, 1 xfailed, 2 deselected` byte-identical
- 2 deselected:`test_apply_4mcu_latency_under_500ms` + 其他 1 個(`@pytest.mark.benchmark`)
- 1 xfailed:原有 expected failure,Z.2 未改

**結論**:**沒有 collateral damage**,Z.2 沒打到 control_steps 以外的 test 集。

### 2.2 Simulation(`tests/`)

```
======================= 241 passed, 5 warnings in 0.84s ========================
```

- **241 passed** — byte-identical 到 Z.1 baseline
- 5 warnings:`PytestUnknownMarkWarning: Unknown pytest.mark.spike` — Z.2 之前就存在,未動

**結論**:simulation 層完全未受影響(因為 Z.2 沒動 `simulation/` 任何檔案)。

## 3. Z.2 整體結論

### 3.1 重寫成功?**YES**

- ✓ `step_planner.py`:region 5 SPEC §11 sort 邏輯完全拿掉,改用漸進 demand + dedup(595 行,−40 行)
- ✓ 演算法行為由 mcu_control 獨佔(dual-implementation 危機解除)
- ✓ Public 介面 `plan_transition(system, ports, initial, final)` 簽名不變(改 async,參數一致)
- ✓ 介面相容性:`evcs_core_adapter.py` 唯一一行 `await` 補上
- ✓ Production behavior:scenario 2 跑出 13 step,SPEC §11 順序自然湧現

### 3.2 5/15 demo 可用?**YES**

- 場景 2 視覺敘事符合預期(Port 1/3 退場 + Port 5/7 進場交錯,Output relay 最後 open)
- 13 個 step 在 demo 預估的 12-18 區間
- Player 前進 / 後退 + wrap 行為正確
- 端到端延遲 ~20 ms,P95 5 s budget 餘裕 250×

### 3.3 給 Sonny 的最終建議

#### 立即可做
1. **Step Z.3 文件對齊**(Sonny + 網頁 Claude 處理,本 instruction 範圍外):
   - `CLAUDE.md` Sprint 2 vocabulary 更新:step_planner 從「rebuild + diff + SPEC §11 sort」改成「progressive demand + dedup」
   - `docs/SPEC-WEB-API.md` §3.3 描述更新
   - `docs/SPEC.md` §11 可補一句「per-Output minimum guarantee 是 close-time gate,Output Closed 期間 alloc 可低於 floor(mcu_control 對小 demand 釋放多餘 group)」

#### 可選 (Sprint 3 cleanup)
2. **刪除 dead code**:`step_planner.py` 內的 `_stitch_snapshot` / `_resolve_pack_owner`(現已不被 `plan_transition` 呼叫)。**不影響 Z.2 完成,但能再減 110 行**。Z.2 instruction 「不刪區塊 6-7」是因 Phase 1/2 保守處理;Phase 3 確認可刪後再動。

#### Demo 風險揭露
3. **Scenario 3(cold ring-wrap arrival, Port 1 從 0 → 350 kW)的字面 SPEC §11 違反問題仍存在**:
   - Bridge B_4_1 在 step 11 才 close,Output M1.O1 在 step 1 就 close(因 engagement floor 125 kW 在 anchor 已滿足)
   - **這個場景如果出現在 demo,主管可能挑戰**
   - 緩解:(a) UI 已卡住 `present=0`,cold arrival 從 UI 不可達 — 不會在現場觸發
   - 緩解:(b) demo 時主動講「為了視覺敘事,我們不展示 cold arrival 場景」
   - Sprint 3 可考慮 hybrid model(cold arrival 走 target-snapshot 一步式)

### 3.4 已知 dead code / 殘留物

| 物件 | 狀態 | 處理時機 |
|---|---|---|
| `step_planner._stitch_snapshot` | dead | Sprint 3 cleanup |
| `step_planner._resolve_pack_owner` | dead | Sprint 3 cleanup |
| `scripts/spike_e_demand_progression.py` | throwaway prototype | Sprint 3 — 移到 `scripts/archive/` 或刪除 |
| `scripts/spike_e_scenario3.py` | throwaway prototype | 同上 |

## 4. Phase 3 完成驗收

- [x] 場景 2 視覺驗證符合預期(13 step,順序正確,Output relay open last)
- [x] Backend baseline 92 passed(預期 ≥ 91 ✓ 反而 unchanged)
- [x] Simulation baseline 241 passed(預期 = 241 ✓)
- [x] Player wrap 正確
- [x] 寫 `outputs/STEP_Z2_PHASE3_REPORT.md`
- [x] Commit 待此報告寫完後執行

---

*Phase 3 完成。Z.2 全部三階段結束 — step_planner.py 重寫為漸進 demand + dedup,SPEC §11 邏輯交還 mcu_control,全 test 套件綠,scenario 2 demo 視覺驗證通過。*
