"""fussball-bund: 五大联赛与欧冠足彩数据分析项目。

核心数据源（按可信度/稳定性排序）：
    1. Football-Data.co.uk   历史赔率+战绩 CSV（学术金标准，最稳定）
    2. The Odds API          实时/即将开赛赔率（官方 REST API）
    3. FBref (SoccerData)    比赛统计/xG（StatsBomb 级权威）
    4. Understat (SoccerData) xG/xA（权威）
    5. ClubElo (SoccerData)  球队 Elo 评级
可选: OddsHarvester          oddsportal 实时赔率（Playwright，稳定性低）
"""

__version__ = "0.1.0"
