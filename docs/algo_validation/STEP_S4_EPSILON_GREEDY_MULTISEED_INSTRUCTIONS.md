# STEP S4 — ε-greedy 探索 + multi-seed env-var(覆蓋追加)

> **背景**:F1 + S3 後測試套件功能完整、A1 守護 production fix、最小回歸測試已 commit。Exploration 在 `seed=12345` 單 seed + 純 greedy 設定下覆蓋停在 **285/766 = 37.2%**,binding constraint 是 stagnation≥500(非 step budget)。Unvisited top-20 全為 Hamming=0/1,代表 greedy 卡在局部最佳、不是真實動態可達天花板。
>
> **本任務的兩道槓桿**:
> - **ε-greedy**:scheduler 以機率 ε 選**隨機合法 arrival** 而非貪心,直接打破 stagnation。同 seed 預期覆蓋拉到 50%+。
> - **multi-seed env-var**:`EVCS_SEED` 覆寫 `SEED = 12345` 硬編,讓多 seed run 不必改 code。不同 seed 的 ε-greedy 軌跡彼此互補,union 預期再拉 10–15 pts。
> - **union 分析本輪不做**(若手動觀察數字滿意了就停;若要正式 union 工具留下一輪)。
>
> **鐵律**:
> - **不改 production**。
> - **不引入 current/5A/熱切換**。
> - **既有測試行為不得改變**:env var unset 時必須回到與本任務前**完全相同**的軌跡(同 seed、同步數、同 coverage、同 N)。這是回歸安全網,務必驗證。
> - 超出 allowlist 立即 stop-and-report。

---

## STEP K1 — 實作 + 驗證(單一 commit)

### K1-a 開工前 read-only 確認(~5 分鐘)

先 grep/讀 code 回報,任一有出入立即 stop-and-report:

1. **SEED 怎麼擴散**:`conftest.py:12` 的 `SEED = 12345` 透過哪些路徑被使用(已知:`scheduler` fixture、`test_exploration.py:27 from conftest import SEED`、`:56/69` 等)。
2. **ArrivalScheduler.select_next()(或同等)的內部結構**:
   - 選擇空間:`(output_idx, soc_level, max_kw)` 三維?是否還包含其他?
   - greedy 怎麼算「下一個 arrive」(基於 (O,L) 覆蓋差距 + Hamming?)
   - demand 邏輯(F1-b 之後 250/50 alternating?還是 SOC-綁定?如何映射)
   - 內部 RNG 是 `random.Random(seed)` 還是其他?
3. **§11 報告產出**:`test_exploration.py` 第 ~139 行 `[Run]` 段的 print 結構,確認在哪裡能加 `epsilon=` 一欄而不破壞既有解析。

### K1-b 實作

**File allowlist**(只准動這三個):
```
tests/algo_validation/conftest.py
tests/algo_validation/helpers/arrival_scheduler.py
tests/algo_validation/test_exploration.py    (只准在 §11 報告加 epsilon 欄)
```

**1. env-var SEED override(`conftest.py`)**

```python
import os
SEED = int(os.environ.get("EVCS_SEED", "12345"))   # D-12, multi-seed via env var
```

**2. env-var EPSILON(`conftest.py`)**

```python
EPSILON = float(os.environ.get("EVCS_EPSILON", "0.0"))   # 0=純 greedy(預設,回歸安全);>0 啟用 ε-greedy
```

**default 是 0.0(不是 0.2)**——這是回歸安全的關鍵。env var unset 時行為與本任務前**完全相同**。覆蓋追加要明確 opt-in:`EVCS_EPSILON=0.2 pytest ...`。

**3. scheduler 加 ε-greedy(`helpers/arrival_scheduler.py`)**

- 建構介面加 `epsilon: float = 0.0` 參數
- 在 `select_next()`(或同等方法)**最前面**加分支:
  ```python
  if self.epsilon > 0.0 and self._rng.random() < self.epsilon:
      result = self._random_legal_arrival(current_state)
      if result is not None:
          return result
      # 隨機分支若回 None(例:全滿)→ fall-through 走原本 greedy 邏輯
  # 既有 greedy 邏輯完全不動
  ...
  ```
- `_random_legal_arrival(state)` 設計:
  - output_idx:隨機選一個**未佔用**的 output;若全滿,return None(讓原 greedy 處理空轉)
  - soc_level:隨機 `low`/`mid`/`high` 三選一
  - max_kw:隨機從 `[50, 100, 200, 375]` 四選一——涵蓋「不跨界 / 跨單界 / 跨多界 / 滿載多 group 跨界」,讓 ε 分支主動觸發各種拓樸場景(375 是 S3 已驗證可強制 g4/g5 跨 MCU 借的最小值)
