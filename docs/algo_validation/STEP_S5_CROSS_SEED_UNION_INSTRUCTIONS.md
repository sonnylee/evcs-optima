# STEP S5 — Cross-seed Union 工具(把多 seed 的 visited 集合合起來看全景)

> **背景**:S4 commit 後我們有了 `EVCS_SEED` env-var,可以跑多 seed,但每次 pytest 跑完數字就丟掉。手動 5-seed sweep 看到 visited 數字分別是 261 / 22 / 255 / 259 / 259——這些是**局部觀察**;union(去重後的聯集)才是「在現有 dynamics + ε-greedy 下整體可達了多少」。本任務寫一個小工具把它做出來。
>
> **本工具的兩件事**:
> 1. **Dump 機制**:測試結束時,若 `EVCS_DUMP_VISITED` env-var 有值,把 `coverage_tracker` 內的 visited 集合**寫成 JSON 檔**,含 seed/ε/steps/termination 等 metadata。env-var unset 時不寫(回歸安全)。
> 2. **CLI 工具 `union_coverage.py`**:讀進多個 JSON 檔,輸出 union 大小、per-seed 貢獻、core(全部 seed 都訪過)、frontier(只有 1 個 seed 訪到)、真未訪。
>
> **不在範圍內**:
> - 不改 scheduler 邏輯(union 是後處理,不是探索策略)
> - 不自動跑 multi-seed loop(使用者自己 shell loop,工具只負責「給定一堆 dump 檔 → 算 union」)
> - 不畫圖、不出 HTML 報告(純 stdout 表格)
>
> **鐵律**:
> - **不改 production**。
> - **不引入 current/5A**。
> - **env var `EVCS_DUMP_VISITED` unset 時行為與 S4 commit 後完全相同**(byte-identical 是 Layer-1 紅線,跟 S4 同款)。
> - 超出 allowlist 立即 stop-and-report。

---

## STEP U1 — 實作 + 驗證(單一 commit)

### U1-a 開工前 read-only 確認(~3 分鐘)

先 grep/讀 code 回報:

1. **`CoverageTracker` 內部 visited 結構**:`helpers/coverage_tracker.py`,確認 visited 怎麼存(set of tuples?list of dicts?key 用 `(occupancy_int, L_code_str)` 還是別的?)。dump 時要 round-trip 安全(`L=⊥` 也得能正確序列化與還原)。
2. **`test_exploration.py` 的收尾處**:目前 §11 報告印完後的最後動作是什麼。dump 點放在「§11 報告印完之後」,確保即使 dump 失敗也不影響原本報告產出。
3. **L 的字串表示**:`L_distribution` 用的 keys 是 `'high'/'mid'/'low'/'⊥'`(空站),確認這四個就是全部、且 `⊥` 是 Python str(JSON 可序列化)。

### U1-b 實作

**File allowlist**(只准動這三個):
```
tests/algo_validation/helpers/coverage_tracker.py     (加 dump_to_json 方法)
tests/algo_validation/test_exploration.py             (env-var 觸發 dump)
tests/algo_validation/union_coverage.py               (新:CLI 工具)
```

---

**1. `CoverageTracker.dump_to_json(path, metadata)`**

加一個 method,把當前 visited 集合 + metadata 寫成 JSON。Schema(v1,版本欄是給未來不相容升級的逃生口):

```json
{
  "schema": "evcs-visited-v1",
  "metadata": {
    "seed": 12345,
    "epsilon": 0.2,
    "max_steps": 4000,
    "steps_run": 4011,
    "termination": "max_steps",
    "relay_events": 1763
  },
  "universe_size": 766,
  "visited": [
    [0, "⊥"],
    [3, "low"],
    [7, "high"],
    ...
  ]
}
```

`visited` 是 list of `[occupancy_int, L_code_str]`。**排序**:依 `(occupancy_int, L_code_str)` lexicographic,讓 diff 友善。**目錄不存在時自動 mkdir**(`os.makedirs(dirname, exist_ok=True)`)。錯誤處理:寫失敗印 warning 但**不 raise**(別讓 dump 故障壞了測試本身)。

