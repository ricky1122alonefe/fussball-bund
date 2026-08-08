# fussball-bund

五大联赛与欧冠足彩数据分析项目：赔率抓取、历史战绩、竞猜分析。

---

## 数据源可信度评估（实证验证）

> 下表基于实际访问验证（HTTP 状态码、反爬情况、数据完整性）综合判断。

| 数据源 | 类型 | 稳定性 | 可信度 | 覆盖范围 | 核心价值 |
|--------|------|:------:|:------:|----------|----------|
| **Football-Data.co.uk** | CSV 静态下载 | ⭐⭐⭐⭐⭐ | 学术金标准 | 2000 至今，五大联赛+欧冠+杯赛 | 历史赔率+战绩+开盘/收盘，多庄家 |
| **The Odds API** | 官方 REST API | ⭐⭐⭐⭐⭐ | 高（官方聚合） | 全球联赛实时 | 即将开赛/实时赔率，40+ 庄家 |
| **FBref** (via SoccerData) | 网页抓取 | ⭐⭐⭐ | 极高（StatsBomb） | 五大联赛+欧冠 | xG/传球网络/球员统计 |
| **Understat** (via SoccerData) | 网页抓取 | ⭐⭐⭐ | 高（权威 xG） | 五大联赛 | xG/xA 射门事件 |
| **ClubElo** (via SoccerData) | 轻量 HTML | ⭐⭐⭐⭐ | 高（学术认可） | 全球球队 | Elo 动态评级 |
| OddsHarvester (oddsportal) | Playwright | ⭐⭐ | 中（聚合站） | 即将/历史/实时 | 备用补充，反爬风险高 |

### 选型结论

- **历史赔率 + 战绩基座** → `Football-Data.co.uk`（最稳定，直连 CSV，无反爬，含 2000 年至今所有赛季的开盘/收盘赔率与比赛统计，学术界公认金标准）
- **实时/即将开赛赔率** → `The Odds API`（官方 API，结构化 JSON，最可靠）
- **基本面（xG/球员/球队统计）** → `FBref` + `Understat`（via SoccerData，权威但有 Cloudflare 反爬，靠缓存兜底）
- **球队实力评级** → `ClubElo`（轻量稳定）
- **OddsHarvester** 不纳入核心（Playwright 抓 oddsportal 稳定性最低），作为可选依赖保留

### 为何 Football-Data.co.uk 最可信

1. **稳定性**：静态 CSV 文件下载，实证 HTTP 200，无 JS 渲染、无登录、无反爬
2. **完整性**：单赛季单联赛一个 CSV，含比赛结果、半场/全场比分、射门/角球/红黄牌统计
3. **赔率维度全**：13 家博彩公司（bet365/Pinnacle/William Hill 等）的 1X2 开盘+收盘赔率，BetBrain 聚合的大小球、亚洲盘 max/avg
4. **学术认可**：被大量博彩研究论文与开源预测模型引用，数据质量经长期验证
5. **历史纵深**：自 2000-01 赛季起，适合回测建模

---

## 快速试运行（5 分钟上手）

```bash
cd fussball-bund && source .venv/bin/activate

# 1. 采集英超历史赔率+战绩（约 30 秒/赛季，最稳定数据源）
fussball collect-history --league EPL --season 2023-2024
fussball collect-history --league EPL --season 2024-2025

# 2. 生成竞猜分析简报（推荐：多赛季 Dixon-Coles + 平局校准）
fussball report --league EPL --season 2024-2025 --model dixoncoles --calibrate -o reports/epl.md

# 3. 预测单场比赛
fussball predict --league EPL --season 2024-2025 --home "Man City" --away "Arsenal" --model dixoncoles

# 4. 回测策略盈亏
fussball backtest --league EPL --season 2024-2025 --model dixoncoles --calibrate

# 5. 查看数据库统计
fussball stats
```

简报输出 `reports/epl.md`，含球队实力排名、预测准确率、价值投注清单、回测概览。

> 球队名用 football-data 格式（如 `Man City`、`Nott'm Forest`），
> 可用 `fussball query -l EPL -s 2024-2025 -n 5` 查看实际球队名。

## 安装

```bash
cd fussball-bund
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
# 不强制任何付费 API；整条分析链路可零成本运行
```

## 零付费推荐工作流（默认）

**不需要 The Odds API。** 历史用 Football-Data.co.uk（免费 CSV），赛程/未来场用 FBref（免费网页），模型本地算，结果 MD 丢给 AI 研判。

