# Phase 4 — Bun / React Web UI 開發規格書

> 對應後端 commit：`28cd4fc Phase 3 is complete. All 55 tests pass`
> 文件版本：v1.0（2026-04-28）
> Wireframe：[Figma EVCS-Vision](https://www.figma.com/design/KHQ1AFIbh2lBS5m8TSOrv9/EVCS-Vision?node-id=13-572)

---

## 0. 文件目的與閱讀順序

本規格書把 SPEC-WEB-API.md §4 Phase 4 的六個工作項，展開為前端實作層級的細節，包含：

- 技術棧、目錄結構、開發指令
- 全域狀態設計（Zustand store）
- 與後端的型別契約（OpenAPI client 自動產生）
- 6 個 UI 區塊（每個區塊：UI 元素、props、state、API 呼叫順序、錯誤處理）
- 路由與雙模式（Edit / Player）切換
- 驗收標準與測試策略

**閱讀順序建議**：先看 §1 技術棧與 §2 全域狀態，再依照 §3.1 ~ §3.6 順序實作 6 個 UI 區塊。

---

## 1. 技術棧與專案設定

### 1.1 技術棧

| 層級 | 選用 | 理由 |
|---|---|---|
| 套件管理 / Runtime | **Bun** | SPEC §5 指定；冷啟動快、原生 TS 支援 |
| 前端框架 | **React 18 + TypeScript 5** | 業界標準、後端 schema 用 TS 型別最自然 |
| 狀態管理 | **Zustand** | 輕量、不需 Provider boilerplate；副作用管理單純 |
| API 呼叫 | **openapi-fetch** + **openapi-typescript** | 從後端 OpenAPI 自動產出型別；與 Pydantic schema 自動同步 |
| 樣式 | **Tailwind CSS** | utility-first，快速貼近 Figma wireframe；無 CSS-in-JS runtime cost |
| 構建工具 | **Vite**（透過 Bun） | HMR、快速 dev server |
| 測試 | **Vitest** + **React Testing Library** | Vite 原生整合 |
| 表單驗證（複雜時） | 內建 useState 為主；超過 5 欄位的表單再考慮 React Hook Form | 避免過度設計 |

### 1.2 專案目錄（與 SPEC §5 對齊並擴展）

```
web/evcs-ui/
├── public/
├── src/
│   ├── api/
│   │   ├── schema.ts             # ← openapi-typescript 自動產出
│   │   └── evcsApiClient.ts      # ← 包一層好用的 client（見 §1.4）
│   ├── components/
│   │   ├── topology/
│   │   │   ├── TopologyView.tsx
│   │   │   ├── RecBdLabel.tsx
│   │   │   ├── PackGrid.tsx
│   │   │   ├── RelayIcon.tsx
│   │   │   └── CarIcon.tsx
│   │   ├── config-panel/
│   │   │   ├── ConfigPanel.tsx
│   │   │   ├── RecBdCountInput.tsx
│   │   │   └── ModulePowerInput.tsx
│   │   ├── car-port-panel/
│   │   │   ├── CarPortPanel.tsx
│   │   │   ├── CarPortRow.tsx
│   │   │   ├── MaxRequiredField.tsx     # ← FR-07 +25/-25 + FR-12 手動輸入
│   │   │   ├── PresentTargetFields.tsx  # ← FR-13
│   │   │   └── PriorityField.tsx        # ← FR-16
│   │   ├── step-player/
│   │   │   ├── StepPlayer.tsx
│   │   │   ├── StepProgress.tsx
│   │   │   └── StepDescription.tsx
│   │   ├── shared/
│   │   │   ├── ErrorBanner.tsx
│   │   │   ├── WarningList.tsx
│   │   │   └── Button.tsx
│   │   └── App.tsx
│   ├── stores/
│   │   └── evcsStore.ts          # ← Zustand global store
│   ├── hooks/
│   │   ├── useDebounce.ts
│   │   └── useSnapshotRefetch.ts # ← FR-09 聯動觸發
│   ├── types/
│   │   └── evcs.ts               # ← 從 schema.ts re-export 常用型別別名
│   ├── utils/
│   │   ├── validation.ts         # ← clamp、round-to-25 等小工具
│   │   └── colors.ts             # ← 顏色 helpers
│   ├── main.tsx
│   └── index.css
├── tests/
│   ├── components/
│   └── stores/
├── index.html
├── package.json
├── tsconfig.json
├── tailwind.config.js
├── vite.config.ts
└── bun.lockb
```

### 1.3 啟動 / 構建指令

`package.json`：

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:ui": "vitest --ui",
    "gen:api": "curl http://localhost:8000/openapi.json -o openapi.json && bunx openapi-typescript openapi.json -o src/api/schema.ts",
    "lint": "eslint . --ext ts,tsx"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "zustand": "^4.5.0",
    "openapi-fetch": "^0.13.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "openapi-typescript": "^7.4.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0",
    "@testing-library/react": "^16.0.0",
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
```

開發 workflow：

```bash
# Terminal 1：啟動後端
python3 -m uvicorn app.main:app --app-dir services/evcs-api --reload --port 8000

# Terminal 2：第一次啟動前端時先產 API client
cd web/evcs-ui
bun install
bun run gen:api          # ← 產出 src/api/schema.ts
bun run dev              # ← Vite dev server on :5173
```

> **API schema 同步**：每次後端 PR 改 schema 後，前端跑一次 `bun run gen:api`，TypeScript 編譯器會立刻指出哪些前端代碼需要跟著改。

### 1.4 evcsApiClient.ts 包裝

`src/api/evcsApiClient.ts`：

```typescript
import createClient from 'openapi-fetch';
import type { paths } from './schema';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const apiClient = createClient<paths>({ baseUrl: BASE_URL });

// 常用呼叫 wrap（讓元件層更乾淨，且集中錯誤處理）
export const evcsApi = {
  getConstants: () => apiClient.GET('/api/v1/constants'),

  getPalette: (count: number, cycle: boolean) =>
    apiClient.GET('/api/v1/palette', { params: { query: { count, cycle } } }),

  validateModulePowers: (raw: string) =>
    apiClient.POST('/api/v1/validate/module-powers', { body: { raw } }),

  validateCarPorts: (
    batch: paths['/api/v1/validate/car-ports']['post']['requestBody']['content']['application/json']['batch'],
    system_config?: paths['/api/v1/validate/car-ports']['post']['requestBody']['content']['application/json']['system_config'],
  ) =>
    apiClient.POST('/api/v1/validate/car-ports', { body: { batch, system_config } }),

  validateSystemConfig: (cfg: paths['/api/v1/validate/system-config']['post']['requestBody']['content']['application/json']) =>
    apiClient.POST('/api/v1/validate/system-config', { body: cfg }),

  createSession: (body: paths['/api/v1/sessions']['post']['requestBody']['content']['application/json']) =>
    apiClient.POST('/api/v1/sessions', { body }),

  patchSession: (
    sessionId: string,
    body: paths['/api/v1/sessions/{session_id}']['patch']['requestBody']['content']['application/json'],
  ) =>
    apiClient.PATCH('/api/v1/sessions/{session_id}', {
      params: { path: { session_id: sessionId } },
      body,
    }),

  getSnapshot: (sessionId: string) =>
    apiClient.GET('/api/v1/sessions/{session_id}/snapshot', {
      params: { path: { session_id: sessionId } },
    }),

  computeSnapshot: (body: paths['/api/v1/snapshot/compute']['post']['requestBody']['content']['application/json']) =>
    apiClient.POST('/api/v1/snapshot/compute', { body }),

  topologyPreview: (body: paths['/api/v1/topology/preview']['post']['requestBody']['content']['application/json']) =>
    apiClient.POST('/api/v1/topology/preview', { body }),

  applyAndGenerate: (sessionId: string) =>
    apiClient.POST('/api/v1/sessions/{session_id}/apply-and-generate', {
      params: { path: { session_id: sessionId } },
    }),

  step: (sessionId: string, direction: 'forward' | 'back') =>
    apiClient.POST('/api/v1/sessions/{session_id}/step', {
      params: { path: { session_id: sessionId }, query: { direction } },
    }),
};
```

---

## 2. 全域狀態設計（Zustand Store）

### 2.1 狀態形狀

`src/stores/evcsStore.ts`：

```typescript
import { create } from 'zustand';
import type { components } from '../api/schema';

type SystemConfig = components['schemas']['SystemConfig'];
type CarPortInput = components['schemas']['CarPortInput'];
type VisualSnapshot = components['schemas']['VisualSnapshot'];
type ControlStepSequence = components['schemas']['ControlStepSequence'];
type WarningDetail = components['schemas']['WarningDetail'];
type ErrorDetail = components['schemas']['ErrorDetail'];

type Mode = 'edit' | 'player';

interface EvcsStore {
  // ----- Identity -----
  sessionId: string | null;

  // ----- Config (FR-10, FR-11) -----
  systemConfig: SystemConfig | null;
  configErrors: ErrorDetail[];

  // ----- Car ports (FR-07, FR-12, FR-13, FR-16) -----
  carPorts: CarPortInput[];
  carPortWarnings: WarningDetail[];
  carPortErrors: ErrorDetail[];

  // ----- Snapshot (FR-02..06, FR-09) -----
  snapshot: VisualSnapshot | null;

  // ----- Player (FR-15) -----
  mode: Mode;
  stepSequence: ControlStepSequence | null;
  currentStepIndex: number;       // 0 = Initial State

  // ----- UX -----
  isLoading: boolean;
  globalError: string | null;     // network / 5xx

  // ----- Actions -----
  initSession: (cfg: SystemConfig, ports: CarPortInput[]) => Promise<void>;
  updateSystemConfig: (cfg: SystemConfig) => Promise<void>;
  updateCarPort: (portId: number, patch: Partial<CarPortInput>) => Promise<void>;
  nudgeMaxRequired: (portId: number, delta: 25 | -25) => Promise<void>;  // FR-07
  refreshSnapshot: () => Promise<void>;                                   // FR-09
  applyAndGenerate: () => Promise<void>;                                  // FR-14
  stepForward: () => Promise<void>;                                       // FR-15
  stepBack: () => Promise<void>;                                          // FR-15
  exitPlayer: () => void;                                                 // FR-15
}
```

### 2.2 關鍵 actions 行為

#### `initSession(cfg, ports)`

1. `evcsApi.createSession({ system_config: cfg, car_ports: ports })`
2. 取回 `session_id`，設 `sessionId`、`systemConfig`、`carPorts`
3. 立刻呼叫 `refreshSnapshot()`

#### `updateSystemConfig(cfg)` — FR-10/11

當 REC BD 數量或模塊功率變更：

1. 先呼叫 `evcsApi.validateSystemConfig(cfg)`
2. 若有 errors → 寫入 `configErrors`，不繼續
3. 若 `cfg.rec_bd_count` 改變 → 清空 `carPorts.priority`（SPEC FR-16 規定）
4. `evcsApi.patchSession(sessionId, { system_config: cfg })`
5. `refreshSnapshot()`

#### `updateCarPort(portId, patch)` — FR-12/13/16

依照 `patch` 的鍵決定後續行為（這是 FR-13「Target 不立即重畫」的關鍵）：

| patch 包含 | 是否 PATCH session | 是否 refreshSnapshot |
|---|---|---|
| `max_required` | ✅ | ✅（FR-09） |
| `present` | ✅ | ❌（FR-13）|
| `target` | ✅ | ❌（FR-13）|
| `priority` | ✅ | ❌（FR-16，僅供 FR-14 使用）|

實作：

```typescript
updateCarPort: async (portId, patch) => {
  const next = get().carPorts.map(p =>
    p.port_id === portId ? { ...p, ...patch } : p,
  );
  set({ carPorts: next });

  // 永遠 PATCH 後端
  await evcsApi.patchSession(get().sessionId!, { car_ports: next });

  // 只有 max_required 才重畫
  if ('max_required' in patch) {
    await get().refreshSnapshot();
  }
}
```

#### `nudgeMaxRequired(portId, delta)` — FR-07

```typescript
nudgeMaxRequired: async (portId, delta) => {
  const port = get().carPorts.find(p => p.port_id === portId);
  if (!port) return;
  const clamped = Math.max(0, Math.min(600, port.max_required + delta));
  if (clamped === port.max_required) return;  // 邊界（FR-08）保護

  await get().updateCarPort(portId, { max_required: clamped });
}
```

#### `refreshSnapshot()` — FR-09

```typescript
refreshSnapshot: async () => {
  const { sessionId } = get();
  if (!sessionId) return;
  const { data, error } = await evcsApi.getSnapshot(sessionId);
  if (error) {
    set({ globalError: '無法取得最新狀態' });
    return;
  }
  set({ snapshot: data });
}
```

#### `applyAndGenerate()` — FR-14

```typescript
applyAndGenerate: async () => {
  const { sessionId } = get();
  if (!sessionId) return;
  set({ isLoading: true });

  const { data, error, response } = await evcsApi.applyAndGenerate(sessionId);

  if (response.status === 422) {
    // 後端拒絕（priorities 不足或 target > capacity）
    set({ carPortErrors: error.detail.errors, isLoading: false });
    return;
  }
  if (error) {
    set({ globalError: '計算失敗', isLoading: false });
    return;
  }

  // No change required → 不進入播放器
  if (data.total_steps === 0) {
    set({
      isLoading: false,
      carPortWarnings: [
        ...get().carPortWarnings,
        { code: 'NO_CHANGE_REQUIRED', field: '', message: 'No change required' } as WarningDetail,
      ],
    });
    return;
  }

  set({
    mode: 'player',
    stepSequence: data,
    currentStepIndex: 0,
    snapshot: data.initial_state,
    isLoading: false,
  });
}
```

#### `stepForward / stepBack` — FR-15

```typescript
stepForward: async () => {
  const { sessionId } = get();
  if (!sessionId) return;
  const { data, error } = await evcsApi.step(sessionId, 'forward');
  if (error || !data) return;
  set({
    currentStepIndex: data.current_step_index,
    snapshot: data.snapshot,
  });
}
// stepBack 同樣，傳 'back'
```

> 後端已實作 wrap-around（forward 過末端→0、back 過 0→末端），前端不需自行處理。

#### `exitPlayer()` — FR-15

```typescript
exitPlayer: () => {
  set({ mode: 'edit', currentStepIndex: 0 });
  // 不清 stepSequence，使用者可能想再看；不清 carPorts，輸入值保留
  get().refreshSnapshot();
}
```

---

## 3. UI 區塊規格（依實作順序）

### 3.1 ConfigPanel — REC BD 數量與模塊功率配置

**對應 FR**：FR-10、FR-11
**對應 API**：`POST /validate/module-powers`、`POST /validate/system-config`

#### UI 元素

| 元素 | 規格 |
|---|---|
| **REC BD 數量輸入** | 數字輸入框，default 4，邊界 [1, 12]，超過上限即時顯示警告（紅色 helper text）|
| **每 REC BD 模塊功率輸入**（×N 個） | 文字輸入框，placeholder「50, 75, 75, 50」；輸入時 debounce 400ms 後呼叫 `validateModulePowers` |
| **每 REC BD 容量小字** | 顯示 `total_capacity_kw`（從 validate 回應取）|
| **Apply 按鈕** | 點擊後 `updateSystemConfig`；驗證未過時 disabled |

#### Props / state

```typescript
interface ConfigPanelProps {
  // 從 store 讀，無需傳入
}

// 內部 state
const [recBdCount, setRecBdCount] = useState(4);
const [moduleStrings, setModuleStrings] = useState<string[]>(['50, 75, 75, 50', /* ... */]);
const [parseResults, setParseResults] = useState<ModulePowerStringResponse[]>([]);
```

#### API 呼叫順序

```
使用者改 REC BD 數量 (例 4 → 5)
  ↓
本地 setRecBdCount(5) + 自動補一個空字串到 moduleStrings
  ↓ (UI 即時反映)
使用者填新 REC BD 5 的字串「50, 50, 50, 50」
  ↓ debounce 400ms
POST /validate/module-powers { raw: "50, 50, 50, 50" }
  ↓
顯示容量、warnings
  ↓
使用者按 Apply
  ↓
POST /validate/system-config { rec_bd_count: 5, rec_bds: [...] }
  ↓ 成功
store.updateSystemConfig(cfg)
  ↓ (action 內部會 PATCH session + refresh snapshot)
TopologyView 重畫
```

#### 錯誤處理 / 邊界情況

| 情況 | UI 處理 |
|---|---|
| 模塊功率非 25 倍數 | 即時顯示 warning「值將被四捨五入到 X kW」（FR-11）|
| 模塊功率 < 50 或 > 100 | 即時顯示 error，紅框；Apply 按鈕 disabled |
| REC BD 數量改變 | 警告 modal「優先級設定將被清除」確認後執行（FR-16）|
| 後端 422 | 在面板頂部顯示 ErrorBanner，列出每個 errors[].message |

---

### 3.2 TopologyView — 主視覺面板

**對應 FR**：FR-01 ~ FR-06
**對應 API**：`POST /topology/preview`（靜態結構）+ `GET /sessions/{id}/snapshot`（動態狀態）

#### 區塊結構（對齊 Figma wireframe）

```
┌──────────────────────────────────────────────────────────────┐
│  [REC BD 1]   [50kW Pack]──●──[Output Relay]──●─🚗 Car 1     │
│  blue, 250kW  [75kW Pack]                                     │
│  Occupied     [75kW Pack]                                     │
│               [50kW Pack]──●──[Output Relay]──●─🚗 Car 2     │
│                                                                │
│  ──● Bridge B_1_2 ●──                                         │
│                                                                │
│  [REC BD 2]   [50kW Pack]──●──[Output Relay]──●─🚗 Car 3     │
│  green        ...                                              │
│  ...                                                           │
└──────────────────────────────────────────────────────────────┘
```

#### 子元件分工

| 元件 | 職責 | 資料來源 |
|---|---|---|
| `<TopologyView>` | 編排佈局；訂閱 `snapshot` | store |
| `<RecBdLabel recBd>` | 顯示「REC BD N、Power: XkW、Occupied/Idle」 | `RecBdSnapshot` |
| `<PackGrid packs ownerColors>` | 渲染該 REC BD 的 Pack 方格陣列；底色 = `pack.color` | `PackSnapshot[]` |
| `<RelayIcon relay>` | 紅底（Closed）/ 白底（Open） | `RelaySnapshot` |
| `<CarIcon car>` | 藍/淺灰；常駐顯示 `Car N — Max. Required: XXX kW` | `CarSnapshot` |
| `<BridgeRelay bridge>` | 跨 REC BD 的橋接 relay | `RelaySnapshot.kind === 'bridge'` |

#### 顏色與樣式對應（直接從後端常數取）

```typescript
// src/utils/colors.ts
export const COLORS = {
  RELAY_CLOSED: '#E53E3E',     // FR-04 紅
  RELAY_OPEN: '#FFFFFF',
  CAR_ACTIVE: '#3182CE',       // FR-05 藍
  CAR_INACTIVE: '#A0AEC0',     // FR-05 淺灰
  PACK_IDLE: '#EDF2F7',        // FR-03 淺灰白
};
```

> ⚠️ **不要在前端寫死這些顏色**，理想做法是首次載入時呼叫 `GET /palette` 把 `semantic` 區塊存進 store，TopologyView 從 store 讀。這樣後端改色時前端零改動。

#### 渲染邏輯

```typescript
// 偽碼
{snapshot.rec_bds.map(recBd => (
  <RecBdLabel key={recBd.id} recBd={recBd}>
    <PackGrid
      packs={snapshot.packs.filter(p => p.rec_bd_id === recBd.id)}
    />
    <RelayRow
      relays={snapshot.relays.filter(
        r => r.rec_bd_id === recBd.id && r.kind !== 'bridge',
      )}
    />
    <CarRow
      cars={snapshot.cars.filter(c => c.rec_bd_id === recBd.id)}
    />
  </RecBdLabel>
))}
{snapshot.relays
  .filter(r => r.kind === 'bridge')
  .map(b => <BridgeRelay key={b.id} bridge={b} />)}
```

#### Player 模式下的差異

**完全沒有差異**——Player 模式下 store 的 `snapshot` 會被替換成當前步驟的 snapshot（從 `step()` 回應取），TopologyView 自動 re-render。**這是把 snapshot 設計成單一資料來源的最大好處**。

---

### 3.3 CarPortPanel — 每路輸入面板

**對應 FR**：FR-07、FR-12、FR-13、FR-16
**對應 API**：`PATCH /sessions/{id}` + `GET /sessions/{id}/snapshot` + `POST /validate/car-ports`

#### UI 結構

每一路（Port）一橫列，2N 列（N = REC BD 數量）：

```
中欄(白底,FR-07/09)                                右欄(灰底,FR-13/16)
─────────────────────────────────────────────     ─────────────────────────────────
                                                   優先級    Present     Target
Car 1 - Max. Required: [125] kW [+25][-25]         [1]      [50] kW    [100] kW
Car 2 - Max. Required: [  0] kW [+25][-25]         [3]      [50] kW    [100] kW
... 8 列                                           ... 8 列
                                                    ┌─────────────────┐
                                                    │ Apply and Gen.  │
                                                    └─────────────────┘
```

#### 子元件 — `<MaxRequiredField>`（FR-07 + FR-12）

| 元素 | 行為 |
|---|---|
| 數字輸入框 | onBlur 或 Enter 時觸發 `store.updateCarPort(portId, { max_required: value })`<br>輸入時不觸發 |
| `-25` 按鈕 | onClick → `store.nudgeMaxRequired(portId, -25)` |
| `+25` 按鈕 | onClick → `store.nudgeMaxRequired(portId, +25)` |
| 顯示 unit | 「kW」固定 |

```typescript
function MaxRequiredField({ portId, value }: Props) {
  const nudge = useEvcsStore(s => s.nudgeMaxRequired);
  const update = useEvcsStore(s => s.updateCarPort);
  const [draft, setDraft] = useState(String(value));

  // 父層 value 變動時同步（包含 +25/-25 按鈕造成的變動）
  useEffect(() => setDraft(String(value)), [value]);

  const commit = () => {
    const num = parseInt(draft, 10);
    if (isNaN(num)) {
      setDraft(String(value));
      return;
    }
    // 前端先做 clamp + round（避免送一個明顯越界的請求被 schema 422）
    const clamped = Math.max(0, Math.min(600, num));
    const rounded = Math.round(clamped / 25) * 25;
    update(portId, { max_required: rounded });
  };

  return (
    <div className="flex gap-1 items-center">
      <button onClick={() => nudge(portId, -25)} aria-label="Decrease 25kW">-25</button>
      <input
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit(); }}
        className="w-16 text-right"
      />
      <span className="text-sm">kW</span>
      <button onClick={() => nudge(portId, 25)} aria-label="Increase 25kW">+25</button>
    </div>
  );
}
```

> **FR-07 (6) 按鈕不需 disabled** —「點擊已是 600 的 +25 按鈕」會在 store 的 `nudgeMaxRequired` 計算出 clamped == 原值後 early return，不打 API、UI 不變化。實作上自然成立，毋須特別處理。

#### 子元件 — `<PresentTargetFields>`（FR-13）

兩個獨立輸入框，行為一致：

```typescript
function PresentField({ portId, value }: Props) {
  const update = useEvcsStore(s => s.updateCarPort);
  const [draft, setDraft] = useState(String(value));
  // ... 同 MaxRequiredField，但 commit 時送 { present: rounded } 而非 max_required
  // ⚠️ store action 已保證不觸發 refreshSnapshot（FR-13）
}
```

#### 子元件 — `<PriorityField>`（FR-16）

```typescript
function PriorityField({ portId, value, allPriorities, maxN }: Props) {
  const update = useEvcsStore(s => s.updateCarPort);
  const [draft, setDraft] = useState(value === null ? '' : String(value));

  const commit = () => {
    const num = draft === '' ? null : parseInt(draft, 10);
    if (num !== null && (isNaN(num) || num < 1 || num > maxN)) {
      // 即時 error
      return;
    }
    if (num !== null && allPriorities.some(p => p === num)) {
      // 重複錯誤
      return;
    }
    update(portId, { priority: num });
  };
  // ...
}
```

**驗證時機**：每次任一欄位 onBlur 時，呼叫 `POST /validate/car-ports` 檢查整批 priorities，更新 `carPortErrors` 顯示衝突。

#### 與 store 的 binding

整個 panel 從 store 讀 `carPorts`，每列以 `port_id` 為 key 渲染。**不要在 panel 內 cache 一份 carPorts**，否則 Player 模式回到 Edit 後狀態可能不一致。

---

### 3.4 ApplyAndGenerate Flow（FR-14）

**對應 API**：`POST /sessions/{id}/apply-and-generate`

#### UI 元素

位於 Fr14ControlTable(右欄灰底面板)底部,跟優先級 / Present / Target 表格同屬一個灰底視覺區塊。teal 綠色背景白字：

```
[ Apply and Generate Control Steps ]
```

| 狀態 | UI 表現 |
|---|---|
| 預設 | 按鈕可按 |
| `priorities < 2` | 按鈕 disabled，旁邊小字「請至少設定 2 個 Car Port 的優先級」 |
| 計算中 | 按鈕顯示 spinner、disabled |
| 成功有步驟 | 自動切到 Player Mode（store.mode = 'player'）|
| `total_steps === 0` | 不切模式；顯示 toast「No change required，系統狀態已是目標狀態」 |
| 422 (target > capacity / priorities incomplete) | ErrorBanner 顯示後端 errors[].message |
| network / 5xx | toast「計算失敗，請稍後再試」 |

#### 觸發邏輯

```typescript
const onApply = async () => {
  const ready = useEvcsStore.getState().carPorts.filter(p => p.priority !== null).length >= 2;
  if (!ready) return;  // 按鈕本來就 disabled，但雙保險
  await useEvcsStore.getState().applyAndGenerate();
};
```

> 後端會自己再檢查一次（PrioritiesIncompleteError），前端的 disabled 只是 UX 提示，不能取代後端驗證。

---

### 3.5 StepPlayer — 控制步驟播放器（FR-15）

**對應 API**：`POST /sessions/{id}/step?direction=forward|back`

#### UI 結構

```
┌────────────────────────────────────────────┐
│         Control Steps Player                │
├────────────────────────────────────────────┤
│              步驟進度                        │
│              Step X / N                      │
├────────────────────────────────────────────┤
│  當前步驟操作:                                │
│  <step.description>                          │
├────────────────────────────────────────────┤
│  系統狀態摘要:                                │
│  總輸出功率: XXX kW / YYY kW                  │
│  充電中車輛: A / 8                            │
└────────────────────────────────────────────┘

         [<<  Back]      [Forward  >>]
         
         [ ← 返回編輯模式 ]
