# 回测协议（Backtest Protocol）

本协议定义 fussball-bund 模型评估的可信标准，**杜绝数据泄露与未来信息污染**。

## 核心原则

1. **训练数据严格反泄漏**：预测比赛 t 时，训练数据只允许 `match_date < t` 的比赛（跨赛季累积），绝不包含 t 及之后的任何比赛。
2. **下注用开盘赔率（opening）**：默认 `--bet-period opening`。开盘赔率在开赛前发布，有可击败空间；收盘赔率（closing）已吸收全部公开信息，是高效市场。
3. **CLV 对齐收盘**：用 `closing` 赔率计算 CLV（Closing Line Value），衡量下注时是否 beat the closing line——业界公认比 ROI 更可靠的价值先行指标（不受单场结果方差影响，样本需求小）。
4. **禁止用 closing ROI 作为模型选型唯一依据**：closing 赔率含未来信息（开盘→收盘的走势已反映赛果预期），用其 ROI 选型会过拟合市场效率，不代表模型真实预测能力。

## 指标优先级

| 优先级 | 指标 | 说明 | 方向 |
|:------:|------|------|------|
| 1 | CLV | `bet_odds/closing_odds - 1`，不受结果方差影响 | 越高越好 |
| 2 | Brier | 概率均方误差（1X2，范围 [0,2]） | 越低越好 |
| 3 | log-loss | 概率对数损失 | 越低越好 |
| 4 | opening ROI | 开盘赔率结算盈亏（受方差，需大样本） | 越高越好 |

## Walk-forward 流程

```
fussball walkforward -l EPL -s 2024-2025 --model dixoncoles --bet-period opening -o reports/wf_epl.json
```

- 按比赛日推进，每个比赛日 d：
  - 训练数据 = `SELECT ... WHERE league_code=? AND match_date < d`（跨赛季累积，严格反泄漏）
  - 用训练好的模型预测当日所有比赛
  - 记录每场：预测概率、实际结果、opening odds、closing odds
- 重训频率：按比赛日（同日共享模型），约 100 次/赛季
- 赛季初历史数据不足的比赛日会被跳过（不外推）

## Legacy 协议（复现旧基线）

`--protocol legacy`（value/backtest）或 `--bet-period closing` 等价复现 Phase 1-5 的 closing-based 回测，**仅供历史对比，不得用于选型**。

## 验收命令

```bash
pytest -q                                                              # 测试套件
fussball walkforward -l EPL -s 2024-2025 --model dixoncoles \
    --bet-period opening -o reports/wf_epl.json                       # walk-forward 评估
fussball stats                                                        # 数据完整性
```

## 反泄漏测试（必须存在）

`tests/test_antileak.py` 锁死两条不变式：
1. `model.fit(league, max_date=d)` 的训练数据不含 `match_date >= d` 的比赛
2. `run_walkforward` 端到端跑通且每个预测比赛日的训练数据严格在其之前