```bash
# A. 历史战绩 + 开盘/收盘赔率（免费）
fussball collect-history -l EPL -s 2025-2026

# B. 赛程：含未完赛（ft 为空）→ preview 靠这个，不要花钱买实时 API
#    把 <season> 换成当前/下赛季，如 2026-2027
fussball collect-fundamentals -l EPL -s 2026-2027 --source fbref

# C. （可选）xG
fussball map-teams -l EPL --source understat --season 2025-2026 --apply
fussball build-xg -l EPL -s 2025-2026

# D. 赛前清单：只有模型概率也行；无盘口会标「无盘口」，不伪造 edge
fussball preview -l EPL --days 14 --model dixoncoles -o reports/preview_epl.md

# E. 单场 / 复盘 → 把 MD 粘贴给 AI
fussball predict -l EPL -s 2025-2026 --home "Man City" --away Arsenal --model dixoncoles
fussball report -l EPL -s 2025-2026 --model dixoncoles -o reports/report.md
```

| 能力 | 零付费 | 有 Odds API（可选） |
|------|:------:|:------------------:|
| 历史分析 / walk-forward | ✅ | ✅ |
| 模型概率 + 比分 | ✅ | ✅ |
| 赛前 preview | ✅（FBref 赛程） | ✅ |
| vs 实时庄家 edge | ✗（只有历史盘） | ✅ |

## 使用

### 1. 抓取历史赔率与战绩（Football-Data.co.uk，最稳定）

```bash
# 单联赛单赛季
fussball collect-history --league EPL --season 2024-2025

# 五大联赛+欧冠 全部默认赛季（约 5 分钟）
fussball collect-history --all
```

### 2. 抓取实时赔率（The Odds API，**可选**，可不买）

仅当你需要「赛前实时多庄 edge」时再考虑；站点常有免费额度。

```bash
# 仅可选：cp .env.example .env 并填 ODDS_API_KEY
fussball collect-odds --league EPL
```

### 3. 抓取基本面（FBref/Understat/ClubElo，免费）

```bash
# 赛程（含未完赛 → preview 数据源，默认请走这条而不是 collect-odds）
fussball collect-fundamentals --league EPL --season 2026-2027 --source fbref
fussball collect-fundamentals --league EPL --season 2024-2025 --source understat
fussball collect-fundamentals --source clubelo --team "Man City"

# 队名映射（understat→football-data，堵住同日盲匹配，先 --dry-run 审查再 --apply）
fussball map-teams -l EPL --source understat --season 2024-2025 --apply

# 聚合 match 级 xG（每场一行，canonical 队名；需先 map-teams --apply）
fussball build-xg -l EPL -s 2024-2025
# 完成后即可 predict/walkforward --model xgpoisson（fit 直接读 match_xg）
```

### 3a. 欧冠（UCL）采集

> **禁止依赖 football-data.co.uk 欧冠 CSV**（2023 起 404，已停维）。
> UCL 正赛赛程通过 FBref 采集（需一次性注册 SoccerData 自定义联赛字典）。

**前置：注册 UCL 到 SoccerData**（SoccerData 原生不含 UCL）：

```bash
mkdir -p ~/soccerdata/config
cat > ~/soccerdata/config/league_dict.json << 'EOF'
{
  "UEFA-Champions League": {
    "FBref": "UEFA Champions League",
    "season_code": "multi-year"
  }
}
EOF
```

**采集 UCL 正赛赛程 + 比分**：

```bash
fussball collect-fundamentals -l UCL -s 2024-2025 --source fbref  # 189 场（League phase → Final）
fussball collect-fundamentals -l UCL -s 2023-2024 --source fbref  # 125 场
fussball query -l UCL -s 2024-2025 -n 10
```

**赔率**：UCL 1X2 赔率需 The Odds API（`soccer_uefa_champs_league`），配置 `ODDS_API_KEY` 后：

```bash
fussball collect-odds -l UCL  # 仅即将开赛比赛，非历史
```

**覆盖范围与限制**：

| 联赛 | FBref 赛程 | FBref 比分 | 1X2 赔率 | xG | CLV 效果测 |
|------|:---:|:---:|:---:|:---:|:---:|
| UCL（正赛） | ✅ | ✅ | 需 API key | ✗（Understat 不覆盖） | 需 opening/closing 赔率 |
| UCL_Q（预选） | ✗ | ✗ | 预选期间或可用 | ✗ | 暂不能做 |

- **UCL_Q（预选）**：SoccerData/FBref 不覆盖预选赛（FBref 预选在独立页面，非主赛程表）；
  The Odds API 无独立预选 sport key。当前无可用数据源，需手动录入或 API key 验证。
- **CLV 效果测**：UCL 无历史 opening/closing 赔率（football-data.co.uk 已停维，Odds API 仅实时），
  暂不能做 walkforward CLV 效果测。有 API key 后可积累实时赔率逐步补全。

