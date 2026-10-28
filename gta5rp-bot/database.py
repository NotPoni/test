import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(
    guild_id INTEGER, key TEXT, value INTEGER, PRIMARY KEY(guild_id, key));
CREATE TABLE IF NOT EXISTS applications(
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
    message_id INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', data TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS shifts(
    guild_id INTEGER, user_id INTEGER, start INTEGER, PRIMARY KEY(guild_id, user_id));
CREATE TABLE IF NOT EXISTS shift_totals(
    guild_id INTEGER, user_id INTEGER, seconds INTEGER DEFAULT 0, count INTEGER DEFAULT 0,
    PRIMARY KEY(guild_id, user_id));
CREATE TABLE IF NOT EXISTS warns(
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
    mod_id INTEGER, reason TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS events(
    message_id INTEGER PRIMARY KEY, guild_id INTEGER, author_id INTEGER, title TEXT,
    description TEXT, starts TEXT, slots INTEGER, members TEXT DEFAULT '[]');
"""


class Database:
    def __init__(self, path: str = "data.db"):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def execute(self, query, *args):
        cur = await self.conn.execute(query, args)
        await self.conn.commit()
        return cur

    async def fetchone(self, query, *args):
        cur = await self.conn.execute(query, args)
        return await cur.fetchone()

    async def fetchall(self, query, *args):
        cur = await self.conn.execute(query, args)
        return await cur.fetchall()

    async def get_setting(self, guild_id: int, key: str):
        row = await self.fetchone(
            "SELECT value FROM settings WHERE guild_id=? AND key=?", guild_id, key)
        return row["value"] if row else None

    async def set_setting(self, guild_id: int, key: str, value: int):
        await self.execute(
            "INSERT INTO settings(guild_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
            guild_id, key, value)
