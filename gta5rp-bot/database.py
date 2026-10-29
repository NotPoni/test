"""Слой доступа к SQLite.

Одно соединение на процесс, WAL-режим и индексы. Все запросы сериализуются
через внутренний lock, поэтому несколько корутин не могут перемешать
операции одной транзакции.
"""
import asyncio
from contextlib import asynccontextmanager

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(
    guild_id INTEGER, key TEXT, value INTEGER, PRIMARY KEY(guild_id, key));

CREATE TABLE IF NOT EXISTS apps(
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, kind TEXT,
    channel_id INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', data TEXT,
    reviewer_id INTEGER DEFAULT 0, created INTEGER);

CREATE TABLE IF NOT EXISTS shifts(
    guild_id INTEGER, user_id INTEGER, start INTEGER, PRIMARY KEY(guild_id, user_id));
CREATE TABLE IF NOT EXISTS shift_totals(
    guild_id INTEGER, user_id INTEGER, seconds INTEGER DEFAULT 0, count INTEGER DEFAULT 0,
    PRIMARY KEY(guild_id, user_id));

CREATE TABLE IF NOT EXISTS warns(
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
    mod_id INTEGER, reason TEXT, ts INTEGER);

CREATE TABLE IF NOT EXISTS capt_menus(
    message_id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER, thread_id INTEGER DEFAULT 0,
    title TEXT, time_text TEXT, categories TEXT, roster TEXT DEFAULT '{}',
    reg_open INTEGER DEFAULT 1, status TEXT DEFAULT 'open', author_id INTEGER);
CREATE TABLE IF NOT EXISTS events_log(
    guild_id INTEGER, user_id INTEGER, kind TEXT, ts INTEGER);

CREATE TABLE IF NOT EXISTS afk(
    guild_id INTEGER, user_id INTEGER, kind TEXT, until INTEGER, reason TEXT,
    msg_id INTEGER DEFAULT 0, PRIMARY KEY(guild_id, user_id));

CREATE TABLE IF NOT EXISTS points(
    guild_id INTEGER, user_id INTEGER, points REAL DEFAULT 0, voice_seconds INTEGER DEFAULT 0,
    streak INTEGER DEFAULT 0, last_day TEXT DEFAULT '', PRIMARY KEY(guild_id, user_id));
CREATE TABLE IF NOT EXISTS points_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER,
    amount REAL, kind TEXT, reason TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS shop_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, name TEXT, price REAL,
    description TEXT, stock INTEGER DEFAULT -1);
CREATE TABLE IF NOT EXISTS purchases(
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, item_name TEXT,
    price REAL, message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'new', ts INTEGER);

CREATE TABLE IF NOT EXISTS cabinets(
    guild_id INTEGER, user_id INTEGER, channel_id INTEGER, static TEXT, server TEXT,
    video TEXT, info_msg INTEGER DEFAULT 0, PRIMARY KEY(guild_id, user_id));
CREATE TABLE IF NOT EXISTS cabinet_threads(
    channel_id INTEGER, name TEXT, thread_id INTEGER, PRIMARY KEY(channel_id, name));
CREATE TABLE IF NOT EXISTS cabinet_capts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, date TEXT,
    result TEXT, kills INTEGER, damage INTEGER, rollback TEXT DEFAULT '',
    message_id INTEGER DEFAULT 0, thread_id INTEGER DEFAULT 0);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_apps_guild_user ON apps(guild_id, user_id, status);
CREATE INDEX IF NOT EXISTS idx_apps_channel ON apps(channel_id);
CREATE INDEX IF NOT EXISTS idx_warns_guild_user ON warns(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_points_guild_points ON points(guild_id, points DESC);
CREATE INDEX IF NOT EXISTS idx_points_log_guild_user ON points_log(guild_id, user_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_guild_user ON events_log(guild_id, user_id, kind);
CREATE INDEX IF NOT EXISTS idx_cabinet_capts_guild_user ON cabinet_capts(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_cabinet_capts_channel ON cabinet_capts(message_id);
CREATE INDEX IF NOT EXISTS idx_afk_guild_kind ON afk(guild_id, kind);
CREATE INDEX IF NOT EXISTS idx_capt_menus_thread ON capt_menus(thread_id);
CREATE INDEX IF NOT EXISTS idx_shift_totals_guild ON shift_totals(guild_id, seconds DESC);
"""


class Database:
    def __init__(self, path: str = "data.db"):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        # isolation_level=None — autocommit: обычные запросы не оставляют открытую
        # транзакцию, поэтому явный BEGIN IMMEDIATE в transaction() не конфликтует.
        self.conn = await aiosqlite.connect(self.path, isolation_level=None)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(SCHEMA)
        await self.conn.executescript(INDEXES)
        await self.conn.commit()

    async def close(self):
        if self.conn is not None:
            try:
                await self.conn.commit()
                await self.conn.close()
            except Exception:  # соединение могло уже закрыться
                pass
            finally:
                self.conn = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("База данных не подключена: вызовите Database.connect()")
        return self.conn

    async def execute(self, query, *args):
        async with self._lock:
            cur = await self._require_conn().execute(query, args)
            await self.conn.commit()
            return cur

    async def fetchone(self, query, *args):
        async with self._lock:
            cur = await self._require_conn().execute(query, args)
            return await cur.fetchone()

    async def fetchall(self, query, *args):
        async with self._lock:
            cur = await self._require_conn().execute(query, args)
            return await cur.fetchall()

    async def commit(self):
        async with self._lock:
            await self._require_conn().commit()

    @asynccontextmanager
    async def transaction(self):
        """Транзакция: внутри работайте только с ``conn.execute``, не с ``db.execute``."""
        async with self._lock:
            conn = self._require_conn()
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                await conn.rollback()
                raise
            else:
                await conn.commit()

    async def get_setting(self, guild_id: int, key: str):
        row = await self.fetchone("SELECT value FROM settings WHERE guild_id=? AND key=?", guild_id, key)
        return row["value"] if row else None

    async def set_setting(self, guild_id: int, key: str, value: int):
        await self.execute(
            "INSERT INTO settings(guild_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value", guild_id, key, value)

    async def settings_like(self, guild_id: int, prefix: str) -> dict:
        rows = await self.fetchall(
            "SELECT key,value FROM settings WHERE guild_id=? AND key LIKE ? ORDER BY key",
            guild_id, prefix + "%")
        return {r["key"]: r["value"] for r in rows}
