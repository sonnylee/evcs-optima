# EVCS Optima 智慧充電站電力管理系統 — 技術規格書

---

## 1. 系統概述

### 1.1 專案目標

建構一套完整的智慧電動車充電站（EVCS）電力管理模擬引擎，具備以下核心能力：

- 以視覺化方式呈現 Relay 在多種情境下的狀態變化（Timing Diagram）
- 涵蓋多維度測試參數：車輛種類、來車 SOC、預定充電量、來車密集率等
- 車輛與充電站之間的完整交握流程模擬
- 後端開發語言：**Python**（未來核心演算法將移植為嵌入式 C 語言部署於真實 MCU 硬體）

### 1.2 設計哲學

- **分散式自治**：無集中式協調者，每個 MCU 獨立自治運作
- **Local View（本地視角）**：所有業務邏輯限定在本地視角內完成
- **Time Step 驅動**：固定時間間隔執行，非事件觸發

---

## 2. 系統架構

### 2.1 Time Step 驅動架構

| 設計原則 | 說明 |
|---|---|
| 時間步進為核心 | 固定時間間隔執行，不是事件觸發 |
| 輪詢式處理 | 每個 step 檢查所有狀態變化 |
| 同步執行 | Environment → Modules |
| 狀態快照 | 每個 step 產生完整的系統狀態快照 |

### 2.2 硬體架構

系統採用環形拓撲（Ring Topology），每個 MCU 管理一塊 REC BD（Rectifier Board），包含 4 個 SMR Group 與 2 個 Output（充電槍）。

**單一 MCU 硬體配置：**

- 4 個 SMR Group：G1（50kW）、G2（75kW）、G3（75kW）、G4（50kW），交替排列
- 2 個 Output：O1 直連 G1，O2 直連 G4
- Relay 連接相鄰 Group，控制功率流向與 Group 串聯/斷開

**3-MCU 線性參考配置（開發用）：**

```
O1   O2       O3   O4       O5   O6
 |    |        |    |        |    |
G1-R2-G2-R3-G3-R4-G4-R5-G5-R6-G6-R7-G7-R8-G8-R9-G9-R10-G10-R11-G11-R12-G12
|--- 50  75  75  50 ---|--- 50  75  75  50 ---|--- 50   75   75   50 ---|
       MCU1                   MCU2                     MCU3
```

- R1、R5、R9 為對外的 Bridge Relay（跨 MCU 邊界）
- MCU2 為本體，作為演算法的 Local 視角
- 充電槍與 Group 直連對應：O1↔G1、O2↔G4、O3↔G5、O4↔G8、O5↔G9、O6↔G12

**4-MCU 環形拓撲（第一階段目標）：**

```
MCU1 ↔ MCU2 ↔ MCU3
MCU2 ↔ MCU3 ↔ MCU4
MCU3 ↔ MCU4 ↔ MCU1
形成閉環（Ring）
```

第二階段可調整 MCU 個數為 1～12。

**可達離散功率等級（每 MCU）：** 50 / 125 / 200 / 250 kW

**啟動充電最小保證：** 125 kW

**借電優先級：** 右 > 左 > 雙側

### 2.3 軟體架構

整體分為兩層：Simulation Environment 與 Simulation Modules。

#### 第一層：Simulation Environment（模擬環境）

系統的時間驅動者與輸出管理者，本身不執行任何業務邏輯。

**Time Step**
系統的心跳產生器。每個迴圈推進一個 dt，對所有 Simulation Modules 發出 `step(dt)` 呼叫。時間推進是唯一的驅動來源，沒有任何外部事件可以繞過此機制。

**Vision Output**
狀態收集與可視化輸出的管理者。透過 `get_status()` 從所有 Modules 收集狀態快照，執行一致性驗證，通過後才輸出 Timing Diagram 與 Global View。驗證不通過則報錯，禁止輸出。報錯機制搭配 RelayEventLog 設計。

#### 第二層：Simulation Modules（模擬模組）

所有模組平等並列，無主從關係、無集中式統籌者。每個 dt 收到 `step(dt)` 後各自執行 `update()`，再各自回報 `get_status()`。

---

## 3. 模組定義

### 3.1 Vehicle（車輛實例）