---

**2. `test_exploration.py` 觸發 dump**

§11 報告印完後加(放在 test function 末尾、§11 print 之後):

```python
import os
if dump_path := os.environ.get("EVCS_DUMP_VISITED"):
    tracker.dump_to_json(dump_path, metadata={
        "seed": SEED,
        "epsilon": EPSILON,
        "max_steps": _MAX_STEPS,
        "steps_run": tc.step_index,
        "termination": <既有 termination 字串>,
        "relay_events": <既有 count>,
    })
```

`EVCS_DUMP_VISITED` unset 時整段 skip,**對既有行為零影響**。

---

**3. `union_coverage.py` CLI 工具(新檔)**

**功能規格**:

- 用法:`python tests/algo_validation/union_coverage.py FILE [FILE ...]`(支援 glob,例如 `/tmp/visited_*.json`)
- 讀進所有 JSON,驗證 schema(`evcs-visited-v1`),不符或 universe_size 不一致 → 報錯停止
- 計算:
  - union = `set().union(*all_visited_sets)`
  - core = `set.intersection(*all_visited_sets)`(對非空集合做交集,**collapsed seed**(visited≪正常)要單獨標出,別把它的 22 個拉低 core 數字——具體判定:若某 seed 的 |visited| < 50% × median(others),歸類 `degenerate` 排除於 core 計算之外,但仍列入 per-seed table)
  - per-seed `unique_to_this`:`set − union_of_others`
  - per-seed `new_to_union`:按輸入順序累積計算「處理到這個 seed 時 union 多了幾個」——這是 diminishing-returns 曲線
- 輸出純 stdout,固定欄寬表格(便於貼 commit message / report):

```
=== Cross-seed coverage union ===
Files:    5 (1 degenerate: /tmp/visited_7.json with visited=22)
Universe: 766 nodes

Per-seed:
  file                       seed    ε     steps  termination       visited    new_to_union
  /tmp/visited_1.json        1       0.2   4015   max_steps         261/766    261
  /tmp/visited_7.json        7       0.2    323   stagnation         22/766      0  (degenerate)
  /tmp/visited_42.json       42      0.2   4007   max_steps         255/766     28
  /tmp/visited_12345.json    12345   0.2   4011   max_steps         259/766     22
  /tmp/visited_67890.json    67890   0.2   4003   max_steps         259/766     24

Union:    335/766 (43.7%)        ← excluding degenerate seeds: 335

Overlap (over 4 non-degenerate seeds):
  Core (visited by all 4):       150 (45% of union)
  Frequent (visited by ≥3):      215
  Frontier (visited by 1 only):  120 (36% of union)
  Still unvisited by any seed:   431 (56.3% of universe)

Diminishing returns (cumulative union after each seed):
  +seed=1      → 261
  +seed=7      → 261   (degenerate, +0)
  +seed=42     → 289   (+28)
  +seed=12345  → 311   (+22)
  +seed=67890  → 335   (+24)

Top-10 frontier nodes (visited by exactly 1 seed):
  occ=00010110  L=low    only seed=42
  occ=00100011  L=high   only seed=1
  ...
```

**Code 結構建議**(~80 LOC):
- `load_dump(path) -> dict` — 讀 JSON、驗 schema、回傳 metadata + visited set
- `is_degenerate(visited, peers) -> bool` — 偵測 collapsed seed
- `compute_union_stats(dumps: list[dict]) -> dict` — 主邏輯
- `render_report(stats) -> str` — 純表格輸出
- `main()` — argparse + glob.glob 展開 + 呼叫上述

**不要**:畫圖、寫 HTML、寫 CSV、彩色輸出(stdout 純文字才好貼進文件 / git commit message)。

---

### U1-c 驗證

