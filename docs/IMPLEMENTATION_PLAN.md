# fussball-bund 优化实施计划（交接文档）

> **读者**：接手实施的开发者/分析人员  
> **目标**：在现有 CLI 数据管线与模型基础上，把评估做可信、信号做增强、产出做成可日更的赛前足彩分析工作流  
> **原则**：先改评估再改模型；每个阶段必须有可复现验收指标；禁止用含未来信息的数据拟合模型  

**文档版本**：v1.0  
**基线日期**：2026-08  
**代码基线**：`fussball-bund` 0.1.0（Phase 1–5 已完成）  
**仓库路径**：`fussball-bund/`

---

## 0. 背景与现状（实施前必读）

### 0.1 项目是什么

五大联赛（+欧冠配置）足彩/赔率数据分析项目：

1. 采集历史战绩与庄家赔率  
2. 用进球模型预测胜平负 / 大小球  
3. 对比庄家隐含概率识别价值投注  
4. 回测 ROI，生成 Markdown 简报  

CLI 入口：`fussball`（`src/fussball_bund/cli.py`）

### 0.2 已完成能力（不要重复建设）

| Phase | 内容 | 状态 |
|-------|------|:----:|
| 1 | Football-Data.co.uk / Odds API / SoccerData 采集 + SQLite | 已完成 |
| 2 | 去水、Poisson、价值投注、回测 | 已完成 |
| 3 | Dixon-Coles、简报 | 已完成 |
| 4 | 多赛季拟合、弱队先验、平局校准 | 已完成 |
| 5 | xG-Poisson（Understat）+ 队名启发式映射 | 半完成 |

### 0.3 核心代码地图

```
fussball-bund/
├── config/leagues.yaml                 # 联赛与数据源映射
├── src/fussball_bund/
│   ├── cli.py                          # 全部命令入口
│   ├── config.py                       # env + yaml
│   ├── models.py                       # Match / Odds dataclass
│   ├── reporting.py                    # Markdown 简报
│   ├── collectors/
│   │   ├── football_data_uk.py         # ★ 历史主源
│   │   ├── odds_api.py                 # 实时赔率
│   │   └── fundamentals.py             # FBref / Understat / ClubElo
│   ├── storage/
│   │   ├── db.py                       # SQLite 封装
│   │   └── schema.sql                  # 主表结构（不完整，见缺口）
│   └── analysis/
│       ├── probability.py              # Shin/Power/Naive 去水
│       ├── models.py                   # PoissonModel
│       ├── dixon_coles.py              # DixonColesModel
│       ├── xg_model.py                 # XGPoissonModel
│       ├── calibration.py              # 平局α混合
│       └── value.py                    # ValueBetFinder + backtest
├── data/fussball.db                    # 运行时库（勿入库密钥）
└── reports/*.md                        # 历史简报样例
```

### 0.4 本地数据基线（实施验收时对比）

截至 2026-07 前后库内大致：

| 表 | 量级 |
|----|------|
| matches | ~2.9k |
| odds_1x2 | ~25k |
| odds_totals / asian | ~26k |
| understat_shots | EPL 23-24 / 24-25 有数据 |
| EPL 多赛季 | 2021-22～2024-25（4 季） |
| 其他五大联赛 | 基本仅 2024-25 |
| UCL | football-data.co.uk CSV 不可用，被 skip |

**英超基线指标（多赛季 Dixon-Coles + 校准，`reports/epl_2425_v4.md`）**：

| 指标 | 值 |
|------|-----|
| 最大概率命中率 | 51.6% |
| 单位注 ROI（min_edge=0.03, closing/Pinnacle） | -2.3% |
| 预测分布中平局 | 0 场（结构性问题） |

> **重要**：-2.3% ROI 不能证明模型“只差一点点就能盈利”。当前回测存在**评估偏差**（见 0.5），Phase A 完成前禁止用 ROI 作为模型选型唯一依据。

### 0.5 已知结构性问题（必须修）

| ID | 问题 | 位置 | 影响 |
|----|------|------|------|
| B1 | 回测非 walk-forward：整季参数静态 | `analysis/value.py`, 模型 `fit` | 高估/误估实盘可用信号 |
| B2 | 价值投注默认对比 **closing** | `value.py` `period="closing"` | 有“事后看盘”嫌疑，应用 opening 或赛前快照 |
| B3 | 评估指标过粗（仅准确率+固定单位 ROI） | `reporting.py`, `value.backtest` | 无法判断概率质量 |
| B4 | 平局几乎从不成为 max-prob 预测 | Poisson 类模型通病 | 命中率解释困难 |
| B5 | xG 队名映射：按 `match_date` + LIMIT 1 | `xg_model.py` L73-77 | 同日多场会错配 |
| B6 | ClubElo / match_stats / 亚盘入库但未进模型 | collectors + schema | 数据浪费 |
| B7 | report 不支持 `xgpoisson` | `reporting.py` `_build_model` | 与 CLI 能力不一致 |
| B8 | understat/club_elo 运行时建表 | `fundamentals.py` | 与 schema.sql 不一致 |
| B9 | 非英超历史过短 | data | 多赛季 DC 无法泛化 |
| B10 | 无自动化测试 | tests/ 不存在 | 回归风险高 |
| B11 | 欧冠主路径缺失 | `leagues.yaml` UCL fd code=null | 配置名不实 |
| B12 | 未对接国内竞彩赔付结构 | — | 若目标用户是竞彩则缺口 |

