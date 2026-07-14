"""
Yengil SQLite qatlami.

RAGFlow o'zi document/chunk/session ma'lumotlarini saqlaydi, lekin bizga
o'z tomonimizda quyidagi bog'lanishlarni saqlash kerak:
  - tenant_name  -> ragflow dataset_id, ragflow chat_id
  - (tenant, user_id) -> ragflow session_id

Bu productionda albatta Postgres/MySQL bo'lishi kerak, lekin boshlanish
uchun SQLite yetarli va kod bir xil qoladi (faqat connection string o'zgaradi).
"""
import sqlite3
from contextlib import contextmanager
from typing import Optional

from config import get_settings

settings = get_settings()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_name TEXT PRIMARY KEY,
                dataset_id  TEXT NOT NULL,
                chat_id     TEXT NOT NULL,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                tenant_name TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_name, user_id)
            )
            """
        )
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------- tenants ----------

def save_tenant(tenant_name: str, dataset_id: str, chat_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tenants (tenant_name, dataset_id, chat_id)
            VALUES (?, ?, ?)
            ON CONFLICT(tenant_name) DO UPDATE SET
                dataset_id = excluded.dataset_id,
                chat_id = excluded.chat_id
            """,
            (tenant_name, dataset_id, chat_id),
        )
        conn.commit()


def get_tenant(tenant_name: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM tenants WHERE tenant_name = ?", (tenant_name,)
        )
        return cur.fetchone()


def set_tenant_chat(tenant_name: str, chat_id: str) -> None:
    """Tenant uchun chat assistant keyinroq (lazy) yaratilganda chat_id'ni yozadi."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE tenants SET chat_id = ? WHERE tenant_name = ?",
            (chat_id, tenant_name),
        )
        conn.commit()


# ---------- sessions ----------

def save_session(tenant_name: str, user_id: str, session_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sessions (tenant_name, user_id, session_id)
            VALUES (?, ?, ?)
            ON CONFLICT(tenant_name, user_id) DO UPDATE SET
                session_id = excluded.session_id
            """,
            (tenant_name, user_id, session_id),
        )
        conn.commit()


def get_session(tenant_name: str, user_id: str) -> Optional[str]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT session_id FROM sessions WHERE tenant_name = ? AND user_id = ?",
            (tenant_name, user_id),
        )
        row = cur.fetchone()
        return row["session_id"] if row else None
