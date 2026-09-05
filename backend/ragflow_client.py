"""
RAGFlow REST API uchun yupqa (thin) async client.

RAGFlow o'zining /api/v1/... endpointlariga ega. Bu yerda faqat bizga kerak
bo'lgan funksiyalar wrap qilingan. Bitta umumiy AsyncClient (connection pool)
ishlatiladi va tarmoq uzilishlarida yengil retry qo'llanadi (ngrok tunnellari
vaqti-vaqti bilan uziladi).
"""
import asyncio
import os
from typing import Any, Optional

import httpx

from config import get_settings

settings = get_settings()

_MAX_RETRIES = 3
_RETRY_BACKOFF = 0.5  # soniya

# Umumiy async client (lazy). Startup/shutdown'da boshqariladi.
_client: Optional[httpx.AsyncClient] = None


class RAGFlowError(Exception):
    def __init__(self, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.payload = payload


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.ragflow_base_url.rstrip("/"),
            timeout=httpx.Timeout(120.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.ragflow_api_key}",
        "Content-Type": "application/json",
    }


async def _request(method: str, path: str, **kwargs) -> dict:
    client = get_client()
    last_exc: Optional[Exception] = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = await client.request(method, path, headers=_headers(), **kwargs)
        except (httpx.TransportError, httpx.RemoteProtocolError) as e:
            # Tarmoq/tunnel uzilishi — qayta urinib ko'ramiz
            last_exc = e
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF * attempt)
                continue
            raise RAGFlowError(f"RAGFlow'ga ulanib bo'lmadi: {e}")

        try:
            data = resp.json()
        except ValueError:
            raise RAGFlowError(f"RAGFlow'dan JSON bo'lmagan javob: {resp.text[:300]}")

        # RAGFlow konvensiyasi: code == 0 -> muvaffaqiyatli
        if data.get("code") not in (0, None) or resp.status_code >= 400:
            raise RAGFlowError(
                data.get("message", f"RAGFlow xatosi (status {resp.status_code})"),
                payload=data,
            )
        return data

    # bu yerga yetib kelmaydi, lekin xavfsizlik uchun
    raise RAGFlowError(f"RAGFlow xatosi: {last_exc}")


# ---------------------------------------------------------------------
# SYSTEM PROMPT — persona + majburiy bilim bazasi (knowledge) bloki
# ---------------------------------------------------------------------

# RAGFlow'da RAG ishlashi uchun system prompt ichida {knowledge} bo'lishi SHART.
# Foydalanuvchi bergan persona shu majburiy blok bilan birlashtiriladi.
_KNOWLEDGE_BLOCK = """
QOIDALAR:
1. Foydalanuvchi qaysi tilda yozsa, ANIQ O'SHA TILDA javob bering.
2. Faqat quyidagi bilim bazasi (knowledge base) asosida javob bering.
3. Agar javob bilim bazasida topilmasa, buni ochiq ayting (foydalanuvchi tilida),
   o'zingizdan to'qib chiqarmang.
4. Suhbat tarixini hisobga oling.

Bilim bazasi:
{knowledge}
"""

_DEFAULT_PERSONA = "Siz ko'p tilli aqlli yordamchisiz."


def build_system_prompt(persona: Optional[str]) -> str:
    """Persona + majburiy {knowledge} blokini birlashtirib to'liq system prompt qaytaradi."""
    persona = (persona or _DEFAULT_PERSONA).strip()
    return f"{persona}\n{_KNOWLEDGE_BLOCK}"


def _prompt_config(persona: Optional[str]) -> dict:
    """RAGFlow chat assistant uchun to'liq prompt_config.

    MUHIM: RAGFlow custom system prompt va retrieval sozlamalarini
    `prompt_config` kaliti ostida kutadi (`prompt` emas — u jimgina IGNORE qilinadi).
    """
    cfg: dict[str, Any] = {
        "system": build_system_prompt(persona),
        "parameters": [{"key": "knowledge", "optional": False}],
        "top_n": settings.rag_top_n,
        "similarity_threshold": settings.rag_similarity_threshold,
        "keywords_similarity_weight": settings.rag_keywords_weight,
    }
    # Rerank model sozlangan bo'lsagina qo'shamiz (bo'sh string RAGFlow'da xato beradi)
    if settings.rag_rerank_id:
        cfg["rerank_id"] = settings.rag_rerank_id
    return cfg


# ---------------------------------------------------------------------
# DATASET (Knowledge Base) MANAGEMENT
# ---------------------------------------------------------------------

async def create_dataset(name: str, description: str = "") -> dict:
    return await _request(
        "POST", "/api/v1/datasets", json={"name": name, "description": description}
    )


