# S2.3.2 — SPEC §11 / 125 kW 引用 Catalogue

**Date:** 2026-05-08
**Purpose:** S2.5 開工前釐清「125 kW」這個常數在整個 repo 中的所有引用點,
按性質分五類,讓 S2.5 知道完整工作面積、避免漏改造成 SPEC↔code↔test 之間
不一致。

> ⚠️ **本 spike 在執行期間發現 `docs/SPEC.md` §11 已被 user 改寫**
> (line 461-467),從固定「125 kW」改為 per-output 公式
> `output_min_guarantee = module_powers[0] + module_powers[1]`(O0)/
> `module_powers[3] + module_powers[2]`(O1)。125 kW 現在只是
> default `[50, 75, 75, 50]` 的特例。下面的 catalogue 把每一筆都
> 重新標註「在新公式下是否仍正確」。

---

## 1. Spike 範圍

**做什麼:** read-only catalogue,跑一系列 grep,逐筆讀上下文,分類。
**不做什麼:** 不改任何檔、不跑任何 code/test、不寫修法。

---

## 2. 分類定義

| # | 類別 | 含義 | S2.5 必須處理 ? |
|---|---|---|---|
| C1 | **Code: 硬 125 常數 / 數值 gate** | production 程式碼裡 `125.0` / `125` 的常數宣告或條件判斷 | **必須** |
| C2 | **Code: 125 相關註解 / docstring** | production 註解描述 SPEC §11 floor 等於 125 | **必須**(對齊新公式) |
| C3 | **Tests: 125 floor 斷言** | 測試裡直接以 125 為閾值的 assert / invariant check | **必須**(改成 per-config 公式) |
| C4 | **SPEC / 文件: 125 floor 描述** | docs/*.md / *.md / TEST-SPEC.md 中描述 125 floor 的段落 | **必須** |
| C5 | **Inert / 不相關 125** | 測試輸入值(`max_required=125`)、FR-12 round-to-25 範例(130→125)、dim-A baseline 參考表 | **不要動** |

---

## 3. 分類統計

| 類別 | 筆數 | 摘要 |
|---|---|---|
| C1(硬常數 / gate) | **3** | mcu_control 1 + step_planner 1(死代碼)+ rectifier_board 1(GROUP_CONFIGS 是 dim A 不算) |
| C2(註解 / docstring) | **~12** | mcu_control 4 處 + rectifier_board 2 處 + web_session_engine 5 處 + simulation_engine 1 處 |
| C3(測試 floor 斷言) | **9** | test_control_steps 5 + test_web_session_engine 2 + test_snapshot_module_powers 1 + test_engine_for_web_spike 2 + test_mcu_control_relay_phase 4(集中於 TC-PHASE-02 family) |
| C4(SPEC / 文件) | **8** | SPEC.md 2 處 + SPEC-WEB-API 3 處 + CLAUDE.md 2 處 + TEST-SPEC.md 1 處 + SPIKE 報告 1 處(historical,可不動) |
| C5(Inert) | **80+** | 大部分是 test demand `125`、FR-12 例子、SPEC 範例 trace 表(L675-701)、Dim-A 參考設定 |

> 「~」是因為註解類有時一個段落出現多次「125」,以 distinct 段落計。

---

## 4. 必答問題

### 4.A SPEC §11 主檔位置

**位置:** `docs/SPEC.md` 第 **457-475 行**,標題 `## 11. 關鍵約束與硬體限制`。

**現狀:** §11 已被 user 改寫(本對話啟動前的 file-modification reminder 也提示
過)。新版定義最小保證為 per-output 公式:
- `output_0_min_guarantee = module_powers[0] + module_powers[1]`
- `output_1_min_guarantee = module_powers[3] + module_powers[2]`
- 「default `[50, 75, 75, 50]` 是這個公式的特例,其值為 125 kW」

**自相矛盾點:** SPEC.md L78「啟動充電最小保證: **125 kW**」沒同步更新,跟 §11
新公式衝突 — S2.5 必須對齊。

### 4.B 程式碼 gate 是否只有 mcu_control 一處?

**回答:NO,但其他位置都不是真正的 production gate。**

| 位置 | 性質 | 是 mirror gate ? |
|---|---|---|
| `simulation/modules/mcu_control.py:26` `MIN_START_POWER_KW = 125.0` | **唯一真正的 production 常數** | 主 gate |
| `simulation/modules/mcu_control.py:458` `if available_power_kw + 1e-9 >= MIN_START_POWER_KW:` | **唯一真正的 production gate** | 主 gate |
| `services/evcs-api/app/adapters/step_planner.py:58` `MIN_ENGAGE_KW = 125  # SPEC §11` | **死代碼** — `grep -rn MIN_ENGAGE_KW` 全 repo 只此一處宣告,**沒任何 caller** | 偽 mirror(宣告但未引用)|
| `tests/integration/test_engine_for_web_spike.py:213, 311` `if output.available_power_kw + 1e-6 < 125:` raise | **測試 invariant**,屬於 C3,不是 production 邏輯 | 不算 gate |
| `services/evcs-api/tests/test_web_session_engine.py:85` `assert car.allocated_kw >= 125` | 同上 | 不算 gate |

**結論:S2.5 修 mcu_control.py:458 即可解開 production gate;step_planner.py:58
那行雖然宣告 `MIN_ENGAGE_KW`,但因為沒被引用,實質是死代碼,順手刪除或改寫即
可,不算另一處要小心同步的 mirror gate。**

### 4.C 哪些 125 引用是 dim A 假設,S2.5 不該動?

**有,大約 60+ 筆,清單如下(僅列代表性,非詳盡):**

| 檔/節 | 為什麼是 dim-A inert |
|---|---|
| `simulation/hardware/rectifier_board.py:13-15` `GROUP_CONFIGS = [2, 3, 3, 2]` 註解「O0 gets {G0,G1}=125kW, O1 gets {G2,G3}=125kW」 | S2.5 範圍是「unlock module_powers」(dim B);per-MCU module_powers 的真正硬體 shape 變動屬 **dim A**(GROUPS_PER_MCU 維持 4),這個註解描述的 [50,75,75,50] baseline 仍對。S2.5 不該重寫 GROUP_CONFIGS。 |
| `docs/SPEC.md:675-701`(範例 trace 表)出現大量「125kW」 | 範例 trace 是 N=2、[50,75,75,50] 的預設情境演示,不是 floor 規範。**保留**。 |
| `docs/SPEC.md:78`「啟動充電最小保證:125 kW」 | **不是 dim A inert,反而是要動** — 與 §11 新公式不一致,屬 C4。(列在這裡為避免誤判 inert) |
| `services/evcs-api/tests/test_snapshot_routes_integration.py:104`「Anchor for O0 is G0+G1 = 50+75 = 125 kW」 | 描述 default 配置下的事實,test 只在 default `_cfg(4)` 跑,不會看到非 125 的值。**保留**。 |
| `services/evcs-api/tests/test_snapshot.py:76, 165, 196, 200, 214, 251` 的 `max_required=125` | 純 test 輸入值,不是 floor 斷言。 |
| `services/evcs-api/tests/test_compute_snapshot_reactive.py:60-109` `single_port_125kw` fixture | fixture 名,不是 floor。 |
| `services/evcs-api/tests/test_web_session_engine_perf.py:51-55` 的 `single_125 / two_local / full_8_ports`(每 port 125 kW) | 性能 scenario 裡選 125 是「anchor 剛好填滿」的方便值,不是 floor 邏輯。 |
| `services/evcs-api/tests/test_sessions.py:42` / `test_control_steps.py` 大量 `max_required: 125, target: 125` | 同上,test demand 值。 |
| `STEP_F09_5_INSTRUCTIONS.md:125, 465`、`docs/SPEC-WEB-API.md:410`、`docs/SPEC-WEB-UI.md:575, 807, 910, 950` | UI / FR-12 文件範例(「130→125」是 round-to-25 規則,跟 SPEC §11 floor 無關)。 |
| `tests/unit/environment/test_time_controller.py:159-161` 的 `available_power_kw=125.0` | 測 VisionOutput 行為,跟 floor 無關。 |
| `tests/unit/modules/test_mcu_control_local.py:77, 105, 249` | 註解寫「available = G0+G1 = 125kW」,在 default config 下成立 — 修這個 test 等於 S2.5 改它,要區分「描述事實」vs「斷言 floor」 — 此處屬「描述事實」,保留。 |
| `tests/unit/modules/test_mcu_control_borrow_return.py:163`、`test_vehicle.py:91` 的 `present_power_kw = 125.0` | 純測試輸入。 |

**S2.5 應動的 dim-A inert = 0(這些都不該動)。** 上面列表純粹是給 reviewer
打勾用的避雷指南。

### 4.D S2.5 工作面積估計

| 範疇 | 數量 | 工時感 |
|---|---|---|
| **SPEC / docs**(C4) | **2 處主修 + 4 處對齊**:`SPEC.md` L78 改公式、L461-467 已是新版需 sanity-check;`SPEC-WEB-API.md` L291/293/460 把「125 kW」改成「最小保證(default 125)」措辭;`CLAUDE.md` L132/193 同;`TEST-SPEC.md` L677/682 改成 per-config | 半天 |
| **程式碼 hard gate / 常數**(C1) | **2 處**:`mcu_control.py:26 + 458`(主)、`step_planner.py:58`(死代碼,刪 or 補引用) | 視乎 §C1 解法選擇 — 若改成「讀 module_powers 算 floor」,涉及一段重構,1-2 天 |
| **程式碼註解**(C2) | **約 12 處**:見 §3 詳列 | 隨 C1 改完一起改,半天 |
| **測試 floor 斷言**(C3) | **9 個 test 函式 / case**:test_control_steps 的 `test_arrival_holds_output_open_until_125kw` / `test_arrival_below_125kw_never_closes_output` / `test_steps_engagement_signal_at_125kw` 系列、test_web_session_engine 的 invariant 迴圈、test_snapshot_module_powers Test C(本 spike 已 catalogue)、TC-PHASE-02 family 4 個 unit test、test_engine_for_web_spike 2 處 | 1-2 天(每個 test 改成「讀 config 算 floor」) |

**總估:** S2.5 寫的 production code 改動範圍中等(~1-2 處 production 邏輯熱點 +
~12 處註解),測試改動範圍偏大(9 個 test 要重新理解「per-config floor」概念
後重寫斷言),SPEC/docs 改動範圍小但很關鍵(SPEC §11 是 source of truth,要
先對齊)。**直觀工時感:3-5 個工作天**(假設沒踩到 dim A 範疇且不需重新跑
14-scenario regression)。

---

## 5. S2.5 應該動哪些檔 / 章節 / line(只列範圍,不寫修法)

### 5.1 SPEC / docs(C4)

| 檔 | 章節 / 行 | 動作 |
|---|---|---|
| `docs/SPEC.md` | L78「啟動充電最小保證:125 kW」 | 改成「依 §11 公式計算」或刪 |
| `docs/SPEC.md` | L457-475(§11 表格) | sanity-check user 已改的公式無語病,並把「Output 的 Relay 切換時機」表格列改寫指向公式 |
| `docs/SPEC-WEB-API.md` | L291, L293, L460 三段 | 改「125 kW」措辭 |
| `CLAUDE.md` | L132, L193 | 改 floor 措辭 |
| `associate/TEST-SPEC.md` | L677, L682 (TC-PHASE-01/02) | 改成 per-config 表達 |

### 5.2 程式碼(C1 + C2)

| 檔 | 行 | 性質 |
|---|---|---|
| `simulation/modules/mcu_control.py` | **L26**(`MIN_START_POWER_KW = 125.0`) | 改成「讀 module_powers 算 per-output floor」或保留 default 加 lookup |
| `simulation/modules/mcu_control.py` | **L458**(主 gate) | 同上對齊 |
| `simulation/modules/mcu_control.py` | L24-25, L61, L456, L882 | 註解 |
| `simulation/hardware/rectifier_board.py` | L155-156 | 註解(關 SPEC §11 字眼) |
| `simulation/hardware/rectifier_board.py` | L13-15 | **不動**(dim A baseline 描述) |
| `services/evcs-api/app/services/web_session_engine.py` | L101, L102, L121, L132, L145 | 註解 |
| `services/evcs-api/app/adapters/step_planner.py` | **L58**(`MIN_ENGAGE_KW = 125`)| 死代碼,刪除或改成 per-port lookup |
| `simulation/environment/simulation_engine.py` | L101, L265 | 註解(SPEC §6.1 / §11) |

### 5.3 測試(C3)

| 檔 | 行 / test 函式 | 動作 |
|---|---|---|
| `services/evcs-api/tests/test_control_steps.py` | L135 `test_arrival_holds_output_open_until_125kw`、L164 `test_arrival_below_125kw_never_closes_output`、L239(engagement signal)、L150-158, L182-184(125 floor 迴圈) | 改成「讀 config 算 per-port floor」 |
| `services/evcs-api/tests/test_web_session_engine.py` | L80-87(active output 全 ≥ 125 invariant)| 改成 per-port floor |
| `services/evcs-api/tests/test_snapshot_module_powers.py` | L156-158(Test C 的 `125 <= allocated <= 250`)| 改 lower bound 為 per-port floor |
| `tests/integration/test_engine_for_web_spike.py` | L205, L213-215, L311-313 | 改 invariant |
| `tests/unit/modules/test_mcu_control_relay_phase.py` | L50, L56, L70, L79(TC-PHASE-02 family)| 改成 per-config floor 構造 |

### 5.4 不要動(C5)

- `simulation/hardware/rectifier_board.py:13-15` GROUP_CONFIGS 註解(dim-A baseline)
- `docs/SPEC.md:675-701` 範例 trace 表(歷史 N=2 範例)
- `services/evcs-api/tests/test_snapshot_routes_integration.py:104` 註解(default 事實)
- 所有把 `125` 當 test demand 用的 test 輸入(test_snapshot.py / test_compute_snapshot_reactive.py / test_sessions.py 等)
- UI / FR-12 文件中的「130→125 round-to-25」範例
- `tests/unit/environment/test_time_controller.py:159-161`(無關)
- `tests/unit/modules/test_mcu_control_local.py:77, 105, 249`(default 配置下的事實描述,非 floor 斷言)
- `tests/unit/modules/test_mcu_control_borrow_return.py:163`、`test_vehicle.py:91`(test 輸入)
- `STEP_F09_5_INSTRUCTIONS.md`、`docs/SPEC-WEB-UI.md` 中的 UI demo 範例

---

## 6. 附錄:原始 grep 命令 + 結果摘要

### G1 — `MIN_START_POWER_KW`

```
grep -rn "MIN_START_POWER_KW" --include="*.py" .
```
**命中 2 筆**:`mcu_control.py:26, 458`(C1 全部)。

### G2 — `§11`

```
grep -rn "§11" --include="*.py" --include="*.md" --include="*.ts" --include="*.tsx" .
```
**命中 67 筆**。摘要(去掉本 spike 報告與 outputs/):
- C2(production 註解):`mcu_control.py` ~9 處 + `rectifier_board.py:156` + `simulation_engine.py:202, 228, 265` + `vision_output.py:75` + `module_assignment.py:11` + `messages.py:30, 45` + `return_protocol.py:19` + `web_session_engine.py:196`
- C3(測試):`test_snapshot_module_powers.py:129, 132` + `test_web_session_engine.py:5, 80, 87` + `test_control_steps.py:136, 165, 171, 189, 511` + `test_engine_for_web_spike.py:205, 429`
- C4(文件):`SPEC.md` `## 11.` heading 一處 + `SPEC-WEB-API.md:460, 463, 672` + `SPIKE-FR09-REPORT.md:25, 206`(historical)+ `CLAUDE.md:129, 132, 133, 135, 193` + `step_planner.py:8, 20, 27, 246, 296, 596`(混在 docstring,屬 C2/C4 跨類)+ `TEST-SPEC.md:875`

### G3 — `125 kW` 字面字串

```
grep -rn -E "\b125\s*kW\b|\b125\s*KW\b|\b125kW\b|125 kW" --include="*.py" --include="*.md" --include="*.ts" --include="*.tsx" --include="*.json" .
```
**命中 84 筆**。截前 60 + 後 25 已記錄於 spike 工作流。
分布:`SPEC.md`(範例 trace + L78 + L467)~30 處(多為 C5 範例 trace);`docs/SPIKE-FR09-REPORT.md` 19 處(歷史 spike,C5);`mcu_control.py` 3-4 處(C2);`web_session_engine.py` 4 處(C2);其餘為 test 輸入(C5)或 UI 例子(C5)。

### G4 — 「最小保證 / minimum-guarantee / minimum guaranteed」

```
grep -rn -E "最小保證|minimum.guarantee|minimum.guaranteed|min.start.power|MIN_START|MIN_ENGAGE|启动充电最小" --include="*.py" --include="*.md" --include="*.ts" --include="*.tsx" .
```
**命中 9 筆**(去本 spike):`SPEC.md:78, 461, 468`、`mcu_control.py:26, 458`、`rectifier_board.py:156`、`step_planner.py:58`、`test_control_steps.py:165`。**全部都是 C1/C2/C4**,沒有 C5 雜訊。

### G5 — 純數字 125 (Python)

```
grep -rn -E "[^0-9]125[^0-9]" --include="*.py" .
```
**命中 ~120 筆**(去 docs/、outputs/、associate/);截前 50 + 50-120 已記錄。
絕大多數是 C5 test demand `max_required=125` / `target=125` / fixture 名 / FR-12 例子。

### G6 — anchor / initial group 結構引用

```
grep -rn -E "anchor.*group|initial.*group|required_min|required_max|_group_base \+ 1|G0.*G1|G2.*G3" --include="*.py" .
```
**命中 30+ 筆**。重點:`mcu_control.py:493-580` `handle_vehicle_arrival`
是 hardcode `[G0,G1]` / `[G2,G3]` 的源頭(屬 dim A 邏輯,但 C1 floor 計算
**會**用到這個結構讀 module_powers 算 per-output floor)。

### G7 — `MIN_ENGAGE_KW`(死代碼確認)

```
grep -rn -E "MIN_ENGAGE_KW|engagement_kw|ENGAGE_FLOOR" --include="*.py" .
```
**只命中 1 筆**:`step_planner.py:58` 宣告本身,**無任何 caller** → 確認死代碼。

### G8 — relay phase gates 跨檔散布

```
grep -rn -E "advance_relay_phases|pre_step_guard|pending_output_relay_close|gun_live_ticks" --include="*.py" .
```
**命中 33 筆**,全部集中於 `mcu_control.py`(實作)+ `tests/unit/modules/test_mcu_control_relay_phase.py`(unit test)+ `tests/integration/test_engine_for_web_spike.py`(invariant 檢查)。**無外溢到其他 production 檔** — 確認 C1 主 gate 唯一性。

### G9 — `rectifier_board.py` 預設配置註解

`rectifier_board.py:13-15` GROUP_CONFIGS 與 anchor / 125 註解 — 列入 C5(dim-A
baseline,S2.5 不動)。`rectifier_board.py:155-156` 屬 C2(註解要更新)。

### G10 — `TEST-SPEC.md` TC-PHASE-02 family

`associate/TEST-SPEC.md:677, 682-689` 描述「Tick T+2 available >= 125kW」
→ 屬 C4(必修)。

### G11-G18 — 其他 grep(SPEC.md 段落、SPEC-WEB-API/UI 文件、Web UI、STEP 指令文件)

詳見上文 §3-§5,皆已分類。**Web UI(`web/evcs-ui/src/**/*.ts*`)目前
全 repo 0 筆 125 kW 引用** — Phase 4 尚未開工,FR-08 邊界限制與 SPEC §11
floor 是兩件事,不會在 Phase 4 才意外冒出新 mirror gate。

---

## 7. 卡住點 / 不確定判斷

1. **`step_planner.py:58` `MIN_ENGAGE_KW = 125`** 雖然無 caller,但變數名暗示
   它本來想做為「step planner 自己的 engage floor」 — 是否之前的 step_planner
   實作真的有引用、後來被刪掉?**read-only 無法判斷**。建議 S2.5 視為
   「未連線的 mirror gate」 — 要嘛刪、要嘛補引用,不要留死代碼。
2. **SPEC.md L78「啟動充電最小保證:125 kW」** 與 §11 新公式衝突,但這個
   修改是否也是 user 預期 S2.5 一併修?**read-only 無法判斷**;§4.A 已標
   「自相矛盾」提醒。
3. **`tests/unit/modules/test_mcu_control_local.py:77, 105, 249`** 的「available
   = G0+G1 = 125kW」註解,在 default `[50, 75, 75, 50]` 下是事實,但若
   S2.5 把 mcu_control 改成讀 module_powers,這個 unit test 是否還能用 default
   fixture?**read-only 無法判斷**(需要看 fixture 是否硬寫 [50,75,75,50])。
   保險起見 S2.5 跑完應 visual-inspect 該 test 的 fixture。
4. **`docs/SPIKE-FR09-REPORT.md` 19 筆 125 kW 引用**:全是 historical 報告
   描述,屬 C5,不要動。但若 reviewer 將 SPIKE 報告當「規範」誤解,可能要求
   一併更新 — 建議 S2.5 PR 描述明確標明「historical spike,不更新」。
