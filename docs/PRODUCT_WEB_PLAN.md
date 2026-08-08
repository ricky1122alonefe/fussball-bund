# fussball-bund 产品化计划

> **⚠️ 现行指令（2026-08）**  
> - **交付仓库：`fussball-bund`**  
> - **只读参考：`guess_you_like`**（serve / poll / 竞彩形态）  
> - **只做国内竞彩场次**，不做五大联赛科研 Web  
> - **完整派工**：[docs/JINGCAI_IMPLEMENTATION_ORDERS.md](./JINGCAI_IMPLEMENTATION_ORDERS.md)  
> 下文「多联赛免费路径 Web」**作废**，仅存档。

---

# fussball-bund 产品化计划（存档 · 已作废）

> **读者**：实现 / 前端 / 联调人员  
> **目标**：在 **fussball-bund** 现有数据采集 + 量化模型基础上，交付类似 [guess_you_like](../../guess_you_like/) 的 **HTTP 服务 + Web 看板 + AI 研判**，默认 **零付费 API**，能力与可信度要 **超过世界杯版 guess_you_like**。  
> **原则**：分析引擎继续用 fussball-bund；HTTP/UI 形态学 gyl；**禁止再做成「只有 CLI」**。  
> **版本**：v1.0 · 2026-08 · **已作废**

---

## 0. 背景与对标结论

### 0.1 guess_you_like（世界杯/竞彩版）有什么

| 能力 | 实现要点 |
|------|----------|
| 启动形态 | `guess-you-like serve` → `http://127.0.0.1:8765` |
| 后台采集 | `poll` 轮询 500.com → Postgres |
| Web | 首页看板、单场详情、当日推荐、世界杯盘路、设置页 |
| AI | 服务内嵌 DeepSeek 等 + SSE 对话 |
| 体量 | `serve.py` ~2k 行 + `web_ui.py` ~7k 行 |

**启动心智**：打开浏览器就能用。

### 0.2 fussball-bund 现在有什么

| 能力 | 状态 |
|------|:----:|
| 五大联赛历史 + FD 开收盘 | ✅ |
| 欧冠正赛 FBref 赛程/比分 | ✅ |
| Poisson / Dixon-Coles / xG + walk-forward 评估 | ✅（比 gyl 更「学术可复现」） |
| preview / report MD → 外带 AI | ✅ 半成品 |
| **HTTP / 浏览器入口** | ❌ |
| 竞彩 500 盘口 / 串关产品 | ❌（可后补，非 v1 必做） |

**启动心智**：现在仍是 CLI，用户会觉得「怎么启动」。

### 0.3 「比原来世界杯项目更强」的定义（验收时按此打分）

必须 **同时** 满足：

| # | 更强点 | 相对 gyl |
|---|--------|----------|
| S1 | **可解释评估**：Brier / CLV / walk-forward，选型有协议 | gyl 偏展示推荐，缺统一反泄漏协议 |
| S2 | **联赛纵深**：五大联赛多赛季 + 英超 xG；非只 WC 窗口 | gyl 世界杯向 |
| S3 | **零付费默认路径**：FD + FBref 赛程 + 本地模型；Odds API 可选 | gyl 依赖抓盘稳定性 |
| S4 | **同级 UX**：`serve` + 浏览器首页 + 单场页 + 赛前清单 | 必须达到「能打开网页」 |
| S5 | **AI 研判内嵌**：服务内一键生成可读结论（可选 LLM key）；无 key 时用规则简报 | gyl 有 AI，我们要「模型数字 + AI」一体 |
| S6 | **诚实边界**：无 edge 时不写死盈利、预选标注不可做 | 产品可信度 |

非目标（v1 不做）：全面复刻 7k 行 UI、竞彩串关、自动跟注、打赢 Pinnacle 承诺。

---

## 1. 目标架构

```text
                    ┌──────────────────────────────┐
   Browser          │  Web UI (简洁看板，非 7k 行)   │
   :8765            └──────────────┬───────────────┘
                                   │ JSON / HTML
                    ┌──────────────▼───────────────┐
                    │  serve.py  HTTP 门面          │
                    │  (stdlib ThreadingHTTPServer  │
                    │   或 FastAPI，二选一见任务 W1) │
                    └──────────────┬───────────────┘
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
   analysis/*               collectors/*              storage/*
   predict/preview/         FD + FBref schedule         SQLite
   walkforward/report       (免费)；poll 可选           team_map/xG
           │
           ▼
   AI bridge (可选 DEEPSEEK/OPENAI 兼容；无 key 则规则摘要)
```