### 0.6 技术栈与运行

```bash
cd fussball-bund
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # ODDS_API_KEY 实时盘需要
fussball --help
```

依赖：`requests, pandas, pyyaml, click, soccerdata, shin, scipy`  
可选：`pytest, ruff`；`oddsharvester` 不进核心路径  

**Python**：>=3.11  
**DB**：SQLite + WAL  

### 0.7 工程规范（实施约定）

1. 包布局保持 `src/fussball_bund/`，不要打散成脚本丛林  
2. 新表先写 `storage/schema.sql` + 迁移说明，禁止只在 collector 里隐式建表  
3. 新评估脚本必须**可 CLI 调用**或至少 `python -m`  
4. 禁止把 `data/*.db`、`.env`、密钥提交 git  
5. PR 粒度：单阶段可多 PR，但每个 PR 必须有验收说明  
6. 模型对比以 **walk-forward Brier / log-loss / opening-CLV** 为主；准确率、closing-ROI 仅为辅助  
7. 注释与用户可见文案可中文；函数/模块文档建议中英均可，风格与现有代码一致  

---

## 1. 总体目标与成功标准

### 1.1 产品目标

| 用户场景 | 目标输出 |
|----------|----------|
| 赛季复盘 | 可信回测报告（无信息泄露） |
| 赛前决策 | 本周末关注场：1X2/大小球 edge、仓位建议、风险提示 |
| 模型研发 | 多模型横向对比表（同一套 walk-forward 协议） |

### 1.2 总体成功标准（项目级 DoD）

完成全部 Phase A–C 后，应满足：

- [ ] 存在文档化的 **Walk-forward 回测协议 v1**，代码与文档一致  
- [ ] 至少覆盖 **EPL + 另外 2 个联赛** 各 ≥3 个完整历史赛季  
- [ ] 任一模型对比可输出：Brier、log-loss、1X2 校准、opening ROI、CLV  
- [ ] xG 链路通过**正式队名映射表**接入，错误映射率有统计  
- [ ] 周五/赛前可一键生成简报（含实时或最近一次 odds 快照时间戳）  
- [ ] 核心模块有 pytest 覆盖（见 Phase A 测试清单）  
- [ ] README 与本 plan 中“后续路线”同步为已完成/进行中  

### 1.3 非目标（本计划不要求）

- 保证正 ROI / 盈利（市场有效，不作为硬 KPI）  
- 重写为复杂微服务或多 DB 架构  
- OddsPortal Playwright 作为核心数据源  
- 完整交易下单对接  
- 大规模深度学习 / 比赛事件序列模型  

---

## 2. 阶段总览与依赖

```
Phase A 评估可信  ──────────────►  Phase B 信号增强
        │                              │
        │  A 完成前禁止宣称“新模型更好”   │
        ▼                              ▼
Phase D 工程硬化（贯穿全程）         Phase C 产品闭环
```

| 阶段 | 名称 | 预估人天 | 依赖 | 建议顺序 |
|------|------|:--------:|------|:--------:|
| **A** | 评估与回测可信化 | 5–8 | 无 | 1 |
| **B** | 特征/模型增强 | 8–12 | A 的评估框架 | 2 |
| **C** | 赛前产品与自动化 | 6–10 | A；B 的主力模型可选 | 3 |
| **D** | 工程硬化 | 3–5 | 贯穿 | 与 A 并行起点 |

**建议编制**：1 名偏数据/模型 + 1 名偏工程；单人串行约 5–7 周。

---

## 3. Phase A — 评估与回测可信化（P0）

**目标**：消除信息泄露与 closing 事后偏差，建立统一评估协议。  
**时长**：5–8 人天  
**负责人角色**：数据科学家 / 后端均可  

### 3.1 任务列表

#### A1. 文档化回测协议（0.5 天）

**交付物**：`docs/BACKTEST_PROTOCOL.md`

必须写清：

1. 训练集时点：预测比赛日 `t` 时，仅允许 `match_date < t` 的比赛进入 `fit`  
2. 赔率时点：  
   - 主路径：`period=opening`  
   - 辅助：`period=closing` 仅用于 CLV 与共识基准  
3. 下注规则：`min_edge`、`min_odds`、固定 1u 与 half-Kelly 两种  
4. 基准模型：`dixoncoles` + 前 3 季（与现 CLI 默认一致），α 校准开关分开展示  
5. 报告字段定义（与 A3 输出 JSON/CSV schema 一致）

