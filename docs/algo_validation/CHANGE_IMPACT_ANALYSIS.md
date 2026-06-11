# EVCS Optima — 需求影響分析報告 (Change Impact Analysis)

> 模式：**只讀考古 (read-only)**。本報告未修改任何程式碼。
> 分析對象：三項需求變更對 SPEC、Simulation Core、Web API 三層的衝擊。
> 座標慣例：`file:line`。所有行號為探索當下快照，後續 commit 可能漂移。

---

## 0. 系統現況速覽（與本報告相關的事實基礎）

| 維度 | 現況 | 權威來源 |
|---|---|---|
| MCU 數量 (REC BD count) | **動態 1–12**（Sprint 2 已解鎖 dim B） | `CLAUDE.md` Sprint status、`relay_matrix.py:32` |
| 每 MCU 的 SMR Group 數 | **固定 4**（dim A 未解鎖，Sprint 3 待辦） | `topology.py:10 GROUPS_PER_MCU = 4` |
| 每 MCU 的 Output 數 | **固定 2** | `OUTPUTS_PER_MCU`（topology.py） |
| 借電範圍 | **僅一階鄰居（左/右）** | SPEC §2.2 / §11、`_get_neighbor_for_group` |
| 借電節奏 | **循序單步**：每 step 每 output 最多借/還 1 個 group | `_handle_tick` / `_find_expansion_target` |
| module_powers | 每 REC BD 獨立，但 core 仍強制 `len==4` | `rectifier_board.py:51` |
| Web→Core 演算法 | rebuild-engine：每次請求建新 `SimulationEngine` 讀穩態即丟 | `web_session_engine.py` |

關鍵觀察：**需求 1（N 階借電）與需求 2（可變 Group 數）正好對應 SPEC 中尚未動的兩個自由度**；需求 2 即 `outputs/S2_0_DYNAMIC_GROUPS_ASSESSMENT.md` 所稱的「dim A」。

---

## 需求 1：跨 MCU 借電 — 從「一階鄰居」擴展到「任意階（N 階）」

### 1.1 SPEC 現行定義（原文位置）

| 規定 | 原文 | 位置 |
|---|---|---|
| Ring 借還僅限相鄰 | 「**Ring Topology 約束**：只有物理相鄰的 MCU 才能進行功率借還」 | SPEC.md §11 約束表 |
| 借電優先級 | 「借電優先級：**右 > 左 > 雙側**」 | SPEC.md §2.2、§11 |
| 環形定址只算前後一個 | `前一個 = (idx-1+N)%N`、`下一個 = (idx+1+N)%N` | SPEC.md §7.1 |
| 跨 MCU 借用步驟 | §6.1 step 4「本地資源不足時，才往外（跨 MCU）繼續擴展 MAX」 | SPEC.md §6.1 |
| CAN Bus 對應 | 「用上述公式算出**前後節點 ID** 即可建立通訊」 | SPEC.md §7.2 |

**結論**：SPEC 在語義上把「跨 MCU」與「物理相鄰一階」綁定。N 階借電是 **SPEC 層級的語義變更**，不只是實作調整。

### 1.2 Simulation 借電搜尋範圍如何決定

不是 BFS，而是**固定 left/right 的單步區間擴張**，靠三道結構性閘門限制在一階：

1. **目標選擇**（`mcu_control.py:748-777 `_find_expansion_target`）：只看 `interval_max+1`（右）與 `interval_min-1`（左），local-first → 跨 MCU；一次只回傳**一個** virtual 索引。
2. **可達性檢查**（`_can_assign` → RelayMatrix `is_legal`）：RelayMatrix 是 **3-MCU window（self + 左 + 右，18×18）**（`relay_matrix.py:24-43`）。超過一階的 group 在矩陣中根本沒有合法配線 → `_can_assign` 直接 false。
3. **鄰居派送**（`mcu_control.py:1063-1067 `_get_neighbor_for_group`）：`neighbor_mcu = group_phys // GROUPS_PER_MCU`，只回 `right_neighbor` 或 `left_neighbor`，**沒有「兩階外」的引用**。

> 補充：借電的 interval **可以跨到 self+左+右共 3 個 MCU**（因為 window 是 3-MCU），但無法再遠。所以現況精確說是「**跨一階鄰居**」而非「只在本體內」。