代表一輛正在充電或等待充電的電動車。持有該車輛的 SOC 與充電功率關係圖（充電曲線）、初始 SOC、截止 SOC。每個 dt 更新當前 SOC。車輛生成後直接與對應的 MCU 互動，不經過任何中央管理者。

### 3.2 Traffic Simulator（來車模擬器）

車輛的來源產生器。根據設定的車輛密集度，決定是否在本 dt 生成新的 Vehicle 實例，並將車輛路由到對應充電槍。車輛連接完成後，Traffic Simulator 不再介入後續充電互動。

### 3.3 VehicleGenerator（車輛產生器）

依 `vehicle_profiles` 設定產生 Vehicle 實例，由 Traffic Simulator 呼叫。

### 3.4 MCU Control（MCU 控制器）

MCU 的業務邏輯核心，與其他 Module 地位平等。在每個 dt 的 `update()` 中自行判斷是否需執行借電、還電、功率重新分配等決策。透過 Ring Topology 僅與左右相鄰 MCU 協商邊界，協商完成後回到 Local 自行處理。

### 3.5 Charging Station（充電站容器）

充電站實體設備的數位替身，同時作為充電站殼（Shell）的模擬容器。不執行業務邏輯，為唯一對外可見的全域容器。

內部由四個子物件組成：

- **RectifierBoard（整流板）**：對應實體的 REC BD，是充電站硬體的頂層容器與 SMR Group 的主板。管理 SMR 群組、Relay 與 Output，提供硬體狀態查詢，不包含業務邏輯（硬體抽象層，有狀態無行為）。
- **SMRGroup（整流模組群組）**：對應多顆 25kW SMR 模組。MCU Control 決策後下達 Relay 切換指令，決定 Group 之間的串聯或斷開。
- **SMR（Switching Mode Rectifier）**：系統的最小功率單元（25kW）。
- **Relay（繼電器）**：直流繼電器的模擬物件，共兩種類型——(1) 控制功率流向 Output 的通路開關；(2) 負責 SMR Group 之間的斷開與閉合。切換時序是 Timing Diagram 的主要呈現內容。
- **Output（充電輸出）**：充電槍輸出端的模擬物件，代表實際對車輛輸出的直流功率通道。Vehicle 透過 Output 與 Charging Station 建立充電關係。

---

## 4. Time Step 流程

### 4.1 名詞定義

| 名詞 | 定義 |
|---|---|
| Max Require Power | 車輛更新 SOC 後，查詢自身功率曲線得出，表達「我現在需要多少功率」 |
| Available Power | MCU Control 評估自身功率餘裕後產出，表達「我現在最多能給你多少功率」 |
| Present Power | 車輛目前實際用電量，取 Available Power 與 Max Require Power 之最小值，由車輛主動向 MCU Control 提出 |

### 4.2 流程概覽

整個流程分為**初始化**與**主迴圈**兩個階段。

**初始化階段：** Start + Config File → Initialize Environment → 完成環境建構與參數載入。

**主迴圈：**

```
WHILE t(k) < t_end:
    t(k+1) = t(k) + ΔT                    // 推進時間

    Traffic Simulator:                      // 判斷是否生成新車輛
        根據密集度決定是否生成 Vehicle
        若生成則連接至對應充電槍
        連接完成後不再介入

    step(dt):                               // 核心步驟
        Vehicles:
            1. 根據充電功率積分更新 SOC
            2. 根據新 SOC 更新 Max Require Power
            3. 計算 Present Power 並通知 MCU Control

        Charging Station:
            MCU Control（決策判斷）:
                對照 Present Power vs Available Power
                執行借還電策略
                判斷實際分配功率
            Relays（依序切換）:
                依 MCU Control 指令執行繼電器切換
                更新硬體狀態

END → Vision Output 收集所有最終狀態 → 產出 Global View 與 Timing Diagram
```

### 4.3 設計原則

物件之間的互動屬於**內部引發的連鎖行為**。Vehicle 更新自身狀態後，MCU Control 得到功率變化並做出對應決策。Vehicles 與 MCU Control 都是連鎖行為的主體，透過共享的功率狀態資訊（Present Power / Available Power）產生互動，此資訊流是雙方內部邏輯引發的，而非外部安排的呼叫順序。

---

## 5. 資料結構

本系統使用兩張核心矩陣表，作為管理充電站電力資源的「共同語言」。

### 5.1 Relay Matrix（繼電器關係合法矩陣）

