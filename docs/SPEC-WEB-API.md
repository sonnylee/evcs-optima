# EVCS Optima Web Service Software Architecture

## 1. Architecture Overview

採用三層式軟體架構：

1. **Web Layer：Bun Web Interface**
2. **Service Layer：Python FastAPI Service**
3. **Core Layer：Existing Python Simulation Core**

整體設計目標是保留既有 Python Core 的模擬與演算法邏輯，並透過 FastAPI 將核心功能包裝成 Web API，再由 Bun Web Interface 提供使用者操作介面與結果視覺化。

```text
+-----------------------------+
|        Bun Web UI           |
| React / TypeScript / Bun    |
| MCU Topology View           |
+-------------+---------------+
              |
              | REST API
              v
+-----------------------------+
| Python FastAPI Service      |
| API Layer                   |
| Application Service Layer   |
+-------------+---------------+
              |
              | Python function call
              v
+-----------------------------+
| Existing Python Core        |
| SimulationEngine            |
| TrafficSimulator            |
| VehicleGenerator            |
| MCU / Relay / SMR Logic     |
+-------------+---------------+
              |
              v
+-----------------------------+
| Result Output               |
| snapshots / trace.csv       |
| boundary.jsonl              |
| timeline JSON               |
+-----------------------------+ 

```

## 2. Web GUI - wireframe
fetch at : "https://www.figma.com/design/KHQ1AFIbh2lBS5m8TSOrv9/EVCS-Vision?node-id=13-572&t=m6yBYmEzyui9emih-1"

## 3. 功能需求總覽

| 需求編號 | 需求名稱 | 類型 |
|----------|----------|------|
| FR-01 | REC BD 顏色區分識別 | 顯示 |
| FR-02 | REC BD 即時功率顯示 | 顯示 |
| FR-03 | 25kW 模塊色彩對應 REC BD | 顯示 |
| FR-04 | Relay 閉合/斷開狀態視覺化 | 顯示 |
| FR-05 | 車輛充電狀態色彩顯示 | 顯示 |
| FR-06 | 每迴路最大需求量顯示 | 顯示 |
| FR-07 | 需求量調整按鈕（+25kW / -25kW） | 互動 |
| FR-08 | 需求量邊界限制（0kW ~ 600kW） | 邏輯 |
| FR-09 | 調整後即時全局聯動更新 | 行為 |
| FR-10 | REC BD 模組數量可擴充配置 | 配置 |
| FR-11 | 模塊功率（Module Group 容量）可調整 | 配置 |
| FR-12 | Car Max. Required 手動輸入 | 互動 |
| FR-13 | Present 與 Target 手動輸入 | 互動 |
| FR-14 | Apply and Generate Control Steps | 互動 |
| FR-15 | 控制步驟播放器（Forward / Back） | 互動 |
| FR-16 | 來車自定義優先級 | 配置 |

---

## 3.1 補充定義

### Max. Required（最大需求功率）

車輛端向充電站聲明的最大充電功率上限。這是車輛「願意接受」的最大值，代表該路充電槍在當前會話中允許系統分配的功率天花板。系統實際分配給該路的功率不會超過此值。單位為 kW，以 25kW 為步進單位，範圍 0 ~ 600kW。

### Present（當前輸出功率）

系統目前正在對該路充電槍實際輸出的功率值。這是系統現在的運行狀態，反映的是 REC BD 模塊分配與 Relay 等通後，該路實際送出的電力。Present 是計算控制步驟的「出發點」。

### Target（目標輸出功率）

使用者希望系統切換至的目標輸出功率值。代表操作人員手動設定的新目標，希望該路最終輸出的功率。Target 是計算控制步驟的「終點」，系統依據 Present → Target 的差異產生逐條控制步驟。

---

## 4. 詳細功能需求規格

### FR-01 — REC BD 顏色區分識別

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-01 |
| 需求名稱 | REC BD 顏色區分識別 |
| 需求類型 | 顯示（Visual） |

**需求描述**

系統需為每個 REC BD 分配一個唯一識別色，作為跨區塊視覺識別的基礎。此顏色統一用於 REC BD 標籤背景色及對應 25kW 模塊的著色（參見 FR-03）。

**顯示格式**

- 每個 REC BD 擁有不同的背景識別色，顏色間視覺區辨度明顯
- 識別色從預設調色盤依序指定（不可重複），調色盤至少支援 N 種顏色以上以應對擴充需求
- REC BD 標籤需顯示：編號（如「REC BD 1」）、狀態（Occupied / Idle）、目前使用功率（如「Power: 250kW」）

