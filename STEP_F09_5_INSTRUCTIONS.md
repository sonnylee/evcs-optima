# Step F09.5 — Main Page UI 對齊 PDF + FR-07/09 串通(灰底欄位也接通 store) — Claude Code 執行指令

> **背景**:`associate/main-page.pdf` 是設計團隊提供的目標 layout。當前 UI(Phase 1 完成的 ConfigPanel + TopologyView)的視覺結構跟 PDF 差異很大 — 不是補 CarPortPanel 就好,**整個主畫面 layout 要重做**。
>
> **本 step 範圍**:
> 1. **主畫面重做為「左圖右控」雙欄 layout**(對齊 main-page.pdf)
> 2. **白底元件接通(FR-07/09)**:右欄上半的 ±25 按鈕、Max Required 欄位 → store → backend
> 3. **灰底元件 PATCH session 但不串 Apply API(FR-13/16)**:右欄下半的 priority / present / target 欄位 onChange → `updateCarPort` → PATCH session(SPEC §2.2 表格規定)。**Apply 按鈕仍是 noop**(F14.3 接後端)
>
> **執行時間**:2 天(2026-05-05 ~ 5/6)
>
> **前置**:
> - 後端 FR-09 路徑(F09.1 ~ F09.3)已完成
> - UI Phase 1 已 commit:`ConfigPanel` / `TopologyView`(舊 layout)/ `evcsStore` / `evcsApiClient`
> - SPEC-WEB-UI.md §2.2、§3.3 是 store action 的權威規格(layout 部分以 main-page.pdf 為準)
> - **參考圖**:`associate/main-page.pdf` 與 repo 根目錄的 `MAIN_PAGE_REFERENCE.jpg`
>
> **執行後**:F09.6 做端到端整合測試;F14 系列做 player-page

---

## 給 Claude Code 的指令

把下面這整段(從 `=== 指令開始 ===` 到 `=== 指令結束 ===`)貼給 Claude Code:

=== 指令開始 ===

請執行 Step F09.5,目標是把主畫面 layout 重做成對齊 `associate/main-page.pdf`,把 FR-07/09 整條鏈接通,灰底欄位的 PATCH session 也接通(但 Apply 按鈕還是 noop)。

## 範圍限制

1. **禁止改 `services/evcs-api/` 任何後端檔案** — 後端 FR-09 已完成
2. **禁止改 `simulation/`**
3. **禁止串接 `apply-and-generate` API** — Apply 按鈕 onClick 是 console.log noop,F14.3 才會接通
4. 允許大幅改動:
   - `web/evcs-ui/src/components/App.tsx`(重做主 layout)
   - `web/evcs-ui/src/components/topology/TopologyView.tsx`(重做為直立 REC BD 鏈 + 右側水平車輛佈局)
   - `web/evcs-ui/src/components/topology/*.tsx`(視需要調整)
   - `web/evcs-ui/src/stores/evcsStore.ts`(補 actions)
5. 新增允許:
   - `web/evcs-ui/src/components/main-panel/MainPanel.tsx`(右欄總容器)
   - `web/evcs-ui/src/components/main-panel/CarRow.tsx`(右欄上半 8 列 ±25)
   - `web/evcs-ui/src/components/main-panel/MaxRequiredField.tsx`
   - `web/evcs-ui/src/components/main-panel/Fr14ControlTable.tsx`(右欄下半灰底)
   - `web/evcs-ui/src/components/main-panel/PriorityField.tsx`
   - `web/evcs-ui/src/components/main-panel/PresentField.tsx`
   - `web/evcs-ui/src/components/main-panel/TargetField.tsx`

## 工作項

### 1. 主畫面 layout(對齊 main-page.pdf)

#### 1.1 整體 Layout

**三欄並排**(對齊 main-page.pdf,**不是雙欄**):

- **左欄**:`TopologyView`,垂直 REC BD 鏈 + 右側 8 台 Car 圖示與文字
- **中欄(白底)**:8 列 `Car N - Max. Required: [數字] kW [+25] [-25]`(FR-07/09)
- **右欄(灰底)**:8 列 `優先級 / Present / Target` 表格 + 底部 Apply 按鈕(FR-13/14/16)

