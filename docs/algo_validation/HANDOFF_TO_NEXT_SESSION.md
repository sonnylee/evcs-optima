# Session 交接文件 — EVCS 演算法驗證測試設計

> 給下一個 session 的 Claude，這份文件讓你快速接手。先讀這份，再去讀重要的 outputs/ 裡最終的檔案。

## 一、這個 session 在做什麼（一句話）

為 EVCS Optima 的核心演算法（功率分配 / relay 切換 / MCU 鄰居同步）設計一套**驗證測試的規格與高層報告**——目前停在「規格已完成、尚未進入實作」的階段。整個 session 都在**設計與討論**，沒有寫 production code，也沒寫測試 code。

## 二、現在的狀態：用哪些檔案、別管哪些

outputs/ 裡有很多檔案，因為方法論演進了好幾版。**只有以下是最終的，其餘是歷史遺跡**：

### ✅ 最終的（接手就用這些）
- **`STEP_S2_DFS_VALIDATION_SPEC_v4.md`** — 詳細測試規格（給 Claude Code 實作用）。注意檔名仍帶 "DFS" 是歷史包袱，內容已是探索式 v4。
- **`EVCS_EXPLORATION_VALIDATION_HIGHLEVEL_v1.md`** — 高層報告（給主管核可用）。精簡、不含實作細節。這是最新命名（已正名為 EXPLORATION）。
- **`dfs_architecture.svg` / `.png`** — 架構圖最終的（檔名仍帶 dfs，內容已是 v4 複用設施的）。

### ❌ 過時的（不要用，理解演進才參考）
- `STEP_S2_DFS_VALIDATION_SPEC.md` / `_v2` / `_v3` — v1~v3 規格，方法論已被推翻
- `EVCS_DFS_VALIDATION_HIGHLEVEL.md` / `_v4` — 舊高層報告
- `STEP_S2_EXPLORE_SIM_INTERFACE.md` — 第一輪 explorer（v2 時代）
- `state_space_skeleton.svg/png` — v3 時代的 25 節點分層圖（節點數已從 25 改成 766，此圖過時）

### 📋 explorer 指令（已執行完、結果已整合進 v4，保留作記錄）
- `STEP_S2_EXPLORE_v4_STATESPACE.md` — 查狀態空間 766 / 對稱性
- `STEP_S2_EXPLORE_v4_SETTLE_FREQ.md` — 查穩態頻率
- `STEP_S2_EXPLORE_v4_REUSE.md` — 查既有設施複用

## 三、方法論演進：為什麼搞這麼多版

關鍵轉折，理解這個才不會走回頭路：

- **v1~v3（已死）**：原本要用「DFS 預先生成一條覆歷路徑、覆蓋所有可達態轉移」。狀態空間建模為 25 節點 `(N,L)`。
- **v3→v4 的致命轉折**：發現一個根本錯誤——**離場（depart）由系統內部自發觸發，測試無法控制、無法預先規劃路徑**。DFS 預先生成方法整個失敗。
- **v4（現行）**：改為**探索式即時抽樣**。測試只控進場（arrive），被動觀察系統自發離場。狀態空間改為 766 節點 `(O,L)`。

## 四、對話裡定下、但需要強調的關鍵決策

這些決策散落在對話中，是 v4 的骨架：

1. **狀態空間 = 766**：O（8-bit 佔用向量，256）× L（最後來車 SOC 低/中/高，3），扣空站卡縮 = 766。
   - 分母用 766 不用對稱化簡的 ~208，因為系統開 **FR-11（per-MCU 模組功率）打破 C4 對稱**。
   - L 是 **lossy 抽象**（只記最後來車 SOC，不記每車各自 SOC）。
   - 注意：使用者曾追問「766 是否該乘 3!」——答案是不該，L 是「一選三變數」（×3）不是排列（×3!），SOC 已含在 L 裡。

2. **探索式核心限制（已 explorer 實證）**：
   - 測試可控：arrive 時機 + SOC
   - 系統自發：depart（`vehicle.step()` soc≥target → `_trigger_departures()`，`simulation_engine.py:225-233`）