**验收**：评审签字或 PR 合并该文档。

---

#### A2. Walk-forward 引擎（2–3 天）

**新模块建议**：`src/fussball_bund/analysis/walkforward.py`

**接口设计（实施者可微调，但需保持语义）**：

```python
@dataclass
class WFConfig:
    league: str
    season: str                    # 评估赛季
    model_name: str                # poisson | dixoncoles | xgpoisson
    fit_history_seasons: list[str] # 赛季开始前可用的历史季
    include_in_season: bool = True # True: 用本季已赛增量进训练
    bookmaker: str = "Pinnacle"
    bet_period: str = "opening"    # 下注赔率时点
    clv_period: str = "closing"    # CLV 对照
    min_edge: float = 0.03
    min_odds: float = 1.5
    stake: float = 1.0
    calibrate: bool = False
    calibrate_alpha: float = 0.4
    refit_every_n: int = 1         # 每 N 场重拟合；可先=1 或按 matchday 重拟合

def run_walkforward(cfg: WFConfig, db: Database) -> WFResult: ...
```

**算法伪代码**：

```
history = load_matches(league, fit_history_seasons)  # 仅完赛
season_matches = load_matches(league, [season]) ordered by date, id
model = fit(history)  # 初始

for match in season_matches:
    if match has bet_period odds:
        pred = model.predict(home, away)
        if calibrate: pred = mix with implied(bet_period)
        record probability metrics vs actual (if finished)
        value_bets = edge filter on bet_period
        settle bets if finished
        record CLV if clv_period odds exist: clv = bet_odds/closing_odds - 1 (方向正确时)
    if include_in_season and match finished:
        history.append(match)
        if need_refit: model = fit(history)
```

**性能注意**：

- Dixon-Coles 每场重拟合很慢 → 默认 `refit_every_n` 按**轮次/matchday**（同一 `match_date` 批次）重拟合即可  
- 实现时应缓存“本轮次开始前”的一次 fit  

**涉及改动**：

| 文件 | 动作 |
|------|------|
| `analysis/walkforward.py` | 新建 |
| `analysis/__init__.py` | export |
| `cli.py` | 新命令 `fussball walkforward ...` |
| `analysis/value.py` | 抽取 `settle_bet`、`score_markets` 公共函数，避免复制逻辑 |

**CLI 示例**：

```bash
fussball walkforward -l EPL -s 2024-2025 --model dixoncoles \
  --bet-period opening --calibrate -o reports/wf_epl_2425.json
```

**验收**：

- [ ] 对同一场，训练数据中不出现该场及未来场（单测 A6 锁死）  
- [ ] 输出含每场预测概率与下注记录（JSON/CSV）  
- [ ] EPL 2024-25 可在合理时间跑完（DC：建议 < 30min 笔记本；可调 refit 频率）  

---

#### A3. 概率评估与 CLV（1.5 天）

**新模块建议**：`src/fussball_bund/analysis/metrics.py`

必须实现：

| 指标 | 定义 | 用途 |
|------|------|------|
| Brier (1X2) | mean Σ (p_i - y_i)² | 概率质量主指标，越低越好 |
| Log-loss | -mean log p_actual | 对自信错误敏感 |
| Max-prob accuracy | argmax 命中率 | 辅助，注明平局缺陷 |
| Opening ROI | 单位注 / half-Kelly | 实盘近似 |
| CLV | 下注赔率相对 closing 的收口 | 是否抓到错误定价 |
| 校准分桶 | 10 桶 predicted vs empirical | 图或表 |

**输出格式建议** `WFResult.summary`：

```json
{
  "league": "EPL",
  "season": "2024-2025",
  "model": "dixoncoles",
  "n_matches": 380,
  "brier": 0.62,
  "log_loss": 1.01,
  "accuracy": 0.51,
  "roi_flat": -3.2,
  "roi_half_kelly": -1.1,
  "clv_mean": 0.01,
  "n_bets": 120,
  "config": { "...": "..." }
}
```

**验收**：

- [ ] 对人造 3 场可手工验算 Brier/ROI  
- [ ] 简报或 CLI 打印可读摘要  

---

#### A4. ValueBetFinder 参数化改造（1 天）

**文件**：`analysis/value.py`

改动要求：

1. `find(..., period="opening")` 默认改为 **opening**（breaking change：README/CLI 同步）  
2. 若 opening 缺失则可选 fallback closing，并在结果中标记 `odds_fallback=true`  
3. `backtest` 增加参数 `protocol="legacy"|"walkforward"`：  
   - `legacy`：保留现行为（对照旧报告）  
   - `walkforward`：委托 A2 引擎  
4. 抽出：

```python
def settle_market(market: str, ft_result, hg, ag) -> bool: ...
def kelly_fraction(p: float, odds: float, fraction: float = 1.0) -> float: ...
```

