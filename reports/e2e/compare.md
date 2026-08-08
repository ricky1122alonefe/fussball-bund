# 模型对比报告 EPL 2024-2025

- 下注周期: `opening`  庄家: `Pinnacle`  min_edge: `0.03`
- 校准: `False`
- 排序: `brier` 升序（越低越好）

| 模型 | Brier | log-loss | openROI% | n_bets | CLV | CLV+% | n_match | refits |
|------|------:|---------:|---------:|-------:|----:|------:|--------:|-------:|
| dixoncoles | 0.5878 | 0.9833 | -2.7% | 281 | -0.71% | 46% | 380 | 109 |
| poisson | 0.6020 | 1.0097 | -10.4% | 325 | -0.83% | 44% | 380 | 109 |

> 选型优先级: Brier → CLV → opening ROI；禁止用 closing ROI 选型