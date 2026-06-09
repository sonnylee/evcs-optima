# STEP S3 — Cross-MCU 借入者離場 orphan relay 最小回歸測試

> **背景**:F1 的 A1 不變量於 commit `<F1-commit>` 在 exploration test 抓到 production bug——跨-MCU 借入者離場後,出借方 MCU 的 inter-group relay 被遺留 CLOSED(MA mirror 已 release,relay 狀態漏同步)。Root cause 在 `_finalize_departure:660-665` 只做 `ma.release + _mirror_release`,未通知 lender MCU resync;`_open_departure_intergroup_relays:599-643` 只開離場者自己 MCU 的 relay。Production 修覆已完成,A1 已自動轉綠。
>
> **本次任務**:把這個 bug class 從「exploration 機率性抓到」升級為「**單元測試確定性守門**」。寫一支獨立、確定性、毫秒級的 pytest,**每次 CI 都必走「跨-MCU 借入 → 借入者離場 → 斷言 lender relay 釋放」**,跟 seed/scheduler 無關。
>
> **動機(若覺得 A1 已足夠請重看)**:A1 是統計性抓到——seed=12345 恰好走到 step 847 才觸發。換個 seed 就可能整個 run 都沒踩到這條路 → bug 重生無人知。最小回歸測試**每次必走、毫秒級、debug 訊息一行直指根因**。三層防護(production validate / A1 exploration / minimal repro)各管一段。
>
> **鐵律**:
> - **不改 production**(production fix 已完成)。`git status` 應僅顯示 `tests/algo_validation/test_cross_mcu_orphan_relay.py` 新增。
> - **不引入 current/5A/熱切換**判定(同 F1 鐵律)。
> - **不動既有測試或 helpers**(reuse only:`ExplorationDriver`、`inject_arrive`、`is_quiescent`、`empty_engine` fixture)。
> - 超出 allowlist 立即 stop-and-report。

---

## STEP G1 — 單步實作 + 驗證(單一 commit)

**File allowlist(只准新增這個)**:
```
tests/algo_validation/test_cross_mcu_orphan_relay.py
```

### G1-a 開工前快速確認(read-only,~5 分鐘)

先 grep/讀 code 確認三件事,任一有出入立即 stop-and-report,**不要試圖在測試裡 work around**:

1. **prod fix 落在哪、長什麼樣**:`_finalize_departure`(`mcu_control.py:660` 附近)的離場後同步邏輯,確認現在會通知 lender MCU resync 其 relay(對稱於 `_try_return_async:319` 的 return 路徑)。記下 fix commit hash 與關鍵 file:line(後續 docstring 引用)。
2. **強制跨-MCU 借的 demand 門檻**:`_tick_return_condition:235` 的 `(available − demand) ≥ edge_power` 條件 + 單一 MCU 4 groups × 25 kW = 100 kW 本地容量。確認「**單台 EV `max_require_power_kw = 200**」**足以強制**跨-MCU 借(若不夠就拉高到 250)。回報你選的數字與理由。
3. **lender relay 讀取路徑**:依 F0 已確認的 `engine.station.boards[lender_mcu_idx].inter_group_relays[idx].state`(`RelayState.CLOSED`/`OPEN`)——與 F1 一致,無需重查。

### G1-b 撰寫測試

測試名與單一場景(取 F1 trace step 193/196 的 canonical 案例):

```
test_cross_mcu_borrower_depart_releases_lender_relay
```

**場景(完全確定性、不用 scheduler/coverage_tracker/變動 demand)**:

1. **建空站**:`empty_engine` fixture(4 MCU、無 initial_vehicles)。
2. **啟動 actors**:用 `ExplorationDriver.start_actors()`。
3. **注入 1 台高需求 EV**:`inject_arrive(engine, output_idx=6, max_kw=<G1-a 第 2 點選的數字>, soc_level="low")`。output 6 = MCU3.O0,需向 MCU2 借 g10/g11 → MCU2 的 `inter_group_relays[2]`(R_23)應 CLOSE。
4. **推 tick 直到 `is_quiescent`**:借入結算完。
5. **斷言「借走了」(前置條件)**:
   - `engine.station.boards[2].inter_group_relays[2].state == RelayState.CLOSED`
   - MA mirror 顯示 g10/g11 由 output 6 共擁有(用 `_diff_pair` 一致就行,不必自己重寫)
   - 若這步 fail:測試前置不成立(demand 沒高到觸發跨-MCU 借),回報你的觀察、stop-and-report,不要試圖在測試內亂調。
6. **強制離場**:`engine.vehicles[0].current_soc = engine.vehicles[0].target_soc`(下個 tick 系統會 `_trigger_departures` 觸發 COMPLETE → 自發離場)。
7. **推 tick 直到 `is_quiescent`**:離場結算完。
8. **KEY ASSERT(本測試存在的全部理由)**:
   ```
   assert engine.station.boards[2].inter_group_relays[2].state == RelayState.OPEN, \
       "Lender (MCU2) R_23 left CLOSED after cross-MCU borrower (output 6) departed — orphaned closed relay regression"
   ```
   附帶斷言 MA mirror 已清(兩側 g10/g11 ownership 皆 None)。
9. **cleanup**:`finally: await driver.stop_actors()`。

**Docstring 要求**:檔頭與 test docstring 必含:
- bug class 一句話描述(跨-MCU 借入者離場 → lender relay orphaned-closed)
- F1 抓到的 trace 摘要(step 847、A1 fired、seed=12345)
- prod fix commit hash(G1-a 第 1 點記下的)+ file:line
- 「**This test must NEVER be silenced or weakened. If it fails, the cross-MCU departure protocol regressed.**」明示警語

### G1-c 跑測試 + 全套件回歸

1. **單跑新測試**:`pytest tests/algo_validation/test_cross_mcu_orphan_relay.py -v` → PASS 且 < 1 秒。
2. **全套件回歸**:`pytest tests/algo_validation/ -v -s` → **4 passed**(原 3 + 本次新增)。確認沒不小心動到別的東西。
3. **回報** F1 §11 報告數字是否與上一輪一致(coverage/N 等)——本測試不應影響 exploration 行為,但保險起見對照一下。

---

## DoD(stop-and-report)
- [ ] G1-a 三點確認回報(含 prod fix commit hash 與 file:line、選用的 max_kw、其值理由)
- [ ] 新測試確定性 PASS、< 1 秒
- [ ] 全套件 4 passed,既有 3 個未受影響
- [ ] Docstring 含 bug class、F1 trace 引用、prod fix 引用、不可弱化警語
- [ ] `git status` 僅 `tests/algo_validation/test_cross_mcu_orphan_relay.py` 新增
- [ ] production 未改、無 current/5A 殘留、無暫時 instrumentation
- [ ] 草擬 commit message(英文,參照 F1 commit 風格,簡版約 15–25 行即可)

## 回報格式
1. `git status` 與 `git diff --stat`
2. DoD 逐項 ✅/❌ + 證據(file:line / pytest 輸出片段)
3. G1-a 三點答案(prod fix commit、max_kw 選擇、無新發現的接口問題)
4. 新測試 pytest 輸出(PASS 行 + 耗時)
5. 全套件 4 passed 證明
6. 草擬 commit message(供 Psyduck 微調後使用)
7. 任何超出 allowlist 或與既有判讀不符的事項(若有 → 已 STOP,描述)