3. **雙軍驗證**（依穩態頻率實證 91~96% step 處於穩態）：
   - 穩態軍（系統自然到穩態時驗）：L1 狀態 / L2 守恆 / L4 MCU 一致
   - 逐-tick 軍（每 tick 驗）：L3 不變量（含「充電中 relay 須恆為 Closed」）/ L2 relay 切換順序
   - 為何雙軍：部分驗證是「每-tick 性質」，穩態或切換 transient 都要

4. **不重寫 oracle、不用黃金樣本**：不題 module_powers 是否為 SPEC 最佳值，只題合法/守恆/自洽。絕對最佳值由「已交付且 user 無錯誤回饋的線上系統」隱性背書。

5. **覆蓋率是觀察數據，非通過判據**：通過判據 = 走過的穩態 + 每個 tick 的 PASS。覆蓋率低是下一輪迭代的事，非失敗。

6. **大量複用 engine 既有設施（REUSE explorer 定案）**：
   - 複用：`validator.check`（逐-tick 餘存 + L4a ownership 鏡像）、`ChargingStation.validate`（L2）、`engine.snapshots`（trace/(O,L)）、`arrivals_log`
   - 新建（薄）：`is_quiescent()` ~6 行（4 指標彙總多穩態）、L4a relay 鏡像連動、L3 §11 內容、arrival_scheduler、coverage_tracker
   - **不碰 production**：is_quiescent 放測試 helper，使用者明確選此（否決了「加到 engine 公開層」）
   - arrive 注入用底層 API（`output.connect_vehicle` + `handle_vehicle_arrival` + append），因 TrafficSimulator 不支援後期注入
   - trace 用 snapshots 不用 export_csv（export_csv 驗證失敗才不寫）

7. **關鍵常數/設定**：dt = 1.0 秒（`config_loader.py:25`，非 1ms），模擬時間上限 24h = 86,400 步，覆蓋率門檻 60%，停滯閾值 500 步，seed = 12345。

## 五、待辦 / 開放項（下一步可能要做的）

- **命名不一致**：高層報告已正名 EXPLORATION，但詳細規格（`STEP_S2_DFS_VALIDATION_SPEC_v4.md`）和架構圖（`dfs_architecture.svg`）檔名仍帶 DFS。使用者尚未決定要不要改這兩個的命名。
- **高層報告表格的小修**：使用者指出 v1 報告裡「來車 SOC」和「站內初車 SOC」兩個其實是同一個 L，易造成重複/混淆。我已建議把兩個合併或標明「L 由來車 SOC 賦值」，但**使用者還沒回覆是否要改**——這是我留下的一個尚待解決的編輯。
- **尚未進入實作**：規格定案但 Claude Code 還沒開始寫測試。實作順序建議：先 `is_quiescent` + reuse_adapters（驗證複用設施的能力先），再做 scheduler + 雙軍主迴圈。
- **實作時的已知風險**：逐-tick 軍的 I6（充電中 relay 須 Closed）需要 monitor 每 tick 讀到「哪些 output 在充電 + relay 狀態」，這個參數接口 explorer 還沒細查，是實作 monitor 時第一個要確認的點。

## 六、使用者的工作風格（重要）

- 溝通用**繁體中文 + 英文技術行話**，偏好簡短直接。A/B 選項加理由。
- 嚴格工作流：Claude 起草 `STEP_*_INSTRUCTIONS.md` → 使用者 review → Claude Code 執行 → 使用者 commit。**Claude 不直接改 code**。
- 探索任務愛用 **explorer sub-agent 模式**（兩個並行 sub-agent，分工不重疊，保留結論衝突不自行調和）。
- 文件偏好精簡（架構圖要能對主管說明，不要過度複雜）。
- 對數字/概念會追根究柢（分母 25 vs 766、3! 的乘法、Burnside 推導等），解釋要扎實、用具體例子。
- 環境：GitHub Codespaces + 本地 VS Code，Claude Code v2.1.159 (Opus 4.8)，repo = evcs-optima。

## 七、給接手 Claude 的一句話

規格設計已收斂到 v4 探索式 + 雙軍 + 複用既有設施，技術方向穩固且有三輪 explorer 實證背數。最可能的下一步是：(a) 處理命名一致性與報告表格小修，或 (b) 起草給 Claude Code 的實作 STEP 指令。接手時先確認使用者要從哪個方向走，不要預設。