**进程模型（对齐 gyl 心智）：**

| 进程 | 职责 | 命令（目标） |
|------|------|----------------|
| **web** | HTTP + 页面 | `fussball serve --host 127.0.0.1 --port 8765` |
| **scheduler（可选）** | 定时 FBref 赛程 / collect-history | `fussball schedule` 或 serve 内 `--run-on-start` |
| **cli** | 保留现有科研入口 | `fussball predict/preview/...` 不删 |

---

## 2. 页面与 API 清单（v1 必做）

### 2.1 页面（HTML，移动端基本可读）

| 路径 | 名称 | 内容 |
|------|------|------|
| `GET /` | 首页 | 联赛选择、未来 N 天场次表、模型标签、链到详情；链接「如何零付费使用」 |
| `GET /preview` | 赛前清单 | 等价 `fussball preview` 的 HTML 渲染 |
| `GET /match?league=&home=&away=&date=` | 单场 | 模型 1X2 / λ / top 比分 / 有则显示赔率与 edge；「复制给 AI」按钮 |
| `GET /report` | 复盘 | 选联赛赛季 → report 表格摘要 |
| `GET /models` | 模型对比 | walk-forward / model-compare 结果表（缓存 JSON） |
| `GET /health` | 健康检查 | `{ok, version, db, leagues}` |

可选 v1.1：`/settings`（默认联赛、模型、是否启用 AI）。

### 2.2 JSON API（给前端 / 自动化 / 外接 AI）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康 |
| GET | `/api/stats` | 表行数与联赛分布 |
| GET | `/api/fixtures?league=&days=` | 未来场列表 |
| GET | `/api/preview?league=&days=&model=` | preview 结构化 JSON |
| GET | `/api/predict?league=&season=&home=&away=&model=` | 单场预测 |
| GET | `/api/report?league=&season=&model=` | 报告摘要 JSON |
| POST | `/api/ai/brief` | body: preview/match 上下文 → 返回 AI 研判文本（无 key 时规则模板） |
| POST | `/api/collect/fbref` | body: league, season → 触发 FBref 赛程（异步或同步超时保护） |

**认证 v1**：默认仅监听 `127.0.0.1`；不设公网鉴权。

---

## 3. 分阶段实施（按顺序，禁止跳过门面做花活）

### Phase W0 — 对齐与冻结（0.5 天）

**负责人**：产品/主程  

1. 冻结分支：建议从当前 main 切 `feature/web-serve`  
2. 先 **commit 现有 CLI 半成品**（preview、match_xg、UCL、免费路径等），避免和 Web 搅在一个 diff  
3. 通读本文 + `guess_you_like/serve.py` 前 100 行 + `cli.py`（gyl）心智  
4. 确认默认端口 **8765**（与 gyl 习惯一致，可配置）

**验收**：仓库工作区 clean 或明确两个 PR：`cli-finalize` / `web-serve`。

---

### Phase W1 — HTTP 骨架 + /health + /api/stats（1–2 天）【P0】

**任务 ID：W1**

```text
【任务 W1】fussball serve HTTP 骨架

目标：浏览器打开 http://127.0.0.1:8765/health 有 JSON。

选型（二选一，推荐 A 更快对标 gyl）：
  A) 标准库 ThreadingHTTPServer + BaseHTTPRequestHandler（学 gyl serve.py）
  B) FastAPI + uvicorn（更干净；依赖 uvicorn）

交付：
1. src/fussball_bund/serve.py 或 web/serve.py
2. CLI：fussball serve --host 127.0.0.1 --port 8765
3. GET /health  → {"ok":true,"version":"0.x","db_path":"..."}
4. GET /api/stats → 与 fussball stats 同构数字
5. 未匹配路径 404 HTML 简页
6. 测试：tests/test_serve.py 用 http.client 或 httpx 打 /health（无需真起浏览器）
7. README：【Web 启动】一节放在最前

约束：
- 不写大 UI
- 不引入购买 Odds API
- 绑定默认 127.0.0.1

验收：
  pytest -q
  fussball serve --port 8765 &
  curl -s http://127.0.0.1:8765/api/health | head
  curl -s http://127.0.0.1:8765/api/stats | head
```

---

### Phase W2 — 核心 API：fixtures / predict / preview（2–3 天）【P0】

**任务 ID：W2**