**CLI**：

```bash
fussball value -l EPL -s 2024-2025 --period opening --min-edge 0.03
fussball backtest -l EPL -s 2024-2025 --protocol walkforward --period opening
```

**验收**：

- [ ] 旧命令加 `--period closing --protocol legacy` 可复现接近 -2.3% 量级（允许实现细节 ±少量）  
- [ ] 默认 help 文案标明 opening 为生产默认  

---

#### A5. 校准进评估（不先调参刷 ROI）（0.5–1 天）

1. walk-forward 输出两套行：`raw` vs `calibrate=True`  
2. α 网格可后置；先固定 0.3/0.4/0.5 三组对比 Brier，写入报告  
3. **禁止**只选 ROI 最高的 α 而不看 Brier  

**验收**：校准对比表出现在 `reports/` 某次评估 md/json。

---

#### A6. 测试基建（1.5 天）

**目录**：`tests/`

| 测试文件 | 覆盖 |
|----------|------|
| `test_probability.py` | shin/power/naive 和为 1；单调性烟测 |
| `test_settle.py` | home/draw/away/over/under 结算 |
| `test_walkforward_no_leak.py` | mock 数据：预测 t 时训练集 max(date)<t |
| `test_fit_seasons.py` | `_resolve_fit_seasons` 边界 |
| `test_dc_tau.py` | τ 四象限公式 |

**conftest.py**：内存 SQLite fixture，插入 20 场假数据。

**pyproject**：

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.5"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**验收**：`pip install -e ".[dev]" && pytest -q` 全绿。

---

#### A7. 补历史数据（运维向，0.5–1 天）

```bash
# 五大联赛近 4 季示例（实施者按带宽调整）
for L in EPL LALIGA SERIE_A BUNDESLIGA LIGUE_1; do
  for S in 2021-2022 2022-2023 2023-2024 2024-2025; do
    fussball collect-history -l $L -s $S
  done
done
fussball stats
```

**验收**：

- [ ] 五联赛均有 ≥3 季 matches  
- [ ] `stats` 输出贴入 PR 描述  
- [ ] 更新 `config/leagues.yaml` `default_seasons` 为实际需要集合  

**注意**：UCL 会 skip，属预期；记入采集日志即可。

---

### 3.2 Phase A 里程碑验收（全部勾选才算完成）

- [ ] `docs/BACKTEST_PROTOCOL.md` 存在  
- [ ] `fussball walkforward` 可对 EPL 2024-25 产出 JSON  
- [ ] metrics 含 Brier / log-loss / opening ROI / CLV  
- [ ] 默认 value/backtest 走 opening  
- [ ] pytest 全绿  
- [ ] 非英超 ≥3 季历史入库  
- [ ] 基线对比表：legacy closing ROI vs new walkforward opening Brier（允许二者趋势不同）  

### 3.3 Phase A 风险

| 风险 | 缓解 |
|------|------|
| DC 重拟合太慢 | matchday 级 refit；或增量优化（后续） |
| 部分庄家 opening 缺失 | fallback + 覆盖率统计字段 |
| 指标与旧报告不可比 | 强制保留 legacy 模式 |

---

## 4. Phase B — 信号 / 模型增强（P1）

**前置**：Phase A walk-forward + metrics 可用（否则无法科学对比）。  
**时长**：8–12 人天  

### 4.1 任务列表

#### B1. 队名映射体系（1.5–2 天）【堵住 B5】

**问题**：Understat / FBref / football-data 队名不一致；当前按日期盲匹配危险。

**方案**：

1. 新表（写入 `schema.sql`）：

```sql
CREATE TABLE IF NOT EXISTS team_name_map (
    source TEXT NOT NULL,          -- football_data | understat | fbref | clubelo | odds_api
    source_name TEXT NOT NULL,
    league_code TEXT NOT NULL,
    canonical_name TEXT NOT NULL,  -- 统一用 football-data 名为 canonical
    UNIQUE(source, source_name, league_code)
);
```

2. 工具命令：

```bash
fussball map-teams --league EPL --source understat --season 2024-2025 --dry-run
fussball map-teams --league EPL --source understat --apply
```

3. 自动候选：归一化（小写、去 FC、去点号）+ 编辑距离；低置信写入待审 CSV  
4. `xg_model.fit` **只使用** map 表，禁止 date LIMIT 1  

**验收**：

- [ ] EPL understat 映射覆盖 ≥95% 队季  
- [ ] 人工抽检 20 场 xG 聚合两侧球队与 matches 一致  
- [ ] 单测：故意同日两场，映射不会串  

---

#### B2. match 级 xG 聚合表（1 天）

```sql
CREATE TABLE IF NOT EXISTS match_xg (
    match_id INTEGER PRIMARY KEY,   -- 关联 matches.id；无法关联可先 null + 外键可选
    league_code TEXT,
    season TEXT,
    match_date TEXT,
    home_team TEXT,                 -- canonical
    away_team TEXT,
    home_xg REAL,
    away_xg REAL,
    source TEXT DEFAULT 'understat',
    FOREIGN KEY(match_id) REFERENCES matches(id)
);
```