**目的：** 定義哪些硬體連線是「物理上允許的」。告訴系統哪兩個節點之間有實體電路連接，哪些組合根本不存在配線（標記為 -1）。

**座標說明：**
- 橫軸與縱軸分別代表系統中所有的 Group（INDEX 0–11）與 Output（INDEX 12–17）
- MCU INDEX = 1 為本體，INDEX = 0、2 分別代表左邊與右邊鄰居 MCU

**值定義：**
- `0`：繼電器目前開啟（斷路）
- `1`：繼電器目前閉合（通路）
- `-1`：此兩節點之間無實體配線，永遠不合法

**矩陣範例（3-MCU，18×18 對稱矩陣）：**

|  | MCU0 G0 | G1 | G2 | G3 | MCU1 G4 | G5 | G6 | G7 | MCU2 G8 | G9 | G10 | G11 | MCU0 O12 | O13 | MCU1 O14 | O15 | MCU2 O16 | O17 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **G0** | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 |
| **G1** | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 |
| **G2** | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 |
| **G3** | -1 | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | -1 | -1 | -1 |
| **G4** | -1 | -1 | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | -1 | -1 |
| **G5** | -1 | -1 | -1 | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 |
| **G6** | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 |
| **G7** | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | -1 |
| **G8** | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 |
| **G9** | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 |
| **G10** | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 |
| **G11** | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 |
| **O12** | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | - | - | - | - | - | - |
| **O13** | -1 | -1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | - | - | - | - | - | - |
| **O14** | -1 | -1 | -1 | -1 | 0/1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | - | - | - | - | - | - |
| **O15** | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | -1 | -1 | -1 | - | - | - | - | - | - |
| **O16** | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | -1 | -1 | -1 | - | - | - | - | - | - |
| **O17** | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | 0/1 | - | - | - | - | - | - |

查表即可判斷是否「物理可行」，不需逐一查詢硬體配置。

### 5.2 Module Assignment（模組使用狀態矩陣）

**目的：** 記錄當下每個充電模組（Group）正在被哪個充電槍（Output）使用。

**座標說明：**
- 列（Row）= Output（充電槍），欄（Column）= Group（充電模組）
- MCU INDEX = 1 為本體，INDEX = 0、2 分別代表左邊與右邊鄰居

**值定義：**
- `0`：此模組目前空閒，未被任何充電槍使用
- `1`：此模組目前使用中
- `-1`：此模組無法分配給該 Output

**索引轉換公式：**
- `Gx INDEX MOD 4` = 該 Group 在其 MCU 內的位置（0, 1, 2, 3）
- `Gx INDEX / 4` = 該 Group 屬於哪個 MCU（0=MCU0, 1=MCU1, 2=MCU2）

**矩陣範例（Output 2 借用 MCU1 全部 Group 的狀態）：**

| Output＼Group | MCU0 G0 | G1 | G2 | G3 | MCU1 G4 | G5 | G6 | G7 | MCU2 G8 | G9 | G10 | G11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **O0** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | -1 | -1 | -1 | -1 |
| **O1** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | -1 | -1 | -1 | -1 |
| **O2** | 0 | 0 | 0 | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| **O3** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **O4** | -1 | -1 | -1 | -1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **O5** | -1 | -1 | -1 | -1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

**四種查詢用途：**

1. **可用性檢查**：掃描某 Group 行，全為 0 時表示空閒可用
2. **模組歸屬**：掃描某 Group 行，找到值為 1 的那列即知是哪個 Output 在使用
3. **路徑追蹤**：掃描某 Output 列，找出所有 1 即為分配給該 Output 的充電模組
4. **衝突檢測**：掃描某 Group 行，出現多個 1 時表示衝突需處理

### 5.3 共通性原則

借電、還電、來車三種情境，在操作 Relay Matrix 與 Module Assignment 表時遵循同一套原則：

| 共通原則 | 說明 |
|---|---|
| 先找錨點，再擴展 | 任何操作都從「找到充電槍的合法起始 Group（錨點）」開始，再往兩側展開 |
| 本地優先，外部次之 | 操作順序上，本地 MCU 資源先動用，外部借入的資源後動用 |
| 連續區間，不可跳躍 | 所有使用中的 Group 必須形成連續的 [MIN, MAX] 區間，不允許中間有空洞 |