協定面：`send_borrow_request` / `_handle_borrow_request`（`communication/borrow_protocol.py`）是**點對點、收件方就是 lender 本人**——lender 在自己的 MA 預留 cell、自己 resync 自己的 relay（SPEC §11「只有本體 MCU 能切自己的 relay」）。沒有「轉送 (forward)」機制。

### 1.3 擴展到 N 階後，搜尋邏輯該變成什麼

需要兩件事，缺一不可：

1. **可達性放寬**：RelayMatrix / ModuleAssignment 的 3-MCU window 必須擴大到**整個 ring**（或動態 K-hop window）。否則 `_can_assign` 永遠擋住兩階外。
2. **多階協定轉送 (store-and-forward)**：因為 SPEC §11 規定「relay 只能由本體 MCU 切」、且 CAN Bus 只連前後鄰居，借到第 K 階必須**沿途逐跳請求**——M1→M2→M3…，每個中間 MCU 既要切自己邊界的 bridge relay，也要把請求往下轉送。

搜尋策略建議：**沿 ring 單方向的優先級展開（不是 BFS）**。維持 SPEC §2.2「右 > 左」語義，把它推廣成「先沿右環逐跳、再沿左環逐跳」。BFS/最短路在 ring 上退化成「兩個方向各走幾步」，所以**優先級排序 + 逐跳擴張**比通用 BFS 更貼合且更易移植到 C。

### 1.4 受影響檔案

| 檔案 | 函式 | 影響類型 | 備註 |
|---|---|---|---|
| `simulation/data/relay_matrix.py` | `__init__`, `_build_topology`, `local_window`, `abs_to_local_*` | ⚠️ **結構重寫** | 3-MCU window 假設遍佈；改為全 ring 或 K-hop window |
| `simulation/data/module_assignment.py` | `__init__`, `abs_to_local_*`, `assign_if_idle` | ⚠️ **結構重寫** | 同上，window 大小硬編 |
| `simulation/modules/mcu_control.py` | `_get_neighbor_for_group` | ⚠️ 高 | 只回左右鄰；需回「下一跳」而非「目標 owner」 |
| `simulation/modules/mcu_control.py` | `_try_borrow_async` / `_try_return_async` | ⚠️ 高 | 需支援多跳 await 鏈 / 轉送 |
| `simulation/communication/borrow_protocol.py` | `send_borrow_request`, `_handle_borrow_request` | ⚠️ 高 | 新增 forward / TTL / 路徑回溯 |
| `simulation/communication/return_protocol.py` | `send_return_notify`, `_handle_return_notify` | ⚠️ 高 | 對稱地支援多跳歸還 |
| `simulation/modules/mcu_control.py` | `_find_expansion_target`, `_can_assign` | 中 | span guard 與可達性需配合新 window |
| `simulation/environment/vision_output.py` | 邊界一致性檢查（SPEC §9） | 中 | 多跳借電會讓「相鄰對」一致性檢查不足以覆蓋路徑中段 |
| `docs/SPEC.md` | §2.2, §6.1, §7.1, §11 | ⚠️ **規格變更** | 「僅相鄰」語義需改寫 |

### 1.5 與現有邏輯的主要衝突

- ⚠️ **SPEC §11 鐵律「relay 只能由本體 MCU 切」** vs 「借第 3 階的 group」：M1 無法直接切 M3 的 relay，**必須**靠 M2 轉送並由 M2/M3 各自切自己的 relay。這是最大的語義斷層。
- ⚠️ **3-MCU window 假設**深植於兩張矩陣的座標轉換（`abs_to_local_*`），不是改一個常數能解決。
- **借電優先級語義**：「右 > 左 > 雙側」在一階下是三選一；多階下要決定是「沿右環走到底再走左環」還是「左右交替逐跳」，SPEC 未定義，需澄清。**需要進一步確認**。
- **死鎖 / 環形迴圈風險**：多跳請求在 ring 上可能繞回自己（M1→M2→…→M1）。需 TTL 或 visited 集合，目前協定完全沒有。

### 1.6 放寬限制後的簡化路徑

- **若允許放寬「relay 只能本體 MCU 切」**（例如模擬層接受由發起方「代切」中間 MCU relay）→ 可省掉整套 store-and-forward 協定，借電退化成「擴大 window + 直接 assign」，工作量大幅下降。但這**違反硬體現實**（CAN Bus + MCU 自治），僅適合純視覺化 demo，不可移植 C。
- **若把 window 直接設為「全 ring」**（不做 K-hop 動態 window）→ 座標轉換變單純（abs == local 全域），代價是記憶體 O(N²) 矩陣，對 N≤12 完全可接受。**這是最務實的簡化**：用「全域矩陣」換掉「3-MCU 滑動 window」，反而讓 N 階借電幾乎免費。

