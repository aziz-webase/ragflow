"""
PostgreSQL qatlami (asyncpg + connection pool).

Model:
  tenant                     -> ro'yxatdan o'tgan tashkilot
  (tenant, collection)       -> ragflow dataset (hujjat konteyneri)
  agent                      -> tanlangan collectionlar + system prompt
                                (= ragflow chat assistant + metadata)
  (agent_id, user_id)        -> ragflow session_id
  messages                   -> har bir (agent, user) savol-javob tarixi
"""
import json
from typing import Any, Optional

import asyncpg

from config import get_settings

settings = get_settings()

_pool: Optional[asyncpg.Pool] = None


async def connect() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    await init_db()


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _require_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool yaratilmagan — connect() chaqirilmagan")
    return _pool


async def init_db() -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_name TEXT PRIMARY KEY,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS collections (
                id              BIGSERIAL PRIMARY KEY,
                tenant_name     TEXT NOT NULL REFERENCES tenants(tenant_name) ON DELETE CASCADE,
                collection_name TEXT NOT NULL,
                dataset_id      TEXT NOT NULL,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_name, collection_name)
            );

            CREATE TABLE IF NOT EXISTS agents (
                agent_id      TEXT PRIMARY KEY,
                tenant_name   TEXT NOT NULL REFERENCES tenants(tenant_name) ON DELETE CASCADE,
                agent_name    TEXT NOT NULL,
                system_prompt TEXT,
                chat_id       TEXT,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_name, agent_name)
            );

            CREATE TABLE IF NOT EXISTS agent_collections (
                agent_id        TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
                collection_name TEXT NOT NULL,
                PRIMARY KEY (agent_id, collection_name)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                agent_id   TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
                user_id    TEXT NOT NULL,
                session_id TEXT NOT NULL,
                chat_id    TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (agent_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         BIGSERIAL PRIMARY KEY,
                agent_id   TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                reference  JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE INDEX IF NOT EXISTS idx_messages_lookup
                ON messages (agent_id, user_id, created_at);
            """
        )


# ---------- tenants ----------

async def ensure_tenant(tenant_name: str) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tenants (tenant_name) VALUES ($1) ON CONFLICT DO NOTHING",
            tenant_name,
        )


async def tenant_exists(tenant_name: str) -> bool:
    pool = _require_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM tenants WHERE tenant_name = $1", tenant_name)
        return row is not None


# ---------- collections ----------

async def get_collection(tenant_name: str, collection_name: str) -> Optional[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM collections WHERE tenant_name = $1 AND collection_name = $2",
            tenant_name,
            collection_name,
        )


async def create_collection(
    tenant_name: str, collection_name: str, dataset_id: str
) -> asyncpg.Record:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO collections (tenant_name, collection_name, dataset_id)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            tenant_name,
            collection_name,
            dataset_id,
        )


async def list_collections(tenant_name: str) -> list[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM collections WHERE tenant_name = $1 ORDER BY created_at",
            tenant_name,
        )


# ---------- agents ----------

async def create_agent(
    agent_id: str,
    tenant_name: str,
    agent_name: str,
    system_prompt: Optional[str],
    collections: list[str],
) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO agents (agent_id, tenant_name, agent_name, system_prompt)
                VALUES ($1, $2, $3, $4)
                """,
                agent_id,
                tenant_name,
                agent_name,
                system_prompt,
            )
            await conn.executemany(
                "INSERT INTO agent_collections (agent_id, collection_name) VALUES ($1, $2)",
                [(agent_id, c) for c in collections],
            )


async def get_agent(agent_id: str) -> Optional[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM agents WHERE agent_id = $1", agent_id)


async def get_agent_by_name(tenant_name: str, agent_name: str) -> Optional[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM agents WHERE tenant_name = $1 AND agent_name = $2",
            tenant_name,
            agent_name,
        )


async def list_agents(tenant_name: str) -> list[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM agents WHERE tenant_name = $1 ORDER BY created_at",
            tenant_name,
        )


async def get_agent_collections(agent_id: str) -> list[str]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT collection_name FROM agent_collections WHERE agent_id = $1 ORDER BY collection_name",
            agent_id,
        )
        return [r["collection_name"] for r in rows]


async def agent_dataset_ids(agent_id: str) -> list[str]:
    """Agentga biriktirilgan collectionlarning dataset_id'lari."""
    pool = _require_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.dataset_id
            FROM agent_collections ac
            JOIN agents a ON a.agent_id = ac.agent_id
            JOIN collections c
              ON c.tenant_name = a.tenant_name AND c.collection_name = ac.collection_name
            WHERE ac.agent_id = $1
            ORDER BY c.created_at
            """,
            agent_id,
        )
        return [r["dataset_id"] for r in rows]


async def set_agent_chat(agent_id: str, chat_id: str) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agents SET chat_id = $1 WHERE agent_id = $2", chat_id, agent_id
        )


async def update_agent(
    agent_id: str,
    agent_name: Optional[str] = None,
    system_prompt: Optional[str] = None,
    collections: Optional[list[str]] = None,
) -> None:
    """Berilgan maydonlarni yangilaydi. collections berilsa — to'liq almashtiriladi."""
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if agent_name is not None:
                await conn.execute(
                    "UPDATE agents SET agent_name = $1 WHERE agent_id = $2",
                    agent_name,
                    agent_id,
                )
            if system_prompt is not None:
                await conn.execute(
                    "UPDATE agents SET system_prompt = $1 WHERE agent_id = $2",
                    system_prompt,
                    agent_id,
                )
            if collections is not None:
                await conn.execute(
                    "DELETE FROM agent_collections WHERE agent_id = $1", agent_id
                )
                await conn.executemany(
                    "INSERT INTO agent_collections (agent_id, collection_name) VALUES ($1, $2)",
                    [(agent_id, c) for c in collections],
                )


# ---------- sessions ----------

async def get_session(agent_id: str, user_id: str) -> Optional[str]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT session_id FROM sessions WHERE agent_id = $1 AND user_id = $2",
            agent_id,
            user_id,
        )
        return row["session_id"] if row else None


async def save_session(agent_id: str, user_id: str, session_id: str, chat_id: str) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (agent_id, user_id, session_id, chat_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (agent_id, user_id) DO UPDATE SET
                session_id = excluded.session_id,
                chat_id = excluded.chat_id
            """,
            agent_id,
            user_id,
            session_id,
            chat_id,
        )


async def clear_agent_sessions(agent_id: str) -> None:
    """Agent o'zgargach (collections/prompt) eski sessiyalarni tozalaydi."""
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE agent_id = $1", agent_id)


# ---------- messages (history) ----------

async def add_message(
    agent_id: str,
    user_id: str,
    role: str,
    content: str,
    reference: Optional[Any] = None,
) -> None:
    pool = _require_pool()
    ref_json = json.dumps(reference, ensure_ascii=False) if reference is not None else None
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messages (agent_id, user_id, role, content, reference)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            agent_id,
            user_id,
            role,
            content,
            ref_json,
        )


async def get_history(agent_id: str, user_id: str) -> list[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT role, content, reference, created_at
            FROM messages
            WHERE agent_id = $1 AND user_id = $2
            ORDER BY created_at
            """,
            agent_id,
            user_id,
        )
