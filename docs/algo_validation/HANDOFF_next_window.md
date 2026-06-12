# EVCS Optima — 交接 brief(給下一個對話視窗)

> 貼這份到新視窗開頭即可接續。本檔自足,不依賴上一視窗的 context。
> 溝通語言:繁體中文 + 英文技術詞,terse、精準。

---

## 0. 接下來三個任務(本視窗的目標)

1. **找出「現在的 config」,盡可能逼近 100% 覆蓋率**(舊實驗為 92.6% = 709/766)。
2. 任務 1 完成後,**用該 config 重跑一次「跨 Seed 探索覆蓋分析」**,產出報告/dashboard。
3. **修正最終給主管的報告**(demo deck + 年度目標評估),把數字換成「現行 config 可重現」的值,而非舊實驗歷史值。

⚠️ 三個任務的核心張力:**舊的 92.6% 與現在的 config 不相容**(見 §4)。任務 1 的本質就是釐清現行 config 到底能到多少、以及差距在哪。

---

## 1. 專案身分 / workflow / firewall(務必先讀)

- **人**:Psyduck(Sonny Lee),Taoyuan Taiwan, GMT+8。
- **Repo**:`github.com/sonnylee/evcs-optima`(**public**)。
- **專案**:EVCS Optima — 智慧 EV 充電站功率管理,演算法驗證階段。最終要 port 到 C/MCU。
- **Workflow(嚴格)**:Claude 起草 `STEP_*_INSTRUCTIONS.md` → Psyduck review → Claude Code 執行 → Psyduck commit/push → 回報。**Claude 不在 chat 直接改 production code**;所有 production 改動先 read-only spike → Decision Points → fix instruction。
- **commit 慣例**:`git commit -F file.txt`(shell escaping 問題);兩-commit 分離關注點(fix / test)。
- **Firewall(關鍵限制)**:
  - 使用者**無法**把檔案拖進 claude.ai(上傳被擋)。
  - 使用者**可以**貼文字、看 chat 內容、看 **inline 渲染的 SVG/PNG**。→ 所以 Claude 在沙盒建視覺、用 `present_files` inline 呈現(繞過 firewall)。
  - Claude **可以** web_fetch 使用者明確給的 **GitHub blob URL**(`github.com/.../blob/main/...`)。`raw.githubusercontent.com` 被 robots 擋、**不能** fetch。
  - blob view 會在 **~1000 行**截斷,所以要 fetch 的檔案需 **<1000 行**才能完整讀到。
- **沙盒會在 session 間重置**:`/home/claude/*` 不保證跨視窗存在。需要的資料應已 commit 進 repo(見 §6),或在 outputs。

---

## 2. 系統模型(必要事實)

- **4-MCU ring**,16 SMR groups(g0–g15),8 outputs(O0–O7)。
- MCU0=g0–3(O0,O1)、MCU1=g4–7(O2,O3)、MCU2=g8–11(O4,O5)、MCU3=g12–15(O6,O7)。Ox 的 MCU = x//2。
- Anchors:O0→g0, O1→g3, O2→g4, O3→g7, O4→g8, O5→g11, O6→g12, O7→g15。
- **state space = 766 (O,L) 節點** = 1 個空站 (occ=0, L=⊥) + 255 occupancy × 3 SOC{low,mid,high}。
  - node key = (occupancy bitmask:int 0–255, L:str)。L = 最近注入 arrival 的 SOC(last-write-wins),空站為 "⊥"。
- **跨-MCU 借電**:output 可跨 (mcu,mcu+1) 邊界向鄰居借 group;bridge relay 連接兩 MCU。SPEC §11:每個 MCU 只開自己擁有的 **left bridge**(右 bridge 是鄰居的事)。
- **departure 是系統自主**:vehicle 達 `soc>=target`(COMPLETE)時自行離場,測試無法預排事件序列;exploration 用 arrive-driven、passive-depart。

---

## 3. 本次(上一視窗)做了什麼

### 3a. 找到+診斷+修了「第二個」production bug:bridge re-close race
- **如何發現**:換 seed(12345→1)跑 exploration,A1 不變量在 step 3099 fire(`bridge(0,1) CLOSED but boundary g3,g4 not co-owned`)。seed 12345 從不踩到、seed 1 踩到。
- **read-only spike 判定 (A) 真 bug**,且**與 C1 不同類**:
  - C1(commit `7ac4599`)修的是 **never-opened**(release 後 lender relay 卡 CLOSED → 走 ReturnNotify queue)。
  - 這個是 **open-then-re-close-within-departure-tick race**:離場 step 3093 正確 OPEN bridge,**同 tick** step 3094 一個 reconciliation 又 re-CLOSE(g3/g4 已 unowned),再也沒開。