---

## 6. 核心業務邏輯

### 6.1 借電邏輯（找資源）

**定義：** 某個 Output 需要更多電力時，向鄰近空閒 Group 申請使用權的過程。

**觸發條件：**
`Present Power == Available Power` 且持續 N 個 step（例如 3 個 step）→ 借入一個額外 SMR Group。

**邏輯目的：** 在不違反物理配線（Relay Matrix）且不與現有使用者衝突（Module Assignment）的前提下，盡可能為充電槍取得足夠的電力資源。

**步驟：**

1. **初始化：找錨點** — 用 Relay Matrix 查詢 Output_x 對應的合法 Group，找出起點 Gx
2. **確定初始區間** — 從錨點出發，判斷 MCU 內位置，確定最小範圍 MIN 與 MAX
3. **擴展迴圈：優先本地** — 每次擴展先確認下一個 Group 是否屬於本地 MCU，是則優先往該側擴展（MIN-1 或 MAX+1）
4. **跨 MCU 借用** — 本地資源不足時，才往外（跨 MCU）繼續擴展 MAX

借電就是不斷把 [MIN, MAX] 區間往外推的過程。

### 6.2 還電邏輯（放資源）

**定義：** 充電槍用電需求降低時，主動釋放不再需要的 Group。

**觸發條件：**
`Available Power - Present Power >= 1 個 SMR Group` 且持續 N 個 step → 還出一個 SMR Group。

**邏輯目的：** 滿足自身電力需求的前提下釋放多餘資源，優先歸還跨 MCU 借來的資源。

**步驟（從外往內收縮）：**

1. 若 MIN 和 MAX 都屬於外部 MCU → 從 MIN 端開始歸還，MIN 往右移
2. 若只有 MIN 屬於外部 MCU → 先歸還 MIN 端，MIN 往右移
3. 若只有 MAX 屬於外部 MCU → 先歸還 MAX 端，MAX 往左移
4. 若 MIN 和 MAX 都是本地資源 → 若 MIN 是錨點則從 MAX 端歸還，否則從 MIN 端歸還

**原則：** 先還外部的，最後才動本地的。錨點是最後一個被碰的本地核心資源。

### 6.3 來車邏輯（資源管理）

**定義：** 新車輛抵達某 Output，系統為其分配 Group 並偵測是否與現有借電者發生衝突。

**邏輯目的：** 確保新到車輛能取得至少兩個合法 Group，若該模組已被他人借走則主動通知對方歸還。

#### 6.3.1 主動來車步驟

1. **初始化：找錨點** — 用 Relay Matrix 查詢 Output_x 對應的合法 Group
2. **確定初始區間** — 確定最小範圍 Gmin 與 Gmax
3. **衝突偵測** — 用 Module Assignment 表掃描 Gmin 到 Gmax，若某 Group 已被其他 Output 占用（值為 1）即為衝突
4. **通知還電** — 向佔用該 Group 的充電槍（借電方）發出「釋放資源」通知

#### 6.3.2 來車衝突（被通知還電）步驟

1. **收到通知** — 需釋放某個 Group（設為 Gx）
2. **找自己的錨點** — 用 Relay Matrix 找到自己充電槍的錨點位置
3. **判斷歸還方向** —
   - 錨點 < Gx：Gx 在右邊，設 MAX = Gx-1，歸還所有大於 MAX 的 Group
   - 錨點 > Gx：Gx 在左邊，設 MIN = Gx+1，歸還所有小於 MIN 的 Group
4. **執行 Relay 切換** — 先斷開（Open）所有 Relay，再依序閉合（Close）（排除歸還的 Group）

**判斷技巧：** 用 Gx INDEX 與錨點比較數字大小即可判斷需歸還的 Groups。

---

## 7. 環形通訊索引設計

### 7.1 環型 MCU 定址

```
前一個 MCU index = (自身 MCU index - 1 + N) mod N
下一個 MCU index = (自身 MCU index + 1 + N) mod N
```

其中 N = 系統中的 MCU 總數。

**特性：**
- 無論 N 為多少，公式完全相同
- index = 0 的前一個為 N-1（環形繞回正確處理）
- 每個 MCU 只需知道自己的 index，不需要全域參數
- 使用 `+N` 形式（防禦性寫法），避免 C 語言負數取模問題