**命令**：

```bash
fussball build-xg -l EPL -s 2023-2024
fussball build-xg -l EPL -s 2024-2025
```

从 `understat_shots` group by match + map teams + join matches。

**验收**：

- [ ] 场次数与 understat 可匹配的完赛场接近  
- [ ] home_xg+away_xg 分布合理（均值约 1.x）  

---

#### B3. 多赛季 xG 采集（1 天，运维）

```bash
for S in 2021-2022 2022-2023 2023-2024 2024-2025; do
  fussball collect-fundamentals -l EPL -s $S --source understat
  # 其他联赛按反爬节奏错峰
done
```

**注意**：SoccerData/Cloudflare 可能失败；需重试 + 缓存目录 `SOCCERDATA_DIR`；失败写 `collection_log`。

**验收**：EPL ≥3 季 `match_xg` 有数据；至少再 1 个联赛有 ≥2 季。

---

#### B4. xG-Dixon-Coles 或 Hybrid 模型（2–3 天）

**新类建议**：`analysis/xg_dixon_coles.py` 或扩展 `XGPoissonModel`

推荐路径（选一种，写清理由）：

| 方案 | 描述 | 复杂度 |
|------|------|:------:|
| **B4-a（推荐）** | 用 match_xg 的 home_xg/away_xg 代替 goals 做 DC 似然（把 xG 当“软进球”）或用 Poisson 似然在 xG 上估强度 | 中 |
| **B4-b** | λ_goal = w·λ_xg + (1-w)·λ_dc_goals，w 走 walk-forward 网格 | 较高 |
| **B4-c** | 仅在 Poisson 强度上替换 goals→xG（已有 XGPoisson），加上 τ 修正确率 | 低 |

**统一接口**（强制）：

所有模型必须：

```python
class PredictModel(Protocol):
    def fit(self, league, seasons, *, as_of: str | None = None) -> Self: ...
    def predict(self, home: str, away: str) -> MatchPrediction: ...
    # 属性用于 report 排名: attack/defense 或 home_attack/...
```

`walkforward` / `reporting` / CLI `_build_model` 全部经工厂：

```python
# analysis/factory.py
def build_model(name: str, db) -> PredictModel: ...
```

**验收**：

- [ ] `fussball walkforward --model xgdc`（或选定名）可跑  
- [ ] 与 `dixoncoles` 对比：EPL 至少 2 个评估季 Brier 不劣于 baseline 或 CLV 改善（允许并列；若更差需分析原因写入报告）  

---

#### B5. ClubElo 先验（1 天）

1. `collect_clubelo` 批量：联赛球队列表循环（从 matches distinct）  
2. 预测时：canonical 队不在 fit 集合 → 用最近 Elo 分位映射到 attack/defense 先验，替换写死 `(-0.25, 0.25)`  
3. 映射函数需文档化（例如：Elo z-score → 强度）

**验收**：升级队（如 24-25 Ipswich）先验不再盲目与均值等同，有单元测试固定数字。

---

#### B6. 近期状态特征（1.5–2 天，可选但高价值）

`analysis/form.py`：

- 近 5/10 场：进球、失球、xG、xGA（有 xG 时）  
- 主客拆分  
- 衰减权重与 DC `decay` 概念对齐  

接入方式（保持简单）：

- 在 predict 阶段对 λ 乘 form 因子：`λ *= (1 + β * form_z)`，β 小网格 walk-forward 选，防止过拟合  

**验收**：ablation 表：baseline / +form / +xg 的 Brier 对比。

---

#### B7. 大小球与亚盘策略（1.5–2 天）

现状：大小球已在 value 里部分支持；亚盘表有数据未用。

1. **大小球**：独立 walk-forward（仅 over/under 2.5），metrics 与 1X2 分开  
2. **亚盘 v1**：  
   - 用模型进球分布推算出让球口概率（离散盘 -0.5/-0.25/0/0.25…）  
   - 与 `odds_asian_handicap` 比 edge  
   - 结算规则单独实现 + 单测（走水、半赢半负）  

**验收**：亚盘结算单测全绿；有一份亚盘 ROI/CLV 报告（可负）。

---

#### B8. report 对齐 CLI（0.5 天）

- `reporting._build_model` 支持 `xgpoisson` / 新模型  
- 准确率计算若启用 calibrate，应用校准后的 p 再 argmax，并在报告声明  
- 文案不要写死“基础模型 ROI 为负”；改为引用最近 walkforward 数字  

**验收**：`fussball report --model xgpoisson --calibrate` 可生成。

---

#### B9. Ensemble（可选，1.5–2 天）

仅当 B4/B6 有可区分的 Brier 差异时做：