- **Root cause**:`simulation/modules/mcu_control.py::_apply_global_relay_state` 的 **foreign-span loop(:914–932)無 guard**。step 3094 MCU0 resync 時 foreign loop 掃到 g2/g3 仍掛在離場中 O2(MA 未清)→ `_foreign_virtual_span(O2)` → right-bridge 分支(:999–1004)→ bridge 進 `needed` → re-CLOSE。(注意:`:901–905` 那個 guard 只管 **local-interval loop**,是錯半邊。)
- **修法(option a,已執行)**:在 `_foreign_virtual_span (~:1115)` 加 departure skip:
  ```python
  if s.pending_intergroup_open != 0 or s.pending_output_relay_open != 0:
      return None
  ```
  與 local guard `:901–905` 對稱;**只改 close 側、不碰 open-sweep**(ownership 不對稱)。
- **commits**:`1dfeaeb`(mcu_control.py,+13 行)+ `0f39584`(`tests/algo_validation/test_bridge_reclose_race.py`,deterministic/index-agnostic,RED-before/GREEN-after)。
- **驗收(全過)**:seed 1 跑完無 A1 fire;seed 12345 仍過;**256 sim 全綠**;backend 92 passed/1 xfailed;`test_cross_mcu_orphan_relay`(C1)仍綠;A1/既有不變量未動。
- **A1 是對的、非誤報**(bridge 出廠 OPEN、無合法 closed-unowned 狀態)。

### 3b. 跨-seed 覆蓋分析(5 顆 post-fix)
- 5 顆:`1, 1000, 12345, 314159, 67890`(ε=0.0)。
- 各自 records / distinct nodes:1→321/272、1000→321/276、12345→323/263、314159→147/127(提早 stagnation 終止@1794)、67890→323/257。
- **union = 610/766(79.6%)**。
- seed-count 分佈(命中 k 顆的節點數):1→**251**、2→197、3→105、4→50、5→**7**(core)。core 7 個:`(0,⊥)(52,low)(59,low)(124,low)(127,mid)(136,high)(212,high)`。
- union 疊加邊際:272 → +160 → +92 → +34 → +52(到 610)。
- Jaccard 平均 off-diag = **0.22**(高度互補);314159 最獨特(短 run)。
- **artifact**:`EVCS_CrossSeed_Dashboard.svg / .png`(三面板:覆蓋疊圖 / 互補曲線 / Jaccard 矩陣)。
- records 已 commit:`docs/algo_validation/traj_records_{1,1000,12345,314159,67890}.json`。

### 3c. Demo deck 更新(10 → 12 張)
- `EVCS_Validation_Demo.pptx`(outputs),生成器 `/home/claude/pptx_build/deck.js`(**可能未 commit,跨視窗會消失——見 §6 風險**)。
- 前 10 張不動。新增:
  - **Slide 11**:框架抓到真實 production bug(bridge re-close race)——四格時序流 + C1-vs-新bug 對比 + 修法 + takeaway。
  - **Slide 12**:跨 seed 互補——stat chips(610/766, frontier 251, core 7, Jaccard 0.22)+ 聯集成長階梯。
- 配色 Midnight Executive(navy 1E2761 / ice CADCFC / blue 2563EB / green 059669 / red DC2626);字型 Microsoft JhengHei / Calibri / Courier New。
- QA pipeline:`node deck.js → python-pptx 結構驗證 → soffice --convert-to pdf → pdftoppm JPG 視覺檢查`。

### 3d. seed 42 退化問題(已釐清)
- seed 42 在**現行 config** 撞 **F1-b 防呆**(`test_exploration.py:123` `assert checks.anchor_open_while_charging_ticks > 0`)→ pytest FAILED → 無 dump。
- 報告:`steps=3 · visited=1/766`(只記到起點)——run 幾乎沒展開。
- 已知機制:第一個 arrival 一定 LOW demand(`arrival_count % _LOW_DEMAND_EVERY == 0`,count 從 0 起),LOW demand 不借電不 anchor-open;run 太短在進 HIGH demand 前就終止 → F1-b=0。
- **「為什麼只跑 3 步」的確切 termination 機轉尚未診斷**(scheduler.choose 早回 None?還是首 arrival 立刻 COMPLETE 觸發 driver.is_finished()?)→ 若任務 1 需要,先做一個 ~10 行 read-only trace。
- F1-b 實質是**品質過濾器**:擋掉 vacuous run。把退化 seed 放進跨-seed 分析會**污染** Jaccard/互補曲線(多一行幾乎全 0 的重疊),所以排除是對的。

---

## 4. 覆蓋率數字:舊 vs 新(核心 caveat)