### 7.2 硬體對應（CAN Bus）

硬體上各板子透過 CAN Bus 連接，每個節點知道自己的 CAN Bus ID，用上述公式算出前後節點 ID 即可建立通訊。

---

## 8. RelayEventLog 設計

### 8.1 設計決策

| 決策項目 | 選擇 | 理由 |
|---|---|---|
| 時間軸單位 | dt（整數時間步） | 模擬以 dt 為最小驅動單位 |
| 事件類型 | SWITCHED | Relay 切換視為硬體操作，切換即完成（原子操作） |
| 儲存範圍 | 全站統一 | 所有 Relay 在建構時注入同一份 RelayEventLog 參考，切換時主動呼叫 `append()` |

### 8.2 事件序列範例

| dt | relay_id | event_type | 備註 |
|---|---|---|---|
| 10 | 2 | SWITCHED | MCU-1 下令 R2 開路，切換完成 |
| 10 | 3 | SWITCHED | R2 完成後立即切換 R3 閉合 |
| 18 | 2 | SWITCHED | 還電，R2 重新閉合 |
| 18 | 3 | SWITCHED | R3 開路，回復原狀態 |

Timing Diagram 直接依 `dt_index` 繪製每個 Relay 的切換點（from_state → to_state 為開路或閉合）。

---

## 9. 日誌格式設計（邊界一致性檢查）

### 9.1 Log 格式

```json
{
  "type": "boundary_check",
  "time_step": 5,
  "mcu_pair": [0, 1],
  "result": "inconsistent",
  "conflicts": [
    {
      "group": 2,
      "output": 0,
      "field": "allocated_power",
      "values": [125, 100]
    },
    {
      "group": 3,
      "output": 1,
      "field": "relay_state",
      "values": ["CLOSED", "OPEN"]
    }
  ]
}
```

### 9.2 屬性說明

| Key | 說明 |
|---|---|
| `type` | 固定 `boundary_check` |
| `time_step` | 時間步索引 |
| `mcu_pair` | 相鄰 MCU 索引對，順序對應 `values` 陣列 |
| `result` | `consistent` 或 `inconsistent` |
| `conflicts` | 僅在不一致時出現 |
| `conflicts[].group` | 衝突的 Group 索引 |
| `conflicts[].output` | 衝突的 Output 索引 |
| `conflicts[].field` | 衝突欄位 |
| `conflicts[].values` | 兩側 MCU 各自的值，順序對應 `mcu_pair` |

---

## 10. 核心類別總覽

| 組件類別 | 職責說明 |
|---|---|
| Vehicle | 實現電動車的主動充電行為和充電樁交互邏輯 |
| TrafficSimulator | 決定車輛產生的密集度，呼叫 VehicleGenerator 生成 Vehicle，並將其路由至充電槍 |
| VehicleGenerator | 依 `vehicle_profiles` 產生 Vehicle 實例 |
| MCUControl | 實現業務邏輯和智能演算法，管理車輛充電狀態，協調功率借用/歸還 |
| ChargingStation | 充電站殼（Shell），唯一對外可見的全域容器，不執行業務邏輯 |
| RectifierBoard | 管理 SMR 群組、Relay 與 Output，提供硬體狀態查詢，不包含業務邏輯（硬體抽象層） |
| SMRGroup | 管理 N 組 SMR 模組 |
| SMR | Switching Mode Rectifier，系統的最小功率單元（25kW） |
| Output | 充電槍輸出端模擬物件，代表對車輛輸出的直流功率通道 |
| Relay | 兩種類型：(1) 功率流向 Output 的通路開關；(2) Group 之間的斷開與閉合 |
| RelayEvent | Relay 事件的最小單位 |
| RelayEventLog | 全站統一事件日誌，所有 Relay 在建構時注入同一份參考 |

---

## 11. 關鍵約束與硬體限制

| 約束 | 說明 |
|---|---|
| 最小保證功率 | 每個 Output 啟動充電最低 125kW |
| 連續區間約束 | 所有分配給同一 Output 的 Group 必須形成不間斷的連續區間 |
| Ring Topology 約束 | 只有物理相鄰的 MCU 才能進行功率借還 |
| 借電優先級 | 右 > 左 > 雙側 |
| Relay 切換為原子操作 | 無 `COMMAND_ISSUED` 或 `FAILED` 中間狀態，只有 `SWITCHED` |