**關鍵約束 — 三欄水平對齊**:
中欄與右欄每一列(對應 Car N)**必須跟左欄該 Car 圖示處於同一個 horizontal baseline**。例如:
- 左欄 Car 1 圖示的垂直中心點 ≈ 中欄 "Car 1 - Max. Required:" 那列的中心 ≈ 右欄第 1 列(優先級 1 / Present / Target)的中心
- Car 2 同樣對齊,以此類推

不要求 pixel perfect,但 user 視覺上要能「沿著一條水平線從左欄某台車滑到右欄該車的所有控制欄位」。

ConfigPanel 暫時放在主畫面上方一條(高度 ~80px)或側邊 collapsible drawer,Sprint 1 不對齊 config-page.pdf。

#### 1.2 TopologyView 重做(對齊 PDF 左欄)

PDF 左欄結構,以 4 MCU × `[50,75,75,50]` 為例:

```
┌─────────────────────────────────────────────────────────────┐
│              ┌──────┐                                        │
│   ┌────┐  ●──│ 50kW │──● 〔OutRelay〕──●─── Car 1 ── 文字  │
│   │REC │     ├──────┤                                        │
│   │ BD │  ●──│ 75kW │                                        │
│   │ 1  │     ├──────┤                                        │
│   │OCC │  ●──│ 75kW │                                        │
│   │250 │     ├──────┤                                        │
│   │kW  │  ●──│ 50kW │──● 〔OutRelay〕──●─── Car 2 ── 文字  │
│   └────┘     └──────┘                                        │
│         (bridge ●)                                           │
│   ┌────┐     ┌──────┐                                        │
│   │REC │  ●──│ 50kW │──● 〔OutRelay〕──●─── Car 3 ── 文字  │
│   ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

關鍵視覺元素:

- **REC BD 標籤**:垂直 box,寬度約 80px,高度涵蓋 4 個 group。背景色依 RecBdLabel 既有色票(藍/綠/紅/灰);內含 `REC BD N` / `Occupied`(or Idle)/ `Power: XXXkW`
- **Group 方塊**:堆疊 4 個直立方塊,高度依模塊功率視覺成比例(50kW 較矮、75kW 較高);方塊上寫 `50kW` / `75kW`;有 owner 時填底色(同 REC BD 色),無 owner 時白色
- **Inter-group Relay**:左側,4 個 group 之間 3 個小圓點(綠 = closed,灰 = open)
- **Output Relay**:在 group 方塊跟車輛圖示之間,綠色小方框(closed)或灰色(open)
- **Car 圖示**:綠色(active 充電中)或灰色(inactive idle)
- **Car 旁邊文字**:`Car N - Max. Required: XXX kW`
- **Bridge Relay**:REC BD 之間的縱線連接點,綠/灰小方框

**重要**:不要為了 100% 還原 PDF 的每個 pixel 花太久時間。**結構正確 + 配色對齊 + 比例合理**就好。視覺細節 Sprint 2 再 polish。

#### 1.3 MainPanel(中欄白底 + 右欄灰底,並排,皆與左欄水平對齊)

**重要**:中欄(白底)與右欄(灰底)是**左右並排**。每一列(對應 Car N)都跟左欄該 Car 圖示水平對齊。

```
左欄 (TopologyView)        中欄(白底,FR-07/09)                     右欄(灰底,FR-13/14/16)
                          │                                        │
🚗 Car 1                  Car 1 - Max. Required: [600] kW [+25][-25]   [1]   [50] kW   [100] kW
                          │                                        │
🚗 Car 2                  Car 2 - Max. Required: [  0] kW [+25][-25]   [3]   [50] kW   [100] kW
                          │                                        │
🚗 Car 3                  Car 3 - Max. Required: [100] kW [+25][-25]   [2]   [50] kW   [100] kW
                          │                                        │
🚗 Car 4                  Car 4 - Max. Required: [200] kW [+25][-25]   [4]   [50] kW   [100] kW
                          │                                        │
🚗 Car 5                  Car 5 - Max. Required: [ 50] kW [+25][-25]   [5]   [50] kW   [100] kW
                          │                                        │
🚗 Car 6                  Car 6 - Max. Required: [600] kW [+25][-25]   [6]   [50] kW   [100] kW
                          │                                        │
🚗 Car 7                  Car 7 - Max. Required: [  0] kW [+25][-25]   [7]   [50] kW   [100] kW
                          │                                        │