```text
【任务 W2】核心 JSON API

复用：
  analysis.preview.generate_preview
  analysis 各 Model.predict
  storage.db

接口见本文 §2.2 中 fixtures / predict / preview
（predict 查询参数 home/away 用 football-data 短名，与 CLI 一致）

规则：
- preview 无未来场：HTTP 200 + warnings[]（同 CLI 免费 FBref 提示），禁止 500
- model 非法：400
- 内部异常：500 + 日志，body 不堆栈明文给用户（开发模式可开）

可选缓存：
- 同 league+model+days 预览结果 cache 60s（内存 dict），避免每次重 fit 卡死页面

验收：
  curl "http://127.0.0.1:8765/api/preview?league=EPL&days=14&model=dixoncoles"
  curl "http://127.0.0.1:8765/api/predict?league=EPL&season=2025-2026&home=Man%20City&away=Arsenal&model=dixoncoles"
  有历史数据时 predict 返回 p_home/p_draw/p_away
```

---

### Phase W3 — Web 首页 + 赛前页 + 单场页（3–4 天）【P0】

**任务 ID：W3**

```text
【任务 W3】最小可用 Web UI（比 gyl 简洁，但不缺主链路）

不要复用 gyl 的 7k web_ui；新建 src/fussball_bund/web/ 模板或服务端拼 HTML：

1. GET /  
   - 选择联赛（EPL/五大/UCL）
   - 输入 days（默认 7）
   - 模型单选
   - 按钮「刷新赛前清单」→ 渲染表格或跳转 /preview?...
   - 页脚：零付费说明 + 风险声明

2. GET /preview?league=&days=&model=
   - 渲染 generate_preview 结果
   - 「复制全文给 AI」按钮（textarea + clipboard）
   - 无场次：显示 FBref 采集指引 + 可选「触发采集」链到 W4

3. GET /match?...  
   - 单场模型输出美化
   - 若有 odds 展示 edge；无则「无盘口（零付费模式）」

4. 基础 CSS：system-ui、可读对比度、max-width 960；移动端可竖滑即可

设计约束（强约束）：
- 不要紫白 AI 默认风；清爽体育数据风（深字浅底或简洁暗色二选一）
- 首页第一视口：产品名「fussball-bund」+ 一句「联赛 · 可复现模型 · AI 研判」+ 主操作「看本周赛程」
- 禁止一屏堆统计卡片仪表盘

验收：
  人工浏览器打开 / 与 /preview
  无 API key 也能出页面
  与 GYL 同等「打开浏览器就能用」的体感
```

---

### Phase W4 — 采集触发 + 免费赛程一键（1–2 天）【P0】

**任务 ID：W4**

```text
【任务 W4】网页触发「免费更新赛程」

1. POST /api/collect/fbref  { "league":"EPL", "season":"2026-2027" }
   - 调用 FundamentalsCollector.collect_fbref_schedule
   - 同步：超时 120s；或后台线程 + GET /api/collect/status/{job_id}
2. UI：首页按钮「更新 FBref 赛程（免费）」
3. 写入后自动刷新 preview 区
4. 日志进 collection_log

约束：不在 UI 强推 Odds API；文案写「可选」

验收：
  点按钮或 curl POST 后 matches 中 future 场增加（若 FBref 可访问）
  FBref 失败：友好错误「网络/反爬，请稍后重试」
```

---

### Phase W5 — 模型对比页 + 报告页（1–2 天）【P1】

**任务 ID：W5**

```text
【任务 W5】比 gyl 更强的「可复现」展示

1. GET /models 与 /api/models/compare
   - 复用 run_model_compare 或 model_compare；结果缓存到 data/cache/ 或 reports/
   - 注明：Brier 优先；禁止用 closing ROI 选型
2. GET /report?league=&season=
   - 摘要表格 + 下载 MD 链接
3. 首页入口：「模型可信度」

验收：
  EPL 2024-2025 对比表可显示（可预计算缓存加速首屏）
```

---

### Phase W6 — AI 研判桥（2 天）【P1】

**任务 ID：W6**

```text
【任务 W6】内嵌 AI 研判（可选密钥，无密钥降级）

目标：浏览器内点「AI 研判」得到一段中文结论，不必切换别的工具。

1. 环境变量（可选）：
   OPENAI_API_KEY 或 DEEPSEEK_API_KEY
   OPENAI_BASE_URL（兼容网关）
2. POST /api/ai/brief
   输入：场次列表 + 模型概率（来自 preview JSON）
   输出：markdown 研判（倾向/风险/需关注信息/「勿迷信 edge」）
3. 无 key：用服务端模板规则摘要（基于概率与强弱差）仍返回 200
4. UI：预览页「生成 AI 研判」按钮
5. 禁止把完整系统提示/密钥打进前端

参考 gyl：deepseek_client / ai_prompt 思路，但 prompt 接「可复现概率」上下文，不要只编故事。

验收：
  无 key：仍有规则研判
  有 key：能返回 LLM 文本（实现者自测，不必 CI 调外网）
```