---

### FR-02 — REC BD 即時使用功率顯示

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-02 |
| 需求名稱 | REC BD 即時使用功率顯示 |
| 需求類型 | 顯示（Visual） |

**需求描述**

每個 REC BD 標籤需即時顯示該 REC BD 目前正在輸出的總功率（kW）。功率數值由系統依照所有已導通 Relay 與對應需求計算得出，並在每次需求調整後（FR-09）同步更新。

**計算規則**

- REC BD 使用功率 = 該 REC BD 所有已分配模塊對應的輸出功率加總
- 若 REC BD 無任何使用中模塊，顯示「Power: 0kW」，狀態標示為 Idle
- 若至少有一個模塊被使用，狀態標示為 Occupied

**顯示格式**

- 顯示範例：「Power: 250kW」，單位固定為 kW，整數顯示，無小數

---

### FR-03 — 25kW 模塊色彩對應 REC BD

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-03 |
| 需求名稱 | 25kW 模塊色彩對應 REC BD |
| 需求類型 | 顯示（Visual） |

**需求描述**

中間區塊的每個 25kW 功率模塊（Pack 方格），其背景色需對應該模塊目前被使用的 REC BD 之識別色，讓使用者能直覺識別功率來源與分配狀況。

**規格細則**

- 每個 Pack 方格尺寸一致，排列方式與硬體分群對應（每 REC BD 含 10 個 25kW 模塊）
- 已分配給某 Output 使用的 Pack：填充對應 REC BD 的識別色（不透明）
- 未被使用的 Pack：顯示淺灰色或白色底
- 色彩更新與 FR-09 聯動，每次需求調整後同步更新

---

### FR-04 — Relay 導通/斷開狀態視覺化

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-04 |
| 需求名稱 | Relay 閉合 / 斷開狀態視覺化 |
| 需求類型 | 顯示（Visual） |

**需求描述**

介面中每個 Relay（Output Relay 及 Parallel Relay）需提供明確的視覺狀態指示，以底色區分導通與斷開兩種狀態。

**狀態對應規格**

| Relay 狀態 | 顯示底色 | 語意 |
|------------|----------|------|
| 閉合（Closed / ON） | 紅色（如 #E53E3E） | 電路閉合，功率流通中 |
| 斷開（Open / OFF） | 白色（#FFFFFF）或淺灰 | 電路斷開，無功率流通 |

**補充說明**

- Output Relay 與 Parallel Relay 均套用相同顏色規則
- Relay 圖示尺寸固定，僅底色改變，不影響整體版面佈局

---

### FR-05 — 車輛充電狀態色彩顯示

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-05 |
| 需求名稱 | 車輛充電狀態色彩顯示 |
| 需求類型 | 顯示（Visual） |

**需求描述**

每個 Car Port 對應一個車輛圖示，其色彩需反映該輸出迴路的即時充電狀態。

**狀態對應規格**

| 充電狀態 | 車輛圖示顏色 | 判斷條件 |
|----------|-------------|----------|
| 充電中（Active） | 藍色（Blue） | 該路 Output Relay 導通，且 Max Required > 0kW |
| 閒置（Inactive） | 淺灰色（Light Gray） | 該路 Output Relay 斷開，或 Max Required = 0kW |

---

### FR-06 — 每迴路最大需求量顯示

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-06 |
| 需求名稱 | 每迴路最大需求量顯示 |
| 需求類型 | 顯示（Visual） |

**需求描述**

每個 Car Port 常駐標示目前設定的最大需求功率（Max Required），讓使用者清楚掌握每迴路的充電功率設定值。

**顯示規格**

- 格式：「Car N — Max. Required: _XXX_ kW」（N 為輸出路編號，XXX 為功率數值）
- 按鈕變更後數值立即更新，不需重整頁面
- 單位固定為 kW，整數顯示，無小數

---

### FR-07 — 需求量調整按鈕（+25kW / -25kW）

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-07 |
| 需求名稱 | 需求量調整按鈕 |
| 需求類型 | 互動（Interaction） |

**需求描述**

每個 Car Port 配置兩個操作按鈕，允許使用者以 25kW 為步進單位調整該路的最大需求功率。

**按鈕規格**