🚗 Car 8                  Car 8 - Max. Required: [125] kW [+25][-25]   [8]   [50] kW   [100] kW
                          │                                        │
                                                                          ┌──────────────────────┐
                                                                          │ Apply and Generate   │
                                                                          │ Control steps        │
                                                                          └──────────────────────┘
```

右欄灰底頂部有深色表頭「優先級 / Present / Target」。Apply 按鈕在右欄灰底底部、跟 Car 8 列大約同高或更下方。

實作上一個 clean 做法是用一個 8-row × 2-column grid(中欄 + 右欄各一 column),每 row 對應一個 port。左欄 TopologyView 是獨立的 component,但要確保它的 8 個 Car 圖示的垂直間距跟中欄/右欄的 row 高度匹配 — 這通常需要在三個欄位都用相同的 row height(譬如 `h-12` 或 `py-3`)。

#### 1.4 中欄 CarRow 8 個(FR-07/09,白底)

中欄是一個垂直 stack 的 8 列 CarRow。每列**必須跟左欄對應的 Car 圖示水平對齊**(用相同的 row height,譬如 `h-12` 或 `py-3`)。每列結構:

```tsx
<div className="flex items-center gap-3 py-2">
  <span className="w-32">Car {portId} - Max. Required:</span>
  <MaxRequiredField portId={portId} value={port.max_required} />
  <span>kW</span>
  <button className="bg-yellow-500 text-white px-3 py-1 rounded">+25kW</button>
  <button className="bg-red-500 text-white px-3 py-1 rounded">-25kW</button>
</div>
```

行為:
- 數字輸入框 onBlur / Enter commit → `updateCarPort(portId, { max_required: rounded })` (前端 clamp [0,600] + round 到 25 倍數)
- `+25kW` 按鈕 → `nudgeMaxRequired(portId, +25)`
- `-25kW` 按鈕 → `nudgeMaxRequired(portId, -25)`
- 按鈕**永遠可點**,不 disabled
- 數字 optimistic 立刻更新

#### 1.5 右欄 Fr14ControlTable(灰底,**接通 store 但不串 Apply API**)

右欄是一整片灰底區塊,內含深色表頭(優先級 / Present / Target)+ 8 列控制欄位 + 底部 Apply 按鈕。**8 列控制欄位必須跟左欄/中欄對應的 Car N 水平對齊**(同樣使用相同的 row height)。

```tsx
<div className="bg-slate-100 p-4 rounded">
  <div className="grid grid-cols-3 gap-4 text-center font-bold mb-2 bg-slate-700 text-white p-2 rounded">
    <span>優先級</span>
    <span>Present</span>
    <span>Target</span>
  </div>
  {carPorts.map(port => (
    <div key={port.port_id} className="grid grid-cols-3 gap-4 items-center py-2">
      <PriorityField portId={port.port_id} value={port.priority}
                     allPriorities={allPrioritiesExcept(port.port_id)}
                     maxN={maxN} />
      <PresentField portId={port.port_id} value={port.present} />
      <TargetField portId={port.port_id} value={port.target} />
    </div>
  ))}
  <button
    className="bg-teal-500 text-white px-6 py-3 rounded mt-4 w-full"
    onClick={() => console.log("Apply and Generate — F14.3 will wire backend")}
  >
    Apply and Generate Control steps
  </button>