```

#### 子元件

| 元件 | 內容 | 資料來源 |
|---|---|---|
| `<StepProgress>` | 「Step X / N」 | `currentStepIndex`、`stepSequence.total_steps` |
| `<StepDescription>` | 當前步驟描述 | step 0 顯示 "Initial State (Present)"；其他從 `seq.steps[i-1].description` |
| Forward 按鈕 | onClick → `stepForward` | — |
| Back 按鈕 | onClick → `stepBack` | — |
| 返回編輯模式按鈕 | onClick → `exitPlayer` | — |

#### 鍵盤支援（建議）

```typescript
useEffect(() => {
  if (mode !== 'player') return;
  const handler = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') stepForward();
    if (e.key === 'ArrowLeft') stepBack();
    if (e.key === 'Escape') exitPlayer();
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, [mode]);
```

#### Wrap 行為（已在後端實作）

| 操作 | 後端行為 | 前端不需做任何事 |
|---|---|---|
| 在最後步驟按 Forward | 回到 step 0 | ✅ |
| 在 step 0 按 Back | 跳到最後一步 | ✅ |

---

### 3.6 Error / Warning Display（FR-08、FR-12、FR-13、FR-16）

**對應 FR**：所有需要錯誤提示的 FR

#### 三層錯誤顯示策略

| 層級 | 用途 | UI |
|---|---|---|
| **Inline（欄位旁）** | 單欄位即時錯誤（如 priority 重複、模塊功率非 25 倍數）| 紅框 + 紅字 helper text |
| **Section banner（區塊頂部）** | 該區塊整體驗證錯誤 | `<ErrorBanner>` 列表 |
| **Toast（短暫飄出）**| 網路錯誤、5xx、操作完成提示 | 右下角 3 秒淡出 |

#### `<ErrorBanner>` 規格

```typescript
interface ErrorBannerProps {
  errors: ErrorDetail[];     // from store.carPortErrors / configErrors
  onDismiss?: () => void;
}

// 顯示
errors.map(e => (
  <li key={`${e.code}-${e.field}`}>
    <strong>{e.code}</strong>: {e.message}
    {e.field && <code>{e.field}</code>}
  </li>
))
```

#### `<WarningList>` 規格

警告（如 clamp、round-to-25）只是提示而非阻擋，採折疊式：

```
[!] 3 個警告 ▼  (點擊展開)
   ├ Port 1: Max Required 由 137 自動四捨五入為 125 kW
   ├ Port 3: Present 由 -10 自動截斷為 0 kW
   └ Port 5: Max Required 由 630 自動截斷為 600 kW
```

#### 後端 422 解析

後端 422 回傳格式：

```json
{
  "detail": {
    "errors": [
      { "code": "TARGET_EXCEEDS_CAPACITY", "field": "car_ports.target", "message": "..." }
    ]
  }
}
```

統一解析：

```typescript
async function parseError(response: Response): Promise<ErrorDetail[]> {
  if (response.status !== 422) return [];
  const body = await response.json();
  return body.detail?.errors ?? [];
}
```

---

## 4. 路由與雙模式（Edit / Player）切換

### 4.1 不需 react-router

整個 App 是單頁工具，由 `store.mode` 控制顯示哪一組元件，省去 router 開銷：

```tsx
function App() {
  const mode = useEvcsStore(s => s.mode);
  
  if (mode === 'edit') {
    // 三欄(左圖、中白底、右灰底)
    return (
      <div className="grid grid-cols-[1fr_1fr_1fr] h-screen">
        <main className="overflow-auto p-4 border-r">
          <TopologyView />
        </main>
        <section className="overflow-y-auto p-4 border-r">
          <CarRowsColumn />     {/* FR-07/09 ±25 按鈕 */}
        </section>
        <aside className="overflow-y-auto p-4 bg-slate-100">
          <Fr14ControlTable />  {/* FR-13/16 priority/present/target + Apply */}
        </aside>
      </div>
    );
  }
  
  // Player mode - 雙欄(左圖、右 player 面板)
  return (
    <div className="grid grid-cols-[1fr_1fr] h-screen">
      <main className="overflow-auto p-4 border-r">
        <TopologyView />
      </main>
      <aside className="overflow-y-auto p-4">
        <StepPlayer />
      </aside>
    </div>
  );
}
```

### 4.2 雙模式狀態同步表

| 動作 | mode | snapshot 來源 | UI 變化 |
|---|---|---|---|
| 初始化 | edit | `GET /snapshot`（基於 max_required） | 配置面板可編輯 |
| 改 max_required | edit | 重新 `GET /snapshot` | TopologyView 重畫 |
| 改 target/present/priority | edit | **不變** | TopologyView 不重畫（FR-13） |
| Apply（成功有步驟）| **edit → player** | `seq.initial_state` | 切到播放器面板 |
| Apply（No change）| edit | 不變 | 顯示 toast |
| Forward / Back | player | step.snapshot | TopologyView 重畫 |
| 返回編輯模式 | **player → edit** | 重新 `GET /snapshot` | 切回編輯面板，輸入值保留 |

---

## 5. 驗收標準

### 5.1 功能驗收（按 FR 對照）

| FR | 驗收項目 |
|---|---|
| FR-01 | 不同 REC BD 顯示不同識別色；4 個以上時依 cycle 設定循環 |
| FR-02 | 改任一 max_required，對應 REC BD 的 Power 數值即時更新；power=0 時 status 顯示 "Idle" |
| FR-03 | Pack 方格底色與其 owner port 的 home REC BD 同色；無 owner 時為淺灰 |
| FR-04 | Closed relay 顯示紅底，Open 顯示白底，視覺上明顯 |
| FR-05 | max_required>0 且 output relay closed → 車輛藍；否則淺灰 |
| FR-06 | 每車旁常駐顯示「Car N — Max. Required: XXX kW」 |
| FR-07 | 點 +25 一次，max_required 增 25；600 時再點 +25 無變化 |
| FR-08 | 手動輸入 700，blur 後變 600，旁邊有 warning |
| FR-09 | 改 max_required 後 0.5 秒內全部視覺元件更新 |
| FR-10 | REC BD 從 4 改 5，畫面新增第 5 個 REC BD，Car 9/10 出現 |
| FR-11 | 輸入「100, 100, 100, 100」，REC BD 容量顯示 400 kW，pack 數為 16 |
| FR-12 | 輸入 130，blur 後變 125（round-to-25），有 warning |
| FR-13 | 改 target，TopologyView 不變；改 max_required，立刻變 |
| FR-14 | 設定 priority 全部 + present=0、target=125 全部 → 點 Apply → 切到播放器，顯示 N>0 步驟 |
| FR-15 | Forward 一次 → step+1、snapshot 更新；最後一步按 Forward → 回 step 0；step 0 按 Back → 跳到最後 |
| FR-16 | 兩個 port 設同 priority → 兩格同時紅框、Apply 按鈕 disabled |

### 5.2 非功能驗收

| 項目 | 標準 |
|---|---|
| 首次載入時間 | < 2 秒（Vite production build）|
| 任意操作回應 | < 200ms（UI 立即反應；snapshot fetch 視網路）|
| TypeScript 編譯 | 零 error、零 any 顯式使用 |
| Lint | 零 warning |
| 測試覆蓋率 | 元件邏輯測試 ≥ 70%；store actions ≥ 90% |
| 可訪問性 | 所有按鈕有 aria-label；鍵盤可操作播放器 |

---

## 6. 測試策略

### 6.1 單元測試（Vitest）

| 對象 | 測試重點 |
|---|---|
| `evcsStore` 各 action | mock `evcsApi`，驗證 state transition 正確 |
| `nudgeMaxRequired` | 邊界（0、600）不打 API；其他情況呼叫 PATCH + GET |
| `updateCarPort` | 改 max_required 時呼叫 refreshSnapshot；改 target/priority 時不呼叫 |
| `applyAndGenerate` | 422 時寫入 errors；total_steps=0 時不切 mode；成功時切到 player |
| `MaxRequiredField` | onBlur 觸發 update；按鈕 onClick 觸發 nudge；輸入非數字 revert |
| `PriorityField` | 重複偵測；out-of-range 偵測 |

### 6.2 整合測試（React Testing Library + MSW）

用 MSW（Mock Service Worker）攔截 API，跑端到端 user flow：

```
test('FR-14 完整流程：配置 → 輸入 → Apply → 進入播放器 → Forward', async () => {
  render(<App />);
  // 1. ConfigPanel 設定 4 REC BD
  // 2. CarPortPanel 全部 priority=1..8、present=0、target=125
  // 3. 點擊 Apply
  // 4. 等待 mode 切到 player
  // 5. 點擊 Forward → 驗證 StepProgress 顯示 "Step 1 / N"
});
```

### 6.3 視覺迴歸（建議但非必須）

用 Playwright 對 TopologyView 在幾個固定 snapshot 下截圖比對，確保未來樣式調整不破壞 wireframe 一致性。

---

## 7. 開發里程碑 4 個 Phase

| Phase | 工作項 | 對應 §3 |
|---|---|---|
| **P1** | ConfigPanel + TopologyView（含所有子元件，靜態樣式對齊 Figma）| §3.1 §3.2 |
| **P2** | CarPortPanel（含 +25/-25、手動輸入、priority、validation 串接） | §3.3 |
| **P3** | Apply and Generate flow + StepPlayer + Edit/Player 模式切換 | §3.4 §3.5 §4 |
| **P4** | Error/Warning display 統一打磨、鍵盤支援、測試補齊、E2E 驗收 | §3.6 §6 |

---

## 8. 新增後端 1 個 follow-up 請求

要讓前端開發更順利，**建議**加 1 個 endpoint（非阻擋）：

```
POST /api/v1/sessions/{session_id}/car-ports/{port_id}/nudge?delta=25|-25
→ Response: { car_port: CarPortInput, snapshot: VisualSnapshot }
```

**好處**：
- FR-07 一次點擊由前端 2 個 API call（PATCH + GET）變 1 個
- 後端集中保證 clamp 與步進對齊邏輯
- 前端 store 的 `nudgeMaxRequired` 可從 5 行縮成 2 行

---

## 9. 附錄

### 附錄 A — 環境變數

```
# web/evcs-ui/.env.development
VITE_API_BASE_URL=http://localhost:8000

# web/evcs-ui/.env.production
VITE_API_BASE_URL=/api    # 由反向代理路由到 FastAPI
```

### 附錄 B — 後端可用的 17 個 endpoint（quick ref）

```
GET    /api/v1/health
GET    /api/v1/constants
GET    /api/v1/palette?count=N&cycle=true|false
POST   /api/v1/validate/module-powers
POST   /api/v1/validate/car-ports
POST   /api/v1/validate/system-config
POST   /api/v1/sessions
GET    /api/v1/sessions
GET    /api/v1/sessions/{id}
PATCH  /api/v1/sessions/{id}
DELETE /api/v1/sessions/{id}
POST   /api/v1/topology/preview
POST   /api/v1/snapshot/compute
GET    /api/v1/sessions/{id}/snapshot
POST   /api/v1/sessions/{id}/apply-and-generate
GET    /api/v1/sessions/{id}/control-steps
POST   /api/v1/sessions/{id}/step?direction=forward|back
```

### 附錄 C — Wireframe 連結

[Figma EVCS-Vision (node 13:572)](https://www.figma.com/design/KHQ1AFIbh2lBS5m8TSOrv9/EVCS-Vision?node-id=13-572&t=m6yBYmEzyui9emih-1)

實作前建議重點對齊：
- REC BD 標籤的形狀與內距
- Pack 方格的尺寸與間距（每 REC BD 排一列還是兩列）
- Relay 圖示樣式（圓形 vs 方形）
- Car icon 圖樣（剪影 / icon font / SVG）
- 配色精確 hex 值（前端不寫死，從 `/palette` 拿）

實作 Web UI 需與  Figma 連結中的畫面一致，如果無法讀取 Figma 連結，可以參考下列 .pdf 檔案
- 已上傳 @associate/main-page.pdf (對應到的元件為 topology + car-port-panel)
- 已上傳 @associate/config-page.pdf (對應到的元件為 topology + config-panel)
- 已上傳 @associate/player-page.pdf (對應到的元件為 topology + step-player)