---

## 需求 2：SMR Group 數量 — 從固定 4 改為可調 1–4

### 2.1 SPEC 現行規定（原文位置）

| 規定 | 原文 | 位置 |
|---|---|---|
| 每 MCU 4 個 Group | 「4 個 SMR Group：G1(50)、G2(75)、G3(75)、G4(50)，交替排列」 | SPEC.md §2.2 |
| Output 直連錨點 | 「O1 直連 G1，O2 直連 G4」 | SPEC.md §2.2 |
| 最小保證公式假設 4 模組 | `output_0 = mp[0]+mp[1]`、`output_1 = mp[3]+mp[2]` | SPEC.md §11 |
| 索引轉換 | `Gx / 4` = MCU、`Gx MOD 4` = 群內位置 | SPEC.md §5.2 |

⚠️ SPEC §11 的最小保證公式**直接寫死 index 0/1 與 3/2**，這是 Group 數 < 4 時第一個壞掉的地方。

### 2.2 Simulation 中「4」出現的位置（檔案 + 行號）

| 檔案:行 | 內容 | 角色 |
|---|---|---|
| `simulation/utils/topology.py:10` | `GROUPS_PER_MCU = 4` | **單一真實來源（但被複製）** |
| `simulation/modules/mcu_control.py:44` | `GROUPS_PER_MCU = 4` | ⚠️ 重複定義（非 import） |
| `simulation/modules/mcu_control.py:46` | `ANCHOR_GROUP_LOCAL_IDX = (0, GROUPS_PER_MCU - 1)` | O1/O2 錨點 = (0, 3) |
| `mcu_control.py` | `:114,116,619,846,930-931,958-959,1064,1071,1078-1079` | group base / total / 迴圈 / 索引換算 |
| `simulation/hardware/rectifier_board.py:51` | `if len(module_powers) != 4:` | ⚠️ **硬性 reject 非 4 模組** |
| `simulation/hardware/rectifier_board.py:16` | `GROUP_CONFIGS = [2,3,3,2]` | 預設 SMR 數（×25kW）|
| `rectifier_board.py:38,66,74,122` | `mcu_id * 4`, `4 * num_mcus`, `prev_mcu*4+3` | 全域索引換算 |
| `simulation/data/relay_matrix.py:24-26` | `WINDOW_GROUPS_3MCU = 3*GROUPS_PER_MCU` 等 | 矩陣 shape |
| `simulation/data/module_assignment.py:22-23,37-38` | window groups/outputs | 矩陣 shape |
| `simulation/hardware/charging_station.py:104-105` | `g_base = mcu_id*4; range(4)` | 站體裝配 |
| `simulation/utils/validator.py:83-84` | `range(GROUPS_PER_MCU)` | 邊界驗證 |
| `simulation/modules/mcu_control.py:24-39` | `output_min_guarantee_kw` | ⚠️ **寫死存取 mp[0],mp[1],mp[3],mp[2]** |

> ⚠️ **設計氣味**：`GROUPS_PER_MCU` 在 `topology.py:10` 與 `mcu_control.py:44` **各定義一次**。改為 config 參數前，先統一來源。

### 2.3 Web API 層是否依賴固定數量

**幾乎不依賴**，只有一個硬編點：

| 檔案:行 | 內容 | 影響 |
|---|---|---|
| `services/evcs-api/app/services/web_session_engine.py:246` | `abs_g = mcu_idx * 4 + g_local` | ⚠️ **唯一硬編 "4"**；變動 Group 數會算錯絕對索引 → 應改 `mcu_idx * len(rec_bd.module_powers)` |
| `app/schemas/topology.py:13,25` | docstring「0..3 for default 4-module」 | 僅註解，不擋 |
| `app/services/config_service.py:17,58` | `DEFAULT_MODULE_POWERS=[50,75,75,50]` | 預設值，非強制 |

**驗證層完全不擋非 4 模組**：`validation_service.py:62-82 validate_module_powers` 只檢查「25 倍數」與「50–100 範圍」，**沒有 `len==4` 檢查**；`schemas/config.py:23-33` 同樣不檢查長度。換言之 **Web 已經能接受 1–4 模組的輸入，是 core 的 `rectifier_board.py:51` 把它擋下來**。

### 2.4 最小改動路徑（改為 config 參數）

