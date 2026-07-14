"""
RAGFlow REST API uchun yupqa (thin) async client.

Rasmiy hujjat: RAGFlow "OpenAI-Compatible API" emas, o'zining
/api/v1/... endpointlariga ega. Bu yerda faqat bizga kerak bo'lgan
funksiyalar wrap qilingan.
"""
import os
from typing import Any, Optional

import httpx

from config import get_settings

settings = get_settings()


class RAGFlowError(Exception):
    def __init__(self, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.payload = payload


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.ragflow_api_key}",
        "Content-Type": "application/json",
    }


async def _request(method: str, path: str, **kwargs) -> dict:
    url = f"{settings.ragflow_base_url}{path}"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.request(method, url, headers=_headers(), **kwargs)

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


# ---------------------------------------------------------------------
# DATASET (Knowledge Base) MANAGEMENT
# ---------------------------------------------------------------------

async def create_dataset(name: str, description: str = "") -> dict:
    return await _request(
        "POST",
        "/api/v1/datasets",
        json={"name": name, "description": description},
    )


async def list_datasets(name: Optional[str] = None) -> dict:
    params = {"name": name} if name else {}
    return await _request("GET", "/api/v1/datasets", params=params)


async def delete_dataset(dataset_id: str) -> dict:
    return await _request(
        "DELETE", "/api/v1/datasets", json={"ids": [dataset_id]}
    )


# ---------------------------------------------------------------------
# FILE / DOCUMENT INGEST
# ---------------------------------------------------------------------

async def upload_documents(dataset_id: str, file_paths: list[str]) -> dict:
    """Bir yoki bir nechta faylni datasetga yuklaydi (multipart/form-data)."""
    url = f"{settings.ragflow_base_url}/api/v1/datasets/{dataset_id}/documents"
    files = []
    opened = []
    try:
        for p in file_paths:
            f = open(p, "rb")
            opened.append(f)
            files.append(("file", (os.path.basename(p), f)))

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.ragflow_api_key}"},
                files=files,
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

MULTILINGUAL_SYSTEM_PROMPT = """Siz ko'p tilli aqlli yordamchisiz.

QOIDALAR:
1. Foydalanuvchi qaysi tilda savol yozsa, siz ANIQ O'SHA TILDA javob bering.
   - O'zbekcha savolga -> o'zbekcha javob
   - Ruscha savolga -> ruscha javob
   - Inglizcha savolga -> inglizcha javob
   - Boshqa tilda savol bo'lsa -> o'sha tilda javob bering
2. Faqat quyida berilgan bilim bazasi (knowledge base) asosida javob bering.
3. Agar javob bilim bazasida topilmasa, buni ochiq ayting (o'sha foydalanuvchi
   tilida), o'zingizdan to'qib chiqarmang.
4. Suhbat tarixini (chat history) hisobga oling, agar savol oldingi xabarlarga
   bog'liq bo'lsa.

Bilim bazasi:
{knowledge}

Yuqoridagi bilim bazasi asosida, foydalanuvchi savol yozgan tilda javob bering.
"""


async def create_chat_assistant(
    name: str,
    dataset_ids: list[str],
    llm_id: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> dict:
    payload: dict[str, Any] = {
        "name": name,
        "dataset_ids": dataset_ids,
        "llm": {"model_name": llm_id or settings.default_llm_id},
        "prompt": {
            "system": system_prompt or MULTILINGUAL_SYSTEM_PROMPT,
            "parameters": [{"key": "knowledge", "optional": False}],
        },
    }
    return await _request("POST", "/api/v1/chats", json=payload)


async def update_chat_assistant(chat_id: str, **fields) -> dict:
    return await _request("PUT", f"/api/v1/chats/{chat_id}", json=fields)


async def list_chat_assistants() -> dict:
    return await _request("GET", "/api/v1/chats")


async def delete_chat_assistant(chat_id: str) -> dict:
    return await _request("DELETE", "/api/v1/chats", json={"ids": [chat_id]})


# ---------------------------------------------------------------------
# SESSION + CHAT HISTORY
# ---------------------------------------------------------------------

async def create_session(chat_id: str, session_name: str = "session") -> dict:
    return await _request(
        "POST",
        f"/api/v1/chats/{chat_id}/sessions",
        json={"name": session_name},
    )


async def list_sessions(chat_id: str) -> dict:
    return await _request("GET", f"/api/v1/chats/{chat_id}/sessions")


async def delete_sessions(chat_id: str, session_ids: list[str]) -> dict:
    return await _request(
        "DELETE",
        f"/api/v1/chats/{chat_id}/sessions",
        json={"ids": session_ids},
    )


async def ask(chat_id: str, session_id: str, question: str, stream: bool = False) -> dict:
    return await _request(
        "POST",
        f"/api/v1/chats/{chat_id}/completions",
        json={
            "question": question,
            "session_id": session_id,
            "stream": stream,
        },
    )