| 按鈕 | 標籤 | 行為 |
|------|------|------|
| +25kW 按鈕 | +25kW | 將該路 Max Required 增加 25kW；若結果超過 600kW，則設定為 600kW（上限截斷） |
| -25kW 按鈕 | -25kW | 將該路 Max Required 減少 25kW；若結果低於 0kW，則設定為 0kW（下限截斷） |

**互動說明**

- 每次點擊觸發一次計算與更新，點擊後所有聯動元件（FR-09）立即更新
- 按鈕不需 disabled 狀態，數值受邊界邏輯（FR-08）保護

---

### FR-08 — 需求量邊界限制（0kW ~ 600kW）

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-08 |
| 需求名稱 | 需求量邊界限制 |
| 需求類型 | 邏輯（Logic / Constraint） |

**需求描述**

每路 Max Required 數值受硬性邊界限制，確保系統操作在安全範圍內。

**邊界規格**

| 邊界 | 數值 | 說明 |
|------|------|------|
| 下限（Minimum） | 0 kW | 最小值，代表該路無充電需求，Relay 全斷開，車輛圖示轉為淺灰色 |
| 上限（Maximum） | 600 kW | 最大值，代表單路最大允許功率需求；超過 600kW 時強制截斷為 600kW |
| 步進單位 | 25 kW | 每次按鈕操作僅改變 25kW，確保需求量始終為 25 的整數倍 |

**邊界行為說明**

- Max Required = 0kW 時：該路所有 Relay 斷開（白底），車輛圖示變為淺灰色，REC BD 不計算此路功率
- Max Required = 600kW 時：點擊 +25kW 按鈕無效，數值維持 600kW，介面無異常
- 每次按鈕操作後，邊界檢查在計算更新前執行

---

### FR-09 — 調整後即時全局聯動更新

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-09 |
| 需求名稱 | 即時全局聯動更新 |
| 需求類型 | 行為（Behavior） |

**需求描述**

每次使用者透過按鈕調整任一 Car Port 的 Max Required 後，系統需立即重新計算並更新所有聯動視覺元件，確保介面與計算狀態一致。

**聯動更新範圍**

| 元件 | 更新項目 | 對應需求 |
|------|----------|----------|
| REC BD 標籤 | 使用功率數值、Occupied / Idle 狀態 | FR-02 |
| 25kW 模塊方格（Pack） | 底色（REC BD 識別色 或 灰白） | FR-03 |
| Relay 圖示 | 紅底（導通）/ 白底（斷開） | FR-04 |
| 車輛圖示 | 藍色（充電中）/ 淺灰色（閒置） | FR-05 |
| Max. Required 數值標示 | 數值更新（即時反映） | FR-06 |

---

### FR-10 — REC BD 模組數量可擴充配置

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-10 |
| 需求名稱 | REC BD 模組數量可擴充配置 |
| 需求類型 | 配置（Configuration） |

**需求描述**

使用者需能在介面上自由設定 REC BD 的數量，不再侷限預設 4 個。系統依照使用者設定的 REC BD 數量，動態渲染對應數量的 REC BD 標籤、模塊方格、Relay 圖示與輸出路線。

**規格細則**

- 需求類型為配置：將會新增配置功能以進行組態的設定
- REC BD 數量由使用者透過介面輸入（數字輸入框或選單），初始預設值為 4
- 最小值為 1，最大值建議 12，超出可提示使用者
- 設定後點擊「套用」或「Apply」使介面重新渲染（配置層與顯示層分離）
- 新增的 REC BD 自動從顏色調色盤取得下一個未使用的識別色
- 新增的 REC BD 顏色調色可以選擇固定 4 種配色循環
- 版面配置：REC BD 數量增加時，介面垂直延伸；Car Port 數量同步跟隨 REC BD 數量調整（每個 REC BD 對應 2 個 Car Port）

**範例**

- REC BD = 4 → 8 個 Car Port
- REC BD = 5 → 10 個 Car Port（REC BD 5 新增，對應 Car 9、Car 10）
- REC BD = 6 → 12 個 Car Port

---

### FR-11 — 模塊功率（Module Group 容量）可調整

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-11 |
| 需求名稱 | 模塊功率（Module Group 容量）可調整 |
| 需求類型 | 配置（Configuration） |

**需求描述**

允許使用者自訂每個 REC BD 的模塊功率配置，不再侷限於預設的 50kW 或 75kW，且每個 REC BD 的模塊功率可獨立設定。

**規格細則**

