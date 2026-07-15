"""
PostgreSQL qatlami (asyncpg + connection pool).

Saqlanadigan bog'lanishlar:
  - tenant                       -> ro'yxatdan o'tgan tashkilot
  - (tenant, collection)         -> ragflow dataset_id, chat_id, system_prompt
  - tenant ("all" scope)         -> combined chat_id, system_prompt
  - (tenant, user_id, scope)     -> ragflow session_id
  - messages                     -> har bir user savol-javob tarixi (nusxa)

scope = collection_name | 'all'
"""
import json
from typing import Any, Optional

import asyncpg

from config import get_settings

settings = get_settings()

ALL_SCOPE = "all"

_pool: Optional[asyncpg.Pool] = None


async def connect() -> None:
    """Startup'da connection pool yaratadi va sxemani init qiladi."""
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
                chat_id         TEXT,
                system_prompt   TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_name, collection_name)
            );

            CREATE TABLE IF NOT EXISTS tenant_assistants (
                tenant_name   TEXT PRIMARY KEY REFERENCES tenants(tenant_name) ON DELETE CASCADE,
                chat_id       TEXT,
                system_prompt TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                tenant_name TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                scope       TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                chat_id     TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_name, user_id, scope)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          BIGSERIAL PRIMARY KEY,
                tenant_name TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                scope       TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                reference   JSONB,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE INDEX IF NOT EXISTS idx_messages_lookup
                ON messages (tenant_name, user_id, scope, created_at);
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
        row = await conn.fetchrow(
            "SELECT 1 FROM tenants WHERE tenant_name = $1", tenant_name
        )
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


async def set_collection_chat(tenant_name: str, collection_name: str, chat_id: str) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE collections SET chat_id = $1 WHERE tenant_name = $2 AND collection_name = $3",
            chat_id,
            tenant_name,
            collection_name,
        )


async def set_collection_prompt(
    tenant_name: str, collection_name: str, system_prompt: str
) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE collections SET system_prompt = $1 WHERE tenant_name = $2 AND collection_name = $3",
            system_prompt,
            tenant_name,
            collection_name,
        )


async def list_collections(tenant_name: str) -> list[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM collections WHERE tenant_name = $1 ORDER BY created_at",
            tenant_name,
        )


async def all_dataset_ids(tenant_name: str) -> list[str]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT dataset_id FROM collections WHERE tenant_name = $1 ORDER BY created_at",
            tenant_name,
        )
        return [r["dataset_id"] for r in rows]


# ---------- tenant "all" assistant ----------

async def get_tenant_assistant(tenant_name: str) -> Optional[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM tenant_assistants WHERE tenant_name = $1", tenant_name
        )


async def set_tenant_assistant_prompt(tenant_name: str, system_prompt: str) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tenant_assistants (tenant_name, system_prompt)
            VALUES ($1, $2)
            ON CONFLICT (tenant_name) DO UPDATE SET system_prompt = excluded.system_prompt
            """,
            tenant_name,
            system_prompt,
        )


async def set_tenant_assistant_chat(tenant_name: str, chat_id: str) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tenant_assistants (tenant_name, chat_id)
            VALUES ($1, $2)
            ON CONFLICT (tenant_name) DO UPDATE SET chat_id = excluded.chat_id
            """,
            tenant_name,
            chat_id,
        )


# ---------- sessions ----------

async def get_session(tenant_name: str, user_id: str, scope: str) -> Optional[str]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT session_id FROM sessions WHERE tenant_name = $1 AND user_id = $2 AND scope = $3",
            tenant_name,
            user_id,
            scope,
        )
        return row["session_id"] if row else None


async def save_session(
    tenant_name: str, user_id: str, scope: str, session_id: str, chat_id: str
) -> None:
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (tenant_name, user_id, scope, session_id, chat_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tenant_name, user_id, scope) DO UPDATE SET
                session_id = excluded.session_id,
                chat_id = excluded.chat_id
            """,
            tenant_name,
            user_id,
            scope,
            session_id,
            chat_id,
        )


# ---------- messages (history nusxasi) ----------

async def add_message(
    tenant_name: str,
    user_id: str,
    scope: str,
    role: str,
    content: str,
    reference: Optional[Any] = None,
) -> None:
    pool = _require_pool()
    ref_json = json.dumps(reference, ensure_ascii=False) if reference is not None else None
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messages (tenant_name, user_id, scope, role, content, reference)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            tenant_name,
            user_id,
            scope,
            role,
            content,
            ref_json,
        )


async def get_history(
    tenant_name: str, user_id: str, scope: Optional[str] = None
) -> list[asyncpg.Record]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        if scope:
            return await conn.fetch(
                """
                SELECT scope, role, content, reference, created_at
                FROM messages
                WHERE tenant_name = $1 AND user_id = $2 AND scope = $3
                ORDER BY created_at
                """,
                tenant_name,
                user_id,
                scope,
            )
        return await conn.fetch(
            """
            SELECT scope, role, content, reference, created_at
            FROM messages
            WHERE tenant_name = $1 AND user_id = $2
            ORDER BY created_at
            """,
            tenant_name,
            user_id,
        )