---

### Phase W7 — 体验增强（平行，2–3 天）【P2】

**任务 ID：W7**（可砍）

- 多联赛 tab（EPL | 西甲 | 欧冠）  
- 简单 `scripts/run_local.sh`：serve 前台一行  
- Docker：可选仅 web + SQLite 挂载（不必上 Postgres，这就是比 gyl **更轻**之一）  
- 性能：DC fit 缓存按 league+as_of_date  

---

## 4. 明确「更强」落地检查表（产品评审用）

上线 v1 自评：

- [ ] **S4** 打开 `http://127.0.0.1:8765` 能当工作台  
- [ ] **S3** 文档与 UI 写清：无需买 Odds API  
- [ ] **S1** 有 /models 展示 Brier/CLV，并有协议链接 `docs/BACKTEST_PROTOCOL.md`  
- [ ] **S2** 至少 EPL + 另一五大联赛 + UCL 查询可用  
- [ ] **S5** AI 按钮存在（可无 key）  
- [ ] **S6** 页脚风险声明 + 预选 UCL_Q 标注不可用  

对比 gyl 必须能说出口的三句：

1. 「我们有 walk-forward 概率评估，不只是荐号。」  
2. 「五大联赛+欧冠正赛数据纵深，不是只做一个杯赛窗口。」  
3. 「默认零付费；服务形态一样是浏览器打开就用。」  

---

## 5. 给实现人员的统一约束

1. **不破坏 CLI**：所有新能力优先函数化，CLI/HTTP 双入口  
2. **不默认付费 API**  
3. **fit 可能慢**：preview/API 层必须有超时与「分析中」反馈（UI spinner 或同步提示「首次 10–30s」）  
4. **队名**：继续 football-data 短名；FBref 写入已有 resolve_to_canonical  
5. **安全**：默认 bind 127.0.0.1；禁止打开公网无鉴权  
6. **提交粒度**：W1→W2→W3 各至少一个 PR，便于回滚  
7. **禁止** 把 gyl 的 `web_ui.py` 整文件拷贝（许可证/体量/耦合都不可控）；只学结构  

---

## 6. 建议排期（1 名全职）

| 周 | 交付 | 可对外演示 |
|----|------|------------|
| W1 | W0+W1+W2 | curl API |
| W2 | W3+W4 | **浏览器完整演示**（对上 gyl 心智） |
| W3 | W5+W6 | 「比 gyl 更强」评审材料齐 |

2 人并行：A=后端 API，B=HTML/CSS；W3 会师。

---

## 7. 启动命令（目标态，写进 README 置顶）

```bash
cd fussball-bund
source .venv/bin/activate
pip install -e .

# 一次性：有历史可跳过
# fussball collect-history -l EPL -s 2025-2026
# fussball collect-fundamentals -l EPL -s 2026-2027 --source fbref

fussball serve --host 127.0.0.1 --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

---

## 8. 第一个派工包（立刻复制）

### 包 A — 只做 W1（本周先让「像服务」）

见上文 **任务 W1** 全文。

### 包 B — W1 通过后立刻做 W2+W3

见 **任务 W2、W3**。

### 包 C — 产品验收清单

见 **§4**；未勾满不算「超过世界杯项目」上线。

---

## 9. 风险

| 风险 | 缓解 |
|------|------|
| Dixon-Coles 首屏过慢 | 缓存 fitted 模型；首页默认 poisson 可选 |
| FBref 反爬 | 失败文案 + 保留 CLI 手工；缓存 soccerdata |
| UI 做大失控 | 硬限 v1 仅 4 个页面 |
| 与 gyl 抢同一端口 | 可改 8766；文档写明 |

---

## 10. 一句话目标

> **把 fussball-bund 从「科研 CLI」升级成「浏览器打开即用的联赛分析台」：骨架学 guess_you_like，内核用可复现模型与免费数据，交付体验与可信度全面压过世界杯专题站。**

---

## 附录：参考代码路径

| 用途 | 路径 |
|------|------|
| gyl HTTP 心智 | `guess_you_like/serve.py`, `cli.py`, `scripts/run_local.sh` |
| gyl 启动 | `docker-compose.yml` web 服务 |
| 本项目模型/preview | `src/fussball_bund/analysis/*`, `cli.py` |
| 免费赛程 | `collectors/fundamentals.py` FBref |
| 评估协议 | `docs/BACKTEST_PROTOCOL.md` |