- 每個 REC BD 的模塊功率配置以逗號分隔的數值列表表示，例如：「50, 75, 75, 50」或「50, 50, 50, 50」或「100, 100, 100, 100」
- 使用者透過文字輸入框輸入配置字串，格式驗證即時進行
- 模塊功率單位為 kW，最小值為 50kW，最大值建議不超過 100kW（單一模塊），超出需顯示警告；模塊功率輸入值需為 25 的整數倍
- 每組功率 50kW、75kW、100kW 要看出每個群組有分別切成 2×25 或 3×25 或 4×25
- 同一 REC BD 的所有模塊功率相加即為該 REC BD 的額定總容量
- 修改後需點擊「套用」或「Apply」使介面重新渲染

**輸入格式範例**

| 輸入範例 | 解析結果 | REC BD 總容量 |
|----------|----------|---------------|
| 50, 75, 75, 50 | 4 個模塊，分別為 50kW、75kW、75kW、50kW | 250kW |
| 50, 50, 50, 50 | 4 個模塊，均為 50kW | 200kW |
| 75, 100, 100, 75 | 分別為 75kW、100kW、100kW、75kW | 350kW |

---

### FR-12 — Car Max. Required 手動輸入

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-12 |
| 需求名稱 | Car Max. Required 手動輸入 |
| 需求類型 | 互動（Interaction） |

**需求描述**

Max. Required 的調整方式由步進按鈕改為支援直接手動輸入數值，使使用者能更快速設定大幅度的功率變更，同時保留原有的步進按鈕作為輔助操作（選擇性保留）。

**規格細則**

- 每個 Car Port 的 Max. Required 欄位改為可編輯的數字輸入框（Input Field）
- 使用者可直接輸入任意整數，系統在 blur（失去焦點）或 Enter 確認時進行邊界驗證
- 邊界規則：下限 0kW，上限 600kW；超出範圍自動截斷並提示
- 輸入值需為 25 的整數倍；若輸入不為 25 倍數，自動四捨五入到最近的 25 倍數並提示
- 步進按鈕（+25kW / -25kW）可選擇保留，作為精細調整的輔助操作
- 任何 Max Req. 輸入變更（手動或按鈕）直接觸發全局重算，又或按下「Apply and Generate」（FR-15）依照 Present 與 Target 的參數計算步驟序列

**驗收標準**

- 輸入 250 → 系統接受並顯示 250kW
- 輸入 630 → 自動截斷為 600kW，顯示警告提示
- 輸入 -10 → 自動截斷為 0kW，顯示警告提示
- 輸入 130 → 四捨五入為 125kW，顯示提示

---

### FR-13 — Present 與 Target 欄位可手動輸入

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-13 |
| 需求名稱 | Present 與 Target 欄位可手動輸入 |
| 需求類型 | 互動（Interaction） |

**需求描述**

Present 欄與 Target 欄均需支援手動輸入數值，讓使用者能自由指定系統的當前狀態與目標狀態，以此作為控制步驟計算的輸入依據。

**Present 欄位規格**

- 支援手動輸入代表系統當前（出發點）每個 Car Port 的功率輸出狀態
- 數值邊界：0kW 至 600kW

**Target 欄位規格**

- 代表使用者期望系統切換至的目標功率狀態
- 支援手動輸入，輸入後不立即更新視覺面板（需等 Apply and Generate 計算後才反映在播放器步驟中）
- 數值邊界：0kW 至 600kW，25kW 的整數倍
- Target 欄位數值作為「Apply and Generate」（FR-14）的目標輸入

**關係說明**

- Present（當前狀態）→ Target（目標狀態）：系統計算兩者之差異，產生必要的控制步驟序列
- 若 Present = Target（所有 Car Port 功率相同），則無需控制步驟，系統提示「No change required」

---

### FR-14 — Apply and Generate Control Steps

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-14 |
| 需求名稱 | Apply and Generate Control Steps |
| 需求類型 | 互動 |

**需求描述**

使用者完成所有參數輸入後，點擊此按鈕觸發計算引擎，依照 Present 狀態與 Target 目標狀態的差異，產生有序的逐條控制步驟序列。

**觸發條件**

- 使用者完成所有必填欄位的輸入（Present 與 Target 至少需有差異）
- 所有輸入通過邊界驗證（無非法數值）
- 點擊「Apply and Generate Control Steps」按鈕

**控制步驟生成規則**