1. **統一常數**：刪 `mcu_control.py:44` 的重複定義，全部 import `topology.GROUPS_PER_MCU`；再把它從模組常數改成「由 config / per-board `len(module_powers)` 推導」的值。
2. **拔 core 硬閘**：`rectifier_board.py:51` 的 `len != 4` 改為 `1 <= len <= 4`（或動態上限）。
3. **動態化矩陣 shape**：`relay_matrix.py` / `module_assignment.py` 的 window 常數改為依實際 groups-per-mcu 計算。
4. **修最小保證公式**：`output_min_guarantee_kw`（mcu_control.py:24-39）對 < 4 模組需重新定義（O1 錨 G0、O2 錨 G_last；當 group 數少時兩錨點可能重疊或相鄰，公式 `mp[3]+mp[2]` 越界）。⚠️ **語義需 SPEC 補定義**。
5. **Web 修一行**：`web_session_engine.py:246` 改用 `len(rec_bd.module_powers)`。
6. **註解/docstring** 清掉「4-module」字樣。

### 2.5 影響最大的地方

| 排名 | 位置 | 為何最痛 |
|---|---|---|
| 1 | ⚠️ `relay_matrix.py` / `module_assignment.py` 的 shape 與 `abs_to_local_*` | 整套座標系統假設「4 groups + 2 outputs / MCU」，是 dim A 的核心，牽動最廣 |
| 2 | ⚠️ `output_min_guarantee_kw`（SPEC §11） | 公式寫死 4 個 index；Group<4 時語義未定義，需 SPEC 拍板 |
| 3 | 錨點 `ANCHOR_GROUP_LOCAL_IDX=(0,3)` | O2 錨點 = 「最後一個 group」，需從常數改成 `len-1` |
| 4 | UI / 資料結構（次要） | Web 只一行；UI PackGrid 已用 `len(module_powers)` 動態渲染 |

> 本需求即 `CLAUDE.md` 標註的 **Sprint 3 dim A**，已有評估文件 `outputs/S2_0_DYNAMIC_GROUPS_ASSESSMENT.md`（**建議實作前精讀，本報告未展開該檔**）。

---

## 需求 3：借電策略 — 從「循序單步」改為「貪婪一次多個」

### 3.1 目前循序借電的進入點與迴圈結構

| 層級 | 位置 | 結構 |
|---|---|---|
| 觸發計數 | `mcu_control.py:208-225 `_tick_borrow_condition` | Present≈Available 且需求 > Available，連續 `_consecutive_threshold`（預設 **3**）step 才觸發一次 |
| 每 step 主迴圈 | `mcu_control.py:179-195 `_handle_tick`（async）/ `162-175 `_run_local_logic`（sync） | `for output in self._board.outputs:`（**固定 2 次**），每 output 觸發後呼叫**一次** `_try_borrow_async` |
| 單目標選擇 | `mcu_control.py:748-777 `_find_expansion_target` | 一次只回**一個** group（右或左或跨 MCU），回完即 return |
| settle 收斂 | `web_session_engine.py:185-218 `_settle_until_stable`（web 路徑）/ `simulation_engine.py:198-221 `_all_charging_complete`（模擬路徑） | 反覆 tick 直到 relay 狀態連續 `_CONVERGE_STABLE_WINDOW=5` tick 不變，上限 `_CONVERGE_TIMEOUT_TICKS=200` |

### 3.2 「1 次 1 Relay + 1 SMR Group」約束在哪形成

由**兩個機制疊加**而成，不是單一旗標：

1. `_find_expansion_target` **每次呼叫只回傳一個目標 group**（找到右/左就 return）。
2. `_handle_tick` 對每個 output **每 step 只呼叫一次** borrow。

→ 合起來：每 output 每 step 最多前進一個 group（連帶一個 relay）。再加上觸發需「連續 3 step」，所以爬升是**緩坡**：每 ~3 step 才借一格。SPEC §17 的 CSV 範例（一步一個 relay）正是這個節奏的體現。

### 3.3 貪婪策略的語義

「一次算出最大可借量，一次 apply」：

1. 觸發後，不回單一目標，而是**沿區間連續往外掃**，算到「達到 Max Require 或撞到衝突/邊界」為止的**完整 [newMin, newMax]**。
2. 一次性 `assign_if_idle` 整段、一次性 `_apply_global_relay_state` 把該段所有 inter-group relay 閉合，最後才閘 output relay。