---

## 12. Python 分層

simulation/
│
├── environment/
│   ├── simulation_engine.py
│   ├── time_controller.py
│   └── vision_output.py
│
├── modules/
│   ├── vehicle.py
│   ├── traffic_simulator.py
│   ├── mcu_control.py
│   └── vehicle_generator.py
│
├── hardware/
│   ├── charging_station.py
│   ├── rectifier_board.py
│   ├── smr_group.py
│   ├── smr.py
│   ├── relay.py
│   └── output.py
│
├── data/
│   ├── relay_matrix.py
│   ├── module_assignment.py
│
├── communication/
│   ├── borrow_protocol.py
│   ├── return_protocol.py
│
├── log/
│   ├── relay_event.py
│   └── relay_event_log.py
│
└── utils/
    ├── validator.py
    └── config_loader.py


## 13. 建議後續實作順序

Phase 1（基礎）
- Vehicle
- Output
- ChargingStation（無 borrow）
Phase 2
- Relay + Log
- ModuleAssignment
Phase 3
- MCUControl（單 MCU）
Phase 4
- 多 MCU + Borrow/Return
Phase 5
- Validator + Visualization

## 14. 建議架構選擇

要模擬充電站，其中充電槍、電動車都是自行運作 (有自已的 CPU/MCU)
推薦 (但可以不一定要)：asyncio + Queue（Actor Model）

基本骨架
定義基礎 Actor
<fundation-actor>
import asyncio

class Actor:
    def __init__(self, name):
        self.name = name
        self.queue = asyncio.Queue()
        self.running = True

    async def send(self, msg):
        await self.queue.put(msg)

    async def run(self):
        while self.running:
            msg = await self.queue.get()
            await self.handle(msg)

    async def handle(self, msg):
        pass
</fundation-actor>

電動車（EV）
<electric-vehicle>
class EV(Actor):
    def __init__(self, name, charger):
        super().__init__(name)
        self.charger = charger
        self.battery = 20  # %

    async def run(self):
        # 自己的行為（模擬開車/充電需求）
        while self.running:
            if self.battery < 30:
                print(f"{self.name} requesting charge")
                await self.charger.send({
                    "type": "charge_request",
                    "ev": self
                })
            await asyncio.sleep(2)

    async def handle(self, msg):
        if msg["type"] == "charging":
            self.battery += 10
            print(f"{self.name} charging... {self.battery}%")
</electric-vehicle>

充電槍（Output）
<Output>
class Output(Actor):
    def __init__(self, name):
        super().__init__(name)
        self.current_ev = None

    async def handle(self, msg):
        if msg["type"] == "charge_request":
            ev = msg["ev"]

            if self.current_ev is None:
                self.current_ev = ev
                print(f"{self.name} starts charging {ev.name}")

                # 模擬充電過程
                asyncio.create_task(self.charge(ev))
            else:
                print(f"{self.name} busy")

    async def Output(self, ev):
        for _ in range(3):
            await asyncio.sleep(1)
            await ev.send({"type": "charging"})

        print(f"{self.name} finished charging {ev.name}")
        self.current_ev = None
</Output>

啟動整個系統
<sys-starting>
async def main():
    output = Output("Output-1")

    ev1 = EV("EV-1", output)
    ev2 = EV("EV-2", output)

    await asyncio.gather(
        output.run(),
        ev1.run(),
        ev2.run()
    )

asyncio.run(main())
</sys-starting>

## 14. 建議資料庫

使用 TinyDB (memory) 並且將模擬的系統資料都以 JSON 格式儲存下來

## 15. 建議車輛種類與充電功率關係圖（充電曲線）

以一種車輛種類進行開發與驗證：2024 Tesla Cybertruck Cyberbeast (325 kW, optimized)
充電功率關係圖（充電曲線）的目錄位址：/assoicate/ev_curve_data.csv


## 附錄 A：參考連結

- 車輛與充電站交握流程圖：`https://mermaid.ai/d/2bb448cb-38b7-473b-9239-5f025ef1417c`
- 軟體架構圖：`https://mermaid.ai/d/4b7c31fd-e66c-49cf-8858-68147fd288b2`
- Time Step 流程圖：`https://mermaid.ai/d/2a707629-44a3-4641-8e63-8c13707ba232`
