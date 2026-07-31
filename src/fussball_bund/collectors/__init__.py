"""采集器层入口。"""
from fussball_bund.collectors.base import BaseCollector
from fussball_bund.collectors.football_data_uk import FootballDataUKCollector
from fussball_bund.collectors.odds_api import OddsApiCollector
from fussball_bund.collectors.fundamentals import FundamentalsCollector

__all__ = [
    "BaseCollector",
    "FootballDataUKCollector",
    "OddsApiCollector",
    "FundamentalsCollector",
]