控制步驟序列需遵循 EVCS 硬體約束（繼承 2025 年演算法邏輯）。

**計算輸出**

- 完整的控制步驟序列（Step Sequence），每個步驟包含：步驟編號、操作描述、操作後系統狀態快照
- 步驟序列儲存於前端狀態中，供播放器（FR-15）使用

**錯誤與邊界情況**

| 情況 | 處理方式 |
|------|----------|
| Present = Target（無差異） | 提示「No change required，系統狀態已是目標狀態」，不進入播放器 |
| 所有 Target = 0kW | 產生關閉所有路線的步驟序列 |
| Target 超過系統總容量 | 提示「超過總容量，請調整 Target 設定」，不計算 |
| 輸入包含非法值 | 阻止計算，標示問題欄位，提示修正 |
| Present 為不合理總值 | 在受限於供給功率情況之下，警示異常的 Present 欄位並給出合理建議值，但系統持續產生逐條控制步驟序列 |
| 來車順序的優先級 | 功率配置會依介面設計由上至下進行功率分配 |

---

### FR-15 — 控制步驟播放器（Forward / Back）

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-15 |
| 需求名稱 | 控制步驟播放器（Forward / Back） |
| 需求類型 | 互動（Interaction） |

**需求描述**

FR-14 計算完成後，選擇介面進入播放器模式，使用者可透過 Forward（前進）與 Back（後退）兩個按鈕，逐步觀察每個控制步驟執行後對系統所有視覺元件的影響，包含 REC BD、Relay、Car 圖示，以及 Max. Required 數值。

**播放器介面元素**

- 步驟進度指示器：顯示「Step X / N」（X 為當前步驟，N 為總步驟數）
- 步驟描述文字：顯示當前步驟的操作說明（如「Close Output Relay 3」、「Reduce Car 2 power from 200kW to 100kW」）
- Forward 按鈕（以符號 >> 表示）：前進至下一步驟，系統更新至下一步驟的狀態快照
- Back 按鈕（以符號 << 表示）：後退至上一步驟，系統還原至上一步驟的狀態快照
- 主視覺面板：REC BD / Relay / Car / Max. Required 視覺佈局，即時反映當前步驟的系統狀態

**播放器行為規格**

| 場景 | 行為 |
|------|------|
| 進入播放器 | 從步驟 0（Initial State = Present 狀態）開始，顯示初始系統狀態 |
| 點擊 Forward（非最後步驟） | 步驟計數 +1，視覺面板更新為下一步的狀態快照 |
| 點擊 Forward（最後步驟） | 步驟重置至步驟 0，視覺面板更新至初使狀態 |
| 點擊 Back（非第一步） | 步驟計數 -1，視覺面板還原為上一步的狀態快照 |
| 點擊 Back（第一步） | 跳至最後步驟，視覺面板更新至最後一步的狀態快照 |
| 重新計算（再次 Apply） | 播放器重置至步驟 0，載入新的步驟序列 |
| 離開播放器 | 提供「返回編輯模式」按鈕，回到參數輸入畫面（不清除輸入值） |

**視覺更新範圍**

每次 Forward / Back 操作後，以下所有元件需同步更新：

| 元件 | 更新項目 |
|------|----------|
| REC BD 標籤 | 使用功率數值、Occupied / Idle 狀態 |
| 25kW 模塊方格（Pack） | 底色（REC BD 識別色 或 灰白） |
| Relay 圖示 | 紅底（導通）/ 白底（斷開） |
| 車輛圖示 | 藍色（充電中）/ 淺灰色（閒置） |
| Max. Required 數值標示 | 每路當前步驟對應的功率設定值 |
| 步驟進度指示器 | 「Step X / N」計數更新 |
| 步驟描述文字 | 顯示對應步驟的操作說明 |

---

### FR-16 — 來車自定義優先級

| 欄位 | 內容 |
|------|------|
| 需求編號 | FR-16 |
| 需求名稱 | 來車自定義優先級 |
| 需求類型 | 配置（Configuration） |

**需求描述**

每個 Car Port 允許使用者手動指定一個唯一的優先級數值，數值越小代表優先級越高（1 為最高優先）。系統進行功率分配時，依優先級由高到低順序分配 REC BD 模塊資源，取代原本固定由上至下依 Car 編號分配的策略。

**優先級規格**