### 4. 模型选型（统一 walk-forward 对比）

一条命令对比 `poisson` / `dixoncoles` / `xgpoisson` 三个模型在同一赛季的 walk-forward 表现，
固化「选型用 Brier/CLV，不用 closing ROI」流程：

```bash
# 三模型对比（终端表 + JSON + Markdown）
fussball model-compare -l EPL -s 2024-2025 \
  --models poisson,dixoncoles,xgpoisson \
  --bet-period opening \
  -o reports/model_compare_epl_2425.json \
  --md reports/model_compare_epl_2425.md

# 仅对比两个模型
fussball model-compare -l EPL -s 2024-2025 --models poisson,dixoncoles

# 启用平局校准后对比
fussball model-compare -l EPL -s 2024-2025 --calibrate --calibrate-alpha 0.4
```

输出每行含：`model` / `brier` / `log_loss` / `opening_roi_pct` / `n_bets` /
`clv_mean` / `clv_positive_pct` / `n_matches` / `refits`，默认按 Brier 升序。

> **选型优先级：Brier → CLV → opening ROI**。
> 禁止用 closing ROI 选型（closing 已是高效市场，且含未来信息）。
> 内部对每个模型复用 `run_walkforward`，不重写回测引擎。

### 5. 赛前工作流（preview → AI 研判，默认零付费）

整理即将开赛场次 + 模型概率（+ 有则附庄家盘/edge）→ 输出 Markdown → 丢给 AI 研判。
不做自动下注、不做竞彩串关。

```bash
# 0. 免费拉赛程（未完赛 ft 为空）— 这条是默认，不需要付费 API
fussball collect-fundamentals -l EPL -s 2026-2027 --source fbref

# 0b.（可选）实时盘 edge：仅当你有免费/自备的 ODDS_API_KEY
# fussball collect-odds -l EPL

# 1. 生成赛前关注清单（未来 14 天 + Dixon-Coles）
fussball preview -l EPL --days 14 --model dixoncoles -o reports/preview_epl.md

# 2. 把 MD 丢给 AI 研判（AI 提示已在报告头）
```

输出每场含：模型胜平负 / 期望进球 λ / Top 3 比分；有盘口才附 edge。
- 无赔率标「无盘口」，不伪造 edge — **够 AI 研判用**
- UCL 等无前序 FD 时自动回退 `max_date` 拟合

> 无未来场时优先提示 **FBref 免费赛程**，不是逼你买 API。

### 6. 查询与统计

```bash
fussball query --league EPL --season 2024-2025 --limit 10
fussball stats
```

---

## 竞彩工作流（500.com → 推荐 → 浏览器）

国内竞彩足球在售场次采集 + SP 解析 + 推荐引擎 + HTTP 浏览界面。

```bash
# 1. 采集竞彩在售场次（500.com live + trade → SQLite）
fussball poll

# 2. 启动浏览服务
fussball serve --port 8901
# → 浏览器打开 http://127.0.0.1:8901

# 3. 页面内点「刷新采集」按钮或重复 fussball poll 更新 SP
```

**数据流**：`live.500.com`（赛程 + liveOddsList SP）+ `trade.500.com/jczq`（让球 + 元数据）
→ `jingcai_matches` + `jingcai_odds` 表 → 推荐引擎 → HTML 列表/详情页

**推荐规则**（纯 SP 驱动，v1）：
- 有 SPF SP → 朴素去水算隐含概率，取向最高方向；最高 < 40% → 观望
- 仅 RQSP → 让球玩法同理，附让球线标签
- 无 SP → 观望（禁止无 SP 冒充可购）

> ⚠️ 仅供研究参考，不构成投注建议。

**API**：
- `GET /api/jingcai/list` — 列表 JSON
- `GET /api/jingcai/{match_num}` — 单场详情 JSON
- `POST /api/poll` — 触发采集
- `GET /health` — 健康检查

---

## 项目结构

```
fussball-bund/
├── config/leagues.yaml          # 五大联赛+欧冠 数据源映射
├── src/fussball_bund/
│   ├── config.py                # 配置加载（env + yaml）
│   ├── models.py                # 数据模型（dataclass）
│   ├── collectors/              # 采集层
│   │   ├── base.py              # HTTP session + 重试基类
│   │   ├── football_data_uk.py  # ★ 历史赔率+战绩（核心，最稳定）
│   │   ├── odds_api.py          # 实时赔率（The Odds API）
│   │   ├── fundamentals.py      # 基本面（FBref/Understat/ClubElo）
│   │   └── jingcai_500.py       # 竞彩足球（500.com）
│   ├── storage/                 # 存储层
│   │   ├── db.py                # SQLite + WAL + upsert
│   │   └── schema.sql           # 表结构（含 jingcai_* 表）
│   ├── analysis/                # 分析层
│   │   ├── models.py            # Poisson / Dixon-Coles / xG
│   │   ├── walkforward.py       # 回测引擎
│   │   ├── model_compare.py     # 模型对比
│   │   ├── preview.py           # 赛前关注清单
│   │   └── jingcai_pick.py      # 竞彩推荐引擎
│   ├── serve.py                 # 竞彩 HTTP 服务（列表+详情+API）
│   └── cli.py                   # 命令行入口
└── data/                        # SQLite 数据库
```