對應改動：`_find_expansion_target` → `_find_expansion_span`（回 list/區間）；`_apply_borrow` → 批次版；`_handle_tick` 內呼叫次數仍是一次，但**單次效果放大**。

### 3.4 DC Relay「不可 hot-switch（電流需 < 5A 才能切）」在貪婪模式的風險

⚠️ **這是需求 3 最大的物理風險**：

- **借電（閉合方向 / 進電）**：閉合 inter-group relay 是「把更多 SMR 串進來」，閉合瞬間該 relay 兩端電位接近、電流小，相對安全；但貪婪**一次閉多個**會讓多個 relay 在**同一 step** 切換，模擬層的原子化（SPEC §8「切換即完成」）會掩蓋真實硬體上「需逐顆等電流落下」的時序。
- **還電 / 重新平衡（斷開方向 / 帶載）**：⚠️ 真正危險。斷開一個**正在導通功率**的 relay 等於帶載熱切。現行循序模式靠「先降功率→再斷 relay」的逐步節奏天然滿足 < 5A；貪婪一次斷多個會**同時帶載熱切多顆**，這是 SPEC §11「EV 充電中 Output relay 必須保持閉合」之外、inter-group relay 層級的硬體安全盲點。
- **結論**：貪婪可安全用於**借電爬升（閉合）**，但**還電/重分配（斷開）必須維持逐步**，或在貪婪斷開前先把該段功率歸零。**需求 3 不應對稱地套用到借與還兩側。**

### 3.5 settle loop 的收斂假設是否仍成立

- 收斂判據是「relay 狀態連續 N tick 不變」（`web_session_engine.py:223-230`），**與每 tick 前進幾格無關**。貪婪只會讓系統**更快**到達不動點，收斂判據仍成立，甚至 `_CONVERGE_TIMEOUT_TICKS=200` 可下修。
- ⚠️ 風險不在收斂與否，而在**中間態**：貪婪單 step 內跨多 relay，若某 step 借了一段又因衝突部分回退，可能出現**單 tick 內 assign→revert 抖動**，需確保 `assign_if_idle` 的全段原子性（要嘛整段成功要嘛整段回退）。

### 3.6 貪婪策略與 SPEC §11 relay 切換順序是否衝突

**部分衝突，但可調和**：

| SPEC §11 規則 | 貪婪下是否成立 | 處理 |
|---|---|---|
| inter-group/bridge 先閉，output 後閉 | ✅ 可保留：批次閉 inter-group，output 仍最後閘 | `_advance_relay_phases` 的 output 閘門（min-guarantee）不動 |
| Output relay 需達「最小保證」才閉 | ✅ 不受影響 | gating 在 output 層，與 inter-group 批次無關 |
| 離站：先開 inter-group 再開 output | ⚠️ 見 3.4，斷開不可貪婪批次 | 還電維持逐步 |
| relay 切換為原子（無中間態） | ⚠️ 模擬 OK，硬體時序被掩蓋 | 移植 C 時需還原逐顆時序 |
| 邊界一致性（§9）| ⚠️ 單 step 大幅變動，相鄰 MCU 可能瞬間不一致 | settle 完才輸出，穩態仍一致 |

---

## 綜合評估

### A. 三需求依賴關係與建議順序

```
需求 2（可變 Group 數）──┐
                         ├─► 需求 1（N 階借電）
需求 3（貪婪借電）───────┘（獨立，但建議最後做）
```

- **需求 1 是最大、最危險的，且部分依賴需求 2 的成果**：N 階借電必須重寫 RelayMatrix / ModuleAssignment 的 window 座標系；而需求 2（dim A）也正要動同兩張矩陣的 shape。**兩者都改矩陣，先做需求 2 把矩陣 shape 動態化，需求 1 再把 window 放大，可共用一次重構，避免改兩遍。**
- **需求 3 與 1/2 在資料結構上正交**：它改的是「節奏/批次」而非「拓樸/座標」。可獨立進行，但**建議放最後**——因為貪婪會放大任何 window/shape 的 bug，先有穩定的 1/2 再加速更安全。

**建議順序：需求 2 → 需求 1 → 需求 3。**

### B. 最大風險點（Top 5）

