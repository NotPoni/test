import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS whitelist(user_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS protection(event TEXT PRIMARY KEY, action TEXT NOT NULL, limit_n INTEGER NOT NULL, ban_hours INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS protection_log(user_id INTEGER, event TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS temp_bans(user_id INTEGER PRIMARY KEY, until REAL);
CREATE TABLE IF NOT EXISTS app_questions(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cooldowns(user_id INTEGER, kind TEXT, until REAL, PRIMARY KEY(user_id, kind));
CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, target TEXT, answers TEXT, status TEXT DEFAULT 'pending', reviewer INTEGER, created REAL, message_id INTEGER);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, kind TEXT DEFAULT 'mp', channel_id INTEGER, message_id INTEGER, is_open INTEGER DEFAULT 1, created_by INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS event_regs(event_id INTEGER, user_id INTEGER, PRIMARY KEY(event_id, user_id));
CREATE TABLE IF NOT EXISTS voice_days(user_id INTEGER, day TEXT, seconds INTEGER, PRIMARY KEY(user_id, day));
CREATE TABLE IF NOT EXISTS voice_sessions(user_id INTEGER PRIMARY KEY, joined REAL);
CREATE TABLE IF NOT EXISTS warns(user_id INTEGER PRIMARY KEY, level INTEGER, reason TEXT, issued_by INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS points(user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS shop_items(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price INTEGER, role_id INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS roulette_rewards(id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, points INTEGER, weight INTEGER);
CREATE TABLE IF NOT EXISTS roulette_history(user_id INTEGER, label TEXT, points INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS portfolios(user_id INTEGER PRIMARY KEY, url TEXT, created REAL);
CREATE TABLE IF NOT EXISTS vacations(user_id INTEGER PRIMARY KEY, until REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS afk(user_id INTEGER PRIMARY KEY, since REAL);
CREATE TABLE IF NOT EXISTS rollbacks(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, url TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS staff_actions(user_id INTEGER, role_kind TEXT, action TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS sign_lists(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, message_id INTEGER UNIQUE, kind TEXT, title TEXT, image_url TEXT, limit_n INTEGER, starts_at REAL, author_id INTEGER, author_name TEXT, data TEXT, closed INTEGER DEFAULT 0, created REAL);
"""


class DB:
    def __init__(self, path):
        self.path = path
        self.conn = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def run(self, sql, *args):
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur

    async def one(self, sql, *args):
        cur = await self.conn.execute(sql, args)
        return await cur.fetchone()

    async def all(self, sql, *args):
        cur = await self.conn.execute(sql, args)
        return await cur.fetchall()

    async def get(self, key, default=None):
        r = await self.one("SELECT value FROM settings WHERE key=?", key)
        return r["value"] if r else default

    async def put(self, key, value):
        await self.run(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            key, str(value),
        )

    async def add_points(self, uid, delta):
        await self.run(
            "INSERT INTO points(user_id,balance) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET balance=MAX(0,balance+?)",
            uid, max(0, delta), delta,
        )

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None
