"""SQLite 存储管理：建表、upsert、查询。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fussball_bund.config import settings

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """轻量 SQLite 封装，开启外键与 WAL 提升并发与一致性。"""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or settings.db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn() as conn:
            conn.executescript(sql)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- 通用 upsert ----------
    def upsert(self, table: str, data: dict[str, Any], conflict: list[str]) -> int | None:
        cols = list(data.keys())
        placeholders = ",".join("?" * len(cols))
        col_str = ",".join(cols)
        update_str = ",".join(f"{c}=excluded.{c}" for c in cols if c not in conflict)
        sql = (
            f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) "
            f"ON CONFLICT({','.join(conflict)}) DO UPDATE SET {update_str} "
            f"RETURNING id"
        )
        with self._conn() as conn:
            row = conn.execute(sql, [data[c] for c in cols]).fetchone()
            conn.commit()
            return row["id"] if row else None

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(sql, params).fetchall()

    # ---------- 业务 upsert ----------
    def upsert_match(self, m: dict[str, Any]) -> int | None:
        return self.upsert(
            "matches",
            m,
            ["league_code", "season", "match_date", "home_team", "away_team"],
        )

    def upsert_stats(self, s: dict[str, Any]) -> None:
        self.upsert("match_stats", s, ["match_id"])

    def upsert_odds_1x2(self, o: dict[str, Any]) -> None:
        self.upsert("odds_1x2", o, ["match_id", "bookmaker", "period"])

    def log_collection(
        self, collector: str, status: str, detail: str = "",
        league_code: str | None = None, season: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO collection_log(collector, league_code, season, status, detail) "
                "VALUES (?,?,?,?,?)",
                (collector, league_code, season, status, detail),
            )
            conn.commit()


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
