# fussball-bund 实现指令：国内竞彩（参考 guess_you_like）

> **一句话**  
> 在 **`fussball-bund`** 里做出可 `serve` 的**国内竞彩工作台**；架构与交互 **学 `guess_you_like`**，代码实现落在 **本仓库**，**不要去改 guess_you_like 当交付物**。  
> **主数据对象**：**500.com 竞彩足球在售场次**（编号 + SP）。  
> **非目标**：五大联赛科研站、欧冠 FBref 产品、Odds API、世界杯专题、改 gyl 源码交差。

**修订说明（2026-08）**：此前「在 gyl 上收敛」的指令 **作废**。gyl 只作 **对照仓库**。

---

## 0. 关系说明

| 角色 | 路径 | 能不能动 |
|------|------|----------|
| **交付仓库** | `fussball-bund` | ✅ 实现、提交、验收都在这里 |
| **参考仓库** | `guess_you_like` | 📖 只读对照；允许抄结构/思路，**不要**以改 gyl 为交付 |
| 旧计划 `PRODUCT_WEB_PLAN` 多联赛 Web | — | ❌ 按本文竞彩范围覆盖 |

### 从 gyl 学什么（抄能力形态，不抄整仓 7k UI）

| 能力 | gyl 对照位置 | fussball-bund 目标 |
|------|--------------|-------------------|
| HTTP 服务 | `serve.py` + `ThreadingHTTPServer` | `fussball serve` → `:8765` |
| 轮询采集 | `poll_service.py` / `poll_500.py` / `jingcai_500.py` | `fussball poll` 或 serve 内嵌定时 |
| 竞彩编号+SP | `jingcai_500` / `jingcai_pick` | 本仓 `collectors/jingcai_500.py` + 推荐层 |
| 首页看板 | 当日/可售场列表 | `/` 只列竞彩在售 |
| 单场详情 | `/match/...` | 编号、SP、模型或规则观点、AI |
| CLI | `guess-you-like serve\|poll` | 扩 `fussball serve\|poll\|…` |

### 本仓可复用（次要）

- SQLite / `get_db`、CLI 风格、现有分析代码  
- **可选**：对「映射到有历史的联赛场」再调 Poisson/DC 作**参考概率**，**购买与展示主键仍是竞彩 SP**，无 SP 不进「可购」

### 明确禁止

- 把首页做成 EPL/UCL `preview` 科研页  
- 交付依赖改 `guess_you_like`  
- 自动购彩、打爆 500 的高频率爬

---

## 1. 目标架构（本仓）

```text
Browser :8765
    │
    ▼
fussball serve          ← 学 gyl serve 形态
    │
    ├─ storage (SQLite)  表：jingcai_matches / jingcai_odds_snapshots / …
    ├─ collectors/jingcai_*  ← 对照 gyl jingcai_500 + poll_500，重新接入本仓
    ├─ analysis/jingcai_pick  ← 对照 gyl jingcai_pick（可简化）
    ├─ web/ 最小 HTML        ← 勿整文件复制 gyl web_ui.py
    └─ (可选) AI brief
```

进程心智（与 gyl 对齐）：

```bash
fussball poll          # 拉 500 竞彩在售 + 写库
fussball serve         # HTTP + 看板
# 可选：serve --poll-interval 300 内嵌轮询
```

---

## 2. 数据模型（v1 最小）

实现前先定表（名称可微调，字段必须够展示）：

**jingcai_matches**

- `fixture_id`（500 分析 id，若有）
- `match_num`（如 `周一001`）**主键维度**
- `kickoff` / `league_name` / `home` / `away`
- `sell_status`（在售/截止等，能抓到就写）
- `updated_at`

**jingcai_odds**

- `match_num` 或 `fixture_id`
- `market`：`spf` | `rqspf`
- `line`（让球，spf 可 null）
- `sp_home` / `sp_draw` / `sp_away`
- `source`：`500`
- `ts`

**prediction / pick（可 JSON 列或别表）**

- `pick`：主/平/客/观望  
- `market`、`sp`、`reason`、`confidence`

队名与 bund 历史模型对齐：**后置可选**，v1 不阻塞「有列表有 SP」。

---

## 3. 页面与 API（v1）

### 页面

| 路径 | 内容 |
|------|------|
| `GET /` | **仅竞彩在售**表：编号、时间、对阵、SPF、让球、推荐 |
| `GET /match/{match_num或id}` | SP、推荐、可选参考概率、复制/AI |
| `GET /health` | ok、最后 poll 时间、在售场数 |

### API

| 方法 | 路径 |
|------|------|
| GET | `/api/health` |
| GET | `/api/jingcai/list` 当日/在售 |
| GET | `/api/jingcai/{id}` 详情 |
| POST | `/api/poll` 触发一轮采集（本机） |
| POST | `/api/ai/brief` 可选 |

---

## 4. 分阶段任务（在 fussball-bund 执行）

### J0 — 分支与基线（0.5 天）

```bash
cd /Users/popmart/Documents/python/fussball-bund
git checkout -b feature/jingcai-serve
# 对照阅读（只读）:
#   ../guess_you_like/serve.py          路由怎么挂
#   ../guess_you_like/poll_500.py
#   ../guess_you_like/jingcai_500.py
#   ../guess_you_like/jingcai_pick.py
#   ../guess_you_like/cli.py            serve/poll 入口
```

**验收**：能说清「gyl 从哪拉竞彩、怎么进页」；本仓尚无代码也可。

---

### J1 — 采集器：500 竞彩 → SQLite【P0，2–3 天】