</div>
```

**灰底欄位行為(關鍵 — 跟 v2 不同)**:

- `PriorityField` onBlur commit:
  - 前端驗證:範圍 `[1, maxN]`、不重複(用 `allPriorities` 檢查)
  - 通過驗證 → `updateCarPort(portId, { priority: num })`
  - PATCH session 會被觸發,但 **`refreshSnapshot()` 不會**(SPEC §2.2 表格規定)
- `PresentField` onBlur commit:
  - 前端 clamp [0, 600] + round to 25
  - `updateCarPort(portId, { present: rounded })`
  - 同樣 PATCH 但不 refresh snapshot
- `TargetField`:同 `PresentField`,但用 `target` 欄位
- `Apply` 按鈕:onClick `console.log(...)`,**完全不呼叫後端**

**這個分流邏輯由 store 的 `updateCarPort` 統一處理**(見下方 §2.1)。F09.5 的 `Fr14ControlTable` 元件只是把 onChange 接到對的 store action,不需要在元件層面做 mode 判斷。

### 2. 補齊 store actions(`evcsStore.ts`)

依 SPEC-WEB-UI §2.2 規格新增三個 actions:

#### 2.1 `updateCarPort(portId, patch)` — **核心分流邏輯**

```typescript
updateCarPort: (portId: number, patch: Partial<CarPortInput>) => Promise<void>;
```

行為:

1. Optimistic local update:`set({ carPorts: next })`
2. **永遠 PATCH 後端整個 array**(SPEC §1.2 規定 PATCH body 是完整 list,不是 partial)
3. **只有當 `patch` 包含 `max_required` 時才呼叫 `refreshSnapshot()`**

對應 SPEC §2.2 表格(極關鍵,寫錯違反 SPEC):

| patch 包含 | PATCH session | refreshSnapshot |
|---|---|---|
| `max_required` | ✅ | ✅(FR-09) |
| `present` | ✅ | ❌(FR-13)|
| `target` | ✅ | ❌(FR-13)|
| `priority` | ✅ | ❌(FR-16,僅供 FR-14 使用)|

具體實作:

```typescript
updateCarPort: async (portId, patch) => {
  const sid = get().sessionId;
  if (!sid) return;  // 無 session noop
  
  // 1. Optimistic local update
  const next = get().carPorts.map(p =>
    p.port_id === portId ? { ...p, ...patch } : p,
  );
  set({ carPorts: next });
  
  // 2. PATCH backend
  const { data, error } = await evcsApi.patchSession(sid, { car_ports: next });
  if (error || !data) {
    set({ globalError: 'Failed to update car port' });
    return;
  }
  
  // 3. Replace local with server response (avoid drift)
  set({ carPorts: data.car_ports });
  
  // 4. Refresh snapshot ONLY if max_required changed
  if ('max_required' in patch) {
    await get().refreshSnapshot();
  }
},
```

#### 2.2 `nudgeMaxRequired(portId, delta)`

```typescript
nudgeMaxRequired: (portId: number, delta: number) => Promise<void>;
```

行為(依 SPEC-WEB-UI §2.2):

1. 從 store 讀當前 port
2. clamp `[0, 600]`
3. **若 clamped === current,early return**(不打 API,FR-08 邊界保護)
4. delegate 到 `updateCarPort(portId, { max_required: clamped })`

```typescript
nudgeMaxRequired: async (portId, delta) => {
  const port = get().carPorts.find(p => p.port_id === portId);
  if (!port) return;
  const clamped = Math.max(0, Math.min(600, port.max_required + delta));
  if (clamped === port.max_required) return;
  await get().updateCarPort(portId, { max_required: clamped });
},
```

#### 2.3 在 `EvcsStore` interface 加上 type 宣告

不要忘記同步補 type。

### 3. 整合到 `App.tsx`

```tsx
<div className="min-h-screen">
  <ConfigPanel />  {/* 縮成 collapsible 或一條,Sprint 2 重做 */}
  <div className="grid grid-cols-[1fr_1fr_1fr] gap-6 p-6">
    {/* 三欄並排,每欄佔約 1/3 寬度;比例可微調 */}
    <TopologyView />
    <CarRowsColumn />     {/* 中欄白底,8 列 ±25 */}
    <Fr14ControlTable />  {/* 右欄灰底,8 列 priority/present/target + Apply */}
  </div>
</div>
```

或者如果你判斷「中欄 + 右欄合併在 MainPanel 內」結構更乾淨,也可以:

```tsx
<div className="grid grid-cols-2 gap-6 p-6">
  <TopologyView />
  <MainPanel />  {/* 內部再分白底/灰底兩欄 */}