1. ⚠️ **`relay_matrix.py` / `module_assignment.py` 的 3-MCU window 與 `abs_to_local_*` 座標換算** — 需求 1、2 的共同震央，最容易引入靜默索引錯誤。
2. ⚠️ **`output_min_guarantee_kw`（mcu_control.py:24-39）寫死 mp[0/1/3/2]** — Group<4 直接越界；SPEC §11 公式本身需重新定義。
3. ⚠️ **N 階借電與「relay 只能本體 MCU 切」(SPEC §11) 的根本衝突** — 強迫引入 store-and-forward 多跳協定（含 TTL/防環），是全新且易死鎖的子系統。
4. ⚠️ **貪婪「還電/重分配」的帶載熱切（< 5A 約束）** — 模擬層原子化會掩蓋，移植 C 時變成真實硬體安全事故。
5. ⚠️ **`GROUPS_PER_MCU` 雙重定義（topology.py:10 + mcu_control.py:44）** — 改 config 時若只改一處，會產生極難察覺的不一致。

### C. 可放寬而大幅降低難度的假設

| 放寬 | 效果 |
|---|---|
| 把「3-MCU 滑動 window」換成「**全 ring 全域矩陣**」（N≤12，O(N²) 可接受） | 需求 1 的可達性問題幾乎消失，座標換算變 `abs==local`，N 階借電「免費」 |
| 需求 3 **只對借電（閉合）貪婪、還電維持逐步** | 規避 3.4 帶載熱切風險，且仍拿到主要加速 |
| N 階借電**只沿單一方向（右環）逐跳**、不做左右交替 | 協定路徑單純化，防環只需 TTL |
| 允許 Group 數的下限定在 **2 而非 1** | 保住「2 outputs 各有獨立錨點」的前提，min-guarantee 公式較易推廣 |

### D. 原以為會受影響、實際不必動的地方

- **`Vehicle` / `TrafficSimulator` / `VehicleGenerator`** — 三需求都不碰車輛或來車邏輯（功率曲線、SOC、到達節奏均無關）。
- **Web 驗證層 `validate_module_powers`** — 已經不檢查 `len==4`，需求 2 不需放寬它（瓶頸在 core 的 `rectifier_board.py:51`）。
- **UI `PackGrid` / `ModulePowerInput`** — 已用 `len(module_powers)` 動態渲染，需求 2 對前端幾乎零改。
- **`RelayEventLog` / `RelayEvent`（SPEC §8）** — 原子 `SWITCHED` 事件模型對三需求都成立，無需新事件型別。
- **FR-14 `step_planner` 的 rebuild+diff 主幹** — 它消費 `to_visual_snapshot` 的結果，只要 snapshot 正確，diff/排序邏輯不需因需求 1/2 改寫（需求 3 改的是 core 收斂速度，planner 不變）。
- **`web_session_engine` 的 settle/收斂判據** — 與借電節奏正交，需求 3 後仍成立（見 3.5）。

---

## 需要進一步確認的開放問題

1. **N 階借電的優先級語義**：SPEC「右 > 左 > 雙側」推廣到多階時，是「右環走到底再左環」還是「左右逐跳交替」？SPEC 未定義。
2. **Group 數 < 4 時的最小保證公式**：兩錨點重疊/相鄰時 `output_min_guarantee` 如何定義？需 SPEC §11 補述。
3. **是否容許放寬「relay 只能本體 MCU 切」**：決定需求 1 走「store-and-forward 多跳」(忠於硬體) 或「全域矩陣直接 assign」(僅 demo)。
4. **`outputs/S2_0_DYNAMIC_GROUPS_ASSESSMENT.md`** 的既有結論：本報告未展開該檔，需求 2 實作前應對照，避免重複評估。

---

**探索完成時間**：2026-06-04

**Claude Code 對本分析的信心程度：Medium-High**

理由：
- **High** 部分 — 三需求的程式碼錨點（檔案/行號/函式）經直接讀檔與多 agent 交叉驗證，事實層可靠：借電的一階限制（3-MCU window + `_get_neighbor_for_group`）、`GROUPS_PER_MCU` 全部出現位置、循序借電迴圈結構、Web 唯一硬編 `web_session_engine.py:246`、SPEC §11 順序機制，皆已落到行號。
- **Medium** 部分 — 兩個下修信心的因素：(1) 未實際執行測試或 trace，貪婪策略對 settle 收斂的「抖動」風險、N 階多跳協定的死鎖風險屬**推論而非驗證**；(2) 未閱讀 `outputs/S2_0_DYNAMIC_GROUPS_ASSESSMENT.md`，需求 2 可能已有更細的官方評估與本報告互補或修正。SPEC 對 N 階優先級、Group<4 的最小保證等語義留白，屬規格層待澄清而非程式碼事實。
