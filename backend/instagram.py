"""
Instagram Messaging (Meta webhook) integratsiyasi.

Oqim:
  1. Meta  GET  /instagram/webhook  -> verify_token tekshiriladi, hub.challenge qaytariladi
  2. Meta  POST /instagram/webhook  -> X-Hub-Signature-256 tekshiriladi, xabarlar ajratiladi
  3. Har bir matnli xabar fonda RAG_AGENT_ID agentiga beriladi (/chat bilan bir xil session/tarix)
  4. Javob Instagram Graph API orqali foydalanuvchiga yuboriladi

Meta 200 javobni tez kutadi (aks holda qayta yuboradi), shuning uchun javob
tayyorlash BackgroundTasks'da bajariladi va takroriy xabarlar `mid` bo'yicha tashlanadi.
"""
import hashlib
import hmac
import logging
import re
from collections import OrderedDict
from typing import Optional

import httpx

from config import get_settings

settings = get_settings()
log = logging.getLogger("instagram")

# Instagram bitta xabar uchun matn limiti
MAX_MESSAGE_LEN = 1000

_client: Optional[httpx.AsyncClient] = None
_seen_mids: "OrderedDict[str, None]" = OrderedDict()
_SEEN_LIMIT = 5000


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def verify_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """X-Hub-Signature-256: 'sha256=<hex>' — IG_APP_SECRET bilan HMAC-SHA256.

    IG_APP_SECRET bo'sh bo'lsa tekshiruv o'tkazib yuboriladi.
    """
    if not settings.ig_app_secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.ig_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


def is_duplicate(mid: Optional[str]) -> bool:
    """Meta bir xabarni qayta yuborishi mumkin — `mid` bo'yicha takrorni aniqlash."""
    if not mid:
        return False
    if mid in _seen_mids:
        return True
    _seen_mids[mid] = None
    if len(_seen_mids) > _SEEN_LIMIT:
        _seen_mids.popitem(last=False)
    return False


def extract_text_messages(payload: dict) -> list[dict]:
    """Webhook payload'dan foydalanuvchi yuborgan matnli xabarlarni ajratadi.

    Echo (biz yuborgan xabar), o'qildi/reaksiya kabi eventlar va matnsiz
    (rasm, stiker) xabarlar tashlanadi.
    """
    out: list[dict] = []
    if payload.get("object") != "instagram":
        return out
    for entry in payload.get("entry", []) or []:
        account_id = str(entry.get("id", ""))
        for ev in entry.get("messaging", []) or []:
            msg = ev.get("message") or {}
            sender_id = str((ev.get("sender") or {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            if not msg or msg.get("is_echo") or not sender_id or sender_id == account_id:
                continue
            if not text:
                continue
            out.append({"sender_id": sender_id, "mid": msg.get("mid"), "text": text})
    return out


_CITATION_RE = re.compile(r"\s*\[ID:\d+\]")


def clean_answer(text: str) -> str:
    """RAGFlow iqtibos belgilarini ([ID:0]) Instagram foydalanuvchisi uchun olib tashlaydi."""
    return _CITATION_RE.sub("", text or "").strip()


def split_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Uzun javobni Instagram limitiga sig'adigan bo'laklarga (iloji bo'lsa so'z chegarasida) bo'ladi."""
    parts: list[str] = []
    text = text.strip()
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


async def send_text(recipient_id: str, text: str) -> None:
    """Instagram Graph API orqali foydalanuvchiga matn yuboradi."""
    if not settings.ig_access_token:
        log.error("IG_ACCESS_TOKEN sozlanmagan — javob yuborilmadi")
        return
    url = f"https://graph.instagram.com/{settings.ig_api_version}/me/messages"
    headers = {"Authorization": f"Bearer {settings.ig_access_token}"}
    for part in split_message(text):
        resp = await _get_client().post(
            url,
            headers=headers,
            json={"recipient": {"id": recipient_id}, "message": {"text": part}},
        )
        if resp.status_code >= 400:
            log.error("Instagram send xatosi %s: %s", resp.status_code, resp.text[:500])
            return