**任务包：复制给开发**

```text
【任务 J1】fussball-bund 竞彩采集

目标：fussball poll-jingcai（或 fussball poll）一轮后，库里有编号+SP。

实现：
1. src/fussball_bund/collectors/jingcai_500.py
   - 对照 gyl 的 fetch 逻辑，用本仓 http 客户端/session 风格重写
   - 允许参考 gyl 解析逻辑，但放进 fussball 包结构，依赖写进 pyproject
2. schema 迁移：storage 增加 jingcai 表（或 schema.sql + 自动 migrate）
3. CLI：fussball poll（或 poll-jingcai）
4. 测试：tests/test_jingcai_parse.py 用 fixture HTML/JSON mock，不依赖外网 CI

约束：
- 不要 import guess_you_like 包（避免跨仓运行时依赖）；逻辑本仓自洽
- 默认请求频率保守；失败写 collection_log
- 不实现购彩下单

验收：
  fussball poll
  fussball query 或 sqlite3 可见 match_num + sp_*
  空赛程日：0 行且 exit 0
```

---

### J2 — HTTP 骨架 + 列表 API【P0，1–2 天】

```text
【任务 J2】fussball serve（学 gyl）

选型：stdlib ThreadingHTTPServer（与 gyl 一致，少依赖）

交付：
1. src/fussball_bund/serve.py（或 web/serve.py）
2. CLI：fussball serve --host 127.0.0.1 --port 8765
3. GET /health、/api/health、/api/jingcai/list
4. tests/test_serve.py 打 health（可 mock db）

验收：
  fussball serve &
  curl -s http://127.0.0.1:8765/api/jingcai/list | head
```

---

### J3 — Web：首页 + 单场【P0，2–3 天】

```text
【任务 J3】最小竞彩看板

1. GET /  表格在售场；无数据时提示「先 fussball poll 或点刷新采集」
2. GET /match/...  SP + 元数据
3. 按钮：触发 POST /api/poll（可选）
4. CSS：简洁可读；产品名 fussball-bund；勿做成 EPL 科研 dashboard
5. 不要整文件复制 gyl web_ui.py（体量与耦合）；只保主链路页

验收：
  浏览器打开 / 能看见编号场次（有 poll 数据时）
  无 gyl 进程、不依赖 gyl 代码路径
```

---

### J4 — 推荐层（学 jingcai_pick，本仓实现）【P0，1–2 天】

```text
【任务 J4】竞彩推荐

1. analysis/jingcai_pick.py（或 services/）
   - 有 SPF → 可出方向+SP；仅 RQ → 让球；无 SP → 观望
   - 外盘/模型概率仅作「参考分歧」标签，禁止无 SP 冒充可购
2. 列表/详情展示推荐
3. 单测 mock odds

（可选后置）用本仓历史模型对映射成功的队名出 p_home/draw/away，标「模型参考」
```

---

### J5 — AI 研判（可选）【P1，1–2 天】

```text
【任务 J5】
POST /api/ai/brief，上下文=编号+对阵+SP+推荐
无 key → 规则摘要
有 key → OpenAI 兼容 / DeepSeek（env）
对照 gyl 的 AI 入口形态即可，prompt 短、只谈竞彩
```

---

### J6 — README + 启动脚本【P1，0.5 天】

README **置顶**（替换任何「先 collect-history EPL」产品入口）：

```bash
cd fussball-bund && source .venv/bin/activate && pip install -e .
fussball poll
fussball serve --host 127.0.0.1 --port 8765
# 打开 http://127.0.0.1:8765
```

说明：数据来自 500 竞彩；欧盘历史 CLI 仅作高级/研究，不写进主路径。

---

## 5. 验收总清单（产品说「做完了」）

- [ ] 只在 **fussball-bund** 起服务即可用，**不启动** guess_you_like  
- [ ] `fussball poll` 写入竞彩编号与 SP  
- [ ] `fussball serve` 首页 **只围绕竞彩场次**  
- [ ] 推荐无 SP 不装可购  
- [ ] 文档不把五大联赛 collect 写成主流程  
- [ ] 竞彩解析单测不依赖外网  

---

## 6. 派工摘要（直接转发）

```text
【项目】fussball-bund — 国内竞彩工作台
【参考】只读 guess_you_like 的 serve / poll_500 / jingcai_500 / jingcai_pick
【交付】全部代码在 fussball-bund；禁止把 gyl 当交付仓库
【范围】仅 500 竞彩足球在售场；其它联赛产品线不碰
【顺序】J0 对照阅读 → J1 采集入库 → J2 serve API → J3 页面 → J4 推荐 → J5 AI → J6 README
【验收】poll + serve 浏览器可看当日竞彩；不依赖 gyl 进程
```

---

## 7. 风险

| 风险 | 处理 |
|------|------|
| 500 页面改版 | 解析单测 + 失败日志；对照 gyl 近期改动能跑再移植 |
| 误做成 bund 联赛站 | 首页 review：无 EPL 选择器就过 |
| 复制粘贴 gyl 半套路径错乱 | 禁止 `sys.path` 指到 gyl；必须本仓模块 |

---

## 8. 与错误方向的切割

| 错误理解 | 正确 |
|----------|------|
| 在 gyl 上改竞彩交差 | ❌ 交付在 fussball-bund |
| 学 gyl 做五大联赛 Web | ❌ 学 gyl 做**竞彩** Web |
| fussball 只搞模型不搞 HTTP | ❌ 必须有 serve，形态学 gyl |