- 特征：`p_dc`, `p_xg`, `p_market`, elo_diff  
- 模型：多类 logistic 或简单加权  
- **必须** nested / walk-forward 外层防止泄漏  

**验收**：ensemble 外层指标；若不及最优单模型则文档记录弃用。

---

### 4.2 Phase B 里程碑验收

- [ ] team_name_map + match_xg 进 schema 并有数据  
- [ ] xG 主路径模型接入 walkforward  
- [ ] Elo 先验替代裸 prior  
- [ ] 至少一份 `reports/model_compare_epl.md`（多模型 A3 指标）  
- [ ] report 支持新模型  

### 4.3 Phase B 风险

| 风险 | 缓解 |
|------|------|
| Understat 反爬失败 | 缓存；缩小联赛范围先 EPL |
| xG 不稳单季方差大 | 强制多季 + 时间衰减 |
| 亚盘结算复杂 | 先支持整球/半球，再角球盘 |

---

## 5. Phase C — 赛前产品闭环（P1/P2）

**前置**：A 完成；B 的主力模型可选（可先 DC）。  
**时长**：6–10 人天  

### 5.1 任务列表

#### C1. 实时赔率入库规范（1.5 天）

审阅 `collectors/odds_api.py`：

1. 写入 matches（未来场 `ft_*` null）+ odds_1x2（`period=live_snapshot` 或 `opening`）  
2. 记录 `collected_at`（新列或用 collection_log + odds 侧 timestamp 表）  
3. 队名与 football-data 对齐（map 表 source=`odds_api`）  

建议表：

```sql
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY,
    match_id INTEGER,
    bookmaker TEXT,
    market TEXT,           -- 1x2
    home REAL, draw REAL, away REAL,
    collected_at TEXT NOT NULL,
    source TEXT DEFAULT 'odds_api'
);
```

**验收**：

```bash
fussball collect-odds -l EPL
# 库中有未来场 + snapshot 时间
```

---

#### C2. 赛前简报命令（2 天）

```bash
fussball preview -l EPL --days 7 --model dixoncoles --calibrate -o reports/preview_epl.md
```

**内容结构**（固定模板）：

1. 元数据：模型、拟合 as_of、赔率快照时间、数据缺口警告  
2. 本周赛程表（日期、对阵、Pinnacle 1X2）  
3. 模型概率 vs 隐含概率、edge、建议仓位 half-Kelly（设上限如 2% 资金）  
4. Top N 关注场（按 edge 且过滤 odds 极端值 >8）  
5. 风险声明模板（固定法律/娱乐声明）  

**实现**：`reporting.generate_preview(...)`，与赛后 report 分离。

**验收**：无完赛赔率时仍可对未来场生成；缺数据场标红。

---

#### C3. 调度与运维脚本（1 天）

交付：

- `scripts/daily_job.sh` 或 `docs/ops.md` 中 cron 示例  

```text
# 每天 12:00（示例）
collect-odds 五大联赛
preview 输出到 reports/daily/
```

可选：失败 exit code ≠0；可对接飞书 webhook（环境变量 `FEISHU_WEBHOOK`），失败不阻塞。

**验收**：文档中一步粘贴可部署；人工 dry-run 成功 1 次。

---

#### C4. 仓位与风控（1–1.5 天）

`analysis/risk.py`：

| 规则 | 默认 |
|------|------|
| Kelly 系数 | 0.25–0.5（half/quarter） |
| 单场上限 | 银行的 2% |
| 单日同方向联赛暴露 | 上限 N 注 |
| 剔除相关冲突 | 同场只取 1 个 market |
| max odds | 8.0（与现 report 一致） |

walkforward 增加 `roi_risk_adjusted`。

**验收**：单测资金路径；报告中列出名义 Kelly vs 风控后仓位。

---

#### C5. 竞彩适配层（可选，2–3 天）

**仅当产品目标含国内竞彩时做。**

1. 配置 `config/jingcai.yaml`：玩法、截止、赔付（若有数据源）  
2. 输出字段：竞彩场次编号、胜平负档、串关候选（2/3 串）  
3. **不强依赖** 爬取官方；可先手工映射 CSV  

若无数据源：本任务标为 **Deferred**，README 标明“欧盘研究版”。

---

#### C6. 欧冠数据路径（1–2 天，可选）

- 使用 Odds API `soccer_uefa_champs_league` + FBref schedule 写 matches  
- 不走 football-data.co.uk  
- 简报表标记样本偏差  

**验收**：`fussball collect-ucl --season 2024-2025` 或复用 collect-odds + fundamentals 文档路径。

---

#### C7. 轻量 API（可选，P2，2 天）

- FastAPI：`GET /health`, `GET /preview?league=EPL`  
- 不强制前端  

---

### 5.2 Phase C 里程碑验收

- [ ] `preview` 命令产出赛前 md  
- [ ] odds 快照可追溯时间  
- [ ] 日更文档/脚本存在  
- [ ] 风控参数可配置  