async def list_datasets(name: Optional[str] = None) -> dict:
    params = {"name": name} if name else {}
    return await _request("GET", "/api/v1/datasets", params=params)


async def delete_dataset(dataset_id: str) -> dict:
    return await _request("DELETE", "/api/v1/datasets", json={"ids": [dataset_id]})


# ---------------------------------------------------------------------
# FILE / DOCUMENT INGEST
# ---------------------------------------------------------------------

async def upload_documents(dataset_id: str, file_paths: list[str]) -> dict:
    """Bir yoki bir nechta faylni datasetga yuklaydi (multipart/form-data)."""
    client = get_client()
    files = []
    opened = []
    try:
        for p in file_paths:
            f = open(p, "rb")
            opened.append(f)
            files.append(("file", (os.path.basename(p), f)))

        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            headers={"Authorization": f"Bearer {settings.ragflow_api_key}"},
            files=files,
            timeout=300,
        )
        data = resp.json()
        if data.get("code") not in (0, None):
            raise RAGFlowError(data.get("message", "Upload xatosi"), payload=data)
        return data
    finally:
        for f in opened:
            f.close()


async def parse_documents(dataset_id: str, document_ids: list[str]) -> dict:
    return await _request(
        "POST",
        f"/api/v1/datasets/{dataset_id}/chunks",
        json={"document_ids": document_ids},
    )


async def list_documents(dataset_id: str) -> dict:
    return await _request("GET", f"/api/v1/datasets/{dataset_id}/documents")


async def delete_documents(dataset_id: str, document_ids: list[str]) -> dict:
    return await _request(
        "DELETE",
        f"/api/v1/datasets/{dataset_id}/documents",
        json={"ids": document_ids},
    )


# ---------------------------------------------------------------------
# CHAT ASSISTANT MANAGEMENT
# ---------------------------------------------------------------------

async def create_chat_assistant(
    name: str,
    dataset_ids: list[str],
    persona: Optional[str] = None,
    llm_id: Optional[str] = None,
) -> dict:
    payload: dict[str, Any] = {
        "name": name,
        "dataset_ids": dataset_ids,
        "llm": {"model_name": llm_id or settings.default_llm_id},
        "prompt_config": _prompt_config(persona),
    }
    return await _request("POST", "/api/v1/chats", json=payload)


async def update_chat_assistant(chat_id: str, **fields) -> dict:
    return await _request("PUT", f"/api/v1/chats/{chat_id}", json=fields)


async def update_chat_prompt(chat_id: str, persona: Optional[str]) -> dict:
    return await update_chat_assistant(chat_id, prompt_config=_prompt_config(persona))


async def update_chat_datasets(chat_id: str, dataset_ids: list[str]) -> dict:
    return await update_chat_assistant(chat_id, dataset_ids=dataset_ids)


async def list_chat_assistants() -> dict:
    return await _request("GET", "/api/v1/chats")


async def delete_chat_assistant(chat_id: str) -> dict:
    return await _request("DELETE", "/api/v1/chats", json={"ids": [chat_id]})


# ---------------------------------------------------------------------
# SESSION + CHAT HISTORY
# ---------------------------------------------------------------------

async def create_session(chat_id: str, session_name: str = "session") -> dict:
    return await _request(
        "POST", f"/api/v1/chats/{chat_id}/sessions", json={"name": session_name}
    )


async def list_sessions(chat_id: str) -> dict:
    return await _request("GET", f"/api/v1/chats/{chat_id}/sessions")


async def delete_sessions(chat_id: str, session_ids: list[str]) -> dict:
    return await _request(
        "DELETE", f"/api/v1/chats/{chat_id}/sessions", json={"ids": session_ids}
    )


async def ask(chat_id: str, session_id: str, question: str, stream: bool = False) -> dict:
    return await _request(
        "POST",
        f"/api/v1/chats/{chat_id}/completions",
        json={"question": question, "session_id": session_id, "stream": stream},
    )


# ---------------------------------------------------------------------
# RETRIEVAL-ONLY (LLM'siz) — retrieval sifati/latency'ni alohida sinash uchun
# ---------------------------------------------------------------------

async def search_datasets(dataset_ids: list[str], question: str, top_k: int = 30) -> dict:
    """RAGFlow'ning tayyor retrieval-test endpoint'i: embedding + rerank,
    LLM chaqirmaydi. Javob shakli create_chat_assistant/ask'dagi
    `reference.chunks`ga o'xshash (`similarity`, `vector_similarity`,
    `term_similarity`, `content_with_weight`, ...).
    """
    return await _request(
        "POST",
        "/api/v1/datasets/search",
        json={"dataset_ids": dataset_ids, "question": question, "top_k": top_k},
    )
