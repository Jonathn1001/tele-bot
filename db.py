import ssl

import asyncpg
from buffer import Message


async def init_pool(dsn: str, ca_cert: str = "") -> asyncpg.Pool:
    if ca_cert:
        # Verifies the server certificate and hostname (verify-full);
        # plain ssl="require" encrypts but is open to MITM.
        ssl_ctx: ssl.SSLContext | str = ssl.create_default_context(cafile=ca_cert)
    else:
        ssl_ctx = "require"
    pool = await asyncpg.create_pool(dsn, ssl=ssl_ctx)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         SERIAL PRIMARY KEY,
                channel    TEXT        NOT NULL,
                sender     TEXT,
                text       TEXT        NOT NULL,
                date       TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    return pool


async def insert_message(pool: asyncpg.Pool, msg: Message) -> None:
    from datetime import timezone
    date = msg.date.replace(tzinfo=timezone.utc) if msg.date.tzinfo is None else msg.date
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (channel, sender, text, date) VALUES ($1, $2, $3, $4)",
            msg.channel, msg.sender, msg.text, date,
        )


async def prune_old_messages(pool: asyncpg.Pool, retention_days: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM messages WHERE created_at < NOW() - make_interval(days => $1)",
            retention_days,
        )