---

## 6. Phase D — 工程硬化（贯穿）

**时长**：累计 3–5 人天，从 Week 1 开始穿插  

### 6.1 任务列表

#### D1. Schema 统一（0.5 天）

将以下全部移入 `schema.sql`：

- understat_shots  
- club_elo  
- team_name_map  
- match_xg  
- odds_snapshots（若做 C1）  

Collectors 仅 `CREATE IF NOT EXISTS` 兼容，主真相是 schema.sql。

可选简单迁移：`fussball db-init` 打印 schema 版本号表 `schema_version`。

---

#### D2. 配置化（0.5 天）

`config/analysis.yaml` 示例：

```yaml
fit_seasons_default: 3
dc_decay: 0.0018
min_edge: 0.03
min_odds: 1.5
max_odds: 8.0
calibrate_alpha: 0.4
bookmaker: Pinnacle
bet_period: opening
kelly_fraction: 0.5
max_stake_pct: 0.02
```

`config.py` 加载；CLI 参数覆盖 yaml。

---

#### D3. 采集质量命令（0.5 天）

```bash
fussball data-quality -l EPL -s 2024-2025
```

输出：完赛率、Pinnacle opening/closing 覆盖率、缺统计场次、最新 collection_log。

---

#### D4. 代码质量（0.5 天）

- ruff check  
- `_build_model` / `_resolve_fit_seasons` 去掉 `cli.py` 与 `reporting.py` 重复，收口到 `analysis/factory.py`  
- 类型：新增模块补类型注解  

---

#### D5. README 同步（0.5 天）

更新：

- 快速开始含 walkforward / preview  
- 已知局限（评估协议变更后重写数字）  
- 后续路线勾选状态  
- 指向 `docs/IMPLEMENTATION_PLAN.md` 与 `BACKTEST_PROTOCOL.md`  

---

### 6.2 Phase D 验收

- [ ] schema.sql 与实库一致  
- [ ] 配置外置  
- [ ] data-quality 可用  
- [ ] ruff + pytest CI 本地脚本或 GitHub Action（可选）  

---

## 7. 工作分解与建议排期

### 7.1 按周（单人全职参考）

| 周 | 交付 |
|----|------|
| W1 | A1 协议、A6 测试骨架、D1 schema、A7 部分拉数 |
| W2 | A2 walkforward、A3 metrics、A4 value 改造 |
| W3 | A5 校准对比、A7 补全、Phase A 验收报告 |
| W4 | B1 映射、B2 match_xg、B3 采集 |
| W5 | B4 模型、B5 Elo、B8 report、model_compare 报告 |
| W6 | B6/B7 择优；C1+C2 preview |
| W7 | C3 调度、C4 风控、D2–D5、缓冲 |

双人并行：一人 A+D，一人 B 采集/映射，W3 后汇合模型。

### 7.2 任务优先级（砍 scope 时保留）

| 优先级 | 必须做 | 可砍 |
|:------:|--------|------|
| P0 | A2 A3 A4 A6 A7 B1 B2 | — |
| P1 | A5 B3 B4 B5 B8 C1 C2 C4 | B6 B7 |
| P2 | C3 D* | B9 C5 C6 C7 |

**最小可用版本（MVP）**：A 全部 + B1/B2 + C2（模型仍用 dixoncoles）+ D1/D5。

---

## 8. 验收用例清单（QA 可直接测）

### 8.1 功能回归

| # | 步骤 | 期望 |
|---|------|------|
| R1 | `fussball collect-history -l EPL -s 2023-2024` | success 写 matches/odds |
| R2 | `fussball predict -l EPL -s 2024-2025 --home "Man City" --away Arsenal --model dixoncoles` | 输出概率与比分 |
| R3 | `fussball walkforward -l EPL -s 2024-2025 --model dixoncoles --bet-period opening` | JSON + 无异常 |
| R4 | `fussball value -l EPL -s 2024-2025 --period opening` | 表头含 edge/EV |
| R5 | `fussball backtest --protocol legacy --period closing` | 接近历史 -2% 量级 ROI（辅助） |
| R6 | `fussball report -l EPL -s 2024-2025 -o /tmp/t.md` | 生成 md |
| R7 | `fussball preview -l EPL --days 7`（C 后） | 未来场列表 |
| R8 | `pytest -q` | 全绿 |

### 8.2 反泄漏抽检

随机抽 walkforward 日志中 5 场：确认 fit 用的最大 `match_date` < 该场日期。

### 8.3 数据质量抽检

| 检查 | 方法 |
|------|------|
| 队名映射 | 抽 10 支 understat 名 → canonical 人工核对 |
| xG | 单场 home_xg 与 understat 官网量级一致 |
| 赔率 | Pinnacle 1X2 与 FD CSV 手眼核对 3 场 |

---

## 9. 交付物清单（给发起人 check）