| | 舊 sweep | 新 post-fix study |
|---|---|---|
| config | ε=0.2、9 seeds、舊不變量 | ε=0.0、5 seeds、post-fix + 強化不變量 + F1-b |
| 覆蓋 | **709/766 = 92.6%** | **610/766 = 79.6%** |
| seeds | 1,1000,12345,314159,**42**,67890,17,2,31 | 1,1000,12345,314159,67890 |

**92.6%(709)的 9 顆組成 + 邊際(舊 config,加入順序)**:
1→+261(261), 1000→+167(428), 12345→+107(535), 314159→+64(599), 42→+36(635), 67890→+40(**675 = Sweep R1, 6 顆 88.1%**), 17→+22(697), 2→+6(703), 31→+6(**709 = R1+R2, 9 顆 92.6%**)。

⚠️ **709 不可用現行 config 重現**:它含 seed 42(+36),而 42 在現行 config 退化撞 F1-b;17/2/31 是 plateau 尾巴,八成也撐不住。
⚠️ 兩個數字基底不同,**不可混用/相加**。
⚠️ 小不一致:demo slide 8 的「S5 4-seed union = 590」與邊際表前 4 累積 = 599 對不起來(差 9)→ 可能不同 run/不同 ε,對外講前要釐清。

---

## 5. Config 旋鈕 & sweep 工具(任務 1 的著力點)

- **環境變數**:
  - `EVCS_EPSILON`(default 0.0,greedy;舊 92.6% 用 0.2)
  - `EVCS_SEED`(default 12345)
  - `EVCS_DUMP_VISITED=<path>`(**是路徑不是 flag**;=1 會寫出一個叫「1」的檔)→ 產 visited dump
  - `EVCS_DUMP_TRAJECTORY=1`(配合上者,trajectory 才進 dump)
- **test_exploration.py 內常數**(需讀檔確認現值):`_MAX_STEPS`(=4000 CI budget)、`_COVERAGE_TARGET`、`_STAGNATION`(=500)、`_SETTLE_BUDGET`、`_LOW_DEMAND_KW`、`_HIGH_DEMAND_KW`、`_LOW_DEMAND_EVERY`、`_EXPLORE_BATTERY_KWH`。
- **union 工具**:`union_coverage.py`(吃多個 dump、算聯集,忽略未知 key)、`sweep_union.sh`(跑多 seed sweep)。
- **dump→records 抽取 pattern**(已驗證可用):
  ```bash
  for S in <seeds>; do
    EVCS_DUMP_VISITED=dump_$S.json EVCS_DUMP_TRAJECTORY=1 EVCS_SEED=$S \
      pytest tests/algo_validation/test_exploration.py -q
  done
  # 再用 python 抽 dump_$S.json["trajectory"]["records"] → docs/algo_validation/traj_records_$S.json
  ```

### 任務 1 建議路徑(spike-first)
1. **讀現行 config**:fetch/讀 `test_exploration.py`(<1000 行?確認)+ `conftest.py` + `arrival_scheduler.py`,把現值列出來。
2. **決定旋鈕**:逼近 100% 的槓桿 = (a) 更多 seeds、(b) ε=0.2(增加軌跡多樣性)、(c) 拉高 `_MAX_STEPS`/`_STAGNATION`、(d) demand 模型。
3. **跑 union sweep**(現行 config,多 seed,可能 ε=0.2),記錄聯集成長到平台。
4. **釐清剩餘 unreachable 節點**:舊說法是 ~57 個(7.4%)結構不可達(per-MCU dynamic power 破壞 C4 對稱)。**100% 是否可達取決於這些節點是否真的結構不可達**——需要實證,別假設。若真不可達,「最大可達覆蓋」才是誠實的目標(不是 100%)。
5. degenerate seeds(撞 F1-b)排除,不納入 union。

---

## 6. 關鍵檔案 & commits

**Production**(read-only 除非有 fix instruction):
- `simulation/modules/mcu_control.py`(**已含 bridge-race guard** `_foreign_virtual_span ~:1115`;`_apply_global_relay_state` foreign-span loop :914–932 / local guard :901–905 / open-sweep :934–936 / close loop :955–964 / right-bridge :999–1004;`_finalize_departure` / `_drain_pending_foreign_release_notifies` / `_handle_return_notify` = C1 queue 路徑)
- `simulation/hardware/rectifier_board.py`(bridge 出廠 OPEN;:61 pristine 述詞)、`charging_station.py`、`relay.py`
- `simulation/data/module_assignment.py`

**Test 層**:`tests/algo_validation/test_exploration.py`(:123 F1-b guard、dump caller ~:138)、`helpers/{coverage_tracker,arrival_scheduler,tick_checks,steady_checks,relay_invariants,async_driver,arrive_inject}.py`、`test_cross_mcu_orphan_relay.py`、`test_relay_phase_teardown.py`、`test_bridge_reclose_race.py`(新)、`conftest.py`、`union_coverage.py`、`sweep_union.sh`