## 数据库表

| 表 | 内容 |
|----|------|
| `matches` | 比赛基本信息：联赛、赛季、日期、对阵、半场/全场比分、结果 |
| `match_stats` | 比赛统计：射门、射正、犯规、角球、红黄牌 |
| `odds_1x2` | 1X2 赔率：庄家、开盘/收盘、主胜/平/客胜 |
| `odds_totals` | 大小球：庄家、2.5 线、大/小 |
| `odds_asian_handicap` | 亚洲盘：庄家、盘口、主/客 |
| `collection_log` | 采集日志，追踪数据新鲜度 |

## 分析层（Phase 2）

赔率去水、进球预测、价值投注识别、策略回测。

### 赔率 → 隐含概率（去水）

庄家赔率含 margin（水位），直接 `1/odds` 归一化会高估冷门概率。提供三种去水方法：

| 方法 | 说明 | 精度 |
|------|------|:----:|
| `shin` | Shin 方法（默认），考虑内幕投注者偏好偏差，封装 mberk/shin 库 | 最高 |
| `power` | Power 方法，Shin 的良好近似，纯实现无 scipy 依赖 | 高 |
| `naive` | 朴素归一化，仅按 margin 比例缩放 | 低 |

### Poisson 进球模型

基于历史比分估计每队攻防强度（主/客场 × 攻击/防守），用 Poisson 分布预测各比分概率，汇总为胜平负 + 大小球。

### 使用

```bash
# 预测比赛（默认用前一赛季拟合，避免数据泄露）
# --model poisson（基础）/ dixoncoles（低比分修正+时间衰减，预测更准）
fussball predict -l EPL -s 2024-2025 --home "Man City" --away "Arsenal" --model dixoncoles

# 识别价值投注（模型概率 vs 庄家收盘赔率）
fussball value -l EPL -s 2024-2025 --min-edge 0.05

# 回测策略盈亏（历史赛季拟合，目标赛季回测）
fussball backtest -l EPL -s 2024-2025 --min-edge 0.05

# 查看庄家水位
fussball margin -l EPL -s 2024-2025

# 生成竞猜分析简报（球队排名+预测准确率+价值投注+回测）
fussball report -l EPL -s 2024-2025 -o reports/epl_2425.md
```

### 回测说明

基础 Poisson 模型对比 Pinnacle 收盘赔率，默认 `min_edge=0.03` 下 ROI 为负——这符合市场效率假说
（Pinnacle 收盘赔率已是高效市场，简单模型难以稳定击败）。提高 `min_edge` 阈值可筛选更高质量信号。
改进方向：多赛季拟合、Dixon-Coles 低比分修正、xG 替代进球、加入近期状态/伤停因子。

---

## 已知局限

- **平局预测**：Poisson 类模型原始预测从不预测平局；启用 `--calibrate` 后混合庄家隐含平局概率可显著改善（命中率 +1.3%）
- **市场效率**：多赛季 Dixon-Coles + 校准后 ROI 已改善至 -2.3%（接近盈亏平衡），但仍为负

## 改进效果（Phase 4 实测）

| 配置 | 预测命中率 | 回测 ROI |
|------|:----------:|:--------:|
| 单赛季 Poisson | 41.3% | -7.8% |
| 单赛季 Dixon-Coles | — | -8.0% |
| 多赛季 Dixon-Coles | 51.6% | -2.8% |
| 多赛季 Dixon-Coles + 平局校准 | — | **-2.3%** |

## 后续路线

- [x] Phase 1: 稳定赔率+战绩采集（Football-Data.co.uk / The Odds API / SoccerData）
- [x] Phase 2: 赔率去水（Shin）、Poisson 进球模型、价值投注识别、策略回测
- [x] Phase 3: Dixon-Coles 修正（低比分τ+时间衰减）、竞猜分析简报生成
- [x] Phase 4: 多赛季加权拟合、升降级弱队先验、平局校准
- [x] Phase 5: xG 模型（Understat 数据链路 + 球队名自动映射）
- [ ] Phase 6: 多赛季 xG 采集、伤停/状态因子、实时赔率简报