- **RNG 紀律**:全程用 `self._rng`(已 seeded with `SEED`),**不准**用 `random.random()` 直接(會污染全域 + 破壞 determinism)
- **Greedy 路徑不動**:確保 `epsilon=0.0` 時整支函式行為 byte-identical 於本任務前

**4. fixture 串接(`conftest.py`)**

```python
@pytest.fixture
def scheduler() -> ArrivalScheduler:
    return ArrivalScheduler(num_outputs=NUM_MCUS * 2, seed=SEED, epsilon=EPSILON)
```

**5. §11 報告印 epsilon(`test_exploration.py`)**

把現有 `[Run]` 段的 seed 行改成:
```
- steps=... sim_time=...s seed=12345 epsilon=0.0
```
其餘 print 不動。

### K1-c 驗證(三層)

**Layer 1:回歸安全網(最重要)**
```bash
# 不設 env var,完全等同 ε-greedy 引入前的行為
pytest tests/algo_validation/ -v -s 2>&1 | tee /tmp/k1c_layer1.log
```
比對 §11 報告:**steps=4007、seed=12345、epsilon=0.0、coverage=263/766、N=63 ticks/55 states、relay_events=1672**(對應 F1 commit `7ac4599` 之後、`_MAX_STEPS=4000` 設定的紀錄)——**任何數字漂移就是 epsilon=0.0 路徑沒做到 byte-identical**,須回頭排查。**這層不過,後面都不算數。**

**Layer 2:單 seed + ε-greedy**
```bash
EVCS_EPSILON=0.2 pytest tests/algo_validation/test_exploration.py -k exploration -s 2>&1 | tee /tmp/k1c_layer2.log
```
回報 §11 數字(coverage / steps / N / termination)。預期 coverage 顯著超過 263(目標 50%+),且 termination 應該還是 stagnation 或 max_steps——不該出現 exception。

**Layer 3:multi-seed 巡跑(手動)**
```bash
for s in 1 7 42 12345 67890; do
  echo "=== seed=$s ==="
  EVCS_SEED=$s EVCS_EPSILON=0.2 pytest tests/algo_validation/test_exploration.py -k exploration -s 2>&1 \
    | grep -E "(visited=|epsilon|steps=|relay_events|F1-b)" | head -6
done
```
列出 5 個 seed 的 visited 數字。不要求自動 union 計算,人眼掃就行。

---

## DoD(stop-and-report)
- [ ] K1-a 三點 read-only 確認回報(scheduler 內部結構簡述)
- [ ] `EVCS_SEED` env-var 覆寫(unset 時保持 12345)
- [ ] `EVCS_EPSILON` env-var 覆寫(unset 時 **0.0**,>0 啟用 ε-greedy)
- [ ] `_random_legal_arrival` 用 fixture 內 RNG、不污染全域
- [ ] **Layer 1 byte-identical**:ε=0.0 結果與 ε-greedy 引入前完全一致(coverage/steps/N/relay_events 全對齊)
- [ ] Layer 2 ε=0.2 跑出來 coverage 顯著超過 263、其他不變量仍 PASS
- [ ] Layer 3 multi-seed 5 個 seed 的 visited 數字(不做 union)
- [ ] §11 報告含 `epsilon=` 欄
- [ ] production 未改、無 current/5A 殘留、無暫時 instrumentation
- [ ] `git status` 僅上列三檔
- [ ] 草擬 commit message

## 回報格式
1. `git status` 與 `git diff --stat`
2. DoD 逐項 ✅/❌
3. K1-a 三點答案
4. **Layer 1 比對表**(ε=0.0 vs 任務前各指標)——byte-identical 是這次能算成立的前提
5. Layer 2 §11 報告貼上(ε=0.2 數字)
6. Layer 3 五 seed visited 數字表
7. commit message 草稿
8. 任何超出 allowlist 或與假設不符之處

---

## 給你(Psyduck)後續手動觀察的建議

- **單 seed ε=0.2 跑出來若覆蓋 < 50%**:可能 ε 太低或 `_random_legal_arrival` 沒涵蓋關鍵維度(例如 max_kw 選擇集太窄)。下一輪可 EVCS_EPSILON=0.3 試。
- **multi-seed 之間若 visited 數字差異大**(例:有的 280、有的 450):好事——代表 ε-greedy 的隨機性確實多樣化軌跡。各 seed 互補空間大,union 會比單 seed 大不少。
- **multi-seed 之間若幾乎一樣**:壞事——可能隨機分支太晚才生效(greedy 強壓),或 `_random_legal_arrival` 的選擇空間不夠廣。
- 真要算 union 數字,本輪先用最樸素的方法:在 §11 報告加印「**visited (O,L) 序列**」一行(每個 seed 跑完出一個 list),手動合併取 set。下一輪可以包成 `tests/algo_validation/union_coverage.py` 之類的工具。