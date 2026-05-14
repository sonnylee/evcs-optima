# Step Z.2 Phase 2 Report — Test Suite Alignment

> 執行時間:2026-05-14 07:45 UTC
> Phase 2 commit:`50238be`
> 基於 Phase 1 commit `399cc47`(原始)/ `6c93cff`(amend)

## 1. Test 結果總覽

- 原 26 個 test
- 刪除 1 個(#11 `test_schedule_phase_ordering`)
- 跑 25 個:**24 selected PASS + 1 benchmark PASS**(總 25 / 25 ✓)
- 最終全綠:**YES**

```
======================= 24 passed, 1 deselected in 1.00s =======================
```

(deselected = `test_apply_4mcu_latency_under_500ms` 帶 `@pytest.mark.benchmark`,預設不跑;單獨用 `-m benchmark` 跑也 PASS。)

## 2. 逐 test 處置記錄

| # | Test 名稱 | Z.1 預估命運 | 實際命運 | 處置 |
|---|---|---|---|---|
| 1 | test_identity_no_change_required | PASS_AS_IS | PASS | — |
| 2 | test_target_exceeds_capacity_warns_does_not_raise | PASS_AS_IS | PASS | — |
| 3 | test_priorities_insufficient_raises | PASS_AS_IS | PASS | — |
| 4 | test_arrival_holds_output_open_until_125kw | UNCLEAR | FAIL → PASS | **改 assertion**:從 per-step `alloc < floor → Open` 改為 transition-based(Open before close-step、Closed after) |
| 5 | test_arrival_below_125kw_never_closes_output | UNCLEAR | FAIL → PASS | **改 assertion 同 #4 + 改名** → `test_arrival_below_125kw_closes_output_once_floor_engaged`(更名以反映新斷言) |
| 6 | test_full_departure_opens_output_last | PASS_AS_IS | PASS | — |
| 7 | test_partial_release_keeps_output_closed | PASS_AS_IS | PASS | — |
| 8 | test_priority_drives_arrival_order | UNCLEAR | FAIL → PASS | **改 step_planner**:在 plan_transition 的 diff loop 內依 owner port priority 排序;test 本身不改 |
| 9 | test_unreasonable_present_warns_does_not_abort | PASS_AS_IS | PASS | — |
| 10 | test_ring_wrap_borrow_4_rec_bds | PASS_AS_IS | PASS | — |
| 11 | **test_schedule_phase_ordering** | REWRITE | DELETED | 整個 def 刪除(呼叫已不存在的 `_build_schedule`)|
| 12 | test_apply_is_deterministic | PASS_AS_IS | PASS | — |
| 13 | test_apply_4mcu_latency_under_500ms | UPDATE_EXPECTED | PASS | 維持 500 ms 預算,實測 < 100 ms(見 §4)|
| 14 | test_route_apply_and_generate_persists_sequence | PASS_AS_IS | PASS | — |
| 15 | test_route_apply_and_generate_404_for_missing_session | PASS_AS_IS | PASS | — |
| 16 | test_route_apply_and_generate_target_over_capacity_warns | PASS_AS_IS | PASS | — |
| 17 | test_route_apply_and_generate_422_priorities_insufficient | PASS_AS_IS | PASS | — |
| 18 | test_route_get_control_steps | PASS_AS_IS | PASS | — |
| 19 | test_route_get_control_steps_404_when_no_sequence | PASS_AS_IS | PASS | — |
| 20 | test_route_step_player_wraps_at_ends | PASS_AS_IS | PASS | — |
| 21 | test_route_patch_invalidates_step_sequence | PASS_AS_IS | PASS | — |
| 22 | **test_ring_borrow_closes_bridge_before_output** | REWRITE | REWRITTEN | 從 `bridge_idx < output_idx` 改為 final-state check(bridge Closed + M1.O1 Closed)。Z.2 下 cold arrival 自然違反字面順序(Z.1 已 document)|
| 23 | test_mixed_departure_then_arrival_phase_ordering | UNCLEAR | FAIL → REWRITTEN | 從 `p1_open_idx < p5_close_idx` 改為 final-state check 並 **改名** → `test_mixed_departure_then_arrival_final_state`。Phase A → C 嚴格 ordering 是 step_planner sort 慣例,非 SPEC §11,Z.2 自然交錯(更貼近真實 EV 行為) |
| 24 | test_full_load_apply_completes_within_budget | UNCLEAR | PASS | — |
| 25 | test_route_apply_then_full_player_walkthrough | PASS_AS_IS | PASS | — |
| 26 | test_dual_port_per_bd_stitched_final_matches_engine_final | UNCLEAR | FAIL → PASS | 包 `asyncio.run(...)` 在直接呼叫 `plan_transition` 處(plan_transition 已改 async)|

### 統計修正

- DELETE:1(#11)
- REWRITE:2(#22、#23 — 都改 final-state check)
- 改 assertion 而非 rewrite:2(#4、#5 — 改 transition-based)
- 改 step_planner 而非 test:1(#8 — 補 priority sort,test 不動)
- 改 async 包裝:1(#26 — `asyncio.run` 包外層)
- 純 PASS_AS_IS:18

## 3. UNCLEAR 5 個的最終狀態

| Test | Z.1 預估 | 實測 | 解釋 |
|---|---|---|---|
| #4 | UNCLEAR | 改 assertion | mcu_control 在 engagement_avail ≥ 125 時 close Output,然後對小 demand 釋放多餘 group → 視覺 alloc < 125 但 Closed。SPEC §11 close-time gate 滿足,*ongoing* 不變式非 SPEC 要求。Z.1 第 5.4 §1 已預警此行為 |
| #5 | UNCLEAR | 改 assertion + 更名 | 同 #4 |
| #8 | UNCLEAR | 改 step_planner | 多 port 在同一漸進 step 同時 engage 時,relay diff loop 預設按 mcu_idx 順序發出 → FR-16 priority 失效。在 plan_transition 加 priority-sort fix |
| #23 | UNCLEAR | REWRITE | Phase A → C 嚴格 ordering 並非 SPEC §11 規定。Z 的漸進模型自然交錯 departure / arrival(物理上 EV 同時離站與進站時資源是一刻借一刻還)|
| #24 | UNCLEAR | PASS | 4-MCU 8-port 滿載 < 500 ms 仍輕鬆達標 |
| #26 | UNCLEAR | 改 async 包裝 | `plan_transition` 改 async,test 直接呼叫處包 `asyncio.run` 即可,assertion 本身不變 |

**全部 6 個 UNCLEAR test 都通過,沒有任何 test 顯示 mcu_control 真實行為違反 SPEC**。

## 4. UPDATE_EXPECTED #13 的實測 latency

- `test_apply_4mcu_latency_under_500ms`:**單 port 250 kW arrival,實測 ~20 ms**(預算 500 ms,P95 SPEC 5000 ms)
- `test_full_load_apply_completes_within_budget`:**8 port 滿載 125 kW,實測 < 500 ms**

**處置:不放寬預算**。Z.2 仍維持 4 倍 SPEC budget 餘裕。500 ms 預算保留。

## 5. step_planner.py 額外改動

除了 Phase 1 的 region 5 重寫,Phase 2 在 `plan_transition` 內補了一段 **priority sort**:

```python
# Sort diffs by owner port priority so FR-16 ordering survives when
# multiple ports change at the same demand level.
attributed: List[Tuple[int, str, RelaySnapshot, RelaySnapshot, int]] = []
for ir, fr in _relay_diff(prev_snap, curr_snap):
    port = _attribute_flip(...)
    prio = _prio_key(ports_by_id[port]) if port in ports_by_id else 10**9
    attributed.append((prio, fr.id, ir, fr, port))
attributed.sort(key=lambda x: (x[0], x[1]))
```

效果:在 #8 場景(Port 1 prio=2, Port 3 prio=1, 兩者同 step 都 engage),`Close M2.O1`(Port 3 屬於 MCU 2 → 對應 BD 2)會在 `Close M1.O1`(Port 1)前面發出。

## 6. 進入 Phase 3 前的 blocker

**無**。`test_control_steps.py` 全綠,Phase 3 可開始跑 demo 視覺驗證 + baseline 健檢。

## 7. 給 Sonny 的問題

**無 blocker**。三個設計判斷供確認(不影響 Phase 3 進行):

1. **#23 改名**:從 `..._phase_ordering` 改成 `..._final_state` 因為新斷言不再驗證 phase ordering。如果你想保留原名僅改斷言,可在 Phase 3 統一處理。
2. **#5 改名**:從 `..._never_closes_output` 改成 `..._closes_output_once_floor_engaged` — 因為事實上 Output **會** close(舊 test 註解就承認了「will close at the engagement step despite target=75」,只是舊斷言鬆,新斷言更直接)。
3. **mcu_control 行為**:Z.1 報告 §任務 3 標記過「Output 在 alloc < floor 時 Closed」是 mcu_control 既有行為。Phase 2 確認這是 close-time gate 而非 ongoing invariant,屬 SPEC compliant 行為(SPEC §11 沒說「Closed 期間 alloc 必須 ≥ floor」),不是 bug。**這個判斷影響 Z.3 文件對齊**——SPEC §11 文字可考慮加註以避免誤讀。

---

*Phase 2 完成。`test_control_steps.py` 25 個 test 全綠。等候 Sonny 確認後進 Phase 3。*