| 交付物 | 路径/形式 | 阶段 |
|--------|-----------|------|
| 本实施计划 | `docs/IMPLEMENTATION_PLAN.md` | — |
| 回测协议 | `docs/BACKTEST_PROTOCOL.md` | A |
| Walk-forward CLI | `fussball walkforward` | A |
| 评估报告样例 | `reports/wf_*.json` + 摘要 md | A |
| 测试套件 | `tests/` | A |
| 队名映射数据 | DB + 导出 CSV | B |
| 模型对比报告 | `reports/model_compare_*.md` | B |
| 赛前简报 | `fussball preview` | C |
| 运维说明 | `docs/ops.md` | C |
| README 更新 | `README.md` | D |

---

## 10. 开放决策（实施前需产品确认）

实施负责人启动前找发起人确认：

1. **主服务对象**：欧亚庄家价值研究 / 国内竞彩 / 两者？  
   - 影响是否启动 C5  
2. **是否追求自动化日更**：只要本地 CLI 还是飞书推送？  
3. **可接受的采集范围**：仅 EPL 深度 vs 五联赛均深  
4. **实时 API 预算**：The Odds API 免费额度是否够日更  
5. **ROI 预期管理**：是否明确“研究工具不保证盈利”对外口径  

---

## 11. 附录

### 11.1 现有 CLI 命令一览

| 命令 | 用途 |
|------|------|
| `collect-history` | FD.co.uk 历史 |
| `collect-odds` | Odds API |
| `collect-fundamentals` | FBref/Understat/ClubElo |
| `query` / `stats` | 查询统计 |
| `predict` | 单场预测 |
| `value` / `backtest` | 价值与回测 |
| `margin` | 水位 |
| `report` | 赛后简报 |

### 11.2 模型与关键参数现状

| 模型 | 文件 | 关键默认 |
|------|------|----------|
| poisson | `models.py` | new_team_prior (0.85, 1.15) |
| dixoncoles | `dixon_coles.py` | decay=0.0018, prior (-0.25, 0.25) |
| xgpoisson | `xg_model.py` | 同 Poisson 结构；依赖 understat_shots |
| 平局校准 | `calibration.py` | alpha=0.4 |
| fit 季数 | cli `_resolve_fit_seasons` | 目标季前 3 季 |

### 11.3 建议新建文件一览

```
docs/BACKTEST_PROTOCOL.md
docs/ops.md
config/analysis.yaml
src/fussball_bund/analysis/walkforward.py
src/fussball_bund/analysis/metrics.py
src/fussball_bund/analysis/factory.py
src/fussball_bund/analysis/form.py          # 可选
src/fussball_bund/analysis/risk.py          # C
src/fussball_bund/analysis/xg_dixon_coles.py # 或 hybrid
tests/conftest.py
tests/test_*.py
scripts/daily_job.sh
```

### 11.4 基线复现命令（旧行为）

```bash
fussball collect-history -l EPL -s 2021-2022
fussball collect-history -l EPL -s 2022-2023
fussball collect-history -l EPL -s 2023-2024
fussball collect-history -l EPL -s 2024-2025
fussball report -l EPL -s 2024-2025 --model dixoncoles --calibrate -o reports/epl_baseline.md
fussball backtest -l EPL -s 2024-2025 --model dixoncoles --calibrate --min-edge 0.03
```

（A4 后若默认 period 改变，复现旧基线需显式 `--period closing --protocol legacy`。）

### 11.5 参考报告

- `reports/epl_2425_v4.md`：当前最优配置样例文稿（注意平局预测为 0 的警告行）

---

## 12. 实施检查表（打印用）

**Phase A**

- [ ] A1 协议文档  
- [ ] A2 walkforward 引擎 + CLI  
- [ ] A3 metrics  
- [ ] A4 value/backtest 参数化  
- [ ] A5 校准对比  
- [ ] A6 pytest  
- [ ] A7 多联赛历史  

**Phase B**

- [ ] B1 team_name_map  
- [ ] B2 match_xg  
- [ ] B3 多季 xG  
- [ ] B4 新/增强模型  
- [ ] B5 Elo 先验  
- [ ] B6 form（可选）  
- [ ] B7 亚盘/大小（可选）  
- [ ] B8 report 对齐  
- [ ] B9 ensemble（可选）  

**Phase C**

- [ ] C1 odds 快照  
- [ ] C2 preview  
- [ ] C3 调度文档  
- [ ] C4 风控  
- [ ] C5 竞彩（可选）  
- [ ] C6 欧冠（可选）  

**Phase D**

- [ ] D1 schema  
- [ ] D2 analysis.yaml  
- [ ] D3 data-quality  
- [ ] D4 去重与 ruff  
- [ ] D5 README  

---

*本文档基于仓库现状梳理，供交接实施。若代码前进本 plan 仍保持任务 ID 稳定性（A1、B4…），进度用检查表勾选即可。*