**Layer 1:回歸安全網**
```bash
# env var unset → 行為與 S4 後完全一致
unset EVCS_DUMP_VISITED
pytest tests/algo_validation/ -v -s 2>&1 | tee /tmp/u1c_layer1.log
```
比對:**steps=4007、visited=263/766、N=63/55、relay_events=1672**(S4 commit 後的 baseline,ε=0)。**任何漂移就是 dump 邏輯有副作用,須回頭排查**。

**Layer 2:dump 路徑驗證**
```bash
EVCS_DUMP_VISITED=/tmp/u1c_layer2.json pytest tests/algo_validation/test_exploration.py -k exploration -s
```
驗證:
- `/tmp/u1c_layer2.json` 存在
- schema 是 `evcs-visited-v1`
- `metadata.seed=12345`、`epsilon=0.0`、`steps_run=4007`、`termination=max_steps`
- `len(visited) == 263`
- pytest 本身仍 PASS

**Layer 3:multi-seed sweep + union 計算**
```bash
mkdir -p /tmp/u1c_sweep
for s in 1 7 42 12345 67890; do
  EVCS_SEED=$s EVCS_EPSILON=0.2 EVCS_DUMP_VISITED=/tmp/u1c_sweep/visited_$s.json \
    pytest tests/algo_validation/test_exploration.py -k exploration -s > /dev/null 2>&1
done
python tests/algo_validation/union_coverage.py /tmp/u1c_sweep/visited_*.json | tee /tmp/u1c_layer3.log
```
驗證 union > 261(最高單 seed),collapsed seed=7 被正確標 `degenerate`。

---

## DoD(stop-and-report)
- [ ] U1-a 三點 read-only 確認回報
- [ ] `CoverageTracker.dump_to_json` 寫對 schema、`⊥` round-trip 正確、目錄自動建、錯誤不 raise
- [ ] `test_exploration` 在 §11 印完後 dump、env-var unset 時整段 skip
- [ ] `union_coverage.py` CLI 跑得起來、schema 驗證、degenerate 偵測、報告格式如規格
- [ ] **Layer 1 byte-identical**:env-var unset → 與 S4 baseline 完全一致(263/766/4007/63-55/1672)
- [ ] Layer 2 dump JSON 內容正確
- [ ] Layer 3 multi-seed union > 261、collapsed seed 正確標記
- [ ] production 未改、無 current/5A 殘留、無暫時 instrumentation
- [ ] `git status` 僅上列三檔(`union_coverage.py` 是新增)
- [ ] 草擬 commit message

## 回報格式
1. `git status` 與 `git diff --stat`
2. DoD 逐項 ✅/❌
3. U1-a 三點答案(visited 內部結構簡述)
4. Layer 1 比對表(byte-identical 對齊)
5. Layer 2 dump JSON 的 `metadata` 區塊內容貼上
6. Layer 3 union_coverage.py 完整 stdout 貼上(這份報告即工具產品本身)
7. commit message 草稿
8. 任何超出 allowlist 或與假設不符之處

---

## 給你(Psyduck)後續手動觀察的建議

- **union 數字遠超最高單 seed**(例如 335 vs 261)→ ε-greedy 確實多樣化軌跡,可以拉更多 seed 繼續推
- **diminishing returns 曲線斜率快速衰減**(例如 5→6→7 個 seed 各只 +5 個新節點)→ 接近此 dynamics 下的可達天花板,再加 seed 沒意義
- **frontier 比例高**(>30% of union 只被 1 個 seed 訪到)→ ε-greedy 隨機性有效,但每個邊角靠運氣;若想穩定覆蓋這些 → 提示 scheduler 策略還有改進空間(例如下一輪做 novelty-bonus 或 stagnation-rebound)
- **Still unvisited 比例**(例如 56%)→ 跟 spec §2 講的「766 = 組合上限,動態可達是子集」對照;若這 56% 全部都是 Hamming ≥ 3 的遙遠節點 → 多半是物理不可達;若大量是 Hamming=1 → scheduler 還能調

union 是視野工具,不是覆蓋產生器——它告訴你下一步該調 dynamics、調 scheduler、還是放手承認天花板。