- 每個 Car Port 必須被指定一個唯一的優先級數值，不允許任何兩個 Car Port 擁有相同的優先級數值
- 優先級數值範圍為 1 ~ N，其中 N = REC BD 數量 × 2（每個 REC BD 固定對應 2 個充電輸出路線）；每個數值在系統中恰好出現一次，形成完整排列
- 系統依優先級數值由小到大（1 最優先）順序分配 REC BD 模塊資源

**輸入驗證規則**

| 情況 | 處理方式 |
|------|----------|
| 輸入重複數值 | 即時提示錯誤，阻止確認，標示衝突的兩個欄位 |
| 輸入超出範圍（< 1 或 > N） | 即時提示錯誤，阻止確認 |
| REC BD 數量變更導致 N 改變 | 現有優先級設定清除並要求重新指定，或自動重新正規化 |
| 未填寫至少 2 個 Car Port 的優先級 | 阻止 Apply and Generate 執行，提示「請完成優先級設定」 |

---

## 4. 開發階段

---

### Phase 1 — FastAPI Foundation

| 工作 | 對應需求 |
|---|---|
| 建立 FastAPI project structure | Architecture |
| 建立 `/health`、`/constants`、`/palette` | FR-01, FR-08 |
| 建立 Pydantic schema | FR-01～FR-16 |
| 建立 validation service | FR-08, FR-10, FR-11, FR-12, FR-13, FR-16 |
| 建立 session store | FR-09, FR-14, FR-15 |

完成條件：Web UI 可呼叫 API，且輸入資料具備基本驗證。

---

### Phase 2 — Topology & Visual Snapshot API

| 工作 | 對應需求 |
|---|---|
| REC BD config preview | FR-01, FR-10 |
| Module Group 解析與 25kW Pack 切分 | FR-03, FR-11 |
| Max Required 即時計算 | FR-06, FR-07, FR-08, FR-12 |
| REC BD / Pack / Relay / Car snapshot | FR-02, FR-03, FR-04, FR-05, FR-09 |
| Priority validation | FR-16 |

完成條件：任一 Car Port 功率變更後，API 可回傳完整 `VisualSnapshot` 讓前端重畫畫面。

---

### Phase 3 — Python Core Adapter Integration

| 工作 | 對應需求 |
|---|---|
| 建立 `EvcsCoreAdapter` interface | FR-14 |
| 將 Web Input 轉成 Core Input | FR-13, FR-14, FR-16 |
| 將 Core Output 轉成 API Step Sequence | FR-14, FR-15 |
| 加入不合理 Present warning | FR-14 |
| 加入 Target 超過總容量檢查 | FR-14 |

完成條件：API 可依 Present → Target 產生控制步驟，每個 step 都包含完整 snapshot。

---

### Phase 4 — Bun / React Web UI Implementation

| 工作 | 對應需求 |
|---|---|
| Topology View | FR-01～FR-06 |
| Config Panel | FR-10, FR-11 |
| Car Port Input Panel | FR-07, FR-12, FR-13, FR-16 |
| Apply and Generate flow | FR-14 |
| Step Player | FR-15 |
| Error / Warning display | FR-08, FR-12, FR-13, FR-16 |

完成條件：使用者能在 Web GUI 完成配置、輸入 Present / Target、產生控制步驟並逐步播放。

---

## 5. 建議專案目錄

### FastAPI Service

```text
services/evcs-api/
├── app/
│   ├── main.py
│   ├── api/v1/
│   │   ├── health.py
│   │   ├── constants.py
│   │   ├── sessions.py
│   │   ├── validation.py
│   │   ├── snapshot.py
│   │   └── control_steps.py
│   ├── schemas/
│   │   ├── config.py
│   │   ├── car_port.py
│   │   ├── snapshot.py
│   │   ├── control_step.py
│   │   └── error.py
│   ├── services/
│   │   ├── validation_service.py
│   │   ├── config_service.py
│   │   ├── state_calculation_service.py
│   │   ├── control_step_service.py
│   │   └── session_service.py
│   └── adapters/
│       └── evcs_core_adapter.py
└── tests/
```

### Bun Web UI

```text
web/evcs-ui/
├── src/
│   ├── components/
│   │   ├── topology/
│   │   ├── config-panel/
│   │   ├── car-port-panel/
│   │   └── step-player/
│   ├── api/evcsApiClient.ts
│   ├── stores/evcsStore.ts
│   ├── types/evcs.ts
│   └── utils/validation.ts
├── package.json
└── bun.lockb
```

---