**Docs**(repo):`docs/algo_validation/{SCHEDULER_CORE_CONCEPT, TRAJECTORY_AND_LOG_CONCEPT, ASSERT_NOTATION_L2_L3_L4, SPIKE_A1_BRIDGE_SEED1, traj_records_1/1000/12345/314159/67890}.*`、`docs/SPIKE-XMCU-REPORT.md`

**Outputs(交付物)**:`EVCS_Validation_Demo.pptx`(12 張)、`EVCS_CrossSeed_Dashboard.svg/.png`、`EVCS_Invariant_Map.svg/.png`、`EVCS_Trajectory_Dashboard_seed12345.svg/.png`、各 `STEP_*_INSTRUCTIONS.md`、`HANDOFF_next_window.md`(本檔)

**Commits**:bridge-race fix `1dfeaeb`(fix)+`0f39584`(test);trajectory `20fa3c3`+`ac3828b`;原 orphan fix `7ac4599`。

**⚠️ 風險 — deck.js**:demo 生成器 `/home/claude/pptx_build/deck.js`(29KB→現約 12 張)**只在沙盒,可能未 commit 進 repo**。跨視窗會消失。**建議**:請 Psyduck 確認 deck.js 是否已 commit;若否,任務 3 開始前先把它 commit 到 repo(例如 `tools/deck.js` 或 `docs/demo/`),否則下個視窗要重建生成器。本檔的 §3c 記了它的結構與 QA pipeline 以便必要時重建。

---

## 7. 慣例 & 雷區

- **零 production 修改 = 針對驗證框架**(不得為了讓測試過而改 production)。**修框架找到的真 bug 是例外、是框架的目的**。
- **index-agnostic 測試紀律**:用語意 helper(`mcu_by_id`/`boundary_groups_toward`/`bridge_relay_to`),禁硬編 g3/g4/R_xx;grep guard 強制。
- **regression test 必須修前紅、修後綠**(沒紅 = 沒真重現)。
- **A1 正確、不要動**(關於 relay↔ownership co-ownership iff)。
- **phantom 需求**:「DC hot-switching < 5A」在 production 演算法層**無對應邏輯**,別當現行約束引用。
- **rebuild-engine pattern**:每個 web request 開全新 throwaway engine(cold settle),deterministic,~5–7ms P95,無需 caching。
- **backlog(未做)**:production 端 relay↔MA co-ownership 不變量(`validator.py`,原 Phase B C2);configurable SMR group count → N-hop borrowing → greedy multi-assignment;DFS→EXPLORATION 命名一致化;spec §143「5A」phantom 清理。
- **measurement**:覆蓋率是**觀察指標**;pass/fail 由「所有 visited 狀態與 ticks 通過所有 assertion」定義,不是覆蓋率門檻。

---

## 8. 任務逐項建議(給下個視窗的起手式)

**任務 1(找 config、逼近 100%)**:
- 起手:請 Psyduck 給 `test_exploration.py` + `conftest.py` 的 blob URL(或貼內容),我讀出現行所有常數 + ε 預設。
- 然後寫一份 sweep instruction:現行 config 下跑一輪多-seed union sweep(含 ε=0.2 比較),記錄聯集成長 + 識別 plateau + 剩餘 unreachable 節點清單。
- 關鍵 decision point:**剩餘節點是否結構不可達** → 決定目標是「100%」還是「最大可達 %」。

**任務 2(重跑跨-seed 報告)**:
- 用任務 1 選定的 seed 集 + config,重跑 → 抽 records → commit `traj_records_*.json`。
- 我 fetch 後用沙盒(重畫 `gen_xseed.py` 邏輯,本檔 §3b 有數據格式)重建三面板 dashboard。

**任務 3(修正主管報告)**:
- demo slide 8(coverage trajectory)+ slide 9(marginal)換成**現行 config 可重現**數字;標清「舊 sweep(歷史)vs 現行」。
- slide 11/12 已是現行(保留)。
- 年度目標評估 Word(Microsoft JhengHei 字型):Goal 1 原 ~95%(bridge bug 是 regression gate,現已修 → 可重評);Goal 2 ~40%;Goal 3 ~10%。
- 若 deck.js 未 commit,先處理 §6 風險。

---

## 9. 一句話狀態

兩個 production orphan bug 都已找到並修復(C1 never-opened `7ac4599` + bridge re-close race `1dfeaeb`);跨-seed 框架已能量化「換 seed = 探不同區域 = 浮出不同 bug」(610/766, Jaccard 0.22);demo 12 張就緒。**下一步是釐清現行 config 的真實可達覆蓋上限**(舊 92.6% 不可重現),再據此重跑分析與修正主管報告。