</div>
```

兩種寫法都可以,**重點是視覺結果是三欄並排、每列水平對齊**。

確認既有 `ConfigPanel` 仍可用(雖然視覺位置變了)。

### 4. UI 視覺處理

#### 4.1 Loading state
- ±25 按鈕在 `isLoading === true` 時**不要 disable**
- 可加微弱視覺暗示(數字略灰),不要明顯 spinner

#### 4.2 顏色(對齊 PDF)
- `+25kW` 按鈕:黃色背景白字 `bg-yellow-500 text-white`
- `-25kW` 按鈕:紅色背景白字 `bg-red-500 text-white`
- Apply 按鈕:teal 綠色 `bg-teal-500 text-white`
- 灰底區域:`bg-slate-100`
- 表頭深色:`bg-slate-700 text-white`

#### 4.3 Error display
- `carPortErrors` / 個別欄位錯誤(priority 衝突)在欄位旁紅字
- 不要用 alert / toast popups

### 5. 優先級驗證(PriorityField 內部)

PriorityField commit 流程:

1. parse 輸入(空字串視為 `null`,清除優先級)
2. 若是數字:檢查 `[1, maxN]` 範圍
3. 若已通過 1+2:檢查不跟其他 port 重複(`allPriorities` 是不含當前 port 的其他 port 的 priority list)
4. 通過 → `updateCarPort(portId, { priority: num })`
5. 不通過 → 在欄位旁顯示紅字錯誤訊息,**不送 API**

```typescript
function PriorityField({ portId, value, allPriorities, maxN }: Props) {
  const update = useEvcsStore(s => s.updateCarPort);
  const [draft, setDraft] = useState(value === null ? '' : String(value));
  const [error, setError] = useState<string | null>(null);
  
  useEffect(() => {
    setDraft(value === null ? '' : String(value));
  }, [value]);
  
  const commit = () => {
    setError(null);
    if (draft === '') {
      update(portId, { priority: null });
      return;
    }
    const num = parseInt(draft, 10);
    if (isNaN(num) || num < 1 || num > maxN) {
      setError(`必須在 1 到 ${maxN} 之間`);
      return;
    }
    if (allPriorities.includes(num)) {
      setError(`優先級 ${num} 已被使用`);
      return;
    }
    update(portId, { priority: num });
  };
  
  return (
    <div className="flex flex-col">
      <input
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit(); }}
        className="w-12 text-center border rounded"
      />
      {error && <span className="text-xs text-red-500">{error}</span>}
    </div>
  );
}
```

不需要在 F09.5 接 `validateCarPorts` API(F14.3 的 Apply 流程才會用到後端 batch 驗證)。

### 6. 不要做的事(留給 F14.x 或 Sprint 2)

- ❌ Player 頁面 — F14.3 工作
- ❌ Apply 按鈕的後端串接(`apply-and-generate` API)— F14.3
- ❌ `validateCarPorts` 後端 batch 驗證 — F14.3 的 Apply 流程才會用到
- ❌ Edit / Player mode 切換 — F14.3
- ❌ ConfigPanel 重做 — Sprint 2(5/15 後)

### 7. 完成條件

- `bun run build` 在 `web/evcs-ui/` 成功
- `bun run dev` 啟動後,主畫面結構對齊 main-page.pdf(不要求 pixel perfect)
- Manual smoke test 跑通(以下「給 user 的 review checklist」)
- 既有 222+ test 沒回歸(本 step 不動後端)

### 8. 完成後請回報

1. 新增的檔案路徑與行數
2. 改動的檔案 diff 摘要
3. `bun run build` 結果
4. Manual smoke test 結果
5. PDF 對齊的程度自評(直接畫面跟 PDF 哪些差異最大)
6. 過程中發現的任何問題

## 你可能會踩到的點

1. **PDF 跟 SPEC-WEB-UI.md 文字描述衝突** — 以 PDF 為準。例如 SPEC §3.3 文字描述 CarPortPanel 是「每路一橫列」(包含 priority/present/target 同列),但 PDF 是「三欄並排:左圖、中白底、右灰底」結構。**遇到衝突,優先對齊 PDF**

2. **三欄水平對齊是這個 layout 的核心約束**。實作時要決定一件事:**TopologyView 的 8 個 Car 圖示間距決定整個畫面的 row height**,還是**中欄/右欄的 row height 決定 TopologyView 該如何排車**?
   - 推薦做法:在三個欄位都用相同的 row height(譬如 `h-16` 或 `py-4`),TopologyView 內的車輛區用同樣的高度排,中欄/右欄的每列用同樣高度,這樣自然對齊
   - 如果 REC BD 鏈高度不能配合 8 列車輛(譬如 4 個 REC BD × 250px = 1000px,但 8 列 × 64px = 512px),REC BD 鏈跟車輛分開定位即可,**車輛跟中欄/右欄對齊比 REC BD 跟車輛對齊更重要**

3. **`patchSession` body 是整個 carPorts array** — 不要試圖只 PATCH 改變的那一筆

4. **`refreshSnapshot()` 只在 `max_required` 變化時觸發** — 違反這個會讓 priority/present/target 編輯也觸發畫面重繪,違反 SPEC §FR-13

5. **REC BD layout 比預期難畫** — 簡化是 OK 的。不要為 100% PDF 還原花太久時間

6. **既有 PackGrid / RelayIcon / CarIcon / RecBdLabel / BridgeRelay** — 重用或重構都可,但要對齊新 layout

7. **既有 ConfigPanel 不要改太多** — 縮小或藏起來即可,Sprint 2 會重做

## 如果遇到問題

1. **PDF 視覺細節看不懂**:用合理近似,在回報中說明
2. **既有 ConfigPanel 整合進新 layout 後壞掉**:停下來告訴我
3. **store action 邏輯複雜超出 SPEC**:停下來問
4. **build 失敗但邏輯看起來對**:可能是 type / Tailwind 設定

=== 指令結束 ===

---

## 你(user)的 review checklist

### 1. 視覺結構對齊 PDF

開瀏覽器看,跟 `MAIN_PAGE_REFERENCE.jpg` 對比關鍵元素是否都有:

- 整體**三欄並排** layout(左圖、中白、右灰)— **不是雙欄**
- 左欄 4 個 REC BD 直立鏈
- Group 方塊有 50/75 高度比例差
- Inter-group relay 顯示為小圓點
- 中欄白底 8 列 ±25kW 按鈕(黃 +25 / 紅 −25)
- 右欄灰底 8 列(優先級 / Present / Target)
- 右欄灰底底部 Apply 按鈕(teal)
- **三欄每列水平對齊**:左欄 Car 1 ≈ 中欄 Car 1 那列 ≈ 右欄第 1 列(優先級 1)。沿著一條水平線從左滑到右,看到的是同一台車的相關控制

### 2. **Manual Smoke Test**(關鍵)

```bash
cd web/evcs-ui
bun install
bun run dev
```

跑下面流程:

| 流程 | 預期 |
|---|---|
| 1. ConfigPanel 設 4 MCU 預設配置 | TopologyView 出現 4 REC BD |
| 2. 主畫面右欄出現 8 列 Car 控制 | ✓ |
| 3. Car 1 點 +25kW 五次 → 125 kW | 數字立刻變、左欄 Car 1 變綠、REC BD 1 顯示 5 個 pack 變色、output relay CLOSED |
| 4. Car 1 點 -25kW → 100 kW | 視覺對應縮減 |
| 5. Car 2 連點 +25kW 24 次 → 600 kW | 不卡頓、最終視覺正確 |
| 6. **Car 1 改 priority = 1** | priority 值寫進 store、PATCH session 成功、**TopologyView 不變** |
| 7. **Car 2 也改 priority = 1** | 顯示「優先級 1 已被使用」紅字、不送 API |
| 8. **Car 1 改 Present = 50** | 數字改、PATCH session 成功、**TopologyView 不變** |
| 9. **Car 1 改 Target = 100** | 數字改、PATCH session 成功、**TopologyView 不變** |
| 10. 按 Apply 按鈕 | console.log "F14.3 will wire backend"、**不呼叫後端** |
| 11. 重整網頁(F5) | session lost、需要重新從 ConfigPanel 開始(預期行為,F-15 才有 player mode 持久化) |

**第 3 個流程**:FR-09 端到端核心驗證
**第 6/8/9 個流程**:FR-13/16 灰底欄位的「PATCH 但不重繪」分流驗證(這是新加的)
**第 10 個流程**:FR-14 接通延後到 F14.3 的驗證

### 3. 後端沒被影響

```bash
cd services/evcs-api && pytest -v
```

既有 test 全綠(包含 25 個 xfail),沒新紅。

### 4. 第 5 條回報的「PDF 對齊自評」

如果 Claude Code 自評某些差異很大,看是否合理。Sprint 1 demo 接受合理近似。

---

## 5/5 ~ 5/6 時程

| 時段 | 動作 |
|---|---|
| 5/5 上午 | F09.5 plan + auto:layout 重做 + store actions |
| 5/5 下午 | CarRow + 灰底欄位 + 視覺打磨 |
| 5/5 晚上 | Manual smoke test 第一輪 |
| 5/6 上午 | 修小問題、完成 11 個流程驗證 |
| 5/6 下午 | F09.6 整合測試 + push |

按目前節奏,5/6 下午結束時 FR-09 完整 demo-able,主畫面對齊 PDF,可進 F14 系列。
